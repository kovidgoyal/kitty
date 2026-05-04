package dnd

import (
	"bytes"
	"container/list"
	"context"
	"errors"
	"fmt"
	"io"
	"io/fs"
	"net/url"
	"os"
	"path/filepath"
	"slices"
	"strconv"
	"strings"

	"github.com/kovidgoyal/go-parallel"
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
		if d.path == "" {
			d.dest = &bufferWriteCloser{&bytes.Buffer{}}
		} else {
			d.dest, err = open_file_for_writing(d.path)
			d.close_on_finish = true
			if err != nil {
				return
			}
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

func do_local_copy(ctx context.Context, dest_dir *os.File, uri_list []string) (err error) {
	var src_file *os.File
	defer func() {
		if src_file != nil {
			src_file.Close()
		}
	}()
	for _, path := range uri_list {
		if path == "" {
			continue
		}
		select {
		case <-ctx.Done():
			return ctx.Err()
		default:
		}
		if src_file != nil {
			src_file.Close()
		}
		st, err := os.Lstat(path)
		if err != nil {
			return err
		}
		if st.IsDir() {
			if src_file, err = os.Open(path); err != nil {
				return err
			}
			d, err := utils.CreateDirAt(dest_dir, filepath.Base(path), st.Mode().Perm())
			if err != nil {
				return err
			}
			err = utils.CopyFolderContents(ctx, src_file, d, utils.CopyFolderOptions{
				Filter_files: func(parent *os.File, child os.FileInfo) bool {
					return child.IsDir() || child.Mode().IsRegular() || child.Mode()&fs.ModeSymlink != 0
				},
			})
			d.Close()
			if err != nil {
				return err
			}
		} else if st.Mode().IsRegular() {
			// First try a hard link
			dest := filepath.Join(dest_dir.Name(), filepath.Base(path))
			if err = os.Link(path, dest); err == nil {
				continue
			}
			if src_file, err = os.Open(path); err != nil {
				return err
			}
			d, err := utils.CreateAt(dest_dir, filepath.Base(dest), st.Mode().Perm())
			if err != nil {
				return err
			}
			err = utils.CopyFileAndClose(ctx, src_file, d)
			src_file = nil // already closed
			if err != nil {
				return err
			}
		} else if st.Mode()&fs.ModeSymlink != 0 {
			target, err := os.Readlink(path)
			if err != nil {
				return err
			}
			dest := filepath.Join(dest_dir.Name(), filepath.Base(path))
			if err := os.Symlink(target, dest); err != nil {
				return err
			}
		}
	}
	return
}

func do_local_copy_in_goroutine(ctx context.Context, dest_dir *os.File, completion chan error, uri_list []string, wakeup func()) {
	var err error
	defer func() {
		if r := recover(); r != nil {
			err = parallel.Format_stacktrace_on_panic(r, 1)
		}
		completion <- err
		wakeup()
	}()
	err = do_local_copy(ctx, dest_dir, uri_list)
}

type path_stack struct {
	s list.List
}

func (p *path_stack) push(x string) { p.s.PushBack(x) }
func (p *path_stack) pop() string   { return p.s.Remove(p.s.Front()).(string) }
func (p *path_stack) empty() bool   { return p.s.Front() == nil }

// Return a list of relative paths for all entries in the tree rooted at
// src_dir that also exist in the tree rooted at dest_dir, except for
// directories that exist in both places.
func find_overwrites(src_dir *os.File, dest_dir *os.File) (ans []string, err error) {
	stack := path_stack{}
	stack.push(".")
	for !stack.empty() {
		relpath := stack.pop()
		if err = func() (err error) {
			sd, err := utils.OpenDirAt(src_dir, relpath)
			if err != nil {
				return err
			}
			defer sd.Close()
			dd, err := utils.OpenDirAt(dest_dir, relpath)
			if err != nil {
				return err
			}
			defer dd.Close()
			dest_children, err := dd.ReadDir(0)
			src_children, err := sd.ReadDir(0)
			if err != nil {
				return err
			}
			dest_map := make(map[string]os.DirEntry)
			for _, x := range dest_children {
				dest_map[x.Name()] = x
			}
			for _, x := range src_children {
				if d, found := dest_map[x.Name()]; found {
					crelpath := utils.IfElse(relpath == ".", x.Name(), filepath.Join(relpath, x.Name()))
					if !d.IsDir() || !x.IsDir() {
						ans = append(ans, crelpath)
					} else {
						stack.push(crelpath)
					}
				} else {
					continue
				}
			}
			return
		}(); err != nil {
			return nil, err
		}
	}
	return
}

// Rename the contents of src_dir into dest_dir, handling the case of
// directories already existing in dest_dir transparently.
func rename_contents(src_dir *os.File, dest_dir *os.File) (err error) {
	stack := path_stack{}
	stack.push(".")
	for !stack.empty() {
		relpath := stack.pop()
		if err = func() error {
			sd, err := utils.OpenDirAt(src_dir, relpath)
			if err != nil {
				return err
			}
			defer sd.Close()
			dd, err := utils.OpenDirAt(dest_dir, relpath)
			if err != nil {
				return err
			}
			defer dd.Close()
			for {
				src_children, err := sd.ReadDir(64)
				if err != nil {
					if errors.Is(err, io.EOF) {
						break
					}
					return err
				}
				for _, child := range src_children {
					crelpath := utils.IfElse(relpath == ".", child.Name(), filepath.Join(relpath, child.Name()))
					rerr := utils.RenameAt(sd, child.Name(), dd, child.Name())
					if rerr != nil {
						if child.IsDir() {
							stack.push(crelpath)
						} else {
							return rerr
						}
					}
				}
			}
			return nil
		}(); err != nil {
			return err
		}
	}
	return
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
				if f, derr := utils.CreateDirAt(d.base_dir.handle, d.name, 0o755); derr != nil {
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
		if line == "" || strings.HasPrefix(line, "#") {
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

	dropping_to          *dir_handle
	root_remote_dir      *remote_dir_entry
	open_remote_dir      *remote_dir_entry
	current_remote_entry *remote_dir_entry // used for m=1 only
	pending_remote_dirs  []*remote_dir_entry
	data_requests        struct {
		pending         []DC
		in_flight_count int
	}
	local_copy struct {
		ctx        context.Context
		cancel_ctx context.CancelFunc
		completion chan error
	}
}

func (d *drop_status) reset() {
	if d.local_copy.ctx != nil {
		d.local_copy.cancel_ctx()
		<-d.local_copy.completion
	}
	if d.dropping_to != nil {
		d.dropping_to = d.dropping_to.unref()
	}
	*d = drop_status{cell_x: -1, cell_y: -1}
}

func (d *drop_dest) reset() {
	if d.dest != nil && d.dest != os.Stdout {
		d.dest.Close()
		d.dest = nil
	}
	d.completed = false
	d.close_on_finish = false
	d.b64_decoder = streaming_base64.StreamingBase64Decoder{}
}

func (dnd *dnd) reset_drop() {
	if dnd.drop_status.root_remote_dir != nil {
		dnd.drop_status.root_remote_dir.close_tree()
		dnd.drop_status.root_remote_dir = nil
	}
	dnd.drop_status.reset()
	for _, x := range dnd.drop_dests {
		x.reset()
	}
}

func (root *remote_dir_entry) close_tree() {
	if root.base_dir != nil {
		root.base_dir = root.base_dir.unref()
	}
	for _, child := range root.children {
		child.close_tree()
	}
}

func (dnd *dnd) end_drop(success bool) {
	if dnd.drop_status.reading_data {
		dnd.lp.QueueDnDData(DC{
			Type: 'r', Operation: utils.IfElse(success, dnd.drop_status.action, 0)}) // end drop
	}
	dnd.reset_drop()
}

func (dnd *dnd) all_drop_data_received() (err error) {
	dnd.data_has_been_dropped = true
	var staging_dir *os.File
	if dnd.drop_status.dropping_to != nil {
		staging_dir = dnd.drop_status.dropping_to.handle
		dnd.drop_status.dropping_to = nil
	}
	defer func() {
		if err == nil {
			if len(dnd.confirm_drop.overwrites) == 0 {
				dnd.end_drop(true)
			}
			err = dnd.render_screen()
		} else {
			dnd.end_drop(false)
		}
	}()
	if staging_dir != nil {
		if dnd.opts.ConfirmDropOverwrite {
			overwrites, err := find_overwrites(staging_dir, dnd.drop_output_dir)
			if err != nil {
				return err
			}
			if len(overwrites) > 0 {
				dnd.confirm_drop.overwrites = overwrites
				dnd.confirm_drop.staging_dir = staging_dir
				return dnd.render_screen()
			}
		}
		err := rename_contents(staging_dir, dnd.drop_output_dir)
		staging_dir.Close()
		if err != nil {
			return err
		}
		return nil
	}
	return nil
}

func (dnd *dnd) drop_on_wakeup() error {
	if dnd.drop_status.local_copy.completion == nil {
		return nil
	}
	select {
	case err := <-dnd.drop_status.local_copy.completion:
		dnd.drop_status.local_copy.ctx = nil
		dnd.drop_status.local_copy.completion = nil
		if err != nil {
			return err
		}
		return dnd.all_drop_data_received()
	default:
		return nil
	}
}

func (dnd *dnd) new_tdir() (dir_file *os.File, err error) {
	dnd.tdir_counter++
	name := strconv.Itoa(dnd.tdir_counter)
	return utils.CreateDirAt(dnd.base_tempdir, name, 0o700)
}

func (dnd *dnd) all_mime_data_dropped() (err error) {
	drop_status := &dnd.drop_status
	if len(drop_status.uri_list) == 0 {
		dnd.data_has_been_dropped = true
		dnd.end_drop(true)
		return dnd.render_screen()
	}
	f, err := dnd.new_tdir()
	if err != nil {
		return err
	}
	dnd.drop_status.dropping_to = new_dir_handle(f)
	if drop_status.is_remote_client {
		drop_status.root_remote_dir = &remote_dir_entry{}
		seen := utils.NewSet[string](len(drop_status.uri_list))
		idx := slices.Index(drop_status.offered_mimes, "text/uri-list")
		for i, x := range drop_status.uri_list {
			var c *remote_dir_entry
			if x == "" {
				c = &remote_dir_entry{}
				drop_status.root_remote_dir.num_children_finished++
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
				c = &remote_dir_entry{base_dir: dnd.drop_status.dropping_to.newref(), name: name}
				dnd.queue_data_request(DC{Type: 'r', X: idx + 1, Y: i + 1})
			}
			drop_status.root_remote_dir.children = append(drop_status.root_remote_dir.children, c)
		}
		drop_status.open_remote_dir = drop_status.root_remote_dir
	} else {
		drop_status.local_copy.ctx, drop_status.local_copy.cancel_ctx = context.WithCancel(context.Background())
		drop_status.local_copy.completion = make(chan error, 1)
		go do_local_copy_in_goroutine(drop_status.local_copy.ctx, f, drop_status.local_copy.completion, slices.Clone(drop_status.uri_list), func() { dnd.lp.WakeupMainThread() })
	}
	return
}

func (dnd *dnd) request_mime_data() {
	accepted := utils.NewSetWithItems(dnd.drop_status.accepted_mimes...)
	for idx, m := range dnd.drop_status.offered_mimes {
		if accepted.Has(m) {
			dnd.queue_data_request(DC{Type: 'r', X: idx + 1})
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
	if !dnd.drop_status.in_window || dnd.drag_status.active { // disallow self drag and drop
		dnd.reset_drop()
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
		if dnd.drop_status.action == 0 || len(dnd.drop_status.accepted_mimes) == 0 || dnd.drag_status.active {
			dnd.end_drop(false)
			return
		}
		dnd.drop_status.reading_data = true
		dnd.request_mime_data()
	}
	return
}

var drop_buf []byte

const max_inflight_data_rquests = 64

func (dnd *dnd) queue_data_request(cmd DC) {
	if dnd.drop_status.data_requests.in_flight_count < max_inflight_data_rquests {
		dnd.lp.QueueDnDData(cmd)
		dnd.drop_status.data_requests.in_flight_count++
	} else {
		dnd.drop_status.data_requests.pending = append(dnd.drop_status.data_requests.pending, cmd)
	}
}

func (dnd *dnd) data_request_completed() {
	dnd.drop_status.data_requests.in_flight_count--
	if len(dnd.drop_status.data_requests.pending) > 0 && dnd.drop_status.data_requests.in_flight_count < max_inflight_data_rquests {
		dnd.lp.QueueDnDData(dnd.drop_status.data_requests.pending[0])
		dnd.drop_status.data_requests.in_flight_count++
		dnd.drop_status.data_requests.pending = dnd.drop_status.data_requests.pending[1:]
	}
}

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
			f, err := utils.CreateAt(e.base_dir.handle, e.name, 0o666)
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
	if e.dest == nil { // received all data for this entry
		drop_status.current_remote_entry = nil
		parent := drop_status.open_remote_dir
		parent.num_children_finished++
		dnd.data_request_completed()
		if parent.num_children_finished >= len(parent.children) { // parent is finished
			drop_status.open_remote_dir = nil
			if parent.base_dir != nil {
				parent.base_dir = parent.base_dir.unref()
			}
			if parent.item_type != 0 {
				dnd.lp.QueueDnDData(DC{Type: 'r', Yp: parent.item_type}) // close directory in terminal
			}
			for _, c := range parent.children {
				is_pending := false
				if c.item_type != 0 && c.item_type != 1 {
					if len(c.children) > 0 {
						dnd.drop_status.pending_remote_dirs = append(dnd.drop_status.pending_remote_dirs, c)
						is_pending = true
					}
				}
				if !is_pending {
					if c.base_dir != nil {
						c.base_dir = c.base_dir.unref()
					}
				}
			}
			if len(drop_status.pending_remote_dirs) > 0 {
				drop_status.open_remote_dir = drop_status.pending_remote_dirs[0]
				drop_status.pending_remote_dirs = drop_status.pending_remote_dirs[1:]
				for i := range drop_status.open_remote_dir.children {
					dnd.queue_data_request(DC{Type: 'r', X: i + 1, Yp: drop_status.open_remote_dir.item_type})
				}
			} else {
				return dnd.all_drop_data_received()
			}
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
		if mime == "text/uri-list" {
			b := dest.dest.(*bufferWriteCloser)
			var err error
			if drop_status.uri_list, err = parse_uri_list(b.String()); err != nil {
				return err
			}
		}
		pending := false
		expecting := utils.NewSetWithItems(drop_status.accepted_mimes...)
		for _, d := range dnd.drop_dests {
			if !d.completed && expecting.Has(d.mime_type) {
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

func (dnd *dnd) drop_confirm(accepted bool) error {
	staging_dir := dnd.confirm_drop.staging_dir
	dnd.confirm_drop.overwrites = nil
	dnd.confirm_drop.staging_dir = nil
	defer staging_dir.Close()
	dnd.data_has_been_dropped = accepted
	if accepted {
		if err := rename_contents(staging_dir, dnd.drop_output_dir); err != nil {
			dnd.end_drop(false)
			return err
		}
		dnd.end_drop(true)
	} else {
		dnd.end_drop(false)
	}
	return dnd.render_screen()
}
