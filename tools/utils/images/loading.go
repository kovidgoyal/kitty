// License: GPLv3 Copyright: 2023, Kovid Goyal, <kovid at kovidgoyal.net>

package images

import (
	"fmt"
	"image"
	"image/png"
	"io"
	"os"
	"strings"

	"github.com/kovidgoyal/go-parallel"
	"github.com/kovidgoyal/go-shm"
	"github.com/kovidgoyal/imaging/nrgb"

	"github.com/kovidgoyal/imaging"
)

var _ = fmt.Print

const TempTemplate = "kitty-tty-graphics-protocol-*"

func CreateTemp() (*os.File, error) {
	return os.CreateTemp("", TempTemplate)
}

func CreateTempInRAM() (*os.File, error) {
	if shm.SHM_DIR != "" {
		f, err := os.CreateTemp(shm.SHM_DIR, TempTemplate)
		if err == nil {
			return f, err
		}
	}
	return CreateTemp()
}

type ImageFrame struct {
	Width, Height, Left, Top int
	Number                   int   // 1-based number
	Compose_onto             int   // number of frame to compose onto
	Delay_ms                 int32 // negative for gapless frame, zero ignored, positive is number of ms
	Replace                  bool  // do a replace rather than an alpha blend
	Is_opaque                bool
	Img                      image.Image
}

type SerializableImageFrame struct {
	Width, Height, Left, Top int
	Number                   int  // 1-based number
	Compose_onto             int  // number of frame to compose onto
	Delay_ms                 int  // negative for gapless frame, zero ignored, positive is number of ms
	Replace                  bool // do a replace rather than an alpha blend
	Is_opaque                bool

	Size               int // size in bytes of the serialized data
	Number_of_channels int
	Bits_per_channel   int
	Has_alpha_channel  bool
}

func (s *ImageFrame) Serialize() SerializableImageFrame {
	return SerializableImageFrame{
		Width: s.Width, Height: s.Height, Left: s.Left, Top: s.Top,
		Number: s.Number, Compose_onto: s.Compose_onto, Delay_ms: int(s.Delay_ms),
		Is_opaque: s.Is_opaque, Replace: s.Replace,
	}
}

func (self *ImageFrame) DataAsSHM(pattern string) (ans shm.MMap, err error) {
	_, _, _, d := self.Data()
	if ans, err = shm.CreateTemp(pattern, uint64(len(d))); err != nil {
		return nil, err
	}
	copy(ans.Slice(), d)
	return
}

func (self *ImageFrame) Data() (num_channels, bits_per_channel int, has_alpha_channel bool, ans []byte) {
	if self.Is_opaque {
		return 3, 8, false, imaging.AsRGBData8(self.Img)
	}
	return 4, 8, true, imaging.AsRGBAData8(self.Img)
}

func ImageFrameFromSerialized(s SerializableImageFrame, data []byte) (aa *ImageFrame, err error) {
	ans := ImageFrame{
		Width: s.Width, Height: s.Height, Left: s.Left, Top: s.Top,
		Number: s.Number, Compose_onto: s.Compose_onto, Delay_ms: int32(s.Delay_ms),
		Is_opaque: s.Is_opaque || !s.Has_alpha_channel, Replace: s.Replace,
	}
	bpc := s.Bits_per_channel
	if bpc == 0 {
		bpc = 8
	}
	if bpc != 8 {
		return nil, fmt.Errorf("serialized image data has unsupported number of bits per channel: %d", bpc)
	}
	bytes_per_pixel := bpc * s.Number_of_channels / 8
	if expected := bytes_per_pixel * s.Width * s.Height; len(data) != expected {
		return nil, fmt.Errorf("serialized image data has size: %d != %d", len(data), expected)
	}
	switch s.Number_of_channels {
	case 3, 0:
		ans.Img, err = nrgb.NewNRGBWithContiguousRGBPixels(data, s.Left, s.Top, s.Width, s.Height)
	case 4:
		ans.Img, err = NewNRGBAWithContiguousRGBAPixels(data, s.Left, s.Top, s.Width, s.Height)
	default:
		return nil, fmt.Errorf("serialized image data has unsupported number of channels: %d", s.Number_of_channels)
	}
	return &ans, err
}

type ImageData struct {
	Width, Height    int
	Format_uppercase string
	Frames           []*ImageFrame
}

type SerializableImageMetadata struct {
	Version          int
	Width, Height    int
	Format_uppercase string
	Frames           []SerializableImageFrame
}

const SERIALIZE_VERSION = 1

func (self *ImageFrame) SaveAsUncompressedPNG(output io.Writer) error {
	encoder := png.Encoder{CompressionLevel: png.NoCompression}
	return encoder.Encode(output, self.Img)
}

