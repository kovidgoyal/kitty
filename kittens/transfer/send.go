// License: GPLv3 Copyright: 2023, Kovid Goyal, <kovid at kovidgoyal.net>

package transfer

import (
	"fmt"
	"io/fs"
	"kitty"
	"kitty/tools/tui/loop"
	"kitty/tools/utils"
	"kitty/tools/wcswidth"
	"os"
	"path/filepath"
	"strings"
	"syscall"
	"time"

	"golang.org/x/exp/slices"
)

var _ = fmt.Print

type FileState int

const (
	WAITING_FOR_START FileState = iota
	WAITING_FOR_DATA
	TRANSMITTING
	FINISHED
	ACKNOWLEDGED
)

type FileHash struct{ dev, inode uint64 }

type File struct {
	file_hash                                             FileHash
	file_type                                             FileType
	file_id, hard_link_target                             string
	local_path, symbolic_link_target, expanded_local_path string
	stat_result                                           fs.FileInfo
	state                                                 FileState
	display_name                                          string
	mtime                                                 time.Time
	file_size, bytes_to_transmit                          int64
	permissions                                           fs.FileMode
	remote_path                                           string
	rsync_capable, compression_capable                    bool
	remote_final_path                                     string
	remote_initial_size                                   int64
	err_msg                                               string
	actual_file                                           *os.File
	transmitted_bytes, reported_progress                  int64
	transmit_started_at, transmit_ended_at, done_at       time.Time
}

func get_remote_path(local_path string, remote_base string) string {
	if remote_base == "" {
		return filepath.ToSlash(local_path)
	}
	if strings.HasSuffix(remote_base, "/") {
		return filepath.Join(remote_base, filepath.Base(local_path))
	}
	return remote_base
}

func NewFile(local_path, expanded_local_path string, file_id int, stat_result fs.FileInfo, remote_base string, file_type FileType) *File {
	stat, ok := stat_result.Sys().(*syscall.Stat_t)
	if !ok {
		panic("This platform does not support getting file identities from stat results")
	}
	ans := File{
		local_path: local_path, expanded_local_path: expanded_local_path, file_id: fmt.Sprintf("%x", file_id),
		stat_result: stat_result, file_type: file_type, display_name: wcswidth.StripEscapeCodes(local_path),
		file_hash: FileHash{stat.Dev, stat.Ino}, mtime: stat_result.ModTime(),
		file_size: stat_result.Size(), bytes_to_transmit: stat_result.Size(),
		permissions: stat_result.Mode().Perm(), remote_path: filepath.ToSlash(get_remote_path(local_path, remote_base)),
		rsync_capable:       file_type == FileType_regular && stat_result.Size() > 4096,
		compression_capable: file_type == FileType_regular && stat_result.Size() > 4096 && should_be_compressed(expanded_local_path),
		remote_initial_size: -1,
	}
	return &ans
}

func process(opts *Options, paths []string, remote_base string, counter *int) (ans []*File, err error) {
	for _, x := range paths {
		expanded := expand_home(x)
		s, err := os.Lstat(expanded)
		if err != nil {
			return ans, fmt.Errorf("Failed to stat %s with error: %w", x, err)
		}
		if s.IsDir() {
			*counter += 1
			ans = append(ans, NewFile(x, expanded, *counter, s, remote_base, FileType_directory))
			new_remote_base := remote_base
			if new_remote_base != "" {
				new_remote_base = strings.TrimRight(new_remote_base, "/") + "/" + filepath.Base(x) + "/"
			} else {
				new_remote_base = strings.TrimRight(filepath.ToSlash(x), "/") + "/"
			}
			contents, err := os.ReadDir(expanded)
			if err != nil {
				return ans, fmt.Errorf("Failed to read the directory %s with error: %w", x, err)
			}
			new_paths := make([]string, len(contents))
			for i, y := range contents {
				new_paths[i] = filepath.Join(x, y.Name())
			}
			new_ans, err := process(opts, new_paths, new_remote_base, counter)
			if err != nil {
				return ans, err
			}
			ans = append(ans, new_ans...)
		} else if s.Mode()&fs.ModeSymlink == fs.ModeSymlink {
			*counter += 1
			ans = append(ans, NewFile(x, expanded, *counter, s, remote_base, FileType_symlink))
		} else if s.Mode().IsRegular() {
			*counter += 1
			ans = append(ans, NewFile(x, expanded, *counter, s, remote_base, FileType_regular))
		}
	}
	return
}

