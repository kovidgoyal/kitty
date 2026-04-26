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
	"sync/atomic"

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

type DC = loop.DndCommand

type dir_handle struct {
	handle *os.File
	refcnt atomic.Int32
}

func new_dir_handle(x *os.File) *dir_handle {
	ans := dir_handle{x, atomic.Int32{}}
	ans.refcnt.Store(1)
	return &ans
}

func (d *dir_handle) newref() *dir_handle {
	d.refcnt.Add(1)
	return d
}

func (d *dir_handle) unref() *dir_handle {
	if d.refcnt.Add(-1) <= 0 {
		d.handle.Close()
		d.handle = nil
	}
	return nil
}

type drag_status struct {
	active bool
}

type dnd struct {
	opts                     *Options
	drop_dests               map[string]*drop_dest
	drag_sources             map[string]drag_source
	allow_drops, allow_drags bool

	lp                                     *loop.Loop
	drop_status                            drop_status
	base_tempdir                           *os.File
	tdir_counter                           int
	is_case_sensitive_filesystem           bool
	data_has_been_dropped                  bool
	drag_started                           bool
	in_test_mode                           bool
	copy_button_region, move_button_region button_region
}

func (dnd *dnd) send_test_response(payload string) {
	dnd.lp.DebugPrintln(payload)
}

func (dnd *dnd) setup_base_dir(base_dir string) error {
	base_tdir, err := os.MkdirTemp(base_dir, ".dnd-kitten-drop-*")
	if err != nil {
		return err
	}
	bf, err := os.Open(base_tdir)
	if err != nil {
		os.RemoveAll(base_tdir)
		return err
	}
	dnd.base_tempdir = bf
	if _, serr := os.Stat(filepath.Join(base_dir, strings.ToUpper(filepath.Base(base_tdir)))); serr == nil {
		dnd.is_case_sensitive_filesystem = false
	}
	return nil
}

func (dnd *dnd) remove_tdir() error {
	path := dnd.base_tempdir.Name()
	dnd.base_tempdir.Close()
	dnd.base_tempdir = nil
	return os.RemoveAll(path)
}