func (self *ImageData) SerializeOnlyMetadata() SerializableImageMetadata {
	f := make([]SerializableImageFrame, len(self.Frames))
	for i, s := range self.Frames {
		f[i] = s.Serialize()
	}
	return SerializableImageMetadata{Version: SERIALIZE_VERSION, Width: self.Width, Height: self.Height, Format_uppercase: self.Format_uppercase, Frames: f}
}

func (self *ImageData) Serialize() (SerializableImageMetadata, [][]byte) {
	m := self.SerializeOnlyMetadata()
	data := make([][]byte, len(self.Frames))
	for i, f := range self.Frames {
		df := &m.Frames[i]
		df.Number_of_channels, df.Bits_per_channel, df.Has_alpha_channel, data[i] = f.Data()
		df.Size = len(data[i])
		if !df.Has_alpha_channel {
			df.Is_opaque = true
		}
	}
	return m, data
}

func ImageFromSerialized(m SerializableImageMetadata, data [][]byte) (*ImageData, error) {
	if m.Version > SERIALIZE_VERSION {
		return nil, fmt.Errorf("serialized image data has unsupported version: %d", m.Version)
	}
	if len(m.Frames) != len(data) {
		return nil, fmt.Errorf("serialized image data has %d frames in metadata but have data for: %d", len(m.Frames), len(data))
	}
	ans := ImageData{
		Width: m.Width, Height: m.Height, Format_uppercase: m.Format_uppercase,
	}
	for i, f := range m.Frames {
		if ff, err := ImageFrameFromSerialized(f, data[i]); err != nil {
			return nil, err
		} else {
			ans.Frames = append(ans.Frames, ff)
		}
	}
	return &ans, nil
}

func (self *ImageFrame) Resize(x_frac, y_frac float64) *ImageFrame {
	b := self.Img.Bounds()
	left, top, width, height := b.Min.X, b.Min.Y, b.Dx(), b.Dy()
	ans := *self
	ans.Width = int(x_frac * float64(width))
	ans.Height = int(y_frac * float64(height))
	ans.Img = imaging.ResizeWithOpacity(self.Img, ans.Width, ans.Height, imaging.Lanczos, self.Is_opaque)
	ans.Left = int(x_frac * float64(left))
	ans.Top = int(y_frac * float64(top))
	return &ans

}

func (self *ImageData) Resize(x_frac, y_frac float64) *ImageData {
	ans := *self
	ans.Frames = make([]*ImageFrame, len(self.Frames))
	if err := parallel.Run_in_parallel_over_range(0, func(start, limit int) {
		for i := start; i < limit; i++ {
			ans.Frames[i] = self.Frames[i].Resize(x_frac, y_frac)
		}
	}, 0, len(ans.Frames)); err != nil {
		panic(err)
	}
	if len(ans.Frames) > 0 {
		ans.Width, ans.Height = ans.Frames[0].Width, ans.Frames[0].Height
	}
	return &ans
}

func MakeTempDir(template string) (ans string, err error) {
	if template == "" {
		template = "kitty-img-*"
	}
	if shm.SHM_DIR != "" {
		ans, err = os.MkdirTemp(shm.SHM_DIR, template)
		if err == nil {
			return
		}
	}
	return os.MkdirTemp("", template)
}

func NewImageData(ic *imaging.Image) (ans *ImageData) {
	b := ic.Bounds()
	ans = &ImageData{
		Width: b.Dx(), Height: b.Dy(),
	}
	if ic.Metadata != nil {
		ans.Format_uppercase = strings.ToUpper(ic.Metadata.Format.String())
	}

	for _, f := range ic.Frames {
		fr := ImageFrame{
			Img: f.Image, Left: f.TopLeft.X, Top: f.TopLeft.Y, Width: f.Image.Bounds().Dx(), Height: f.Image.Bounds().Dy(),
			Compose_onto: int(f.ComposeOnto), Number: int(f.Number), Delay_ms: int32(f.Delay.Milliseconds()),
			Replace: f.Replace, Is_opaque: imaging.IsOpaque(f.Image),
		}
		if fr.Delay_ms <= 0 {
			fr.Delay_ms = -1 // -1 is gapless in graphics protocol
		}
		ans.Frames = append(ans.Frames, &fr)
	}
	return
}

func OpenImageFromPath(path string, opts ...imaging.DecodeOption) (ans *ImageData, err error) {
	ic, err := imaging.OpenAll(path, opts...)
	if err != nil {
		return nil, err
	}
	return NewImageData(ic), nil
}

func OpenImageFromReader(r io.Reader, opts ...imaging.DecodeOption) (ans *ImageData, s io.Reader, err error) {
	ic, s, err := imaging.DecodeAll(r, opts...)
	if err != nil {
		return nil, nil, err
	}
	return NewImageData(ic), s, nil
}
