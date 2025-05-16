// License: GPLv3 Copyright: 2023, Kovid Goyal, <kovid at kovidgoyal.net>

package transfer

import (
	"bytes"
	"compress/zlib"
	"errors"
	"fmt"
	"io"
	"io/fs"
	"os"
	"path/filepath"
	"slices"
	"strconv"
	"strings"
	"time"

	"github.com/kovidgoyal/kitty"
	"github.com/kovidgoyal/kitty/kittens/unicode_input"
	"github.com/kovidgoyal/kitty/tools/cli/markup"
	"github.com/kovidgoyal/kitty/tools/rsync"
	"github.com/kovidgoyal/kitty/tools/tui"
	"github.com/kovidgoyal/kitty/tools/tui/loop"
	"github.com/kovidgoyal/kitty/tools/utils"
	"github.com/kovidgoyal/kitty/tools/utils/humanize"
	"github.com/kovidgoyal/kitty/tools/wcswidth"

	"golang.org/x/sys/unix"
)

var _ = fmt.Print

type state int

const (
	state_waiting_for_permission state = iota
	state_waiting_for_file_metadata
	state_transferring
	state_canceled
)

type output_file interface {
	write([]byte) (int, error)
	close() error
	tell() (int64, error)
}

type filesystem_file struct {
	f *os.File
}

func (ff *filesystem_file) tell() (int64, error) {
	return ff.f.Seek(0, io.SeekCurrent)
}

func (ff *filesystem_file) close() error {
	return ff.f.Close()
}

func (ff *filesystem_file) write(data []byte) (int, error) {
	n, err := ff.f.Write(data)
	if err == nil && n < len(data) {
		err = io.ErrShortWrite
	}
	return n, err
}

type patch_file struct {
	path      string
	src, temp *os.File
	p         *rsync.Patcher
}

func (pf *patch_file) tell() (int64, error) {
	if pf.temp == nil {
		s, err := os.Stat(pf.path)
		return s.Size(), err
	}
	return pf.temp.Seek(0, io.SeekCurrent)
}

func (pf *patch_file) close() (err error) {
	if pf.p == nil {
		return
	}
	err = pf.p.FinishDelta()
	pf.src.Close()
	pf.temp.Close()
	if err == nil {
		err = os.Rename(pf.temp.Name(), pf.src.Name())
	}
	pf.src = nil
	pf.temp = nil
	pf.p = nil
	return
}

func (pf *patch_file) write(data []byte) (int, error) {
	if err := pf.p.UpdateDelta(data); err == nil {
		return len(data), nil
	} else {
		return 0, err
	}
}

func new_patch_file(path string, p *rsync.Patcher) (ans *patch_file, err error) {
	ans = &patch_file{p: p, path: path}
	var f *os.File
	if f, err = os.Open(path); err != nil {
		return
	} else {
		ans.src = f
	}
	if f, err = os.CreateTemp(filepath.Dir(path), ""); err != nil {
		ans.src.Close()
		return
	} else {
		ans.temp = f
	}
	ans.p.StartDelta(ans.temp, ans.src)
	return
}

type remote_file struct {
	expected_size                int64
	expect_diff                  bool
	patcher                      *rsync.Patcher
	transmit_started_at, done_at time.Time
	written_bytes                int64
	received_bytes               int64
	sent_bytes                   int64
	ftype                        FileType
	mtime                        time.Duration
	spec_id                      int
	permissions                  fs.FileMode
	remote_path                  string
	display_name                 string
	remote_id, remote_target     string
	parent                       string
	expanded_local_path          string
	file_id                      string
	decompressor                 utils.StreamDecompressor
	compression_type             Compression
	remote_symlink_value         string
	actual_file                  output_file
}

func (self *remote_file) close() (err error) {
	if self.decompressor != nil {
		err = self.decompressor(nil, true)
		self.decompressor = nil
	}

	if self.actual_file != nil {
		af := self.actual_file
		self.actual_file = nil
		cerr := af.close()
		if err == nil {
			err = cerr
		}
	}
	return
}

func (self *remote_file) Write(data []byte) (n int, err error) {
	switch self.ftype {
	default:
		return 0, fmt.Errorf("Cannot write data to files of type: %s", self.ftype)
	case FileType_symlink:
		self.remote_symlink_value += string(data)
		return len(data), nil
	case FileType_regular:
		if self.actual_file == nil {
			parent := filepath.Dir(self.expanded_local_path)
			if parent != "" {
				if err = os.MkdirAll(parent, 0o755); err != nil {
					return 0, err
				}
			}
			if self.expect_diff {
				if pf, err := new_patch_file(self.expanded_local_path, self.patcher); err != nil {
					return 0, err
				} else {
					self.actual_file = pf
				}
			} else {
				if ff, err := os.Create(self.expanded_local_path); err != nil {
					return 0, err
				} else {
					f := filesystem_file{f: ff}
					self.actual_file = &f
				}
			}
		}
		return self.actual_file.write(data)
	}
}

