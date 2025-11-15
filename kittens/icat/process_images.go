// License: GPLv3 Copyright: 2022, Kovid Goyal, <kovid at kovidgoyal.net>

package icat

import (
	"bytes"
	"fmt"
	"image"
	"io"
	"io/fs"
	"math"
	"net/http"
	"net/url"
	"os"
	"path/filepath"
	"strings"

	"github.com/kovidgoyal/imaging"
	"github.com/kovidgoyal/kitty/tools/tty"
	"github.com/kovidgoyal/kitty/tools/tui/graphics"
	"github.com/kovidgoyal/kitty/tools/utils"
	"github.com/kovidgoyal/kitty/tools/utils/images"
)

var _ = fmt.Print

type input_arg struct {
	arg         string
	value       string
	is_http_url bool
}

func is_http_url(arg string) bool {
	return strings.HasPrefix(arg, "https://") || strings.HasPrefix(arg, "http://")
}

func process_dirs(args ...string) (results []input_arg, err error) {
	results = make([]input_arg, 0, 64)
	if opts.Stdin != "no" && (opts.Stdin == "yes" || !tty.IsTerminal(os.Stdin.Fd())) {
		results = append(results, input_arg{arg: "/dev/stdin"})
	}
	for _, arg := range args {
		if arg != "" {
			if is_http_url(arg) {
				results = append(results, input_arg{arg: arg, value: arg, is_http_url: true})
			} else {
				if strings.HasPrefix(arg, "file://") {
					u, err := url.Parse(arg)
					if err != nil {
						return nil, &fs.PathError{Op: "Parse", Path: arg, Err: err}
					}
					arg = u.Path
				}
				s, err := os.Stat(arg)
				if err != nil {
					return nil, &fs.PathError{Op: "Stat", Path: arg, Err: err}
				}
				if s.IsDir() {
					if err = filepath.WalkDir(arg, func(path string, d fs.DirEntry, walk_err error) error {
						if walk_err != nil {
							if d == nil {
								err = &fs.PathError{Op: "Stat", Path: arg, Err: walk_err}
							}
							return walk_err
						}
						if !d.IsDir() {
							mt := utils.GuessMimeType(path)
							if strings.HasPrefix(mt, "image/") {
								results = append(results, input_arg{arg: arg, value: path})
							}
						}
						return nil
					}); err != nil {
						return nil, err
					}
				} else {
					results = append(results, input_arg{arg: arg, value: arg})
				}
			}
		}
	}
	return results, nil
}

type opened_input struct {
	file  io.Reader
	bytes []byte
	path  string
}

type image_frame struct {
	filename                 string
	in_memory_bytes          []byte
	width, height, left, top int
	transmission_format      graphics.GRT_f
	compose_onto             int
	replace                  bool
	number                   int
	delay_ms                 int
}

type image_data struct {
	canvas_width, canvas_height       int
	format_uppercase                  string
	available_width, available_height int
	needs_scaling                     bool
	frames                            []*image_frame
	image_number                      uint32
	image_id                          uint32
	cell_x_offset                     int
	move_x_by                         int
	move_to                           struct{ x, y int }
	width_cells, height_cells         int
	use_unicode_placeholder           bool
	passthrough_mode                  passthrough_type

	// for error reporting
	err         error
	source_name string
}

const inf = math.MaxInt

func set_basic_metadata(imgd *image_data) {
	if imgd.frames == nil {
		imgd.frames = make([]*image_frame, 0, 32)
	}
	if place != nil {
		imgd.available_width = place.width * int(screen_size.Xpixel) / int(screen_size.Col)
		imgd.available_height = place.height * int(screen_size.Ypixel) / int(screen_size.Row)
	} else {
		switch fit_mode {
		case fit_none:
			imgd.available_width, imgd.available_height = inf, inf
		case fit_both:
			imgd.available_width = int(screen_size.Xpixel)
			imgd.available_height = int(screen_size.Ypixel)
		case fit_width:
			imgd.available_width = int(screen_size.Xpixel)
			imgd.available_height = inf
		case fit_height:
			imgd.available_width = inf
			imgd.available_height = int(screen_size.Ypixel)
		}
	}
	imgd.needs_scaling = imgd.canvas_width > imgd.available_width || imgd.canvas_height > imgd.available_height || opts.ScaleUp
}

func report_error(source_name, msg string, err error) {
	imgd := image_data{source_name: source_name, err: fmt.Errorf("%s: %w", msg, err)}
	send_output(&imgd)
}

func make_output_from_input(imgd *image_data, f *opened_input) {
	frame := image_frame{}
	imgd.frames = append(imgd.frames, &frame)
	frame.width = imgd.canvas_width
	frame.height = imgd.canvas_height
	if imgd.format_uppercase != "PNG" {
		panic(fmt.Sprintf("Unknown transmission format: %s", imgd.format_uppercase))
	}
	frame.transmission_format = graphics.GRT_format_png
	if f.bytes != nil {
		frame.in_memory_bytes = f.bytes
	} else if f.path != "" {
		frame.filename = f.path
	} else {
		var err error
		if frame.in_memory_bytes, err = io.ReadAll(f.file); err != nil {
			panic(err)
		}
	}
}

