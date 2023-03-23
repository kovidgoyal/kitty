// License: GPLv3 Copyright: 2023, Kovid Goyal, <kovid at kovidgoyal.net>

package images

import (
	"fmt"
	"image"
	"image/color"
	"image/gif"
	"io"
	"os"
	"strings"

	"kitty/tools/utils"

	"github.com/disintegration/imaging"
)

var _ = fmt.Print

type ImageFrame struct {
	Width, Height, Left, Top int
	Number                   int   // 1-based number
	Compose_onto             int   // number of frame to compose onto
	Delay_ms                 int32 // negative for gapless frame, zero ignored, positive is number of ms
	Is_opaque                bool
	Img                      image.Image
}

type ImageData struct {
	Width, Height    int
	Format_uppercase string
	Frames           []*ImageFrame
}

func CalcMinimumGIFGap(gaps []int) int {
	// Some broken GIF images have all zero gaps, browsers with their usual
	// idiot ideas render these with a default 100ms gap https://bugzilla.mozilla.org/show_bug.cgi?id=125137
	// Browsers actually force a 100ms gap at any zero gap frame, but that
	// just means it is impossible to deliberately use zero gap frames for
	// sophisticated blending, so we dont do that.
	max_gap := utils.Max(0, gaps...)
	min_gap := 0
	if max_gap <= 0 {
		min_gap = 10
	}
	return min_gap
}

func SetGIFFrameDisposal(number, anchor_frame int, disposal byte) (int, int) {
	compose_onto := 0
	if number > 1 {
		switch disposal {
		case gif.DisposalNone:
			compose_onto = number - 1
			anchor_frame = number
		case gif.DisposalBackground:
			// see https://github.com/golang/go/issues/20694
			anchor_frame = number
		case gif.DisposalPrevious:
			compose_onto = anchor_frame
		}
	}
	return anchor_frame, compose_onto
}

func open_native_gif(f io.Reader, ans *ImageData) error {
	gif_frames, err := gif.DecodeAll(f)
	if err != nil {
		return err
	}
	min_gap := CalcMinimumGIFGap(gif_frames.Delay)
	anchor_frame := 1
	for i, paletted_img := range gif_frames.Image {
		b := paletted_img.Bounds()
		frame := ImageFrame{Img: paletted_img, Left: b.Min.X, Top: b.Min.Y, Width: b.Dx(), Height: b.Dy(), Number: len(ans.Frames) + 1, Is_opaque: paletted_img.Opaque()}
		frame.Delay_ms = int32(utils.Max(min_gap, gif_frames.Delay[i]) * 10)
		if frame.Delay_ms == 0 {
			frame.Delay_ms = -1 // gapless frame
		}
		anchor_frame, frame.Compose_onto = SetGIFFrameDisposal(frame.Number, anchor_frame, gif_frames.Disposal[i])
		ans.Frames = append(ans.Frames, &frame)
	}
	return nil
}

func OpenNativeImageFromReader(f io.ReadSeeker) (ans *ImageData, err error) {
	c, fmt, err := image.DecodeConfig(f)
	if err != nil {
		return nil, err
	}
	f.Seek(0, os.SEEK_SET)
	ans = &ImageData{Width: c.Width, Height: c.Height, Format_uppercase: strings.ToUpper(fmt)}

	if ans.Format_uppercase == "GIF" {
		err = open_native_gif(f, ans)
		if err != nil {
			return nil, err
		}
	} else {
		img, err := imaging.Decode(f, imaging.AutoOrientation(true))
		if err != nil {
			return nil, err
		}
		b := img.Bounds()
		ans.Frames = []*ImageFrame{{Img: img, Left: b.Min.X, Top: b.Min.Y, Width: b.Dx(), Height: b.Dy()}}
		ans.Frames[0].Is_opaque = c.ColorModel == color.YCbCrModel || c.ColorModel == color.GrayModel || c.ColorModel == color.Gray16Model || c.ColorModel == color.CMYKModel || ans.Format_uppercase == "JPEG" || ans.Format_uppercase == "JPG" || IsOpaque(img)
	}
	return
}

func OpenMagickImageFromPath(path string) (ans *ImageData, err error) {
	// TODO: Implement this
	return
}

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
			return nil, fmt.Errorf("Failed to load image at %#v with error: %w", path, err)
		}
	} else {
		return OpenMagickImageFromPath(path)
	}
	return
}
