// License: GPLv3 Copyright: 2022, Kovid Goyal, <kovid at kovidgoyal.net>

package icat

import (
	"fmt"
	"os"
	"runtime"
	"strconv"
	"strings"
	"sync/atomic"
	"time"

	"kitty/tools/cli"
	"kitty/tools/tty"
	"kitty/tools/tui"
	"kitty/tools/tui/graphics"
	"kitty/tools/utils"
	"kitty/tools/utils/images"
	"kitty/tools/utils/style"

	"golang.org/x/sys/unix"
)

var _ = fmt.Print

type Place struct {
	width, height, left, top int
}

var opts *Options
var place *Place
var z_index int32
var remove_alpha *images.NRGBColor
var flip, flop bool

type transfer_mode int

const (
	unknown transfer_mode = iota
	unsupported
	supported
)

var transfer_by_file, transfer_by_memory, transfer_by_stream transfer_mode

var files_channel chan input_arg
var output_channel chan *image_data
var num_of_items int
var keep_going *atomic.Bool
var screen_size *unix.Winsize

func send_output(imgd *image_data) {
	output_channel <- imgd
}

func parse_mirror() (err error) {
	flip = opts.Mirror == "both" || opts.Mirror == "vertical"
	flop = opts.Mirror == "both" || opts.Mirror == "horizontal"
	return
}

func parse_background() (err error) {
	if opts.Background == "" || opts.Background == "none" {
		return nil
	}
	col, err := style.ParseColor(opts.Background)
	if err != nil {
		return fmt.Errorf("Invalid value for --background: %w", err)
	}
	remove_alpha = &images.NRGBColor{R: col.Red, G: col.Green, B: col.Blue}
	return
}

func parse_z_index() (err error) {
	val := opts.ZIndex
	var origin int32
	if strings.HasPrefix(val, "--") {
		origin = -1073741824
		val = val[1:]
	}
	i, err := strconv.ParseInt(val, 10, 32)
	if err != nil {
		return fmt.Errorf("Invalid value for --z-index with error: %w", err)
	}
	z_index = int32(i) + origin
	return
}

func parse_place() (err error) {
	if opts.Place == "" {
		return nil
	}
	area, pos, found := utils.Cut(opts.Place, "@")
	if !found {
		return fmt.Errorf("Invalid --place specification: %s", opts.Place)
	}
	w, h, found := utils.Cut(area, "x")
	if !found {
		return fmt.Errorf("Invalid --place specification: %s", opts.Place)
	}
	l, t, found := utils.Cut(pos, "x")
	if !found {
		return fmt.Errorf("Invalid --place specification: %s", opts.Place)
	}
	place = &Place{}
	place.width, err = strconv.Atoi(w)
	if err != nil {
		return err
	}
	place.height, err = strconv.Atoi(h)
	if err != nil {
		return err
	}
	place.left, err = strconv.Atoi(l)
	if err != nil {
		return err
	}
	place.top, err = strconv.Atoi(t)
	if err != nil {
		return err
	}
	return nil
}

func print_error(format string, args ...any) {
	fmt.Fprintf(os.Stderr, format, args...)
	fmt.Fprintln(os.Stderr)
}

func main(cmd *cli.Command, o *Options, args []string) (rc int, err error) {
	opts = o
	err = parse_place()
	if err != nil {
		return 1, err
	}
	err = parse_z_index()
	if err != nil {
		return 1, err
	}
	err = parse_background()
	if err != nil {
		return 1, err
	}
	err = parse_mirror()
	if err != nil {
		return 1, err
	}
	t, err := tty.OpenControllingTerm()
	if err != nil {
		return 1, fmt.Errorf("Failed to open controlling terminal with error: %w", err)
	}
	screen_size, err = t.GetSize()
	if err != nil {
		return 1, fmt.Errorf("Failed to query terminal using TIOCGWINSZ with error: %w", err)
	}

	if opts.PrintWindowSize {
		fmt.Printf("%dx%d", screen_size.Xpixel, screen_size.Ypixel)
		return 0, nil
	}
	if opts.Clear {
		cc := &graphics.GraphicsCommand{}
		cc.SetAction(graphics.GRT_action_delete).SetDelete(graphics.GRT_free_visible)
		cc.WriteWithPayloadTo(os.Stdout, nil)
	}
	if screen_size.Xpixel == 0 || screen_size.Ypixel == 0 {
		return 1, fmt.Errorf("Terminal does not support reporting screen sizes in pixels, use a terminal such as kitty, WezTerm, Konsole, etc. that does.")
	}

	items, err := process_dirs(args...)
	if err != nil {
		return 1, err
	}
	if opts.Place != "" && len(items) > 1 {
		return 1, fmt.Errorf("The --place option can only be used with a single image, not %d", len(items))
	}
	files_channel = make(chan input_arg, len(items))
	for _, ia := range items {
		files_channel <- ia
	}
	num_of_items = len(items)
	output_channel = make(chan *image_data, 1)
	keep_going = &atomic.Bool{}
	keep_going.Store(true)
	if !opts.DetectSupport && num_of_items > 0 {
		num_workers := utils.Max(1, utils.Min(num_of_items, runtime.NumCPU()))
		for i := 0; i < num_workers; i++ {
			go run_worker()
		}
	}

	if opts.TransferMode == "detect" || opts.DetectSupport {
		memory, files, direct, err := DetectSupport(time.Duration(opts.DetectionTimeout * float64(time.Second)))
		if err != nil {
			return 1, err
		}
		if !direct {
			keep_going.Store(false)
			return 1, fmt.Errorf("This terminal does not support the graphics protocol use a terminal such as kitty, WezTerm or Konsole that does")
		}
		if memory {
			transfer_by_memory = supported
		} else {
			transfer_by_memory = unsupported
		}
		if files {
			transfer_by_file = supported
		} else {
			transfer_by_file = unsupported
		}
	}
	if opts.DetectSupport {
		if transfer_by_memory == supported {
			print_error("memory")
		} else if transfer_by_file == supported {
			print_error("files")
		} else {
			print_error("stream")
		}
		return 0, nil
	}
	for num_of_items > 0 {
		imgd := <-output_channel
		num_of_items--
		if imgd.err != nil {
			print_error("Failed to process \x1b[31m%s\x1b[39m: %v\r\n", imgd.source_name, imgd.err)
		} else {
			transmit_image(imgd)
		}
	}
	keep_going.Store(false)
	if opts.Hold {
		fmt.Print("\r")
		if opts.Place != "" {
			fmt.Println()
		}
		tui.HoldTillEnter(false)
	}
	return 0, nil
}

func EntryPoint(parent *cli.Command) {
	create_cmd(parent, main)
}
