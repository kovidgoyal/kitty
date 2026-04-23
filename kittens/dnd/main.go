// License: GPLv3 Copyright: 2022, Kovid Goyal, <kovid at kovidgoyal.net>

package dnd

import (
	"bytes"
	"errors"
	"fmt"
	"io"
	"maps"
	"net/url"
	"os"
	"path/filepath"
	"runtime"
	"slices"
	"strconv"
	"strings"
	"sync/atomic"

	"github.com/kovidgoyal/kitty/tools/cli"
	"github.com/kovidgoyal/kitty/tools/tty"
	"github.com/kovidgoyal/kitty/tools/tui/loop"
	"github.com/kovidgoyal/kitty/tools/utils"
	"github.com/kovidgoyal/kitty/tools/utils/streaming_base64"
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
	close_on_finish  bool
	b64_decoder      streaming_base64.StreamingBase64Decoder
}

func open_file_for_writing(path string) (*os.File, error) {
	f, err := os.Create(path)
	if errors.Is(err, os.ErrNotExist) {
		dir := filepath.Dir(path)
		if err := os.MkdirAll(dir, 0755); err != nil {
			return nil, err
		}
		return os.Create(path)
	}
	return f, err
}

func (d *drop_dest) write(chunk []byte) (err error) {
	if d.dest == nil {
		d.dest, err = open_file_for_writing(d.path)
		d.close_on_finish = true
		if err != nil {
			return
		}

	}
	_, err = d.dest.Write(chunk)
	return
}

func (d *drop_dest) finish() error {
	defer func() {
		d.completed = true
		if d.dest != nil && d.close_on_finish {
			d.dest.Close()
			d.dest = nil
		}
	}()
	if chunk, err := d.b64_decoder.Finish(); err != nil {
		return err
	} else if len(chunk) > 0 {
		return d.write(chunk)
	}
	return nil
}

