// License: GPLv3 Copyright: 2023, Kovid Goyal, <kovid at kovidgoyal.net>

package icat

import (
	"bytes"
	"encoding/json"
	"errors"
	"fmt"
	"image"
	"image/gif"
	"os"
	"os/exec"
	"path/filepath"
	"strconv"
	"strings"

	"kitty/tools/tui/graphics"
	"kitty/tools/utils"
	"kitty/tools/utils/images"
	"kitty/tools/utils/shm"
)

var _ = fmt.Print

var MagickExe = (&utils.Once[string]{Run: func() string {
	ans := utils.Which("magick")
	if ans == "" {
		ans = utils.Which("magick", "/usr/local/bin", "/opt/bin", "/opt/homebrew/bin", "/usr/bin", "/bin", "/usr/sbin", "/sbin")
	}
	return ans
}}).Get

func run_magick(path string, cmd []string) ([]byte, error) {
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
	FmtUppercase      string
	Gap               int
	Canvas            struct{ Width, Height, Left, Top int }
	Width, Height     int
	Dpi               struct{ X, Y float64 }
	Index             int
	Mode              graphics.GRT_f
	NeedsBlend        bool
	Disposal          int
	DimensionsSwapped bool
}

func parse_identify_record(ans *IdentifyRecord, raw *IdentifyOutput) (err error) {
	ans.FmtUppercase = strings.ToUpper(raw.Fmt)
	if raw.Gap != "" {
		ans.Gap, err = strconv.Atoi(raw.Gap)
		if err != nil {
			return fmt.Errorf("Invalid gap value in identify output: %s", raw.Gap)
		}
		ans.Gap = utils.Max(0, ans.Gap)
	}
	area, pos, found := utils.Cut(raw.Canvas, "+")
	ok := false
	if found {
		w, h, found := utils.Cut(area, "x")
		if found {
			ans.Canvas.Width, err = strconv.Atoi(w)
			if err == nil {
				ans.Canvas.Height, err = strconv.Atoi(h)
				if err == nil {
					x, y, found := utils.Cut(pos, "+")
					if found {
						ans.Canvas.Left, err = strconv.Atoi(x)
						if err == nil {
							ans.Canvas.Top, err = strconv.Atoi(y)
							ok = true
						}
					}
				}
			}
		}
	}
	if !ok {
		return fmt.Errorf("Invalid canvas value in identify output: %s", raw.Canvas)
	}
	w, h, found := utils.Cut(raw.Size, "x")
	ok = false
	if found {
		ans.Width, err = strconv.Atoi(w)
		if err == nil {
			ans.Height, err = strconv.Atoi(h)
			ok = true
		}
	}
	if !ok {
		return fmt.Errorf("Invalid size value in identify output: %s", raw.Size)
	}
	x, y, found := utils.Cut(raw.Dpi, "x")
	ok = false
	if found {
		ans.Dpi.X, err = strconv.ParseFloat(x, 64)
		if err == nil {
			ans.Dpi.Y, err = strconv.ParseFloat(y, 64)
			ok = true
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
		ans.Mode = graphics.GRT_format_rgba
	} else {
		ans.Mode = graphics.GRT_format_rgb
	}
	ans.NeedsBlend = q == "blend"
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
		ans.DimensionsSwapped = true
	}
	if ans.DimensionsSwapped {
		ans.Canvas.Width, ans.Canvas.Height = ans.Canvas.Height, ans.Canvas.Width
		ans.Width, ans.Height = ans.Height, ans.Width
	}

	return
}