func scale_up(width, height, maxWidth, maxHeight int) (newWidth, newHeight int) {
	if width == 0 || height == 0 {
		return 0, 0
	}
	// Calculate the ratio to scale the width and the ratio to scale the height.
	// We use floating-point division for precision.
	widthRatio := float64(maxWidth) / float64(width)
	heightRatio := float64(maxHeight) / float64(height)

	// To preserve the aspect ratio and fit within the limits, we must use the
	// smaller of the two scaling ratios.
	var ratio float64
	if widthRatio < heightRatio {
		ratio = widthRatio
	} else {
		ratio = heightRatio
	}

	// Calculate the new dimensions and convert them back to uints.
	newWidth = int(float64(width) * ratio)
	newHeight = int(float64(height) * ratio)

	return newWidth, newHeight
}

func scale_image(imgd *image_data) bool {
	if imgd.needs_scaling {
		width, height := imgd.canvas_width, imgd.canvas_height
		if opts.ScaleUp && (imgd.canvas_width < imgd.available_width || imgd.canvas_height < imgd.available_height) && (imgd.available_height != inf || imgd.available_width != inf) {
			imgd.canvas_width, imgd.canvas_height = scale_up(imgd.canvas_width, imgd.canvas_height, imgd.available_width, imgd.available_height)
		}
		neww, newh := images.FitImage(imgd.canvas_width, imgd.canvas_height, imgd.available_width, imgd.available_height)
		imgd.needs_scaling = false
		x := float64(neww) / float64(width)
		y := float64(newh) / float64(height)
		imgd.canvas_width = int(x * float64(width))
		imgd.canvas_height = int(y * float64(height))
		return true
	}
	return false
}

func add_frame(imgd *image_data, img image.Image, left, top int) *image_frame {
	const shm_template = "kitty-icat-*"
	num_channels := 4
	var pix []byte
	if imaging.IsOpaque(img) {
		num_channels, pix = 3, imaging.AsRGBData8(img)
	} else {
		pix = imaging.AsRGBAData8(img)
	}
	b := img.Bounds()
	f := image_frame{width: b.Dx(), height: b.Dy(), number: len(imgd.frames) + 1, left: left, top: top}
	f.transmission_format = utils.IfElse(num_channels == 3, graphics.GRT_format_rgb, graphics.GRT_format_rgba)
	f.in_memory_bytes = pix
	imgd.frames = append(imgd.frames, &f)
	return &f
}

func process_arg(arg input_arg) {
	var f opened_input
	if arg.is_http_url {
		resp, err := http.Get(arg.value)
		if err != nil {
			report_error(arg.value, "Could not get", err)
			return
		}
		defer resp.Body.Close()
		if resp.StatusCode != http.StatusOK {
			report_error(arg.value, "Could not get", fmt.Errorf("bad status: %v", resp.Status))
			return
		}
		dest := bytes.Buffer{}
		dest.Grow(64 * 1024)
		_, err = io.Copy(&dest, resp.Body)
		if err != nil {
			report_error(arg.value, "Could not download", err)
			return
		}
		f.bytes = dest.Bytes()
		f.file = bytes.NewReader(f.bytes)
	} else if arg.value == "" {
		stdin, err := io.ReadAll(os.Stdin)
		if err != nil {
			report_error("<stdin>", "Could not read from", err)
			return
		}
		f.bytes = stdin
		f.file = bytes.NewReader(f.bytes)
	} else {
		q, err := os.Open(arg.value)
		if err != nil {
			report_error(arg.value, "Could not open", err)
			return
		}
		f.file = q
		f.path = q.Name()
		defer q.Close()
	}

	var img *images.ImageData
	var dopts []imaging.DecodeOption
	needs_conversion := false
	if flip {
		dopts = append(dopts, imaging.Transform(imaging.FlipVTransform))
		needs_conversion = true
	}
	if flop {
		dopts = append(dopts, imaging.Transform(imaging.FlipHTransform))
		needs_conversion = true
	}
	if remove_alpha != nil {
		dopts = append(dopts, imaging.Background(*remove_alpha))
		needs_conversion = true
	}
	switch opts.Engine {
	case "native", "builtin":
		dopts = append(dopts, imaging.Backends(imaging.GO_IMAGE))
	case "magick":
		dopts = append(dopts, imaging.Backends(imaging.MAGICK_IMAGE))
	}
	imgd := image_data{source_name: arg.value}
	dopts = append(dopts, imaging.ResizeCallback(func(w, h int) (int, int) {
		imgd.canvas_width, imgd.canvas_height = w, h
		set_basic_metadata(&imgd)
		if scale_image(&imgd) {
			needs_conversion = true
			w, h = imgd.canvas_width, imgd.canvas_height
		}
		return w, h
	}))
	var err error
	if f.path != "" {
		img, err = images.OpenImageFromPath(f.path, dopts...)
	} else {
		img, f.file, err = images.OpenImageFromReader(f.file, dopts...)
	}
	if err != nil {
		report_error(arg.value, "Could not render image to RGB", err)
		return
	}
	if !keep_going.Load() {
		return
	}
	imgd.format_uppercase = img.Format_uppercase
	imgd.canvas_width, imgd.canvas_height = img.Width, img.Height
	if !needs_conversion && imgd.format_uppercase == "PNG" && len(img.Frames) == 1 {
		make_output_from_input(&imgd, &f)
	} else {
		for _, f := range img.Frames {
			frame := add_frame(&imgd, f.Img, f.Left, f.Top)
			frame.number, frame.compose_onto = int(f.Number), int(f.Compose_onto)
			frame.replace = f.Replace
			frame.delay_ms = int(f.Delay_ms)
		}
	}
	if !keep_going.Load() {
		return
	}
	send_output(&imgd)
}

func run_worker() {
	for {
		select {
		case arg := <-files_channel:
			if !keep_going.Load() {
				return
			}
			process_arg(arg)
		default:
			return
		}
	}
}
