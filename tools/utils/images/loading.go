// License: GPLv3 Copyright: 2023, Kovid Goyal, <kovid at kovidgoyal.net>

package images

import (
	"bytes"
	"encoding/json"
	"errors"
	"fmt"
	"image"
	"image/gif"
	"image/png"
	"io"
	"os"
	"os/exec"
	"path/filepath"
	"slices"
	"strconv"
	"strings"
	"sync"

	"github.com/kovidgoyal/imaging/nrgb"
	"github.com/kovidgoyal/imaging/prism/meta/gifmeta"
	"github.com/kovidgoyal/kitty/tools/utils"
	"github.com/kovidgoyal/kitty/tools/utils/shm"

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
	Size                     int
}

func (s SerializableImageFrame) NeededSize() int {
	return utils.IfElse(s.Is_opaque, 3, 4) * s.Width * s.Height
}

func (s *ImageFrame) Serialize() SerializableImageFrame {
	return SerializableImageFrame{
		Width: s.Width, Height: s.Height, Left: s.Left, Top: s.Top,
		Number: s.Number, Compose_onto: s.Compose_onto, Delay_ms: int(s.Delay_ms),
		Is_opaque: s.Is_opaque, Replace: s.Replace,
	}
}

func (self *ImageFrame) DataAsSHM(pattern string) (ans shm.MMap, err error) {
	bytes_per_pixel := 4
	if self.Is_opaque {
		bytes_per_pixel = 3
	}
	ans, err = shm.CreateTemp(pattern, uint64(self.Width*self.Height*bytes_per_pixel))
	if err != nil {
		return nil, err
	}
	switch img := self.Img.(type) {
	case *imaging.NRGB:
		if bytes_per_pixel == 3 {
			copy(ans.Slice(), img.Pix)
			return
		}
	case *image.NRGBA:
		if bytes_per_pixel == 4 {
			copy(ans.Slice(), img.Pix)
			return
		}
	}
	dest_rect := image.Rect(0, 0, self.Width, self.Height)
	var final_img image.Image
	switch bytes_per_pixel {
	case 3:
		rgb := &imaging.NRGB{Pix: ans.Slice(), Stride: bytes_per_pixel * self.Width, Rect: dest_rect}
		final_img = rgb
	case 4:
		rgba := &image.NRGBA{Pix: ans.Slice(), Stride: bytes_per_pixel * self.Width, Rect: dest_rect}
		final_img = rgba
	}
	ctx := Context{}
	ctx.PasteCenter(final_img, self.Img, nil)
	return

}

func (self *ImageFrame) Data() (ans []byte) {
	bytes_per_pixel := 4
	if self.Is_opaque {
		bytes_per_pixel = 3
	}
	switch img := self.Img.(type) {
	case *imaging.NRGB:
		if bytes_per_pixel == 3 {
			return img.Pix
		}
	case *image.NRGBA:
		if bytes_per_pixel == 4 {
			return img.Pix
		}
	}
	dest_rect := image.Rect(0, 0, self.Width, self.Height)
	var final_img image.Image
	switch bytes_per_pixel {
	case 3:
		rgb := nrgb.NewNRGB(dest_rect)
		final_img = rgb
		ans = rgb.Pix
	case 4:
		rgba := image.NewNRGBA(dest_rect)
		final_img = rgba
		ans = rgba.Pix
	}
	ctx := Context{}
	ctx.PasteCenter(final_img, self.Img, nil)
	return
}

