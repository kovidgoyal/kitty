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

	"github.com/kovidgoyal/kitty/tools/cli"
	"github.com/kovidgoyal/kitty/tools/tty"
	"github.com/kovidgoyal/kitty/tools/tui"
	"github.com/kovidgoyal/kitty/tools/tui/graphics"
	"github.com/kovidgoyal/kitty/tools/utils"
	"github.com/kovidgoyal/kitty/tools/utils/images"
	"github.com/kovidgoyal/kitty/tools/utils/style"

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

var transfer_by_file, transfer_by_memory transfer_mode

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
	area, pos, found := strings.Cut(opts.Place, "@")
	if !found {
		return fmt.Errorf("Invalid --place specification: %s", opts.Place)
	}
	w, h, found := strings.Cut(area, "x")
	if !found {
		return fmt.Errorf("Invalid --place specification: %s", opts.Place)
	}
	l, t, found := strings.Cut(pos, "x")
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
	if opts.UseWindowSize == "" {
		if tty.IsTerminal(os.Stdout.Fd()) {
			screen_size, err = tty.GetSize(int(os.Stdout.Fd()))
		} else {
			t, oerr := tty.OpenControllingTerm()
			if oerr != nil {
				return 1, fmt.Errorf("Failed to open controlling terminal with error: %w", oerr)
			}
			screen_size, err = t.GetSize()
		}
		if err != nil {
			return 1, fmt.Errorf("Failed to query terminal using TIOCGWINSZ with error: %w", err)
		}
	} else {
		parts := strings.SplitN(opts.UseWindowSize, ",", 4)
		if len(parts) != 4 {
			return 1, fmt.Errorf("Invalid size specification: " + opts.UseWindowSize)
		}
		screen_size = &unix.Winsize{}
		var t uint64
		if t, err = strconv.ParseUint(parts[0], 10, 16); err != nil || t < 1 {
			return 1, fmt.Errorf("Invalid size specification: %s with error: %w", opts.UseWindowSize, err)
		}
		screen_size.Col = uint16(t)
		if t, err = strconv.ParseUint(parts[1], 10, 16); err != nil || t < 1 {
			return 1, fmt.Errorf("Invalid size specification: %s with error: %w", opts.UseWindowSize, err)
		}
		screen_size.Row = uint16(t)
		if t, err = strconv.ParseUint(parts[2], 10, 16); err != nil || t < 1 {
			return 1, fmt.Errorf("Invalid size specification: %s with error: %w", opts.UseWindowSize, err)
		}
		screen_size.Xpixel = uint16(t)
		if t, err = strconv.ParseUint(parts[3], 10, 16); err != nil || t < 1 {
			return 1, fmt.Errorf("Invalid size specification: %s with error: %w", opts.UseWindowSize, err)
		}
		screen_size.Ypixel = uint16(t)
		if screen_size.Xpixel < screen_size.Col {
			return 1, fmt.Errorf("Invalid size specification: %s with error: The pixel width is smaller than the number of columns", opts.UseWindowSize)
		}
		if screen_size.Ypixel < screen_size.Row {
			return 1, fmt.Errorf("Invalid size specification: %s with error: The pixel height is smaller than the number of rows", opts.UseWindowSize)
		}
	}

	if opts.PrintWindowSize {
		fmt.Printf("%dx%d", screen_size.Xpixel, screen_size.Ypixel)
		return 0, nil
	}
	if opts.Clear {
		cc := &graphics.GraphicsCommand{}
		cc.SetAction(graphics.GRT_action_delete).SetDelete(graphics.GRT_free_visible)
		if err = cc.WriteWithPayloadTo(os.Stdout, nil); err != nil {
			return 1, err
		}
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
		for range num_workers {
			go run_worker()
		}
	}

	passthrough_mode := no_passthrough
	switch opts.Passthrough {
	case "tmux":
		passthrough_mode = tmux_passthrough
	case "detect":
		if tui.TmuxSocketAddress() != "" {
			passthrough_mode = tmux_passthrough
		}
	}

	if passthrough_mode == no_passthrough && (opts.TransferMode == "detect" || opts.DetectSupport) {
		memory, files, direct, err := DetectSupport(time.Duration(opts.DetectionTimeout * float64(time.Second)))
		if err != nil {
			return 1, err
		}
		if !direct {
			keep_going.Store(false)
			return 1, fmt.Errorf("This terminal does not support the graphics protocol use a terminal such as kitty, WezTerm or Konsole that does. If you are running inside a terminal multiplexer such as tmux or screen that might be interfering as well.")
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
	if passthrough_mode != no_passthrough {
		// tmux doesn't allow responses from the terminal so we can't detect if memory or file based transferring is supported
		transfer_by_memory = unsupported
		transfer_by_file = unsupported
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
	use_unicode_placeholder := opts.UnicodePlaceholder
	if passthrough_mode != no_passthrough {
		use_unicode_placeholder = true
	}
	base_id := uint32(opts.ImageId)
	for num_of_items > 0 {
		imgd := <-output_channel
		if base_id != 0 {
			imgd.image_id = base_id
			base_id++
			if base_id == 0 {
				base_id++
			}
		}
		imgd.use_unicode_placeholder = use_unicode_placeholder
		imgd.passthrough_mode = passthrough_mode
		num_of_items--
		if imgd.err != nil {
			print_error("Failed to process \x1b[31m%s\x1b[39m: %s\r\n", imgd.source_name, imgd.err)
		} else {
			transmit_image(imgd, opts.NoTrailingNewline)
			if imgd.err != nil {
				print_error("Failed to transmit \x1b[31m%s\x1b[39m: %s\r\n", imgd.source_name, imgd.err)
			}
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