func (self *remote_file) write_data(data []byte, is_last bool) (amt_written int64, err error) {
	self.received_bytes += int64(len(data))
	var base, pos int64
	defer func() {
		if err != nil {
			err = fmt.Errorf("Failed writing to %s with error: %w", self.expanded_local_path, err)
		}
	}()
	if self.actual_file != nil {
		base, err = self.actual_file.tell()
		if err != nil {
			return 0, err
		}
	}
	err = self.decompressor(data, is_last)
	if is_last {
		self.decompressor = nil
	}
	if self.actual_file != nil && err == nil {
		pos, err = self.actual_file.tell()
		if err != nil {
			return 0, err
		}
	} else {
		pos = base
	}
	amt_written = pos - base
	if is_last && self.actual_file != nil {
		cerr := self.actual_file.close()
		if err == nil {
			err = cerr
		}
		self.actual_file = nil
	}
	return
}

func syscall_mode(i os.FileMode) (o uint32) {
	o |= uint32(i.Perm())
	if i&os.ModeSetuid != 0 {
		o |= unix.S_ISUID
	}
	if i&os.ModeSetgid != 0 {
		o |= unix.S_ISGID
	}
	if i&os.ModeSticky != 0 {
		o |= unix.S_ISVTX
	}
	// No mapping for Go's ModeTemporary (plan9 only).
	return
}

func (self *remote_file) apply_metadata() {
	t := unix.NsecToTimespec(int64(self.mtime))
	for {
		if err := unix.UtimesNanoAt(unix.AT_FDCWD, self.expanded_local_path, []unix.Timespec{t, t}, unix.AT_SYMLINK_NOFOLLOW); err == nil || !(errors.Is(err, unix.EINTR) || errors.Is(err, unix.EAGAIN)) {
			break
		}
	}
	if self.ftype == FileType_symlink {
		for {
			if err := unix.Fchmodat(unix.AT_FDCWD, self.expanded_local_path, syscall_mode(self.permissions), unix.AT_SYMLINK_NOFOLLOW); err == nil || !(errors.Is(err, unix.EINTR) || errors.Is(err, unix.EAGAIN)) {
				break
			}
		}
	} else {
		_ = os.Chmod(self.expanded_local_path, self.permissions)
	}
}

func new_remote_file(opts *Options, ftc *FileTransmissionCommand, file_id uint64) (*remote_file, error) {
	spec_id, err := strconv.Atoi(ftc.File_id)
	if err != nil {
		return nil, err
	}
	ans := &remote_file{
		expected_size: ftc.Size, ftype: ftc.Ftype, mtime: ftc.Mtime, spec_id: spec_id, file_id: strconv.FormatUint(file_id, 10),
		permissions: ftc.Permissions, remote_path: ftc.Name, display_name: wcswidth.StripEscapeCodes(ftc.Name),
		remote_id: ftc.Status, remote_target: string(ftc.Data), parent: ftc.Parent,
	}
	compression_capable := ftc.Ftype == FileType_regular && ftc.Size > 4096 && should_be_compressed(ftc.Name, opts.Compress)
	if compression_capable {
		ans.decompressor = utils.NewStreamDecompressor(zlib.NewReader, ans)
		ans.compression_type = Compression_zlib
	} else {
		ans.decompressor = utils.NewStreamDecompressor(nil, ans)
		ans.compression_type = Compression_none
	}
	return ans, nil
}

type receive_progress_tracker struct {
	total_size_of_all_files   int64
	total_bytes_to_transfer   int64
	total_transferred         int64
	transfered_stats_amt      int64
	transfered_stats_interval time.Duration
	started_at                time.Time
	transfers                 []Transfer
	active_file               *remote_file
	done_files                []*remote_file
}

func (self *receive_progress_tracker) change_active_file(nf *remote_file) {
	now := time.Now()
	self.active_file = nf
	nf.transmit_started_at = now
}

func (self *receive_progress_tracker) start_transfer() {
	self.started_at = time.Now()
	self.transfers = append(self.transfers, Transfer{at: time.Now()})
}

func (self *receive_progress_tracker) file_written(af *remote_file, amt int64, is_done bool) {
	if self.active_file != af {
		self.change_active_file(af)
	}
	af.written_bytes += amt
	self.total_transferred += amt
	now := time.Now()
	self.transfers = append(self.transfers, Transfer{amt: amt, at: now})
	for len(self.transfers) > 2 && self.transfers[0].is_too_old(now) {
		utils.ShiftLeft(self.transfers, 1)
	}
	self.transfered_stats_interval = now.Sub(self.transfers[0].at)
	self.transfered_stats_amt = 0
	for _, t := range self.transfers {
		self.transfered_stats_amt += t.amt
	}
	if is_done {
		af.done_at = now
		self.done_files = append(self.done_files, af)
	}

}

