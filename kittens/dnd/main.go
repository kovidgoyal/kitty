// License: GPLv3 Copyright: 2022, Kovid Goyal, <kovid at kovidgoyal.net>

package dnd

import (
	"bytes"
	"fmt"
	"io"
	"maps"
	"net/url"
	"os"
	"path/filepath"
	"runtime"
	"slices"
	"strings"

	"github.com/kovidgoyal/kitty/tools/cli"
	"github.com/kovidgoyal/kitty/tools/tty"
	"github.com/kovidgoyal/kitty/tools/tui/loop"
	"github.com/kovidgoyal/kitty/tools/utils"
	"github.com/kovidgoyal/kitty/tools/wcswidth"
)

var _ = fmt.Append
var debugprintln = tty.DebugPrintln
var _ = debugprintln

type uri_list_item struct {
	path, uri, human_name string
	file                  *os.File
}

type drag_source struct {
	human_name, path string
	file             *os.File
	mime_type        string
	uri_list         []uri_list_item
	data             []byte
}

type bufferWriteCloser struct {
	*bytes.Buffer
}

// Close implements the io.Closer interface (as a no-op)
func (bwc *bufferWriteCloser) Close() error {
	return nil
}

type drop_dest struct {
	human_name, path string
	dest             io.WriteCloser
	mime_type        string
	completed        bool
}

type button_region struct {
	left, width, top, height int
}

func (r button_region) has(x, y int) bool {
	return r.left <= x && x < r.left+r.width && r.top <= y && y < r.top+r.height
}

type DC = loop.DndCommand

func truncate_at_space(text string, width int) (string, string) {
	truncated, p := wcswidth.TruncateToVisualLengthWithWidth(text, width)
	if len(truncated) == len(text) {
		return text, ""
	}
	i := strings.LastIndexByte(truncated, ' ')
	if i > 0 && p-i < 12 {
		p = i + 1
	}
	return text[:p], text[p:]
}

type drop_status struct {
	offered_mimes        []string
	accepted_mimes       []string
	cell_x, cell_y       int
	action               int
	in_window            bool
	reading_data         bool
	is_remote_client     bool
	remote_phase_started bool
}

func paragraph_as_lines(text string, width int) (ans []string) {
	for text != "" {
		var line string
		if line, text = truncate_at_space(text, width); line != "" {
			ans = append(ans, line)
		}
	}
	return
}

