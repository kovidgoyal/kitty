package images

import (
	"bytes"
	"encoding/binary"
	"fmt"
	"image"
	"io"
	"os"
	"strings"

	"github.com/kovidgoyal/kitty/tools/cli"
	"github.com/kovidgoyal/kitty/tools/utils"
)

var _ = fmt.Print

func encode_rgba(output io.Writer, img image.Image) (err error) {
	var final_img *image.NRGBA
	switch img.(type) {
	case *image.NRGBA:
		final_img = img.(*image.NRGBA)
	default:
		b := img.Bounds()
		final_img = image.NewNRGBA(image.Rect(0, 0, b.Dx(), b.Dy()))
		ctx := Context{}
		ctx.PasteCenter(final_img, img, nil)
	}
	b := final_img.Bounds()
	header := make([]byte, 8)
	var width = utils.Abs(b.Dx())
	var height = utils.Abs(b.Dy())
	binary.LittleEndian.PutUint32(header, uint32(width))
	binary.LittleEndian.PutUint32(header[4:], uint32(height))
	readers := []io.Reader{bytes.NewReader(header)}
	stride := 4 * width

	if final_img.Stride == stride {
		readers = append(readers, bytes.NewReader(final_img.Pix))
	} else {
		p := final_img.Pix
		for y := 0; y < b.Dy(); y++ {
			readers = append(readers, bytes.NewReader(p[:min(stride, len(p))]))
			p = p[final_img.Stride:]
		}
	}
	_, err = io.Copy(output, io.MultiReader(readers...))
	return
}

func convert_image(input io.ReadSeeker, output io.Writer, format string) (err error) {
	image_data, err := OpenNativeImageFromReader(input)
	if err != nil {
		return err
	}
	if len(image_data.Frames) == 0 {
		return fmt.Errorf("Image has no frames")
	}
	img := image_data.Frames[0].Img
	q := strings.ToLower(format)
	if q == "rgba" {
		return encode_rgba(output, img)
	}
	mt := utils.GuessMimeType("file." + q)
	if mt == "" {
		return fmt.Errorf("Unknown image output format: %s", format)
	}
	return Encode(output, img, mt)
}

func ConvertEntryPoint(root *cli.Command) {
	root.AddSubCommand(&cli.Command{
		Name:            "__convert_image__",
		Hidden:          true,
		OnlyArgsAllowed: true,
		Run: func(cmd *cli.Command, args []string) (rc int, err error) {
			if len(args) != 1 {
				return 1, fmt.Errorf("Usage: __convert_image__ OUTPUT_FORMAT")
			}
			format := args[0]
			buf := bytes.NewBuffer(make([]byte, 0, 1024*1024))
			if _, err = io.Copy(buf, os.Stdin); err != nil {
				return 1, err
			}
			if err = convert_image(bytes.NewReader(buf.Bytes()), os.Stdout, format); err != nil {
				rc = 1
			}
			return
		},
	})
}