type manager struct {
	request_id              string
	file_id_counter         uint64
	cli_opts                *Options
	spec                    []string
	dest                    string
	bypass                  string
	use_rsync               bool
	failed_specs            map[int]string
	spec_counts             map[int]int
	remote_home             string
	prefix, suffix          string
	transfer_done           bool
	files                   []*remote_file
	files_to_be_transferred map[string]*remote_file
	state                   state
	progress_tracker        receive_progress_tracker
}

type transmit_iterator = func(queue_write func(string) loop.IdType) (loop.IdType, error)

type sigwriter struct {
	wid                     loop.IdType
	file_id, prefix, suffix string
	q                       func(string) loop.IdType
	amt                     int64
	b                       bytes.Buffer
}

func (self *sigwriter) Write(b []byte) (int, error) {
	self.b.Write(b)
	if self.b.Len() > 4000 {
		self.flush()
	}
	return len(b), nil
}

func (self *sigwriter) flush() {
	frame := len(self.prefix) + len(self.suffix)
	split_for_transfer(self.b.Bytes(), self.file_id, false, func(ftc *FileTransmissionCommand) {
		self.q(self.prefix)
		data := ftc.Serialize(false)
		self.q(data)
		self.wid = self.q(self.suffix)
		self.amt += int64(frame + len(data))
	})
	self.b.Reset()
}

var files_done error = errors.New("files done")

func (self *manager) request_files() transmit_iterator {
	pos := 0
	return func(queue_write func(string) loop.IdType) (last_write_id loop.IdType, err error) {
		var f *remote_file
		for pos < len(self.files) {
			f = self.files[pos]
			pos++
			if f.ftype == FileType_directory || (f.ftype == FileType_link && f.remote_target != "") {
				f = nil
			} else {
				break
			}
		}
		if f == nil {
			return 0, files_done
		}
		read_signature := self.use_rsync && f.ftype == FileType_regular
		if read_signature {
			if s, err := os.Lstat(f.expanded_local_path); err == nil {
				read_signature = s.Size() > 4096
			} else {
				read_signature = false
			}
		}
		last_write_id = self.send(FileTransmissionCommand{
			Action: Action_file, Name: f.remote_path, File_id: f.file_id, Ttype: utils.IfElse(
				read_signature, TransmissionType_rsync, TransmissionType_simple), Compression: f.compression_type,
		}, queue_write)
		if read_signature {
			fsf, err := os.Open(f.expanded_local_path)
			if err != nil {
				return 0, err
			}
			defer fsf.Close()
			f.expect_diff = true
			f.patcher = rsync.NewPatcher(f.expected_size)
			output := sigwriter{q: queue_write, file_id: f.file_id, prefix: self.prefix, suffix: self.suffix}
			s_it := f.patcher.CreateSignatureIterator(fsf, &output)
			for {
				err = s_it()
				if err == io.EOF {
					break
				} else if err != nil {
					return 0, err
				}
			}
			output.flush()
			f.sent_bytes += output.amt
			last_write_id = self.send(FileTransmissionCommand{Action: Action_end_data, File_id: f.file_id}, queue_write)
		}
		return
	}
}

type handler struct {
	lp                    *loop.Loop
	progress_update_timer loop.IdType
	spinner               *tui.Spinner
	cli_opts              *Options
	ctx                   *markup.Context
	manager               manager
	quit_after_write_code int
	check_paths_printed   bool
	transmit_started      bool
	progress_drawn        bool
	max_name_length       int
	transmit_iterator     transmit_iterator
	last_data_write_id    loop.IdType
}

func (self *manager) send(c FileTransmissionCommand, send func(string) loop.IdType) loop.IdType {
	send(self.prefix)
	send(c.Serialize(false))
	return send(self.suffix)
}

func (self *manager) start_transfer(send func(string) loop.IdType) {
	self.send(FileTransmissionCommand{Action: Action_receive, Bypass: self.bypass, Size: int64(len(self.spec))}, send)
	for i, x := range self.spec {
		self.send(FileTransmissionCommand{Action: Action_file, File_id: strconv.Itoa(i), Name: x}, send)
	}
	self.progress_tracker.start_transfer()
}

func (self *handler) print_err(err error) {
	self.lp.Println(self.ctx.BrightRed(err.Error()))
}

func (self *handler) abort_with_error(err error, delay ...time.Duration) {
	if err != nil {
		self.print_err(err)
	}
	var d time.Duration = 5 * time.Second
	if len(delay) > 0 {
		d = delay[0]
	}
	self.lp.Println(`Waiting to ensure terminal cancels transfer, will quit in no more than`, d)
	self.manager.send(FileTransmissionCommand{Action: Action_cancel}, self.lp.QueueWriteString)
	self.manager.state = state_canceled
	_, _ = self.lp.AddTimer(d, false, self.do_error_quit)
}