func run_loop(opts *Options, drop_dests map[string]*drop_dest, drag_sources map[string]drag_source, uri_list_buffer *bytes.Buffer) (err error) {
	allow_drops, allow_drags := len(drop_dests) > 0, len(drag_sources) > 0
	data_has_been_dropped := false
	drag_started := false
	in_test_mode := false
	lp, err := loop.New()
	if err != nil {
		return err
	}

	send_test_response := func(payload string) {
		lp.DebugPrintln(payload)
	}

	drop_status := drop_status{cell_x: -1, cell_y: -1}
	reset_drop_status := drop_status
	drop_status.cell_x, drop_status.cell_y = -1, -1
	const copy_on_drop = 1
	const move_on_drop = 2

	var copy_button_region, move_button_region button_region
	var offered_mimes_buf strings.Builder

	render_screen := func() error { // {{{
		if !in_test_mode {
			lp.StartAtomicUpdate()
			defer lp.EndAtomicUpdate()
		}
		lp.ClearScreen()
		copy_button_region, move_button_region = button_region{}, button_region{}
		if drag_started {
			lp.Println("Dragging data...")
			return nil
		}
		if drop_status.reading_data {
			lp.Println("Reading dropped data, please wait...")
			return nil
		}
		y := 0
		sz, _ := lp.ScreenSize()
		render_paragraph := func(text string) {
			for _, line := range paragraph_as_lines(text, int(sz.WidthCells)) {
				lp.Println(line)
				y++
			}
		}
		next_line := func() {
			lp.Println()
			y++
		}
		if drop_status.in_window {
			if drop_status.action == 0 {
				render_paragraph("A drag is active. Drop it into one of the boxes below to perform that action on the dragged data. Available MIME types in the drag:")
				next_line()
				render_paragraph(strings.Join(drop_status.offered_mimes, " "))
			} else {
				render_paragraph("The drag can be dropped. Supported MIME types:")
				next_line()
				render_paragraph(strings.Join(drop_status.accepted_mimes, " "))
			}
		} else {
			// Neither active drag nor drop over window
			if allow_drags {
				render_paragraph(`Start dragging anywhere in this window to initiate a drag and drop. If you start the drag in one of the Copy or Move boxes below, only that action will be allowed when dropping, otherwise, the drop destination can pick either copy or move.`)
				next_line()
			}
			if allow_drops {
				if data_has_been_dropped {
					render_paragraph(`Data has been successfully dropped. You can drop more data or press Esc to quit.`)
				} else {
					render_paragraph(`Drag some data from another application into this window to transfer the files here.`)
				}
			}
		}
		frame_width, padding_width := 4, 8
		text_width := len("copymove")
		scale := 5
		for scale > 1 && frame_width+padding_width+text_width*scale > int(sz.WidthCells) {
			scale--
		}
		height := scale + 4
		boxy := 1 + max(0, int(sz.HeightCells)-height)
		lp.MoveCursorTo(1, boxy)
		lp.ClearToEndOfScreen()

		render_box := func(x int, text string, r *button_region) {
			width := scale*wcswidth.Stringwidth(text) + 6
			r.left = x - 1
			r.top = boxy - 1
			r.width = width
			r.height = height
			lp.MoveCursorTo(x, boxy)
			for i := range height {
				lp.SaveCursorPosition()
				switch i {
				case 0:
					lp.QueueWriteString("╭")
					lp.QueueWriteString(strings.Repeat("─", width-2))
					lp.QueueWriteString("╮")
				case height - 1:
					lp.QueueWriteString("╰")
					lp.QueueWriteString(strings.Repeat("─", width-2))
					lp.QueueWriteString("╯")
				default:
					lp.QueueWriteString("│")
					if i == 2 {
						lp.MoveCursorHorizontally(2)
						lp.DrawSizedText(text, loop.SizedText{Scale: scale})
					}
					lp.MoveCursorTo(x+width-1, boxy+i)
					lp.QueueWriteString("│")
				}
				lp.RestoreCursorPosition()
				lp.MoveCursorVertically(1)
			}
		}
		const fg = 32
		if drop_status.action == copy_on_drop {
			lp.Printf("\x1b[%dm", fg)
		}
		render_box(1, "Copy", &copy_button_region)
		lp.QueueWriteString("\x1b[39m")
		box_width := 6 + len("move")*scale
		if drop_status.action == move_on_drop {
			lp.Printf("\x1b[%dm", fg)
		}
		render_box(1+int(sz.WidthCells)-box_width, "Move", &move_button_region)
		lp.QueueWriteString("\x1b[39m")
		_ = in_test_mode
		return nil
	} // }}}

	// Drop handling {{{
	end_drop := func() {
		lp.QueueDnDData(DC{Type: 'r'}) // end drop
		drop_status = reset_drop_status
		render_screen()
	}

	all_mime_data_dropped := func() error {
		if _, found := drop_dests["text/uri-list"]; found && drop_status.is_remote_client {
			// TODO: Handle remote client
		} else {
			drop_status = reset_drop_status
			data_has_been_dropped = true
			render_screen()
		}
		return nil
	}

	request_mime_data := func() {
		for idx := range drop_status.accepted_mimes {
			lp.QueueDnDData(DC{Type: 'r', X: idx + 1})
		}
	}

	on_drop_move := func(cell_x, cell_y int, has_more bool, offered_mimes string, is_drop bool) (needs_rerender bool) {
		prev_status := drop_status
		drop_status.cell_x, drop_status.cell_y = cell_x, cell_y
		if offered_mimes != "" {
			offered_mimes_buf.WriteString(offered_mimes)
			if has_more {
				return
			}
			offered_mimes := offered_mimes_buf.String()
			drop_status.offered_mimes = strings.Fields(offered_mimes)
			drop_status.accepted_mimes = make([]string, 0, len(drop_status.offered_mimes))
			seen := utils.NewSet[string](len(drop_status.offered_mimes))
			for _, x := range drop_status.offered_mimes {
				if _, found := drop_dests[x]; found && !seen.Has(x) {
					drop_status.accepted_mimes = append(drop_status.accepted_mimes, x)
					seen.Add(x)
				}
			}
		}
		offered_mimes_buf.Reset()
		if copy_button_region.has(cell_x, cell_y) {
			drop_status.action = copy_on_drop
		} else if move_button_region.has(cell_x, cell_y) {
			drop_status.action = move_on_drop
		} else {
			switch opts.DropAnywhere {
			case "disallowed":
				drop_status.action = 0
				drop_status.accepted_mimes = nil
			case "copy":
				drop_status.action = copy_on_drop
			case "move":
				drop_status.action = move_on_drop
			}
		}
		drop_status.in_window = cell_x > -1 && cell_y > -1
		if !drop_status.in_window || drag_started { // disallow self drag and drop
			drop_status = reset_drop_status
		}
		mimes_changed := !slices.Equal(prev_status.accepted_mimes, drop_status.accepted_mimes)
		needs_rerender = prev_status.action != drop_status.action || mimes_changed
		if needs_rerender && !is_drop {
			c := DC{Type: 'm', Operation: drop_status.action}
			if drop_status.action != 0 && len(drop_status.accepted_mimes) > 0 {
				c.Payload = utils.UnsafeStringToBytes(strings.Join(drop_status.accepted_mimes, " "))
			}
			lp.QueueDnDData(c)
		}
		needs_rerender = needs_rerender || drop_status.in_window != prev_status.in_window
		if is_drop {
			needs_rerender = true
			if drop_status.action == 0 || len(drop_status.accepted_mimes) == 0 || drag_started {
				end_drop()
				return
			}
			drop_status.reading_data = true
			request_mime_data()
		}
		return
	}

	on_remote_drop_data := func(cmd DC) error {
		// TODO: Implement this
		return nil
	}

	on_drop_data := func(cmd DC) error {
		if drop_status.remote_phase_started {
			return on_remote_drop_data(cmd)
		}
		idx := cmd.X - 1
		if idx < 0 || idx > len(drop_status.accepted_mimes) {
			return fmt.Errorf("terminal sent drop data for a index outside the list of accepted MIMEs")
		}
		mime := drop_status.accepted_mimes[idx]
		dest := drop_dests[mime]
		if cmd.Xp == 1 && mime == "text/uri-list" {
			drop_status.is_remote_client = true
		}
		if !cmd.Has_more && len(cmd.Payload) == 0 {
			dest.completed = true
			pending := false
			for _, d := range drop_dests {
				if !d.completed {
					pending = true
					break
				}
			}
			if !pending {
				return all_mime_data_dropped()
			}
			return nil
		}
		// TODO: Implement this
		return nil
	}
	// }}}

	lp.OnInitialize = func() (string, error) {
		lp.AllowLineWrapping(false)
		lp.SetCursorVisible(false)
		if allow_drops {
			lp.StartAcceptingDrops(opts.MachineId, slices.Collect(maps.Keys(drop_dests))...)
		}
		if allow_drags {
			lp.StartOfferingDrags(opts.MachineId)
		}
		lp.SetWindowTitle("Drag and drop")
		return "", render_screen()
	}

	lp.OnFinalize = func() string {
		lp.AllowLineWrapping(true)
		lp.SetCursorVisible(true)
		if allow_drops {
			lp.StopAcceptingDrops()
		}
		if allow_drags {
			lp.StopOfferingDrags()
		}
		return ""
	}

	lp.OnDnDData = func(cmd loop.DndCommand) error {
		// TODO: Use lp.QueueDnDData to implement drag and drop protocol
		// If allow_drags, start a drag when the terminal sends the t=o
		// event. Presend data for any drag_source objects that have non nil
		// data fields and whose data size is <= 1MB. Set drag_started to true.
		// reset drag_started at the end of the drag. Use opts.DragAction to
		// set what actions are allowed.

		// If a drop enters the window and has one or more MIME types present
		// in drop_dests, accept the drop, unless drag_started is true.

		// Redraw the screen whenever drag or drop status changes.

		// When a drop happens, write all data for the MIME types present in
		// both drop_dests and the actual dropped data. For the text/uri-list
		// type if the terminal indicates it is coming from a remote machine
		// request the data for the file:// entries from the uri-list using the
		// dnd protocol and write it, otherwise, copy the file URLs using
		// normal file system operations. If opts.ConfirmDropOverwrite is true
		// then when some data would overwrite existing file, put it into a
		// temp file instead and after all data is transferred as the user for
		// confirmation and overwrite or not accordingly. While a drop is in
		// progress the render_screen() function should hide the drop
		// destination buttons and instead show the text "Drop in progress,
		// reading data..."
		// Be very careful when writing dropped data from uri-list nothing
		// should be written outside the destination directory (the current
		// working directory by default). In particular, symlinks must be
		// handled with care.

		// When acting as a drag source, dont forget to implement support for
		// remote dragging, which means providing data for the text/uri-list
		// mime type file:// entries when the terminal requests it using the
		// dnd protocol. If the action chosen is move, delete the files
		// corresponding to the drag sources, including the files in the
		// uri-list and exit.

		switch cmd.Type {
		case 'T':
			switch string(cmd.Payload) {
			case "PING":
				send_test_response("PONG")
			case "SETUP":
				in_test_mode = true
				lp.NoRoundtripToTerminalOnExit()
			case "GEOMETRY":
				send_test_response(fmt.Sprintf("GEOMETRY:%d:%d:%d:%d:%d:%d:%d:%d", copy_button_region.left, copy_button_region.top, copy_button_region.width, copy_button_region.height, move_button_region.left, move_button_region.top, move_button_region.width, move_button_region.height))
			case "DROP_MIMES":
				if drop_status.offered_mimes != nil {
					send_test_response(strings.Join(drop_status.offered_mimes, " "))
				} else {
					send_test_response("")
				}
			case "DROP_IS_REMOTE":
				send_test_response(utils.IfElse(drop_status.is_remote_client, "True", "False"))
			default:
				send_test_response("UNKNOWN TEST COMMAND: " + string(cmd.Payload))
			}
		// Drops
		case 'm':
			payload := ""
			if cmd.Payload != nil {
				payload = utils.UnsafeBytesToString(cmd.Payload)
			}
			if on_drop_move(cmd.X, cmd.Y, cmd.Has_more, payload, false) {
				render_screen()
			}
		case 'M':
			if on_drop_move(cmd.X, cmd.Y, cmd.Has_more, utils.UnsafeBytesToString(cmd.Payload), true) {
				render_screen()
			}
		case 'R':
			return fmt.Errorf("error from the terminal while reading dropped data: %s", string(cmd.Payload))
		case 'r':
			err := on_drop_data(cmd)
			render_screen()
			return err
		}
		return nil
	}
	lp.OnKeyEvent = func(e *loop.KeyEvent) (err error) {
		e.Handled = true
		if e.MatchesPressOrRepeat("ctrl+c") || e.MatchesPressOrRepeat("esc") {
			lp.Quit(0)
			return
		}
		return nil
	}
	lp.OnResize = func(old_size loop.ScreenSize, new_size loop.ScreenSize) error {
		return render_screen()
	}
	err = lp.Run()
	if err != nil {
		return
	}
	ds := lp.DeathSignalName()
	if ds != "" {
		fmt.Println("Killed by signal: ", ds)
		lp.KillIfSignalled()
		return
	}
	return
}