func process_mirrored_files(opts *Options, args []string) (ans []*File, err error) {
	paths := utils.Map(func(x string) string { return abspath(x) }, args)
	common_path := utils.Commonpath(paths...)
	home := strings.TrimRight(home_path(), string(filepath.Separator))
	if common_path != "" && strings.HasPrefix(common_path, home+string(filepath.Separator)) {
		paths = utils.Map(func(x string) string {
			r, _ := filepath.Rel(home, x)
			return filepath.Join("~", r)
		}, paths)
	}
	counter := 0
	return process(opts, paths, "", &counter)
}

func process_normal_files(opts *Options, args []string) (ans []*File, err error) {
	if len(args) < 2 {
		return ans, fmt.Errorf("Must specify at least one local path and one remote path")
	}
	args = slices.Clone(args)
	remote_base := filepath.ToSlash(args[len(args)-1])
	args = args[:len(args)-1]
	if len(args) > 1 && !strings.HasSuffix(remote_base, "/") {
		remote_base += "/"
	}
	paths := utils.Map(func(x string) string { return abspath(x) }, args)
	counter := 0
	return process(opts, paths, remote_base, &counter)
}

func files_for_send(opts *Options, args []string) (files []*File, err error) {
	if opts.Mode == "mirror" {
		files, err = process_mirrored_files(opts, args)
	} else {
		files, err = process_normal_files(opts, args)
	}
	if err != nil {
		return files, err
	}
	groups := make(map[FileHash][]*File, len(files))

	// detect hard links
	for _, f := range files {
		groups[f.file_hash] = append(groups[f.file_hash], f)
	}
	for _, group := range groups {
		if len(group) > 1 {
			for _, lf := range group[1:] {
				lf.file_type = FileType_link
				lf.hard_link_target = group[0].file_id
			}
		}
	}

	remove := make([]int, 0, len(files))
	// detect symlinks to other transferred files
	for i, f := range files {
		if f.file_type == FileType_symlink {
			link_dest, err := os.Readlink(f.local_path)
			if err != nil {
				remove = append(remove, i)
				continue
			}
			f.symbolic_link_target = "path:" + link_dest
			is_abs := filepath.IsAbs(link_dest)
			q := link_dest
			if !is_abs {
				q = filepath.Join(filepath.Dir(f.local_path), link_dest)
			}
			st, err := os.Stat(q)
			if err == nil {
				stat, ok := st.Sys().(*syscall.Stat_t)
				if ok {
					fh := FileHash{stat.Dev, stat.Ino}
					gr, found := groups[fh]
					if found {
						g := utils.Filter(gr, func(x *File) bool {
							return os.SameFile(x.stat_result, st)
						})
						if len(g) > 0 {
							f.symbolic_link_target = "fid"
							if is_abs {
								f.symbolic_link_target = "fid_abs"
							}
							f.symbolic_link_target += ":" + g[0].file_id
						}
					}
				}
			}
		}
	}
	if len(remove) > 0 {
		for _, idx := range utils.Reverse(remove) {
			files[idx] = nil
			files = slices.Delete(files, idx, idx+1)
		}
	}
	return files, nil
}

type SendState int

const (
	SEND_WAITING_FOR_PERMISSION SendState = iota
	SEND_PERMISSION_GRANTED
	SEND_PERMISSION_DENIED
	SEND_CANCELED
)

type Transfer struct {
	amt int64
	at  time.Time
}

func (self *Transfer) is_too_old(now time.Time) bool {
	return now.Sub(self.at) > 30*time.Second
}

type ProgressTracker struct {
	total_size_of_all_files, total_bytes_to_transfer int64
	active_file                                      *File
	total_transferred                                int64
	transfers                                        []*Transfer
	transfered_stats_amt                             int64
	transfered_stats_interval                        time.Duration
	started_at                                       time.Time
	signature_bytes                                  int
	total_reported_progress                          int64
}

func (self *ProgressTracker) change_active_file(nf *File) {
	now := time.Now()
	self.active_file = nf
	nf.transmit_started_at = now
}

func (self *ProgressTracker) start_transfer() {
	t := Transfer{at: time.Now()}
	self.transfers = append(self.transfers, &t)
	self.started_at = t.at
}

func (self *ProgressTracker) on_transmit(amt int64) {
	if self.active_file != nil {
		self.active_file.transmitted_bytes += amt
	}
	self.total_transferred += amt
	now := time.Now()
	self.transfers = append(self.transfers, &Transfer{amt: amt, at: now})
	for len(self.transfers) > 2 && self.transfers[0].is_too_old(now) {
		self.transfers = self.transfers[1:]
	}
	self.transfered_stats_interval = now.Sub(self.transfers[0].at)
	self.transfered_stats_amt = 0
	for _, t := range self.transfers {
		self.transfered_stats_amt += t.amt
	}
}

func (self *ProgressTracker) on_file_progress(af *File, delta int64) {
	if delta > 0 {
		self.total_reported_progress += delta
	}
}