func (self *handler) do_error_quit(loop.IdType) error {
	self.lp.Quit(1)
	return nil
}

func (self *manager) finalize_transfer() (err error) {
	self.transfer_done = true
	rid_map := make(map[string]*remote_file)
	for _, f := range self.files {
		rid_map[f.remote_id] = f
	}
	for _, f := range self.files {
		switch f.ftype {
		case FileType_directory:
			if err = os.MkdirAll(f.expanded_local_path, 0o755); err != nil {
				return fmt.Errorf("Failed to create directory with error: %w", err)
			}
		case FileType_link:
			tgt, found := rid_map[f.remote_target]
			if !found {
				return fmt.Errorf(`Hard link with remote id: {%s} not found`, f.remote_target)
			}
			if err = os.MkdirAll(filepath.Dir(f.expanded_local_path), 0o755); err == nil {
				os.Remove(f.expanded_local_path)
				err = os.Link(tgt.expanded_local_path, f.expanded_local_path)
			}
			if err != nil {
				return fmt.Errorf(`Failed to create link with error: %w`, err)
			}
		case FileType_symlink:
			lt := f.remote_symlink_value
			if f.remote_target != "" {
				tgt, found := rid_map[f.remote_target]
				if !found {
					return fmt.Errorf(`Symbolic link with remote id: {%s} not found`, f.remote_target)
				}
				lt = tgt.expanded_local_path
				if !strings.HasPrefix(f.remote_symlink_value, "/") {
					if lt, err = filepath.Rel(filepath.Dir(f.expanded_local_path), lt); err != nil {
						return fmt.Errorf(`Could not make symlink relative with error: %w`, err)
					}
				}
			}
			if lt == "" {
				return fmt.Errorf("Symlink %s sent without target", f.expanded_local_path)
			}
			os.Remove(f.expanded_local_path)
			if err = os.MkdirAll(filepath.Dir(f.expanded_local_path), 0o755); err != nil {
				return fmt.Errorf("Failed to create directory with error: %w", err)
			}
			if err = os.Symlink(lt, f.expanded_local_path); err != nil {
				return fmt.Errorf(`Failed to create symlink with error: %w`, err)
			}
		}
		f.apply_metadata()
	}
	return
}

func (self *manager) on_file_transfer_response(ftc *FileTransmissionCommand) (err error) {
	switch self.state {
	case state_waiting_for_permission:
		if ftc.Action == Action_status {
			if ftc.Status == `OK` {
				self.state = state_waiting_for_file_metadata
			} else {
				return unicode_input.ErrCanceledByUser
			}
		} else {
			return fmt.Errorf(`Unexpected response from terminal: %s`, ftc.String())
		}
	case state_waiting_for_file_metadata:
		switch ftc.Action {
		case Action_status:
			if ftc.File_id != "" {
				fid, err := strconv.Atoi(ftc.File_id)
				if err != nil {
					return fmt.Errorf(`Unexpected response from terminal (non-integer file_id): %s`, ftc.String())
				}
				if fid < 0 || fid >= len(self.spec) {
					return fmt.Errorf(`Unexpected response from terminal (out-of-range file_id): %s`, ftc.String())
				}
				self.failed_specs[fid] = ftc.Status
			} else {
				if ftc.Status == `OK` {
					self.state = state_transferring
					self.remote_home = ftc.Name
					return
				}
				return fmt.Errorf("%s", ftc.Status)
			}
		case Action_file:
			fid, err := strconv.Atoi(ftc.File_id)
			if err != nil {
				return fmt.Errorf(`Unexpected response from terminal (non-integer file_id): %s`, ftc.String())
			}
			if fid < 0 || fid >= len(self.spec) {
				return fmt.Errorf(`Unexpected response from terminal (out-of-range file_id): %s`, ftc.String())
			}
			self.spec_counts[fid] += 1
			self.file_id_counter++
			if rf, err := new_remote_file(self.cli_opts, ftc, self.file_id_counter); err == nil {
				self.files = append(self.files, rf)
			} else {
				return err
			}
		default:
			return fmt.Errorf(`Unexpected response from terminal (invalid action): %s`, ftc.String())
		}
	case state_transferring:
		if ftc.Action == Action_data || ftc.Action == Action_end_data {
			f, found := self.files_to_be_transferred[ftc.File_id]
			if !found {
				return fmt.Errorf(`Got data for unknown file id: %s`, ftc.File_id)
			}
			is_last := ftc.Action == Action_end_data
			if amt_written, err := f.write_data(ftc.Data, is_last); err != nil {
				return err
			} else {
				self.progress_tracker.file_written(f, amt_written, is_last)
			}
			if is_last {
				delete(self.files_to_be_transferred, ftc.File_id)
				if len(self.files_to_be_transferred) == 0 {
					return self.finalize_transfer()
				}
			}
		}

	}
	return
}