func dnd_main(cmd *cli.Command, opts *Options, args []string) (rc int, err error) {
	drop_dests := make(map[string]*drop_dest)
	if os.Stdout != nil && !tty.IsTerminal(os.Stdout.Fd()) {
		drop_dests["text/plain"] = &drop_dest{human_name: "STDOUT", dest: os.Stdout, mime_type: "text/plain"}
	}
	uri_list_buffer := &bytes.Buffer{}
	drop_dests["text/uri-list"] = &drop_dest{
		human_name: "Files", mime_type: "text/uri-list", dest: &bufferWriteCloser{uri_list_buffer}}
	for _, spec := range opts.Drop {
		mime, dest, _ := strings.Cut(spec, ":")
		if dest == "" {
			delete(drop_dests, mime)
		} else {
			path, err := filepath.Abs(dest)
			if err != nil {
				return 1, err
			}
			drop_dests[mime] = &drop_dest{human_name: dest, path: path, mime_type: mime}
		}
	}
	drag_sources := make(map[string]drag_source)
	for _, spec := range opts.Drag {
		mime, src, found := strings.Cut(spec, ":")
		if !found {
			return 1, fmt.Errorf("invalid drag source %s, must be of the form mime-type:path", spec)
		}
		s := drag_source{human_name: src, mime_type: mime}
		if src == "-" || src == "/dev/stdin" {
			s.human_name = "STDIN"
			s.file = os.Stdin
		} else {
			path, err := filepath.Abs(src)
			if err != nil {
				return 1, err
			}
			s.path = path
		}
		drag_sources[mime] = s
	}

	if _, has_plain := drag_sources["text/plain"]; os.Stdin != nil && !has_plain && !tty.IsTerminal(os.Stdin.Fd()) {
		data, err := io.ReadAll(os.Stdin)
		if err != nil {
			return 1, err
		}
		if len(data) > 0 {
			drag_sources["text/plain"] = drag_source{human_name: "STDIN", mime_type: "text/plain", data: data}
		}
	}
	var uri_list []uri_list_item
	for _, arg := range args {
		st, err := os.Stat(arg)
		if err != nil {
			return 1, err
		}
		if st.IsDir() || st.Mode().IsRegular() {
			path, err := filepath.Abs(arg)
			if err != nil {
				return 1, err
			}
			upath := filepath.ToSlash(path)
			if runtime.GOOS == "windows" && !strings.HasPrefix(upath, "/") {
				upath = "/" + upath
			}
			u := &url.URL{Scheme: "file", Path: upath}
			uri_list = append(uri_list, uri_list_item{path: path, uri: u.String(), human_name: arg})
		} else {
			return 1, fmt.Errorf("%s is not a directory or regular file", arg)
		}
	}
	if len(uri_list) > 0 {
		uris := make([]string, len(uri_list))
		for i, u := range uri_list {
			uris[i] = u.uri
		}
		payload := strings.Join(uris, "\r\n") + "\r\n"
		drag_sources["text/uri-list"] = drag_source{
			human_name: "Files", mime_type: "text/uri-list", uri_list: uri_list, data: utils.UnsafeStringToBytes(payload),
		}
	}
	err = run_loop(opts, drop_dests, drag_sources, uri_list_buffer)
	if err != nil {
		return 1, err
	}
	return 0, nil
}

func EntryPoint(parent *cli.Command) {
	create_cmd(parent, dnd_main)
}
