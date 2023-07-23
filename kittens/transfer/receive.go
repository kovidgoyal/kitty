// License: GPLv3 Copyright: 2023, Kovid Goyal, <kovid at kovidgoyal.net>

package transfer

import (
	"bytes"
	"compress/zlib"
	"fmt"
	"io"
	"io/fs"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"time"

	"kitty"
	"kitty/tools/cli/markup"
	"kitty/tools/tui/loop"
	"kitty/tools/utils"
	"kitty/tools/utils/humanize"
	"kitty/tools/wcswidth"
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
	return ff.f.Seek(0, os.SEEK_CUR)
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

type remote_file struct {
	expected_size                int64
	expect_diff                  bool
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
	remote_symlink_value         string
	actual_file                  output_file
}

func (self *remote_file) close() error {
	if self.actual_file != nil {
		af := self.actual_file
		self.actual_file = nil
		return af.close()
	}
	return nil
}

func (self *remote_file) write_data(data []byte, is_last bool) (amt_written int64, err error) {
	self.received_bytes += int64(len(data))
	self.decompressor(data, is_last, func(data []byte) (err error) {
		switch self.ftype {
		case FileType_symlink:
			self.remote_symlink_value += string(data)
			return
		case FileType_regular:
			if self.actual_file == nil {
				parent := filepath.Dir(self.expanded_local_path)
				if parent != "" {
					os.MkdirAll(parent, 0o755)
				}
				if self.expect_diff {
					panic(`TODO: create PatchFile for rsync`)
				} else {
					if ff, err := os.Create(self.expanded_local_path); err != nil {
						return err
					} else {
						f := filesystem_file{f: ff}
						self.actual_file = &f
					}
				}
				base, err := self.actual_file.tell()
				if err != nil {
					return err
				}
				for len(data) > 0 {
					n, werr := self.actual_file.write(data)
					data = data[n:]
					if werr != nil && werr != io.ErrShortWrite {
						return werr
					}
				}
				pos, err := self.actual_file.tell()
				if err != nil {
					return err
				}
				amt_written = pos - base
				if is_last {
					self.actual_file.close()
					self.actual_file = nil
				}
			}
		}
		return
	})
	return
}

func (self *remote_file) apply_metadata() {
	if self.ftype != FileType_symlink {
		os.Chmod(self.expanded_local_path, self.permissions)
		os.Chtimes(self.expanded_local_path, time.Unix(0, int64(self.mtime)), time.Unix(0, int64(self.mtime)))
	}
}

func new_remote_file(opts *Options, ftc *FileTransmissionCommand) (*remote_file, error) {
	spec_id, err := strconv.Atoi(ftc.File_id)
	if err != nil {
		return nil, err
	}
	ans := &remote_file{
		expected_size: ftc.Size, ftype: ftc.Ftype, mtime: ftc.Mtime, spec_id: spec_id,
		permissions: ftc.Permissions, remote_path: ftc.Name, display_name: wcswidth.StripEscapeCodes(ftc.Name),
		remote_id: ftc.Status, remote_target: string(ftc.Data), parent: ftc.Parent,
	}
	compression_capable := ftc.Ftype == FileType_regular && ftc.Size > 4096 && should_be_compressed(ftc.Name, opts.Compress)
	if compression_capable {
		ans.decompressor, err = utils.NewStreamDecompressor(zlib.NewReader)
	} else {
		ans.decompressor, err = utils.NewStreamDecompressor(nil)
	}
	if err != nil {
		return nil, err
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

type handler struct {
	lp                    *loop.Loop
	cli_opts              *Options
	ctx                   *markup.Context
	manager               manager
	quit_after_write_code int
	check_paths_printed   bool
	transmit_started      bool
	progress_drawn        bool
	max_name_length       int
}

func (self *manager) start_transfer(send func(string) loop.IdType) {
	s := func(c FileTransmissionCommand) {
		send(self.prefix)
		send(c.Serialize(false))
		send(self.suffix)
	}
	s(FileTransmissionCommand{Action: Action_receive, Bypass: self.bypass, Size: int64(len(self.spec))})
	for i, x := range self.spec {
		s(FileTransmissionCommand{Action: Action_file, File_id: strconv.Itoa(i), Name: x})
	}
	self.progress_tracker.start_transfer()
}

func (self *handler) print_err(err error) {
	self.lp.Println(self.ctx.BrightRed(err.Error()))
}

func (self *handler) do_error_quit(loop.IdType) error {
	self.lp.Quit(1)
	return nil
}

func (self *handler) abort_transfer(delay time.Duration) {
	if delay <= 0 {
		delay = time.Second * 5
	}
	self.lp.QueueWriteString(self.manager.prefix)
	self.lp.QueueWriteString(FileTransmissionCommand{Action: Action_cancel}.Serialize(false))
	self.lp.QueueWriteString(self.manager.suffix)
	self.manager.state = state_canceled
	self.lp.AddTimer(delay, false, self.do_error_quit)
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
			os.Remove(f.expanded_local_path)
			if err = os.Symlink(lt, f.expanded_local_path); err != nil {
				return fmt.Errorf(`Failed to create symlink with error: %w`, err)
			}
			f.apply_metadata()
		}
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
				return fmt.Errorf(`Permission for transfer denied`)
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
			if rf, err := new_remote_file(self.cli_opts, ftc); err == nil {
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
	parent      *tree_node
	added_files map[*remote_file]*tree_node
}

func (self *tree_node) add_child(f *remote_file) *tree_node {
	if _, found := self.added_files[f]; found {
		return self
	}
	c := tree_node{entry: f, parent: self, added_files: make(map[*remote_file]*tree_node)}
	f.expanded_local_path = filepath.Join(self.entry.expanded_local_path, filepath.Base(f.remote_path))
	self.added_files[f] = &c
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

func ensure_parent(f *remote_file, root_node *tree_node, node_map map[string]*tree_node, fid_map map[string]*remote_file) *tree_node {
	if f.parent == "" {
		return root_node
	}
	if parent, found := node_map[f.parent]; found {
		return parent
	}
	fp := fid_map[f.parent]
	gp := ensure_parent(fp, root_node, node_map, fid_map)
	return gp.add_child(fp)
}

func make_tree(all_files []*remote_file, local_base string) (root_node *tree_node) {
	fid_map := make(map[string]*remote_file, len(all_files))
	for _, f := range all_files {
		fid_map[f.remote_id] = f
	}
	node_map := make(map[string]*tree_node)
	root_node = &tree_node{added_files: make(map[*remote_file]*tree_node)}

	for _, f := range all_files {
		p := ensure_parent(f, root_node, node_map, fid_map)
		p.add_child(f)
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
			walk_tree(tree, func(x *tree_node) error {
				ans = append(ans, x.entry)
				return nil
			})
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
				walk_tree(tree, func(x *tree_node) error {
					ans = append(ans, x.entry)
					return nil
				})
			} else {
				f := files_for_spec[0]
				f.expanded_local_path = dest
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
	self.lp.Println(`Press `, self.ctx.Green(`y`), ` to continue or `, self.ctx.BrightRed(`n`), ` to abort`)
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
			lpath = self.ctx.Prettify(fmt.Sprintf(":red:`%s` ", lpath))
		}
		self.lp.Println(df.display_name, " → ", lpath)
	}
	self.lp.Println(fmt.Sprintf(`Transferring %d file(s) of total size: %s`, len(self.manager.files), humanize.Size(self.manager.progress_tracker.total_size_of_all_files)))
	self.print_continue_msg()
}

func (self *handler) confirm_paths() {
	self.print_check_paths()
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
	err = self.manager.on_file_transfer_response(ftc)
	if err != nil {
		self.print_err(err)
		self.lp.Println(`Waiting to ensure terminal cancels transfer, will quit in a few seconds`)
		self.abort_transfer(-1)
		return
	}
	if !transfer_started && self.manager.state == state_transferring {
		if len(self.manager.failed_specs) > 0 {
			self.print_err(fmt.Errorf(`Failed to process some sources:`))
			for spec_id, msg := range self.manager.failed_specs {
				spec := self.manager.spec[spec_id]
				self.lp.Println(fmt.Sprintf(`  {%s}: {%s}`, spec, msg))
			}
			self.lp.Quit(1)
			return
		}
		zero_specs := make([]string, 0, len(self.manager.spec_counts))
		for k, v := range self.manager.spec_counts {
			if v == 0 {
				zero_specs = append(zero_specs, self.manager.spec[k])
			}
		}
		if len(zero_specs) > 0 {
			self.print_err(fmt.Errorf(`No matches found for: %s`, strings.Join(zero_specs, ", ")))
			self.lp.Quit(1)
			return
		}
		if err = self.manager.collect_files(); err != nil {
			return
		}
		if self.cli_opts.ConfirmPaths {
			self.confirm_paths()
		} else {
			self.start_transfer()
		}
	}
	if self.manager.transfer_done {
		self.lp.QueueWriteString(self.manager.prefix)
		self.lp.QueueWriteString(FileTransmissionCommand{Action: Action_finish}.Serialize(false))
		self.lp.QueueWriteString(self.manager.suffix)
		self.quit_after_write_code = 0
		self.refresh_progress()
	} else if self.transmit_started {
		self.refresh_progress()
	}
	return
}

func (self *handler) on_sigint() (handled bool, err error) {
	handled = true
	if self.quit_after_write_code > -1 {
		return
	}
	if self.manager.state == state_canceled {
		self.lp.Println(`Waiting for canceled acknowledgement from terminal, will abort in a few seconds if no response received`)
		return
	}
	self.print_err(fmt.Errorf(`Interrupt requested, cancelling transfer, transferred files are in undefined state`))
	self.abort_transfer(-1)
	return
}

func (self *handler) on_sigterm() (handled bool, err error) {
	handled = true
	if self.quit_after_write_code > -1 {
		return
	}
	self.print_err(fmt.Errorf(`Terminate requested, cancelling transfer, transferred files are in undefined state`))
	self.abort_transfer(2 * time.Second)
	return
}

func receive_loop(opts *Options, spec []string, dest string) (err error, rc int) {
	lp, err := loop.New(loop.NoAlternateScreen, loop.NoRestoreColors)
	if err != nil {
		return err, 1
	}

	handler := handler{
		lp: lp, quit_after_write_code: -1, cli_opts: opts,
		manager: manager{
			request_id: random_id(), spec: spec, dest: dest, bypass: opts.PermissionsBypass, use_rsync: opts.TransmitDeltas,
			failed_specs: make(map[int]string, len(spec)), spec_counts: make(map[int]int, len(spec)),
			suffix: "\x1b\\", cli_opts: opts, files_to_be_transferred: make(map[string]*remote_file),
		},
	}
	for i := range spec {
		handler.manager.spec_counts[i] = 0
	}
	handler.manager.prefix = fmt.Sprintf("\x1b]{%d};id=%s;", kitty.FileTransferCode, handler.manager.request_id)
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

	lp.OnSIGINT = handler.on_sigint
	lp.OnSIGTERM = handler.on_sigterm

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
		if err = f.close(); err != nil {
			return err, 1
		}
		if f.expect_diff {
			tsf += f.expected_size
			dsz += f.received_bytes
			ssz += f.sent_bytes
		}
	}
	if tsf > 0 && dsz+ssz > 0 {
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