type tree_node struct {
	entry       *remote_file
	added_files map[string]*tree_node
}

func (self *tree_node) add_child(f *remote_file) *tree_node {
	if x, found := self.added_files[f.remote_id]; found {
		return x
	}
	c := tree_node{entry: f, added_files: make(map[string]*tree_node)}
	f.expanded_local_path = filepath.Join(self.entry.expanded_local_path, filepath.Base(f.remote_path))
	self.added_files[f.remote_id] = &c
	return &c
}

func walk_tree(root *tree_node, cb func(*tree_node) error) error {
	for _, c := range root.added_files {
		if err := cb(c); err != nil {
			return err
		}
		if err := walk_tree(c, cb); err != nil {
			return err
		}
	}
	return nil
}

func ensure_parent(f *remote_file, node_map map[string]*tree_node, fid_map map[string]*remote_file) *tree_node {
	if ans := node_map[f.parent]; ans != nil {
		return ans
	}
	parent := fid_map[f.parent]
	gp := ensure_parent(parent, node_map, fid_map)
	node := gp.add_child(parent)
	node_map[parent.remote_id] = node
	return node
}

func make_tree(all_files []*remote_file, local_base string) (root_node *tree_node) {
	fid_map := make(map[string]*remote_file, len(all_files))
	node_map := make(map[string]*tree_node, len(all_files))
	for _, f := range all_files {
		if f.remote_id != "" {
			fid_map[f.remote_id] = f
		}
	}
	root_node = &tree_node{entry: &remote_file{expanded_local_path: local_base}, added_files: make(map[string]*tree_node)}
	node_map[""] = root_node

	for _, f := range all_files {
		if f.remote_id != "" {
			p := ensure_parent(f, node_map, fid_map)
			p.add_child(f)
		}
	}
	return
}

func isdir(path string) bool {
	if s, err := os.Stat(path); err == nil {
		return s.IsDir()
	}
	return false
}

func files_for_receive(opts *Options, dest string, files []*remote_file, remote_home string, specs []string) (ans []*remote_file, err error) {
	spec_map := make(map[int][]*remote_file)
	for _, f := range files {
		spec_map[f.spec_id] = append(spec_map[f.spec_id], f)
	}
	spec_paths := make([]string, len(specs))
	for i := range specs {
		// use the shortest path as the path for the spec
		slices.SortStableFunc(spec_map[i], func(a, b *remote_file) int { return len(a.remote_path) - len(b.remote_path) })
		spec_paths[i] = spec_map[i][0].remote_path
	}
	if opts.Mode == "mirror" {
		common_path := utils.Commonpath(spec_paths...)
		home := strings.TrimRight(remote_home, "/")
		if strings.HasPrefix(common_path, home+"/") {
			for i, x := range spec_paths {
				b, err := filepath.Rel(home, x)
				if err != nil {
					return nil, err
				}
				spec_paths[i] = filepath.Join("~", b)
			}
		}
		for spec_id, files_for_spec := range spec_map {
			spec := spec_paths[spec_id]
			tree := make_tree(files_for_spec, filepath.Dir(expand_home(spec)))
			if err = walk_tree(tree, func(x *tree_node) error {
				ans = append(ans, x.entry)
				return nil
			}); err != nil {
				return nil, err
			}
		}
	} else {
		number_of_source_files := 0
		for _, x := range spec_map {
			number_of_source_files += len(x)
		}
		dest_is_dir := strings.HasSuffix(dest, "/") || number_of_source_files > 1 || isdir(dest)
		for _, files_for_spec := range spec_map {
			if dest_is_dir {
				dest_path := filepath.Join(dest, filepath.Base(files_for_spec[0].remote_path))
				tree := make_tree(files_for_spec, filepath.Dir(expand_home(dest_path)))
				if err = walk_tree(tree, func(x *tree_node) error {
					ans = append(ans, x.entry)
					return nil
				}); err != nil {
					return nil, err
				}
			} else {
				f := files_for_spec[0]
				f.expanded_local_path = expand_home(dest)
				ans = append(ans, f)
			}
		}
	}
	return
}

func (self *manager) collect_files() (err error) {
	if self.files, err = files_for_receive(self.cli_opts, self.dest, self.files, self.remote_home, self.spec); err != nil {
		return err
	}
	self.progress_tracker.total_size_of_all_files = 0
	for _, f := range self.files {
		if f.ftype != FileType_directory && f.ftype != FileType_link {
			self.files_to_be_transferred[f.file_id] = f
			self.progress_tracker.total_size_of_all_files += utils.Max(0, f.expected_size)
		}
	}
	self.progress_tracker.total_bytes_to_transfer = self.progress_tracker.total_size_of_all_files
	return nil
}