func ImageFrameFromSerialized(s SerializableImageFrame, data []byte) (aa *ImageFrame, err error) {
	ans := ImageFrame{
		Width: s.Width, Height: s.Height, Left: s.Left, Top: s.Top,
		Number: s.Number, Compose_onto: s.Compose_onto, Delay_ms: int32(s.Delay_ms),
		Is_opaque: s.Is_opaque, Replace: s.Replace,
	}
	bytes_per_pixel := utils.IfElse(s.Is_opaque, 3, 4)
	if expected := bytes_per_pixel * s.Width * s.Height; len(data) != expected {
		return nil, fmt.Errorf("serialized image data has size: %d != %d", len(data), expected)
	}
	if s.Is_opaque {
		ans.Img, err = nrgb.NewNRGBWithContiguousRGBPixels(data, s.Left, s.Top, s.Width, s.Height)
	} else {
		ans.Img, err = NewNRGBAWithContiguousRGBAPixels(data, s.Left, s.Top, s.Width, s.Height)
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
		data[i] = f.Data()
		m.Frames[i].Size = len(data[i])
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
	ans.Img = imaging.Resize(self.Img, ans.Width, ans.Height, imaging.Lanczos)
	ans.Left = int(x_frac * float64(left))
	ans.Top = int(y_frac * float64(top))
	return &ans

}

func (self *ImageData) Resize(x_frac, y_frac float64) *ImageData {
	ans := *self
	ans.Frames = utils.Map(func(f *ImageFrame) *ImageFrame { return f.Resize(x_frac, y_frac) }, self.Frames)
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

// Native {{{
func OpenNativeImageFromReader(f io.ReadSeeker) (ans *ImageData, err error) {
	ic, _, err := imaging.DecodeAll(f)
	if err != nil {
		return nil, err
	}
	_, _ = f.Seek(0, io.SeekStart)

	ans = &ImageData{Width: int(ic.Metadata.PixelWidth), Height: int(ic.Metadata.PixelHeight), Format_uppercase: strings.ToUpper(ic.Metadata.Format.String())}

	for _, f := range ic.Frames {
		fr := ImageFrame{
			Img: f.Image, Left: f.X, Top: f.Y, Width: f.Image.Bounds().Dx(), Height: f.Image.Bounds().Dy(),
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

// }}}

// ImageMagick {{{
var MagickExe = sync.OnceValue(func() string {
	return utils.FindExe("magick")
})

func check_resize(frame *ImageFrame, filename string) error {
	// ImageMagick sometimes generates RGBA images smaller than the specified
	// size. See https://github.com/kovidgoyal/kitty/issues/276 for examples
	s, err := os.Stat(filename)
	if err != nil {
		return err
	}
	sz := int(s.Size())
	bytes_per_pixel := 4
	if frame.Is_opaque {
		bytes_per_pixel = 3
	}
	expected_size := bytes_per_pixel * frame.Width * frame.Height
	if sz < expected_size {
		missing := expected_size - sz
		if missing%(bytes_per_pixel*frame.Width) != 0 {
			return fmt.Errorf("ImageMagick failed to resize correctly. It generated %d < %d of data (w=%d h=%d bpp=%d)", sz, expected_size, frame.Width, frame.Height, bytes_per_pixel)
		}
		frame.Height -= missing / (bytes_per_pixel * frame.Width)
	}
	return nil
}

func RunMagick(path string, cmd []string) ([]byte, error) {
	if MagickExe() != "magick" {
		cmd = append([]string{MagickExe()}, cmd...)
	}
	c := exec.Command(cmd[0], cmd[1:]...)
	output, err := c.Output()
	if err != nil {
		var exit_err *exec.ExitError
		if errors.As(err, &exit_err) {
			return nil, fmt.Errorf("Running the command: %s\nFailed with error:\n%s", strings.Join(cmd, " "), string(exit_err.Stderr))
		}
		return nil, fmt.Errorf("Could not find the program: %#v. Is ImageMagick installed and in your PATH?", cmd[0])
	}
	return output, nil
}

type IdentifyOutput struct {
	Fmt, Canvas, Transparency, Gap, Index, Size, Dpi, Dispose, Orientation string
}

type IdentifyRecord struct {
	Fmt_uppercase      string
	Gap                int
	Canvas             struct{ Width, Height, Left, Top int }
	Width, Height      int
	Dpi                struct{ X, Y float64 }
	Index              int
	Is_opaque          bool
	Needs_blend        bool
	Disposal           int
	Dimensions_swapped bool
}

func parse_identify_record(ans *IdentifyRecord, raw *IdentifyOutput) (err error) {
	ans.Fmt_uppercase = strings.ToUpper(raw.Fmt)
	if raw.Gap != "" {
		ans.Gap, err = strconv.Atoi(raw.Gap)
		if err != nil {
			return fmt.Errorf("Invalid gap value in identify output: %s", raw.Gap)
		}
		ans.Gap = max(0, ans.Gap)
	}
	area, pos, found := strings.Cut(raw.Canvas, "+")
	ok := false
	if found {
		w, h, found := strings.Cut(area, "x")
		if found {
			ans.Canvas.Width, err = strconv.Atoi(w)
			if err == nil {
				ans.Canvas.Height, err = strconv.Atoi(h)
				if err == nil {
					x, y, found := strings.Cut(pos, "+")
					if found {
						ans.Canvas.Left, err = strconv.Atoi(x)
						if err == nil {
							if ans.Canvas.Top, err = strconv.Atoi(y); err == nil {
								ok = true
							}
						}
					}
				}
			}
		}
	}
	if !ok {
		return fmt.Errorf("Invalid canvas value in identify output: %s", raw.Canvas)
	}
	w, h, found := strings.Cut(raw.Size, "x")
	ok = false
	if found {
		ans.Width, err = strconv.Atoi(w)
		if err == nil {
			if ans.Height, err = strconv.Atoi(h); err == nil {
				ok = true
			}
		}
	}
	if !ok {
		return fmt.Errorf("Invalid size value in identify output: %s", raw.Size)
	}
	x, y, found := strings.Cut(raw.Dpi, "x")
	ok = false
	if found {
		ans.Dpi.X, err = strconv.ParseFloat(x, 64)
		if err == nil {
			if ans.Dpi.Y, err = strconv.ParseFloat(y, 64); err == nil {
				ok = true
			}
		}
	}
	if !ok {
		return fmt.Errorf("Invalid dpi value in identify output: %s", raw.Dpi)
	}
	ans.Index, err = strconv.Atoi(raw.Index)
	if err != nil {
		return fmt.Errorf("Invalid index value in identify output: %s", raw.Index)
	}
	q := strings.ToLower(raw.Transparency)
	if q == "blend" || q == "true" {
		ans.Is_opaque = false
	} else {
		ans.Is_opaque = true
	}
	ans.Needs_blend = q == "blend"
	switch strings.ToLower(raw.Dispose) {
	case "undefined":
		ans.Disposal = 0
	case "none":
		ans.Disposal = gif.DisposalNone
	case "background":
		ans.Disposal = gif.DisposalBackground
	case "previous":
		ans.Disposal = gif.DisposalPrevious
	default:
		return fmt.Errorf("Invalid value for dispose: %s", raw.Dispose)
	}
	switch raw.Orientation {
	case "5", "6", "7", "8":
		ans.Dimensions_swapped = true
	}
	if ans.Dimensions_swapped {
		ans.Canvas.Width, ans.Canvas.Height = ans.Canvas.Height, ans.Canvas.Width
		ans.Width, ans.Height = ans.Height, ans.Width
	}

	return
}

func IdentifyWithMagick(path string) (ans []IdentifyRecord, err error) {
	cmd := []string{"identify"}
	q := `{"fmt":"%m","canvas":"%g","transparency":"%A","gap":"%T","index":"%p","size":"%wx%h",` +
		`"dpi":"%xx%y","dispose":"%D","orientation":"%[EXIF:Orientation]"},`
	cmd = append(cmd, "-format", q, "--", path)
	output, err := RunMagick(path, cmd)
	if err != nil {
		return nil, fmt.Errorf("Failed to identify image at path: %s with error: %w", path, err)
	}
	output = bytes.TrimRight(bytes.TrimSpace(output), ",")
	raw_json := make([]byte, 0, len(output)+2)
	raw_json = append(raw_json, '[')
	raw_json = append(raw_json, output...)
	raw_json = append(raw_json, ']')
	var records []IdentifyOutput
	err = json.Unmarshal(raw_json, &records)
	if err != nil {
		return nil, fmt.Errorf("The ImageMagick identify program returned malformed output for the image at path: %s, with error: %w", path, err)
	}
	ans = make([]IdentifyRecord, len(records))
	for i, rec := range records {
		err = parse_identify_record(&ans[i], &rec)
		if err != nil {
			return nil, err
		}
	}
	return ans, nil
}

type RenderOptions struct {
	RemoveAlpha          *imaging.NRGBColor
	Flip, Flop           bool
	ResizeTo             image.Point
	OnlyFirstFrame       bool
	TempfilenameTemplate string
}

func RenderWithMagick(path string, ro *RenderOptions, frames []IdentifyRecord) (ans []*ImageFrame, fmap map[int]string, err error) {
	cmd := []string{"convert"}
	ans = make([]*ImageFrame, 0, len(frames))
	fmap = make(map[int]string, len(frames))

	defer func() {
		if err != nil {
			for _, f := range fmap {
				os.Remove(f)
			}
		}
	}()

	if ro.RemoveAlpha != nil {
		cmd = append(cmd, "-background", ro.RemoveAlpha.AsSharp(), "-alpha", "remove")
	} else {
		cmd = append(cmd, "-background", "none")
	}
	if ro.Flip {
		cmd = append(cmd, "-flip")
	}
	if ro.Flop {
		cmd = append(cmd, "-flop")
	}
	cpath := path
	if ro.OnlyFirstFrame {
		cpath += "[0]"
	}
	has_multiple_frames := len(frames) > 1
	get_multiple_frames := has_multiple_frames && !ro.OnlyFirstFrame
	cmd = append(cmd, "--", cpath, "-auto-orient")
	if ro.ResizeTo.X > 0 {
		rcmd := []string{"-resize", fmt.Sprintf("%dx%d!", ro.ResizeTo.X, ro.ResizeTo.Y)}
		if get_multiple_frames {
			cmd = append(cmd, "-coalesce")
			cmd = append(cmd, rcmd...)
			cmd = append(cmd, "-deconstruct")
		} else {
			cmd = append(cmd, rcmd...)
		}
	}
	cmd = append(cmd, "-depth", "8", "-set", "filename:f", "%w-%h-%g-%p")
	if get_multiple_frames {
		cmd = append(cmd, "+adjoin")
	}
	tdir, err := MakeTempDir(ro.TempfilenameTemplate)
	if err != nil {
		err = fmt.Errorf("Failed to create temporary directory to hold ImageMagick output with error: %w", err)
		return
	}
	defer os.RemoveAll(tdir)
	mode := "rgba"
	if frames[0].Is_opaque {
		mode = "rgb"
	}
	cmd = append(cmd, filepath.Join(tdir, "im-%[filename:f]."+mode))
	_, err = RunMagick(path, cmd)
	if err != nil {
		return
	}
	entries, err := os.ReadDir(tdir)
	if err != nil {
		err = fmt.Errorf("Failed to read temp dir used to store ImageMagick output with error: %w", err)
		return
	}
	base_dir := filepath.Dir(tdir)
	gaps := make([]int, len(frames))
	for i, frame := range frames {
		gaps[i] = frame.Gap
	}
	// although ImageMagick *might* be already taking care of this adjustment,
	// I dont know for sure, so do it anyway.
	min_gap := gifmeta.CalcMinimumGap(gaps)
	for _, entry := range entries {
		fname := entry.Name()
		p, _, _ := strings.Cut(fname, ".")
		parts := strings.Split(p, "-")
		if len(parts) < 5 {
			continue
		}
		index, cerr := strconv.Atoi(parts[len(parts)-1])
		if cerr != nil || index < 0 || index >= len(frames) {
			continue
		}
		width, cerr := strconv.Atoi(parts[1])
		if cerr != nil {
			continue
		}
		height, cerr := strconv.Atoi(parts[2])
		if cerr != nil {
			continue
		}
		_, pos, found := strings.Cut(parts[3], "+")
		if !found {
			continue
		}
		px, py, found := strings.Cut(pos, "+")
		if !found {
			continue
		}
		x, cerr := strconv.Atoi(px)
		if cerr != nil {
			continue
		}
		y, cerr := strconv.Atoi(py)
		if cerr != nil {
			continue
		}
		identify_data := frames[index]
		df, cerr := os.CreateTemp(base_dir, TempTemplate+"."+mode)
		if cerr != nil {
			err = fmt.Errorf("Failed to create a temporary file in %s with error: %w", base_dir, cerr)
			return
		}
		err = os.Rename(filepath.Join(tdir, fname), df.Name())
		if err != nil {
			err = fmt.Errorf("Failed to rename a temporary file in %s with error: %w", tdir, err)
			return
		}
		df.Close()
		fmap[index+1] = df.Name()
		frame := ImageFrame{
			Number: index + 1, Width: width, Height: height, Left: x, Top: y, Is_opaque: identify_data.Is_opaque,
		}
		frame.Delay_ms = int32(max(min_gap, identify_data.Gap) * 10)
		err = check_resize(&frame, df.Name())
		if err != nil {
			return
		}
		ans = append(ans, &frame)
	}
	if len(ans) < len(frames) {
		err = fmt.Errorf("Failed to render %d out of %d frames", len(frames)-len(ans), len(frames))
		return
	}
	slices.SortFunc(ans, func(a, b *ImageFrame) int { return a.Number - b.Number })
	anchor_frame := uint(1)
	for i, frame := range ans {
		af, co := gifmeta.SetGIFFrameDisposal(uint(frame.Number), anchor_frame, byte(frames[i].Disposal))
		anchor_frame, frame.Compose_onto = af, int(co)
	}
	return
}

func OpenImageFromPathWithMagick(path string) (ans *ImageData, err error) {
	identify_records, err := IdentifyWithMagick(path)
	if err != nil {
		return nil, fmt.Errorf("Failed to identify image at %#v with error: %w", path, err)
	}
	frames, filenames, err := RenderWithMagick(path, &RenderOptions{}, identify_records)
	if err != nil {
		return nil, fmt.Errorf("Failed to render image at %#v with error: %w", path, err)
	}
	defer func() {
		for _, f := range filenames {
			os.Remove(f)
		}
	}()

	for _, frame := range frames {
		filename := filenames[frame.Number]
		data, err := os.ReadFile(filename)
		if err != nil {
			return nil, fmt.Errorf("Failed to read temp file for image %#v at %#v with error: %w", path, filename, err)
		}
		dest_rect := image.Rect(0, 0, frame.Width, frame.Height)
		if frame.Is_opaque {
			frame.Img = &imaging.NRGB{Pix: data, Stride: frame.Width * 3, Rect: dest_rect}
		} else {
			frame.Img = &image.NRGBA{Pix: data, Stride: frame.Width * 4, Rect: dest_rect}
		}
	}
	ans = &ImageData{
		Width: frames[0].Width, Height: frames[0].Height, Format_uppercase: identify_records[0].Fmt_uppercase, Frames: frames,
	}
	return ans, nil
}

// }}}

func OpenImageFromPath(path string) (ans *ImageData, err error) {
	mt := utils.GuessMimeType(path)
	if DecodableImageTypes[mt] {
		f, err := os.Open(path)
		if err != nil {
			return nil, err
		}
		defer f.Close()
		ans, err = OpenNativeImageFromReader(f)
		if err != nil {
			return OpenImageFromPathWithMagick(path)
		}
	} else {
		return OpenImageFromPathWithMagick(path)
	}
	return
}