func (self *ProgressTracker) on_file_done(af *File) {
	af.done_at = time.Now()
}

type SendManager struct {
	request_id                                                 string
	state                                                      SendState
	files                                                      []*File
	bypass                                                     string
	use_rsync                                                  bool
	file_progress                                              func(*File, int)
	file_done                                                  func(*File)
	fid_map                                                    map[string]*File
	all_acknowledged, all_started, has_transmitting, has_rsync bool
	active_idx, current_chunk_uncompressed_size                int
	prefix, suffix                                             string
	last_progress_file                                         *File
	progress_tracker                                           *ProgressTracker
}

func (self *SendManager) start_transfer() string {
	panic("TODO: Implement this")
}

func (self *SendManager) initialize() {
	if self.bypass != "" {
		self.bypass = encode_bypass(self.request_id, self.bypass)
	}
	self.fid_map = make(map[string]*File, len(self.files))
	for _, f := range self.files {
		self.fid_map[f.file_id] = f
	}
	self.active_idx = -1
	self.current_chunk_uncompressed_size = -1
	self.prefix = fmt.Sprintf("\x1b]%d;id=%s;", kitty.FileTransferCode, self.request_id)
	self.suffix = "\x1b\\"
	for _, f := range self.files {
		if f.file_size > 0 {
			self.progress_tracker.total_size_of_all_files += f.file_size
		}
	}
	self.progress_tracker.total_bytes_to_transfer = self.progress_tracker.total_size_of_all_files
}

type SendHandler struct {
	manager                              *SendManager
	opts                                 *Options
	files                                []*File
	lp                                   *loop.Loop
	transmit_started, file_metadata_sent bool
	quite_after_write_code               int
	check_paths_printed                  bool
	max_name_length                      int
	progress_drawn                       bool
	failed_files, done_files             []*File
	done_file_ids                        *utils.Set[string]
	transmit_ok_checked                  bool
	progress_update_timer                loop.IdType
}

func (self *SendHandler) refresh_progress(timer_id loop.IdType) (err error) {
	self.progress_update_timer = 0
	panic("TODO: Implement this")
}

func (self *SendHandler) schedule_progress_update(delay time.Duration) {
	if self.progress_update_timer != 0 {
		self.lp.RemoveTimer(self.progress_update_timer)
		self.progress_update_timer = 0
	}
	timer_id, err := self.lp.AddTimer(delay, false, self.refresh_progress)
	if err == nil {
		self.progress_update_timer = timer_id
	}
}

func (self *SendHandler) on_file_progress(f *File, change int) {
	self.schedule_progress_update(100 * time.Millisecond)
}

func (self *SendHandler) on_file_done(f *File) {
	self.done_files = append(self.done_files, f)
	if f.err_msg != "" {
		self.failed_files = append(self.failed_files, f)
	}
	self.schedule_progress_update(100 * time.Millisecond)
}

func (self *SendHandler) send_payload(payload string) {
	self.lp.QueueWriteString(self.manager.prefix)
	self.lp.QueueWriteString(payload)
	self.lp.QueueWriteString(self.manager.suffix)
}

func (self *SendHandler) send_file_metadata() error {
	panic("TODO: Implement this")
}

func (self *SendHandler) initialize() error {
	self.manager.initialize()
	self.send_payload(self.manager.start_transfer())
	if self.opts.PermissionsBypass != "" {
		// dont wait for permission, not needed with a bypass and avoids a roundtrip
		return self.send_file_metadata()
	}
	return nil
}

func send_loop(opts *Options, files []*File) (err error) {
	lp, err := loop.New(loop.NoAlternateScreen, loop.NoRestoreColors)
	if err != nil {
		return
	}

	handler := &SendHandler{
		opts: opts, files: files, lp: lp, quite_after_write_code: -1,
		max_name_length: utils.Max(0, utils.Map(func(f *File) int { return wcswidth.Stringwidth(f.display_name) }, files)...),
		progress_drawn:  true, done_file_ids: utils.NewSet[string](),
		manager: &SendManager{
			request_id: random_id(), files: files, bypass: opts.PermissionsBypass, use_rsync: opts.TransmitDeltas,
		},
	}
	handler.manager.file_progress = handler.on_file_progress
	handler.manager.file_done = handler.on_file_done

	lp.OnInitialize = func() (string, error) {
		return "", handler.initialize()
	}
	return
}

func send_main(opts *Options, args []string) (err error) {
	fmt.Println("Scanning files…")
	files, err := files_for_send(opts, args)
	if err != nil {
		return err
	}
	fmt.Printf("Found %d files and directories, requesting transfer permission…", len(files))
	fmt.Println()
	err = send_loop(opts, files)

	return
}