func (self *handler) print_continue_msg() {
	self.lp.Println(`Press`, self.ctx.Green(`y`), `to continue or`, self.ctx.BrightRed(`n`), `to abort`)
}

func lexists(path string) bool {
	_, err := os.Lstat(path)
	return err == nil
}

func (self *handler) print_check_paths() {
	if self.check_paths_printed {
		return
	}
	self.check_paths_printed = true
	self.lp.Println(`The following file transfers will be performed. A red destination means an existing file will be overwritten.`)
	for _, df := range self.manager.files {
		self.lp.QueueWriteString(self.ctx.Prettify(fmt.Sprintf(":%s:`%s` ", df.ftype.Color(), df.ftype.ShortText())))
		self.lp.QueueWriteString(" ")
		lpath := df.expanded_local_path
		if lexists(lpath) {
			lpath = self.ctx.Prettify(self.ctx.BrightRed(lpath) + " ")
		}
		self.lp.Println(df.display_name, "→", lpath)
	}
	self.lp.Println(fmt.Sprintf(`Transferring %d file(s) of total size: %s`, len(self.manager.files), humanize.Size(self.manager.progress_tracker.total_size_of_all_files)))
	self.print_continue_msg()
}

func (self *handler) confirm_paths() {
	self.print_check_paths()
}

func (self *handler) transmit_one() {
	if self.transmit_iterator == nil {
		return
	}
	wid, err := self.transmit_iterator(self.lp.QueueWriteString)
	if err != nil {
		if err == files_done {
			self.transmit_iterator = nil
		} else {
			self.abort_with_error(err)
			return
		}
	} else {
		self.last_data_write_id = wid
	}
}

func (self *handler) start_transfer() {
	self.transmit_started = true
	n := len(self.manager.files)
	msg := `Transmitting signature of`
	if self.manager.use_rsync {
		msg = `Queueing transfer of`
	}
	msg += ` `
	if n == 1 {
		msg += `one file`
	} else {
		msg += fmt.Sprintf(`%d files`, n)
	}
	self.lp.Println(msg)
	self.max_name_length = 0
	for _, f := range self.manager.files {
		self.max_name_length = utils.Max(6, self.max_name_length, wcswidth.Stringwidth(f.display_name))
	}
	self.transmit_iterator = self.manager.request_files()
	self.transmit_one()
}

func (self *handler) on_file_transfer_response(ftc *FileTransmissionCommand) (err error) {
	if ftc.Id != self.manager.request_id {
		return
	}
	if ftc.Action == Action_status && ftc.Status == "CANCELED" {
		self.lp.Quit(1)
		return
	}
	if self.quit_after_write_code > -1 || self.manager.state == state_canceled {
		return
	}
	transfer_started := self.manager.state == state_transferring
	if merr := self.manager.on_file_transfer_response(ftc); merr != nil {
		if merr == unicode_input.ErrCanceledByUser {
			// terminal will not respond to cancel request
			return fmt.Errorf("Permission denied by user")
		}
		self.abort_with_error(merr)
		return
	}
	if !transfer_started && self.manager.state == state_transferring {
		if len(self.manager.failed_specs) > 0 {
			self.print_err(fmt.Errorf(`Failed to process some sources:`))
			for spec_id, msg := range self.manager.failed_specs {
				spec := self.manager.spec[spec_id]
				if strings.HasPrefix(msg, `ENOENT:`) {
					msg = `File not found`
				}
				self.lp.Println(fmt.Sprintf(`  %s: %s`, spec, msg))
			}
			self.abort_with_error(nil)
			return
		}
		zero_specs := make([]string, 0, len(self.manager.spec_counts))
		for k, v := range self.manager.spec_counts {
			if v == 0 {
				zero_specs = append(zero_specs, self.manager.spec[k])
			}
		}
		if len(zero_specs) > 0 {
			self.abort_with_error(fmt.Errorf(`No matches found for: %s`, strings.Join(zero_specs, ", ")))
			return
		}
		if merr := self.manager.collect_files(); merr != nil {
			self.abort_with_error(merr)
			return
		}
		if self.cli_opts.ConfirmPaths {
			self.confirm_paths()
		} else {
			self.start_transfer()
		}
	}
	if self.manager.transfer_done {
		self.manager.send(FileTransmissionCommand{Action: Action_finish}, self.lp.QueueWriteString)
		self.quit_after_write_code = 0
		if err = self.refresh_progress(0); err != nil {
			return err
		}
	} else if self.transmit_started {
		if err = self.refresh_progress(0); err != nil {
			return err
		}
	}
	return
}

func (self *handler) on_writing_finished(msg_id loop.IdType, has_pending_writes bool) (err error) {
	if self.quit_after_write_code > -1 {
		self.lp.Quit(self.quit_after_write_code)
	} else if msg_id == self.last_data_write_id {
		self.transmit_one()
	}
	return nil
}

