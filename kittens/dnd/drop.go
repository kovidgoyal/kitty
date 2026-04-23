package dnd

import (
	"bytes"
	"errors"
	"fmt"
	"io"
	"net/url"
	"os"
	"path/filepath"
	"slices"
	"strconv"
	"strings"

	"github.com/kovidgoyal/kitty/tools/utils"
	"github.com/kovidgoyal/kitty/tools/utils/streaming_base64"
)

var _ = fmt.Print

const copy_on_drop = 1
const move_on_drop = 2

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

func (d *remote_dir_entry) add_remote_data(data []byte, output_buf []byte, has_more bool, is_case_sensitive_filesystem bool) error {
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

type drop_status struct {
	offered_mimes    []string
	accepted_mimes   []string
	uri_list         []string
	cell_x, cell_y   int
	action           int
	in_window        bool
	reading_data     bool
	is_remote_client bool

	root_remote_dir      *remote_dir_entry
	open_remote_dir      *remote_dir_entry
	current_remote_entry *remote_dir_entry // used for m=1 only
}

var reset_drop_status = drop_status{cell_x: -1, cell_y: -1}

func (root *remote_dir_entry) close_tree() {
	if root.base_dir != nil {
		root.base_dir = root.base_dir.unref()
	}
	for _, child := range root.children {
		child.close_tree()
	}
}

func (dnd *dnd) end_drop() {
	dnd.lp.QueueDnDData(DC{Type: 'r'}) // end drop
	if dnd.drop_status.root_remote_dir != nil {
		dnd.drop_status.root_remote_dir.close_tree()
		dnd.drop_status.root_remote_dir = nil
	}
	dnd.drop_status = reset_drop_status
	dnd.render_screen()
}

func (dnd *dnd) new_tdir() (dir_file *os.File, err error) {
	dnd.tdir_counter++
	name := strconv.Itoa(dnd.tdir_counter)
	if err = utils.MkdirAt(dnd.base_tempdir, name, 0o700); err != nil {
		return nil, err
	}
	dir_file, err = utils.OpenAt(dnd.base_tempdir, name)
	return
}

func (dnd *dnd) all_mime_data_dropped() (err error) {
	drop_status := &dnd.drop_status
	if s, found := dnd.drop_dests["text/uri-list"]; found {
		b := s.dest.(*bufferWriteCloser)
		if drop_status.uri_list, err = parse_uri_list(b.String()); err != nil {
			return err
		}
	}
	if len(drop_status.uri_list) == 0 {
		*drop_status = reset_drop_status
		dnd.data_has_been_dropped = true
		dnd.render_screen()
		return
	}
	f, err := dnd.new_tdir()
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

func (dnd *dnd) request_mime_data() {
	accepted := utils.NewSetWithItems(dnd.drop_status.accepted_mimes...)
	for idx, m := range dnd.drop_status.offered_mimes {
		if accepted.Has(m) {
			dnd.lp.QueueDnDData(DC{Type: 'r', X: idx + 1})
		}
	}
}

var offered_mimes_buf strings.Builder

func (dnd *dnd) on_drop_move(cell_x, cell_y int, has_more bool, offered_mimes string, is_drop bool) (needs_rerender bool) {
	prev_status := dnd.drop_status
	dnd.drop_status.cell_x, dnd.drop_status.cell_y = cell_x, cell_y
	if offered_mimes != "" {
		offered_mimes_buf.WriteString(offered_mimes)
		if has_more {
			return
		}
		offered_mimes := offered_mimes_buf.String()
		dnd.drop_status.offered_mimes = strings.Fields(offered_mimes)
		dnd.drop_status.accepted_mimes = make([]string, 0, len(dnd.drop_status.offered_mimes))
		seen := utils.NewSet[string](len(dnd.drop_status.offered_mimes))
		for _, x := range dnd.drop_status.offered_mimes {
			if _, found := dnd.drop_dests[x]; found && !seen.Has(x) {
				dnd.drop_status.accepted_mimes = append(dnd.drop_status.accepted_mimes, x)
				seen.Add(x)
			}
		}
	}
	offered_mimes_buf.Reset()
	if dnd.copy_button_region.has(cell_x, cell_y) {
		dnd.drop_status.action = copy_on_drop
	} else if dnd.move_button_region.has(cell_x, cell_y) {
		dnd.drop_status.action = move_on_drop
	} else {
		switch dnd.opts.DropAnywhere {
		case "disallowed":
			dnd.drop_status.action = 0
			dnd.drop_status.accepted_mimes = nil
		case "copy":
			dnd.drop_status.action = copy_on_drop
		case "move":
			dnd.drop_status.action = move_on_drop
		}
	}
	dnd.drop_status.in_window = cell_x > -1 && cell_y > -1
	if !dnd.drop_status.in_window || dnd.drag_started { // disallow self drag and drop
		dnd.drop_status = reset_drop_status
	}
	mimes_changed := !slices.Equal(prev_status.accepted_mimes, dnd.drop_status.accepted_mimes)
	needs_rerender = prev_status.action != dnd.drop_status.action || mimes_changed
	if needs_rerender && !is_drop {
		c := DC{Type: 'm', Operation: dnd.drop_status.action}
		if dnd.drop_status.action != 0 && len(dnd.drop_status.accepted_mimes) > 0 {
			c.Payload = utils.UnsafeStringToBytes(strings.Join(dnd.drop_status.accepted_mimes, " "))
		}
		dnd.lp.QueueDnDData(c)
	}
	needs_rerender = needs_rerender || dnd.drop_status.in_window != prev_status.in_window
	if is_drop {
		needs_rerender = true
		if dnd.drop_status.action == 0 || len(dnd.drop_status.accepted_mimes) == 0 || dnd.drag_started {
			dnd.end_drop()
			return
		}
		dnd.drop_status.reading_data = true
		dnd.request_mime_data()
	}
	return
}

var drop_buf []byte

func (dnd *dnd) on_remote_drop_data(cmd DC) (err error) {
	drop_status := &dnd.drop_status
	if drop_status.open_remote_dir == nil {
		return fmt.Errorf("got a remote data response form the terminal without an open remote dir")
	}
	if cmd.X == 0 && cmd.Y == 0 && cmd.Yp == 0 {
		if drop_status.current_remote_entry == nil {
			return fmt.Errorf("got a remote data response form the terminal without a current remote entry")
		}
	} else {
		num := utils.IfElse(cmd.Yp != 0 && cmd.Yp != 1, cmd.X, cmd.Y) - 1
		if num < 0 || num >= len(drop_status.open_remote_dir.children) {
			return fmt.Errorf("got a remote data response from the terminal for an entry that does not exist")
		}
		drop_status.current_remote_entry = drop_status.open_remote_dir.children[num]
	}
	e := drop_status.current_remote_entry
	if e.dest == nil {
		e.item_type = cmd.Xp
		switch cmd.Xp {
		case 0:
			f, err := utils.CreateAt(e.base_dir.handle, e.name)
			if err != nil {
				return err
			}
			e.dest = f
		default:
			e.dest = &bufferWriteCloser{&bytes.Buffer{}}
		}
	}
	if sz := max(4096, len(cmd.Payload)+4); len(drop_buf) < sz {
		drop_buf = make([]byte, sz)
	}
	if err = e.add_remote_data(cmd.Payload, drop_buf, cmd.Has_more, dnd.is_case_sensitive_filesystem); err != nil {
		return err
	}
	if e.dest == nil { // this entry is finished
		drop_status.open_remote_dir.num_children_finished++
		if len(e.children) > 0 {
			if e.item_type != 0 && e.item_type != 1 {
				dnd.lp.QueueDnDData(DC{Type: 'r', Yp: e.item_type}) // close directory in terminal
			}
			// TODO: request the children
		}
	}
	return nil
}

func (dnd *dnd) on_drop_data(cmd DC) error {
	drop_status := &dnd.drop_status
	if drop_status.root_remote_dir != nil {
		return dnd.on_remote_drop_data(cmd)
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
			return dnd.all_mime_data_dropped()
		}
		return nil
	}
	if sz := max(4096, len(cmd.Payload)+4); len(drop_buf) < sz {
		drop_buf = make([]byte, sz)
	}
	return dest.add_data(cmd.Payload, drop_buf, cmd.Has_more)
}