func (dnd *dnd) run_loop() (err error) {
	defer func() {
		if dnd.in_test_mode && err != nil {
			debugprintln("dnd kitten exiting with error: ", err)
		}
	}()
	base_dir, err := os.Getwd()
	if err != nil {
		return err
	}
	if err = dnd.setup_base_dir(base_dir); err != nil {
		return err
	}
	defer dnd.remove_tdir()

	dnd.allow_drops, dnd.allow_drags = len(dnd.drop_dests) > 0, len(dnd.drag_sources) > 0
	if dnd.lp, err = loop.New(); err != nil {
		return err
	}
	dnd.reset_drop()

	dnd.lp.OnInitialize = func() (string, error) {
		dnd.lp.AllowLineWrapping(false)
		dnd.lp.SetCursorVisible(false)
		if dnd.allow_drops {
			dnd.lp.StartAcceptingDrops("", slices.Collect(maps.Keys(dnd.drop_dests))...)
		}
		if dnd.allow_drags {
			dnd.lp.StartOfferingDrags("")
		}
		dnd.lp.SetWindowTitle("Drag and drop")
		return "", dnd.render_screen()
	}

	dnd.lp.OnFinalize = func() string {
		dnd.lp.AllowLineWrapping(true)
		dnd.lp.SetCursorVisible(true)
		if dnd.allow_drops {
			dnd.lp.StopAcceptingDrops()
		}
		if dnd.allow_drags {
			dnd.lp.StopOfferingDrags()
		}
		return ""
	}

	dnd.lp.OnDnDData = func(cmd loop.DndCommand) error {
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
				dnd.send_test_response("PONG")
			case "SETUP_LOCAL", "SETUP_REMOTE":
				dnd.in_test_mode = true
				dnd.lp.NoRoundtripToTerminalOnExit()
				dnd.drop_status.reset()
				dnd.lp.StopAcceptingDrops()
				dnd.lp.StopOfferingDrags()
				dnd.remove_tdir()
				dnd.setup_base_dir(base_dir)
				machine_id := ""
				if string(cmd.Payload) == "SETUP_REMOTE" {
					machine_id = "remote-client-for-test"
				}
				if dnd.allow_drops {
					dnd.lp.StartAcceptingDrops(machine_id, slices.Collect(maps.Keys(dnd.drop_dests))...)
				}
				if dnd.allow_drags {
					dnd.lp.StartOfferingDrags(machine_id)
				}
				dnd.render_screen()
				dnd.send_test_response("SETUP_DONE")
			case "GEOMETRY":
				dnd.send_test_response(fmt.Sprintf("GEOMETRY:%d:%d:%d:%d:%d:%d:%d:%d", dnd.copy_button_region.left, dnd.copy_button_region.top, dnd.copy_button_region.width, dnd.copy_button_region.height, dnd.move_button_region.left, dnd.move_button_region.top, dnd.move_button_region.width, dnd.move_button_region.height))
			case "DROP_MIMES":
				if dnd.drop_status.offered_mimes != nil {
					dnd.send_test_response(strings.Join(dnd.drop_status.offered_mimes, " "))
				} else {
					dnd.send_test_response("")
				}
			case "DROP_IS_REMOTE":
				dnd.send_test_response(utils.IfElse(dnd.drop_status.is_remote_client, "True", "False"))
			case "DROP_URI_LIST":
				dnd.send_test_response(strings.Join(dnd.drop_status.uri_list, "|"))
			default:
				dnd.send_test_response("UNKNOWN TEST COMMAND: " + string(cmd.Payload))
			}
		// Drops
		case 'm':
			payload := ""
			if cmd.Payload != nil {
				payload = utils.UnsafeBytesToString(cmd.Payload)
			}
			if dnd.on_drop_move(cmd.X, cmd.Y, cmd.Has_more, payload, false) {
				dnd.render_screen()
			}
		case 'M':
			if dnd.on_drop_move(cmd.X, cmd.Y, cmd.Has_more, utils.UnsafeBytesToString(cmd.Payload), true) {
				dnd.render_screen()
			}
		case 'R':
			return fmt.Errorf("error from the terminal while reading dropped data: %s", string(cmd.Payload))
		case 'r':
			return dnd.on_drop_data(cmd)
		}
		return nil
	}

	dnd.lp.OnKeyEvent = func(e *loop.KeyEvent) (err error) {
		e.Handled = true
		if e.MatchesPressOrRepeat("ctrl+c") || e.MatchesPressOrRepeat("esc") {
			dnd.lp.Quit(0)
			return
		}
		return nil
	}

	dnd.lp.OnResize = func(old_size loop.ScreenSize, new_size loop.ScreenSize) error {
		return dnd.render_screen()
	}

	err = dnd.lp.Run()
	if err != nil {
		return
	}
	ds := dnd.lp.DeathSignalName()
	if ds != "" {
		fmt.Println("Killed by signal: ", ds)
		dnd.lp.KillIfSignalled()
		return
	}
	return
}

func dnd_main(cmd *cli.Command, opts *Options, args []string) (rc int, err error) {
	drop_dests := make(map[string]*drop_dest)
	if os.Stdout != nil && !tty.IsTerminal(os.Stdout.Fd()) {
		drop_dests["text/plain"] = &drop_dest{human_name: "STDOUT", dest: os.Stdout, mime_type: "text/plain"}
	}
	drop_dests["text/uri-list"] = &drop_dest{
		human_name: "Files", mime_type: "text/uri-list", dest: &bufferWriteCloser{&bytes.Buffer{}}}
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
	dnd := dnd{opts: opts, drop_dests: drop_dests, drag_sources: drag_sources}
	defer dnd.reset_drop()
	if err = dnd.run_loop(); err != nil {
		return 1, err
	}
	return 0, nil
}

func EntryPoint(parent *cli.Command) {
	create_cmd(parent, dnd_main)
}