func (self *handler) on_interrupt() (handled bool, err error) {
	handled = true
	if self.quit_after_write_code > -1 {
		return
	}
	if self.manager.state == state_canceled {
		self.lp.Println(`Waiting for canceled acknowledgement from terminal, will abort in a few seconds if no response received`)
		return
	}
	self.abort_with_error(fmt.Errorf(`Interrupt requested, cancelling transfer, transferred files are in undefined state.`))
	return
}

func (self *handler) on_sigterm() (handled bool, err error) {
	handled = true
	if self.quit_after_write_code > -1 {
		return
	}
	self.abort_with_error(fmt.Errorf(`Terminate requested, cancelling transfer, transferred files are in undefined state.`), 2*time.Second)
	return
}

func (self *handler) erase_progress() {
	if self.progress_drawn {
		self.lp.MoveCursorVertically(-2)
		self.lp.QueueWriteString("\r")
		self.lp.ClearToEndOfScreen()
		self.progress_drawn = false
	}
}

func (self *handler) render_progress(name string, p Progress) {
	if p.is_complete {
		p.bytes_so_far = p.total_bytes
	}
	ss, _ := self.lp.ScreenSize()
	self.lp.QueueWriteString(render_progress_in_width(name, p, int(ss.WidthCells), self.ctx))
}

func (self *handler) draw_progress_for_current_file(af *remote_file, spinner_char string, is_complete bool) {
	p := &self.manager.progress_tracker
	now := time.Now()
	secs := utils.IfElse(af.done_at.IsZero(), now, af.done_at)
	self.render_progress(af.display_name, Progress{
		spinner_char: spinner_char, is_complete: is_complete,
		bytes_so_far: af.written_bytes, total_bytes: af.expected_size,
		secs_so_far:   secs.Sub(af.transmit_started_at).Seconds(),
		bytes_per_sec: safe_divide(p.transfered_stats_amt, p.transfered_stats_interval),
	})
}

func (self *handler) draw_files() {
	tick := self.ctx.Green(`✔`)
	var sc string
	for _, df := range self.manager.progress_tracker.done_files {
		sc = tick
		if df.ftype == FileType_regular {
			self.draw_progress_for_current_file(df, sc, true)
		} else {
			self.lp.QueueWriteString(fmt.Sprintf("%s %s %s", sc, df.display_name, self.ctx.Italic(self.ctx.Dim(df.ftype.String()))))
		}
		self.lp.Println()
		self.manager.progress_tracker.done_files = nil
	}
	is_complete := self.quit_after_write_code > -1
	if is_complete {
		sc = utils.IfElse(self.quit_after_write_code == 0, tick, self.ctx.Red(`✘`))
	} else {
		sc = self.spinner.Tick()
	}
	p := &self.manager.progress_tracker
	ss, _ := self.lp.ScreenSize()
	if is_complete {
		tui.RepeatChar(`─`, int(ss.WidthCells))
	} else {
		af := p.active_file
		if af != nil {
			self.draw_progress_for_current_file(af, sc, false)
		}
	}
	self.lp.Println()
	if p.total_transferred > 0 {
		self.render_progress(`Total`, Progress{
			spinner_char: sc, bytes_so_far: p.total_transferred, total_bytes: p.total_bytes_to_transfer,
			secs_so_far: time.Since(p.started_at).Seconds(), is_complete: is_complete,
			bytes_per_sec: safe_divide(p.transfered_stats_amt, p.transfered_stats_interval.Abs().Seconds()),
		})
		self.lp.Println()
	} else {
		self.lp.Println(`File data transfer has not yet started`)
	}
}

func (self *handler) schedule_progress_update(delay time.Duration) {
	if self.progress_update_timer != 0 {
		self.lp.RemoveTimer(self.progress_update_timer)
		self.progress_update_timer = 0
	}
	timer_id, err := self.lp.AddTimer(delay, false, self.refresh_progress)
	if err == nil {
		self.progress_update_timer = timer_id
	}
}

func (self *handler) draw_progress() {
	if self.manager.state == state_canceled {
		return
	}
	self.lp.AllowLineWrapping(false)
	defer self.lp.AllowLineWrapping(true)
	self.draw_files()
	self.schedule_progress_update(self.spinner.Interval())
	self.progress_drawn = true
}

func (self *handler) refresh_progress(loop.IdType) error {
	self.lp.StartAtomicUpdate()
	defer self.lp.EndAtomicUpdate()
	self.erase_progress()
	self.draw_progress()
	return nil
}

