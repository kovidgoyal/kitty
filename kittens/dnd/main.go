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
}

func run_loop(opts *Options, drop_dests map[string]drop_dest, drag_sources map[string]drag_source, uri_list_buffer *bytes.Buffer) (err error) {
	allow_drops, allow_drags, drop_accepted := len(drop_dests) > 0, len(drag_sources) > 0, false
	drop_copy_allowed, drop_move_allowed, drag_started := false, false, false
	in_test_mode := false
	lp, err := loop.New()
	if err != nil {
		return err
	}
	send_test_response := func(payload string) {
		in_test_mode = true
		lp.DebugPrintln(payload)
	}
	render_screen := func() error {
		lp.StartAtomicUpdate()
		defer lp.EndAtomicUpdate()
		lp.ClearScreen()
		if allow_drags {
			if drag_started {
				lp.QueueWriteString("Dragging data...")
				return nil
			}
			// TODO: Sow a message to the user saying that they can start
			// dragging anywhere in this window to initiate a drag and drop
		}
		if drop_accepted {
			// TODO: If a drop has entered the window and offers MIME types
			// present in drop_dests then drop_accepted will be true. In this
			// case draw two buttons with triple sized text "Copy" and "Move"
			// using lp.DrawSizedText() with scale=3 which uses the kitty text
			// sizing protocol. Also draw, a message above them saying drop onto the buttons below.
			// Below the buttons if there is space show the list of mime types
			// in the drag. Be careful to not accept drops if drag_started is
			// true, that is if the drag is coming from self.
			// The buttons should only be shown if the drag allows the
			// corresponding operation type. The button should consist of the
			// triple sized text and a frame with rounded corners around the
			// text drawn using unicode box drawing symbols.
			_, _, _ = drop_copy_allowed, drop_move_allowed, in_test_mode

		}
		return nil
	}
	lp.OnInitialize = func() (string, error) {
		lp.AllowLineWrapping(false)
		if allow_drops {
			lp.StartAcceptingDrops(slices.Collect(maps.Keys(drop_dests))...)
		}
		if allow_drags {
			lp.StartOfferingDrags()
		}
		lp.SetWindowTitle("Drag and drop")
		return "", render_screen()
	}
	lp.OnFinalize = func() string {
		lp.AllowLineWrapping(true)
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
			default:
				send_test_response("UNKNOWN TEST COMMAND: " + string(cmd.Payload))
			}
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
	drop_dests := make(map[string]drop_dest)
	if os.Stdout != nil && !tty.IsTerminal(os.Stdout.Fd()) {
		drop_dests["text/plain"] = drop_dest{human_name: "STDOUT", dest: os.Stdout, mime_type: "text/plain"}
	}
	uri_list_buffer := &bytes.Buffer{}
	drop_dests["text/uri-list"] = drop_dest{
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
			drop_dests[mime] = drop_dest{human_name: dest, path: path, mime_type: mime}
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