func (d *drop_dest) add_data(x []byte, output_buf []byte, has_more bool) error {
	d.completed = false
	for chunk, err := range d.b64_decoder.Decode(x, output_buf) {
		if err == nil {
			err = d.write(chunk)
		}
		if err != nil {
			return err
		}
	}
	if !has_more {
		if chunk, err := d.b64_decoder.Finish(); err != nil {
			return err
		} else if len(chunk) > 0 {
			return d.write(chunk)
		}
	}
	return nil
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

type dir_handle struct {
	handle *os.File
	refcnt int32
}

func new_dir_handle(x *os.File) *dir_handle {
	return &dir_handle{x, 1}
}

func (d *dir_handle) newref() *dir_handle {
	atomic.AddInt32(&d.refcnt, 1)
	return d
}

func (d *dir_handle) unref() *dir_handle {
	if atomic.AddInt32(&d.refcnt, -1) <= 0 {
		d.handle.Close()
		d.handle = nil
	}
	return nil
}

type remote_dir_entry struct {
	base_dir              *dir_handle
	name                  string
	item_type             int
	children              []*remote_dir_entry
	num_children_finished int

	dest        io.WriteCloser
	b64_decoder streaming_base64.StreamingBase64Decoder
}

const case_conflict_template = "case-conflict-%d-%s"

func uniqify_child_names(names []string, is_case_sensitive_filesystem bool) []string {
	if is_case_sensitive_filesystem {
		seen := utils.NewSet[string](len(names))
		for i, x := range names {
			name := x
			key := strings.ToLower(name)
			for q := 0; seen.Has(key); q++ {
				name = fmt.Sprintf(case_conflict_template, q+1, x)
				key = strings.ToLower(name)
			}
			seen.Add(key)
			names[i] = name
		}
	}
	return names
}

func (d *remote_dir_entry) add_remote_data(data []byte, output_buf []byte, has_more bool, parent *remote_dir_entry, is_case_sensitive_filesystem bool) error {
	if len(data) > 0 {
		for chunk, derr := range d.b64_decoder.Decode(data, output_buf) {
			if derr != nil {
				return derr
			}
			if _, derr = d.dest.Write(chunk); derr != nil {
				return derr
			}
		}
	} else if !has_more {
		if chunk, derr := d.b64_decoder.Finish(); derr != nil {
			return derr
		} else {
			if _, derr = d.dest.Write(chunk); derr != nil {
				return derr
			}
		}
		defer func() {
			d.dest.Close()
			d.dest = nil
			d.base_dir = d.base_dir.unref()
			parent.num_children_finished++
		}()
		if dest, ok := d.dest.(*bufferWriteCloser); ok {
			if d.item_type == 1 {
				if derr := utils.SymlinkAt(d.base_dir.handle, d.name, dest.String()); derr != nil {
					return derr
				}
			} else { // directory
				if derr := utils.MkdirAt(d.base_dir.handle, d.name, 0o755); derr != nil {
					return derr
				}
				if f, derr := utils.OpenAt(d.base_dir.handle, d.name); derr != nil {
					return derr
				} else {
					handle := new_dir_handle(f)
					defer handle.unref()
					s := utils.NewSeparatorScanner("", "\x00")
					for _, name := range uniqify_child_names(s.Split(dest.String()), is_case_sensitive_filesystem) {
						d.children = append(d.children, &remote_dir_entry{name: name, base_dir: handle.newref()})
					}
				}
			}
		}
	}
	return nil
}

type drop_status struct {
	offered_mimes    []string
	accepted_mimes   []string
	uri_list         []string
	cell_x, cell_y   int
	action           int
	in_window        bool
	reading_data     bool
	is_remote_client bool

	root_remote_dir     *remote_dir_entry
	open_remote_dir     *remote_dir_entry
	pending_remote_dirs []*remote_dir_entry
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

func parse_uri_list(src string) (ans []string, err error) {
	for _, line := range utils.NewSeparatorScanner("", "\r\n").Split(src) {
		line = strings.TrimSpace(line)
		if strings.HasPrefix(line, "#") {
			continue
		}
		if !strings.HasPrefix(line, "file://") {
			ans = append(ans, "")
			continue
		}
		p, err := url.Parse(line)
		if err != nil {
			return nil, err
		}
		ans = append(ans, filepath.Clean(p.Path))
	}
	return
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
	is_case_sensitive_filesystem           bool
	data_has_been_dropped                  bool
	drag_started                           bool
	in_test_mode                           bool
	copy_button_region, move_button_region button_region
}

func (dnd *dnd) send_test_response(payload string) {
	dnd.lp.DebugPrintln(payload)
}

func (dnd *dnd) run_loop() (err error) {
	base_dir, err := os.Getwd()
	if err != nil {
		return err
	}
	base_tdir, err := os.MkdirTemp(base_dir, ".dnd-kitten-drop-*")
	if err != nil {
		return err
	}
	var base_tdir_f *os.File
	defer func() {
		if base_tdir_f != nil {
			utils.RemoveChildren(base_tdir_f)
			base_tdir_f.Close()
		}
		if terr := os.RemoveAll(base_tdir); terr != nil && err == nil {
			err = terr
		}
	}()
	base_tdir_f, err = os.Open(base_tdir)
	if err != nil {
		return
	}
	if _, serr := os.Stat(filepath.Join(base_dir, strings.ToUpper(filepath.Base(base_tdir)))); serr == nil {
		dnd.is_case_sensitive_filesystem = false
	}
	tdir_counter := 0
	new_tdir := func() (dir_file *os.File, err error) {
		tdir_counter++
		name := strconv.Itoa(tdir_counter)
		if err = utils.MkdirAt(base_tdir_f, name, 0o700); err != nil {
			return nil, err
		}
		dir_file, err = utils.OpenAt(base_tdir_f, name)
		return
	}

	dnd.allow_drops, dnd.allow_drags = len(dnd.drop_dests) > 0, len(dnd.drag_sources) > 0
	if dnd.lp, err = loop.New(); err != nil {
		return err
	}

	drop_status := drop_status{cell_x: -1, cell_y: -1}
	reset_drop_status := drop_status
	drop_status.cell_x, drop_status.cell_y = -1, -1

	var offered_mimes_buf strings.Builder

	// Drop handling {{{
	var close_remote_tree func(*remote_dir_entry)
	close_remote_tree = func(root *remote_dir_entry) {
		if root.base_dir != nil {
			root.base_dir = root.base_dir.unref()
		}
		for _, child := range root.children {
			close_remote_tree(child)
		}
	}

	end_drop := func() {
		dnd.lp.QueueDnDData(DC{Type: 'r'}) // end drop
		if drop_status.root_remote_dir != nil {
			close_remote_tree(drop_status.root_remote_dir)
			drop_status.root_remote_dir = nil
		}
		drop_status = reset_drop_status
		dnd.render_screen()
	}

	all_mime_data_dropped := func() (err error) {
		if s, found := dnd.drop_dests["text/uri-list"]; found {
			b := s.dest.(*bufferWriteCloser)
			if drop_status.uri_list, err = parse_uri_list(b.String()); err != nil {
				return err
			}
		}
		if len(drop_status.uri_list) == 0 {
			drop_status = reset_drop_status
			dnd.data_has_been_dropped = true
			dnd.render_screen()
			return
		}
		f, err := new_tdir()
		if err != nil {
			return err
		}
		rd := new_dir_handle(f)
		defer rd.unref()
		drop_status.root_remote_dir = &remote_dir_entry{}
		if drop_status.is_remote_client {
			seen := utils.NewSet[string](len(drop_status.uri_list))
			idx := slices.Index(drop_status.offered_mimes, "text/uri-list")
			for i, x := range drop_status.uri_list {
				var c *remote_dir_entry
				if x == "" {
					c = &remote_dir_entry{}
				} else {
					name := filepath.Base(x)
					if !dnd.is_case_sensitive_filesystem {
						key := strings.ToLower(name)
						for q := 0; seen.Has(key); q++ {
							name = fmt.Sprintf(case_conflict_template, q+1, filepath.Base(x))
							key = strings.ToLower(name)
						}
						seen.Add(key)
					}
					c = &remote_dir_entry{base_dir: rd.newref(), name: name}
					dnd.lp.QueueDnDData(DC{Type: 'r', X: idx + 1, Y: i + 1})
				}
				drop_status.root_remote_dir.children = append(drop_status.root_remote_dir.children, c)
			}
			drop_status.open_remote_dir = drop_status.root_remote_dir
		} else {
			// TODO: copy URLs
		}
		return
	}

	request_mime_data := func() {
		accepted := utils.NewSetWithItems(drop_status.accepted_mimes...)
		for idx, m := range drop_status.offered_mimes {
			if accepted.Has(m) {
				dnd.lp.QueueDnDData(DC{Type: 'r', X: idx + 1})
			}
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
				if _, found := dnd.drop_dests[x]; found && !seen.Has(x) {
					drop_status.accepted_mimes = append(drop_status.accepted_mimes, x)
					seen.Add(x)
				}
			}
		}
		offered_mimes_buf.Reset()
		if dnd.copy_button_region.has(cell_x, cell_y) {
			drop_status.action = copy_on_drop
		} else if dnd.move_button_region.has(cell_x, cell_y) {
			drop_status.action = move_on_drop
		} else {
			switch dnd.opts.DropAnywhere {
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
		if !drop_status.in_window || dnd.drag_started { // disallow self drag and drop
			drop_status = reset_drop_status
		}
		mimes_changed := !slices.Equal(prev_status.accepted_mimes, drop_status.accepted_mimes)
		needs_rerender = prev_status.action != drop_status.action || mimes_changed
		if needs_rerender && !is_drop {
			c := DC{Type: 'm', Operation: drop_status.action}
			if drop_status.action != 0 && len(drop_status.accepted_mimes) > 0 {
				c.Payload = utils.UnsafeStringToBytes(strings.Join(drop_status.accepted_mimes, " "))
			}
			dnd.lp.QueueDnDData(c)
		}
		needs_rerender = needs_rerender || drop_status.in_window != prev_status.in_window
		if is_drop {
			needs_rerender = true
			if drop_status.action == 0 || len(drop_status.accepted_mimes) == 0 || dnd.drag_started {
				end_drop()
				return
			}
			drop_status.reading_data = true
			request_mime_data()
		}
		return
	}

	var current_remote_entry *remote_dir_entry
	var drop_buf []byte

	on_remote_drop_data := func(cmd DC) error {
		if drop_status.open_remote_dir == nil {
			return fmt.Errorf("got a remote data response form the terminal without an open remote dir")
		}
		if cmd.X == 0 && cmd.Y == 0 && cmd.Yp == 0 {
			if current_remote_entry == nil {
				return fmt.Errorf("got a remote data response form the terminal without a current remote entry")
			}
		} else {
			num := utils.IfElse(cmd.Yp != 0 && cmd.Yp != 1, cmd.X, cmd.Y) - 1
			if num < 0 || num >= len(drop_status.open_remote_dir.children) {
				return fmt.Errorf("got a remote data response from the terminal for an entry that does not exist")
			}
			current_remote_entry = drop_status.open_remote_dir.children[num]
		}
		if current_remote_entry.dest == nil {
			current_remote_entry.item_type = cmd.Xp
			switch cmd.Xp {
			case 0:
				f, err := utils.CreateAt(drop_status.open_remote_dir.base_dir.handle, current_remote_entry.name)
				if err != nil {
					return err
				}
				current_remote_entry.dest = f
			default:
				current_remote_entry.dest = &bufferWriteCloser{&bytes.Buffer{}}
			}
		}
		if sz := max(4096, len(cmd.Payload)+4); len(drop_buf) < sz {
			drop_buf = make([]byte, sz)
		}
		if err = current_remote_entry.add_remote_data(cmd.Payload, drop_buf, cmd.Has_more, drop_status.open_remote_dir, dnd.is_case_sensitive_filesystem); err != nil {
			return err
		}
		return nil
	}

	on_drop_data := func(cmd DC) error {
		if drop_status.root_remote_dir != nil {
			return on_remote_drop_data(cmd)
		}
		idx := cmd.X - 1
		if idx < 0 || idx > len(drop_status.offered_mimes) {
			return fmt.Errorf("terminal sent drop data for a index outside the list of accepted MIMEs")
		}
		mime := drop_status.offered_mimes[idx]
		dest := dnd.drop_dests[mime]
		if cmd.Xp == 1 && mime == "text/uri-list" {
			drop_status.is_remote_client = true
		}
		if !cmd.Has_more && len(cmd.Payload) == 0 {
			if err := dest.finish(); err != nil {
				return err
			}
			dest.completed = true
			pending := false
			for _, d := range dnd.drop_dests {
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
		if sz := max(4096, len(cmd.Payload)+4); len(drop_buf) < sz {
			drop_buf = make([]byte, sz)
		}
		return dest.add_data(cmd.Payload, drop_buf, cmd.Has_more)
	}
	// }}}

	dnd.lp.OnInitialize = func() (string, error) {
		dnd.lp.AllowLineWrapping(false)
		dnd.lp.SetCursorVisible(false)
		if dnd.allow_drops {
			dnd.lp.StartAcceptingDrops(dnd.opts.MachineId, slices.Collect(maps.Keys(dnd.drop_dests))...)
		}
		if dnd.allow_drags {
			dnd.lp.StartOfferingDrags(dnd.opts.MachineId)
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
			case "SETUP":
				dnd.in_test_mode = true
				dnd.lp.NoRoundtripToTerminalOnExit()
			case "GEOMETRY":
				dnd.send_test_response(fmt.Sprintf("GEOMETRY:%d:%d:%d:%d:%d:%d:%d:%d", dnd.copy_button_region.left, dnd.copy_button_region.top, dnd.copy_button_region.width, dnd.copy_button_region.height, dnd.move_button_region.left, dnd.move_button_region.top, dnd.move_button_region.width, dnd.move_button_region.height))
			case "DROP_MIMES":
				if drop_status.offered_mimes != nil {
					dnd.send_test_response(strings.Join(drop_status.offered_mimes, " "))
				} else {
					dnd.send_test_response("")
				}
			case "DROP_IS_REMOTE":
				dnd.send_test_response(utils.IfElse(drop_status.is_remote_client, "True", "False"))
			case "DROP_URI_LIST":
				dnd.send_test_response(strings.Join(drop_status.uri_list, "|"))
			default:
				dnd.send_test_response("UNKNOWN TEST COMMAND: " + string(cmd.Payload))
			}
		// Drops
		case 'm':
			payload := ""
			if cmd.Payload != nil {
				payload = utils.UnsafeBytesToString(cmd.Payload)
			}
			if on_drop_move(cmd.X, cmd.Y, cmd.Has_more, payload, false) {
				dnd.render_screen()
			}
		case 'M':
			if on_drop_move(cmd.X, cmd.Y, cmd.Has_more, utils.UnsafeBytesToString(cmd.Payload), true) {
				dnd.render_screen()
			}
		case 'R':
			return fmt.Errorf("error from the terminal while reading dropped data: %s", string(cmd.Payload))
		case 'r':
			err := on_drop_data(cmd)
			dnd.render_screen()
			return err
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
	if err = dnd.run_loop(); err != nil {
		return 1, err
	}
	return 0, nil
}

func EntryPoint(parent *cli.Command) {
	create_cmd(parent, dnd_main)
}