func (self *handler) on_text(text string, from_key_event, in_bracketed_paste bool) error {
	if self.quit_after_write_code > -1 {
		return nil
	}
	if self.check_paths_printed && !self.transmit_started {
		switch strings.ToLower(text) {
		case "y":
			self.start_transfer()
			return nil
		case "n":
			self.abort_with_error(fmt.Errorf(`Canceled by user`))
			return nil
		}
		self.print_continue_msg()
	}
	return nil
}
func (self *handler) on_key_event(ev *loop.KeyEvent) error {
	if self.quit_after_write_code > -1 {
		return nil
	}
	if ev.MatchesPressOrRepeat("esc") {
		ev.Handled = true
		if self.check_paths_printed && !self.transmit_started {
			self.abort_with_error(fmt.Errorf(`Canceled by user`))
		} else {
			if _, err := self.on_interrupt(); err != nil {
				return err
			}
		}
	} else if ev.MatchesPressOrRepeat("ctrl+c") {
		ev.Handled = true
		if _, err := self.on_interrupt(); err != nil {
			return err
		}
	}
	return nil
}

func receive_loop(opts *Options, spec []string, dest string) (err error, rc int) {
	lp, err := loop.New(loop.NoAlternateScreen, loop.NoRestoreColors)
	if err != nil {
		return err, 1
	}

	handler := handler{
		lp: lp, quit_after_write_code: -1, cli_opts: opts, spinner: tui.NewSpinner("dots"),
		ctx: markup.New(true),
		manager: manager{
			request_id: random_id(), spec: spec, dest: dest, bypass: opts.PermissionsBypass, use_rsync: opts.TransmitDeltas,
			failed_specs: make(map[int]string, len(spec)), spec_counts: make(map[int]int, len(spec)),
			suffix: "\x1b\\", cli_opts: opts, files_to_be_transferred: make(map[string]*remote_file),
		},
	}
	for i := range spec {
		handler.manager.spec_counts[i] = 0
	}
	handler.manager.prefix = fmt.Sprintf("\x1b]%d;id=%s;", kitty.FileTransferCode, handler.manager.request_id)
	if handler.manager.bypass != `` {
		if handler.manager.bypass, err = encode_bypass(handler.manager.request_id, handler.manager.bypass); err != nil {
			return err, 1
		}
	}

	lp.OnInitialize = func() (string, error) {
		lp.SetCursorVisible(false)
		lp.Println("Scanning files…")
		handler.manager.start_transfer(lp.QueueWriteString)
		return "", nil
	}

	lp.OnFinalize = func() string {
		lp.SetCursorVisible(true)
		return ""
	}

	lp.OnSIGINT = handler.on_interrupt
	lp.OnSIGTERM = handler.on_sigterm
	lp.OnWriteComplete = handler.on_writing_finished
	lp.OnText = handler.on_text
	lp.OnKeyEvent = handler.on_key_event
	lp.OnResize = func(old_sz, new_sz loop.ScreenSize) error {
		if handler.progress_drawn {
			return handler.refresh_progress(0)
		}
		return nil
	}

	ftc_code := strconv.Itoa(kitty.FileTransferCode)
	lp.OnEscapeCode = func(et loop.EscapeCodeType, payload []byte) error {
		if et == loop.OSC {
			if idx := bytes.IndexByte(payload, ';'); idx > 0 {
				if utils.UnsafeBytesToString(payload[:idx]) == ftc_code {
					ftc, err := NewFileTransmissionCommand(utils.UnsafeBytesToString(payload[idx+1:]))
					if err != nil {
						return fmt.Errorf("Received invalid FileTransmissionCommand from terminal with error: %w", err)
					}
					return handler.on_file_transfer_response(ftc)
				}
			}
		}
		return nil
	}

	err = lp.Run()
	defer func() {
		for _, f := range handler.manager.files {
			f.close()
		}
	}()

	if err != nil {
		return err, 1
	}
	if lp.DeathSignalName() != "" {
		lp.KillIfSignalled()
		return
	}

	if lp.ExitCode() != 0 {
		rc = lp.ExitCode()
	}
	var tsf, dsz, ssz int64
	for _, f := range handler.manager.files {
		if rc == 0 { // no error has yet occurred report errors closing files
			if cerr := f.close(); cerr != nil {
				return cerr, 1
			}
		}
		if f.expect_diff {
			tsf += f.expected_size
			dsz += f.received_bytes
			ssz += f.sent_bytes
		}
	}
	if tsf > 0 && dsz+ssz > 0 && rc == 0 {
		print_rsync_stats(tsf, dsz, ssz)
	}
	return
}

func receive_main(opts *Options, args []string) (err error, rc int) {
	spec := args
	var dest string
	switch opts.Mode {
	case "mirror":
		if len(args) < 1 {
			return fmt.Errorf("Must specify at least one file to transfer"), 1
		}
	case "normal":
		if len(args) < 2 {
			return fmt.Errorf("Must specify at least one source and a destination file to transfer"), 1
		}
		dest = args[len(args)-1]
		spec = args[:len(args)-1]
	}
	return receive_loop(opts, spec, dest)
}
