package images

import (
	"bytes"
	"encoding/binary"
	"fmt"
	"image"
	"io"
	"os"
	"slices"
	"strconv"
	"strings"

	"github.com/kovidgoyal/imaging"
	"github.com/kovidgoyal/kitty/tools/cli"
	"github.com/kovidgoyal/kitty/tools/utils"
)

var _ = fmt.Print

func encode_rgba(output io.Writer, img image.Image) (err error) {
	var final_img *image.NRGBA
	switch ti := img.(type) {
	case *image.NRGBA:
		final_img = ti
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
	img, err := imaging.Decode(input)
	if err != nil {
		return err
	}
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

func images_equal(img, rimg *ImageData) (err error) {
	for i := range img.Frames {
		a, b := img.Frames[i], rimg.Frames[i]
		if a.Img.Bounds() != b.Img.Bounds() {
			return fmt.Errorf("bounds of frame %d not equal: %v != %v", i, a.Img.Bounds(), b.Img.Bounds())
		}
		for y := a.Img.Bounds().Min.Y; y < a.Img.Bounds().Max.Y; y++ {
			for x := a.Img.Bounds().Min.X; x < a.Img.Bounds().Max.X; x++ {
				or, og, ob, oa := a.Img.At(x, y).RGBA()
				nr, ng, nb, na := b.Img.At(x, y).RGBA()
				a, b := []uint32{or, og, ob, oa}, []uint32{nr, ng, nb, na}
				if !slices.Equal(a, b) {
					return fmt.Errorf("pixel at %dx%d differs: %v != %v", x, y, a, b)
				}
			}
		}

	}
	return
}

func develop_serialize(input_data io.ReadSeeker) (err error) {
	img, _, err := OpenImageFromReader(input_data)
	if err != nil {
		return err
	}
	m, b := img.Serialize()
	rimg, err := ImageFromSerialized(m, b)
	if err != nil {
		return err
	}
	return images_equal(img, rimg)
}

func develop_resize(spec string, input_data io.ReadSeeker) (err error) {
	ws, hs, _ := strings.Cut(spec, "x")
	var w, h int
	if w, err = strconv.Atoi(ws); err != nil {
		return
	}
	if h, err = strconv.Atoi(hs); err != nil {
		return
	}
	img, _, err := OpenImageFromReader(input_data)
	if err != nil {
		return err
	}
	aimg := img.Resize(float64(w)/float64(img.Width), float64(h)/float64(img.Height))
	m, b := img.Serialize()
	rimg, err := ImageFromSerialized(m, b)
	if err != nil {
		return err
	}
	if err = images_equal(img, rimg); err != nil {
		return fmt.Errorf("roundtripped images not equal: %w", err)
	}
	bimg := rimg.Resize(float64(w)/float64(rimg.Width), float64(h)/float64(rimg.Height))
	return images_equal(aimg, bimg)
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
			input_data := bytes.NewReader(buf.Bytes())
			switch {
			case format == "develop-serialize":
				err = develop_serialize(input_data)
			case strings.HasPrefix(format, "develop-resize-"):
				err = develop_resize(format[len("develop-resize-"):], input_data)
			default:
				err = convert_image(input_data, os.Stdout, format)
			}
			rc = utils.IfElse(err == nil, 0, 1)
			return
		},
	})
}