func Identify(path string) (ans []IdentifyRecord, err error) {
	cmd := []string{"identify"}
	if MagickExe() != "" {
		cmd = []string{MagickExe(), cmd[0]}
	}
	q := `{"fmt":"%m","canvas":"%g","transparency":"%A","gap":"%T","index":"%p","size":"%wx%h",` +
		`"dpi":"%xx%y","dispose":"%D","orientation":"%[EXIF:Orientation]"},`
	cmd = append(cmd, "-format", q, "--", path)
	output, err := run_magick(path, cmd)
	if err != nil {
		return nil, err
	}
	output = bytes.TrimRight(bytes.TrimSpace(output), ",")
	raw_json := make([]byte, 0, len(output)+2)
	raw_json = append(raw_json, '[')
	raw_json = append(raw_json, output...)
	raw_json = append(raw_json, ']')
	var records []IdentifyOutput
	err = json.Unmarshal(raw_json, &records)
	if err != nil {
		return nil, fmt.Errorf("The ImageMagick identify program returned malformed output, with error: %w", err)
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
	RemoveAlpha    *images.NRGBColor
	Flip, Flop     bool
	ResizeTo       image.Point
	OnlyFirstFrame bool
}

func make_temp_dir() (ans string, err error) {
	if shm.SHM_DIR != "" {
		ans, err = os.MkdirTemp(shm.SHM_DIR, shm_template)
		if err == nil {
			return
		}
	}
	return os.MkdirTemp("", shm_template)
}

func check_resize(frame *image_frame) error {
	// ImageMagick sometimes generates RGBA images smaller than the specified
	// size. See https://github.com/kovidgoyal/kitty/issues/276 for examples
	s, err := os.Stat(frame.filename)
	if err != nil {
		return err
	}
	sz := int(s.Size())
	bytes_per_pixel := 4
	if frame.transmission_format == graphics.GRT_format_rgb {
		bytes_per_pixel = 3
	}
	expected_size := bytes_per_pixel * frame.width * frame.height
	if sz < expected_size {
		missing := expected_size - sz
		if missing%(bytes_per_pixel*frame.width) != 0 {
			return fmt.Errorf("ImageMagick failed to resize correctly. It generated %d < %d of data (w=%d h=%d bpp=%d)", sz, expected_size, frame.width, frame.height, bytes_per_pixel)
		}
		frame.height -= missing / (bytes_per_pixel * frame.width)
	}
	return nil
}

func Render(path string, ro *RenderOptions, frames []IdentifyRecord) (ans []*image_frame, err error) {
	cmd := []string{"convert"}
	if MagickExe() != "" {
		cmd = []string{MagickExe(), cmd[0]}
	}
	ans = make([]*image_frame, 0, len(frames))
	defer func() {
		if err != nil && ans != nil {
			for _, frame := range ans {
				if frame.filename_is_temporary {
					os.Remove(frame.filename)
				}
			}
			ans = nil
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
	tdir, err := make_temp_dir()
	if err != nil {
		err = fmt.Errorf("Failed to create temporary directory to hold ImageMagick output with error: %w", err)
		return
	}
	defer os.RemoveAll(tdir)
	mode := "rgba"
	if frames[0].Mode == graphics.GRT_format_rgb {
		mode = "rgb"
	}
	cmd = append(cmd, filepath.Join(tdir, "im-%[filename:f]."+mode))
	_, err = run_magick(path, cmd)
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
	min_gap := calc_min_gap(gaps)
	for _, entry := range entries {
		fname := entry.Name()
		p, _, _ := utils.Cut(fname, ".")
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
		_, pos, found := utils.Cut(parts[3], "+")
		if !found {
			continue
		}
		px, py, found := utils.Cut(pos, "+")
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
		df, cerr := os.CreateTemp(base_dir, graphics.TempTemplate+"."+mode)
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
		frame := image_frame{
			number: index + 1, width: width, height: height, left: x, top: y,
			transmission_format: identify_data.Mode, filename_is_temporary: true,
			filename: df.Name(),
		}
		frame.set_delay(identify_data.Gap, min_gap)
		err = check_resize(&frame)
		if err != nil {
			return
		}
		ans = append(ans, &frame)
	}
	if len(ans) < len(frames) {
		err = fmt.Errorf("Failed to render %d out of %d frames", len(frames)-len(ans), len(frames))
		return
	}
	ans = utils.Sort(ans, func(a, b *image_frame) bool { return a.number < b.number })
	anchor_frame := 1
	for i, frame := range ans {
		anchor_frame = frame.set_disposal(anchor_frame, byte(frames[i].Disposal))
	}
	return
}

func render_image_with_magick(imgd *image_data, src *opened_input) (err error) {
	err = src.PutOnFilesystem()
	if err != nil {
		return err
	}
	frames, err := Identify(src.FileSystemName())
	if err != nil {
		return err
	}
	imgd.format_uppercase = frames[0].FmtUppercase
	imgd.canvas_width, imgd.canvas_height = frames[0].Canvas.Width, frames[0].Canvas.Height
	set_basic_metadata(imgd)
	if !imgd.needs_conversion {
		make_output_from_input(imgd, src)
		return nil
	}
	ro := RenderOptions{RemoveAlpha: remove_alpha, Flip: flip, Flop: flop}
	if scale_image(imgd) {
		ro.ResizeTo.X, ro.ResizeTo.Y = imgd.canvas_width, imgd.canvas_height
	}
	imgd.frames, err = Render(src.FileSystemName(), &ro, frames)
	if err != nil {
		return err
	}
	return nil
}
