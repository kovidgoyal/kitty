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
	"syscall"
	"time"
	"unicode/utf8"

	"golang.org/x/exp/constraints"

	"github.com/kovidgoyal/kitty"
	"github.com/kovidgoyal/kitty/tools/cli/markup"
	"github.com/kovidgoyal/kitty/tools/rsync"
	"github.com/kovidgoyal/kitty/tools/tui"
	"github.com/kovidgoyal/kitty/tools/tui/loop"
	"github.com/kovidgoyal/kitty/tools/utils"
	"github.com/kovidgoyal/kitty/tools/utils/humanize"
	"github.com/kovidgoyal/kitty/tools/wcswidth"
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

type Compressor interface {
	Compress(data []byte) []byte
	Flush() []byte
}

type IdentityCompressor struct{}

func (self *IdentityCompressor) Compress(data []byte) []byte { return data }
func (self *IdentityCompressor) Flush() []byte               { return nil }

type ZlibCompressor struct {
	b bytes.Buffer
	w zlib.Writer
}

func NewZlibCompressor() *ZlibCompressor {
	ans := ZlibCompressor{}
	ans.b.Grow(4096)
	ans.w = *zlib.NewWriter(&ans.b)
	return &ans
}

func (self *ZlibCompressor) Compress(data []byte) []byte {
	_, err := self.w.Write(data)
	if err != nil {
		panic(err)
	}
	defer self.b.Reset()
	return utils.UnsafeStringToBytes(self.b.String())
}

func (self *ZlibCompressor) Flush() []byte {
	self.w.Close()
	return self.b.Bytes()
}

type File struct {
	file_hash                                             FileHash
	ttype                                                 TransmissionType
	compression                                           Compression
	compressor                                            Compressor
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
	differ                                                *rsync.Differ
	delta_loader                                          func() error
	deltabuf                                              *bytes.Buffer
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

func NewFile(opts *Options, local_path, expanded_local_path string, file_id int, stat_result fs.FileInfo, remote_base string, file_type FileType) *File {
	stat, ok := stat_result.Sys().(*syscall.Stat_t)
	if !ok {
		panic("This platform does not support getting file identities from stat results")
	}
	ans := File{
		local_path: local_path, expanded_local_path: expanded_local_path, file_id: fmt.Sprintf("%x", file_id),
		stat_result: stat_result, file_type: file_type, display_name: wcswidth.StripEscapeCodes(local_path),
		file_hash: FileHash{uint64(stat.Dev), stat.Ino}, mtime: stat_result.ModTime(),
		file_size: stat_result.Size(), bytes_to_transmit: stat_result.Size(),
		permissions: stat_result.Mode().Perm(), remote_path: filepath.ToSlash(get_remote_path(local_path, remote_base)),
		rsync_capable:       file_type == FileType_regular && stat_result.Size() > 4096,
		compression_capable: file_type == FileType_regular && stat_result.Size() > 4096 && should_be_compressed(expanded_local_path, opts.Compress),
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
			ans = append(ans, NewFile(opts, x, expanded, *counter, s, remote_base, FileType_directory))
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
			ans = append(ans, NewFile(opts, x, expanded, *counter, s, remote_base, FileType_symlink))
		} else if s.Mode().IsRegular() {
			*counter += 1
			ans = append(ans, NewFile(opts, x, expanded, *counter, s, remote_base, FileType_regular))
		}
	}
	return
}

func process_mirrored_files(opts *Options, args []string) (ans []*File, err error) {
	paths := utils.Map(func(x string) string { return abspath(expand_home(x)) }, args)
	home := strings.TrimRight(home_path(), string(filepath.Separator)) + string(filepath.Separator)
	paths = utils.Map(func(path string) string {
		if strings.HasPrefix(path, home) {
			r, _ := filepath.Rel(home, path)
			return filepath.Join("~", r)
		}
		return path
	}, paths)
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
	paths := utils.Map(func(x string) string { return abspath(expand_home(x)) }, args)
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
				lf.hard_link_target = "fid:" + group[0].file_id
			}
		}
	}

	remove := make([]int, 0, len(files))
	// detect symlinks to other transferred files
	for i, f := range files {
		if f.file_type == FileType_symlink {
			link_dest, err := os.Readlink(f.expanded_local_path)
			if err != nil {
				remove = append(remove, i)
				continue
			}
			f.symbolic_link_target = "path:" + link_dest
			is_abs := filepath.IsAbs(link_dest)
			q := link_dest
			if !is_abs {
				q = filepath.Join(filepath.Dir(f.expanded_local_path), link_dest)
			}
			st, err := os.Stat(q)
			if err == nil {
				stat, ok := st.Sys().(*syscall.Stat_t)
				if ok {
					fh := FileHash{uint64(stat.Dev), stat.Ino}
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

func (self *ProgressTracker) on_transmit(amt int64, active_file *File) {
	active_file.transmitted_bytes += amt
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
	file_done                                                  func(*File) error
	fid_map                                                    map[string]*File
	all_acknowledged, all_started, has_transmitting, has_rsync bool
	active_idx                                                 int
	prefix, suffix                                             string
	last_progress_file                                         *File
	progress_tracker                                           ProgressTracker
	current_chunk_uncompressed_sz                              int64
	current_chunk_write_id                                     loop.IdType
	current_chunk_for_file_id                                  string
}

func (self *SendManager) start_transfer() string {
	return FileTransmissionCommand{Action: Action_send, Bypass: self.bypass}.Serialize()
}

func (self *SendManager) initialize() {
	if self.bypass != "" {
		q, err := encode_bypass(self.request_id, self.bypass)
		if err == nil {
			self.bypass = q
		} else {
			fmt.Fprintln(os.Stderr, "Ignoring password because of error:", err)
		}

	}
	self.fid_map = make(map[string]*File, len(self.files))
	for _, f := range self.files {
		self.fid_map[f.file_id] = f
	}
	self.active_idx = -1
	self.current_chunk_uncompressed_sz = -1
	self.current_chunk_for_file_id = ""
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
	ctx                                  *markup.Context
	transmit_started, file_metadata_sent bool
	quit_after_write_code                int
	finish_cmd_write_id                  loop.IdType
	check_paths_printed                  bool
	transfer_finish_sent                 bool
	max_name_length                      int
	progress_drawn                       bool
	failed_files, done_files             []*File
	done_file_ids                        *utils.Set[string]
	transmit_ok_checked                  bool
	progress_update_timer                loop.IdType
	spinner                              *tui.Spinner
}

func safe_divide[A constraints.Integer | constraints.Float, B constraints.Integer | constraints.Float](a A, b B) float64 {
	if b == 0 {
		return 0
	}
	return float64(a) / float64(b)
}

type Progress struct {
	spinner_char    string
	bytes_so_far    int64
	total_bytes     int64
	secs_so_far     float64
	bytes_per_sec   float64
	is_complete     bool
	max_path_length int
}

func reduce_to_single_grapheme(text string) string {
	limit := utf8.RuneCountInString(text)
	if limit < 2 {
		return text
	}
	for x := 1; x < limit; x++ {
		tt, w := wcswidth.TruncateToVisualLengthWithWidth(text, x)
		if w <= x {
			return tt
		}
	}
	return text
}

func render_path_in_width(path string, width int) string {
	path = filepath.ToSlash(path)
	if wcswidth.Stringwidth(path) <= width {
		return path
	}
	parts := strings.Split(path, string(filepath.Separator))
	reduced := strings.Join(utils.Map(reduce_to_single_grapheme, parts[:len(parts)-1]), string(filepath.Separator))
	path = filepath.Join(reduced, parts[len(parts)-1])
	if wcswidth.Stringwidth(path) <= width {
		return path
	}
	return wcswidth.TruncateToVisualLength(path, width-1) + `…`
}

func ljust(text string, width int) string {
	if w := wcswidth.Stringwidth(text); w < width {
		text += strings.Repeat(` `, (width - w))
	}
	return text
}

func rjust(text string, width int) string {
	if w := wcswidth.Stringwidth(text); w < width {
		text = strings.Repeat(` `, (width-w)) + text
	}
	return text
}

func render_progress_in_width(path string, p Progress, width int, ctx *markup.Context) string {
	unit_style := ctx.Dim(`|`)
	sep, trail, _ := strings.Cut(unit_style, "|")
	var ratio, rate, eta string
	if p.is_complete || p.bytes_so_far >= p.total_bytes {
		ratio = humanize.Size(uint64(p.total_bytes), humanize.SizeOptions{Separator: sep})
		rate = humanize.Size(uint64(safe_divide(float64(p.total_bytes), p.secs_so_far)), humanize.SizeOptions{Separator: sep}) + `/s`
		eta = ctx.Green(humanize.ShortDuration(time.Duration(float64(time.Second) * p.secs_so_far)))
	} else {
		tb := humanize.Size(p.total_bytes)
		sval, _, _ := strings.Cut(tb, " ")
		val, _ := strconv.ParseFloat(sval, 64)
		ratio = humanize.FormatNumber(val*safe_divide(p.bytes_so_far, p.total_bytes)) + `/` + strings.ReplaceAll(tb, ` `, sep)
		rate = humanize.Size(p.bytes_per_sec, humanize.SizeOptions{Separator: sep}) + `/s`
		bytes_left := p.total_bytes - p.bytes_so_far
		eta_seconds := safe_divide(bytes_left, p.bytes_per_sec)
		eta = humanize.ShortDuration(time.Duration(float64(time.Second) * eta_seconds))
	}
	lft := p.spinner_char + ` `
	max_space_for_path := width/2 - wcswidth.Stringwidth(lft)
	max_path_length := 80
	w := utils.Min(max_path_length, max_space_for_path)
	prefix := lft + render_path_in_width(path, w)
	w += wcswidth.Stringwidth(lft)
	prefix = ljust(prefix, w)
	q := ratio + trail + ctx.Yellow(" @ ") + rate + trail
	q = rjust(q, 25) + ` `
	eta = ` ` + eta
	if extra := width - w - wcswidth.Stringwidth(q) - wcswidth.Stringwidth(eta); extra > 4 {
		q += tui.RenderProgressBar(safe_divide(p.bytes_so_far, p.total_bytes), extra) + eta
	} else {
		q += strings.TrimSpace(eta)
	}
	return prefix + q
}

func (self *SendHandler) render_progress(name string, p Progress) {
	if p.spinner_char == "" {
		p.spinner_char = " "
	}
	if p.is_complete {
		p.bytes_so_far = p.total_bytes
	}
	p.max_path_length = self.max_name_length
	sz, _ := self.lp.ScreenSize()
	self.lp.QueueWriteString(render_progress_in_width(name, p, int(sz.WidthCells), self.ctx))
}

func (self *SendHandler) draw_progress() {
	self.lp.AllowLineWrapping(false)
	defer self.lp.AllowLineWrapping(true)
	var sc string
	for _, df := range self.done_files {
		sc = self.ctx.Green(`✔`)
		if df.err_msg != "" {
			sc = self.ctx.Err(`✘`)
		}
		if df.file_type == FileType_regular {
			self.draw_progress_for_current_file(df, sc, true)
		} else {
			self.lp.QueueWriteString(sc + ` ` + df.display_name + ` ` + self.ctx.Dim(self.ctx.Italic(df.file_type.String())))
		}
		self.lp.Println()
		self.done_file_ids.Add(df.file_id)
	}
	self.done_files = nil
	is_complete := self.quit_after_write_code > -1
	if is_complete {
		sc = self.ctx.Green(`✔`)
		if self.quit_after_write_code != 0 {
			sc = self.ctx.Err(`✘`)
		}
	} else {
		sc = self.spinner.Tick()
	}
	now := time.Now()
	if is_complete {
		sz, _ := self.lp.ScreenSize()
		self.lp.QueueWriteString(tui.RepeatChar(`─`, int(sz.WidthCells)))
	} else {
		af := self.manager.last_progress_file
		if af == nil || self.done_file_ids.Has(af.file_id) {
			if !self.manager.has_transmitting && self.done_file_ids.Len() == 0 {
				if self.manager.has_rsync {
					self.lp.QueueWriteString(sc + ` Transferring rsync signatures...`)
				} else {
					self.lp.QueueWriteString(sc + ` Transferring metadata...`)
				}
			}
		} else {
			self.draw_progress_for_current_file(af, sc, false)
		}
	}
	self.lp.Println()
	if p := self.manager.progress_tracker; p.total_reported_progress > 0 {
		self.render_progress(`Total`, Progress{
			spinner_char: sc, bytes_so_far: p.total_reported_progress, total_bytes: p.total_bytes_to_transfer,
			secs_so_far: now.Sub(p.started_at).Seconds(), is_complete: is_complete,
			bytes_per_sec: safe_divide(p.transfered_stats_amt, p.transfered_stats_interval.Abs().Seconds()),
		})
	} else {
		self.lp.QueueWriteString(`File data transfer has not yet started`)
	}
	self.lp.Println()
	self.schedule_progress_update(self.spinner.Interval())
	self.progress_drawn = true
}

func (self *SendHandler) draw_progress_for_current_file(af *File, spinner_char string, is_complete bool) {
	p := self.manager.progress_tracker
	var secs_so_far time.Duration
	empty := File{}
	if af.done_at == empty.done_at {
		secs_so_far = time.Since(af.transmit_started_at)
	} else {
		secs_so_far = af.done_at.Sub(af.transmit_started_at)
	}
	self.render_progress(af.display_name, Progress{
		spinner_char: spinner_char, is_complete: is_complete,
		bytes_so_far: af.reported_progress, total_bytes: af.bytes_to_transmit,
		secs_so_far: secs_so_far.Seconds(), bytes_per_sec: safe_divide(p.transfered_stats_amt, p.transfered_stats_interval.Abs().Seconds()),
	})
}

func (self *SendHandler) erase_progress() {
	if self.progress_drawn {
		self.progress_drawn = false
		self.lp.MoveCursorVertically(-2)
		self.lp.QueueWriteString("\r")
		self.lp.ClearToEndOfScreen()
	}
}

func (self *SendHandler) refresh_progress(timer_id loop.IdType) (err error) {
	if !self.transmit_started || self.manager.state == SEND_CANCELED {
		return nil
	}
	if timer_id == self.progress_update_timer {
		self.progress_update_timer = 0
	}
	if self.manager.active_file() == nil && !self.manager.all_acknowledged && self.done_file_ids.Len() != 0 && self.done_file_ids.Len() < len(self.manager.files) {
		if err = self.transmit_next_chunk(); err != nil {
			return err
		}
	}
	self.lp.StartAtomicUpdate()
	defer self.lp.EndAtomicUpdate()
	self.erase_progress()
	self.draw_progress()
	return nil
}

func (self *SendHandler) schedule_progress_update(delay time.Duration) {
	if self.progress_update_timer == 0 {
		timer_id, err := self.lp.AddTimer(delay, false, self.refresh_progress)
		if err == nil {
			self.progress_update_timer = timer_id
		}
	}
}

func (self *SendHandler) on_file_progress(f *File, change int) {
	self.schedule_progress_update(100 * time.Millisecond)
}

func (self *SendHandler) on_file_done(f *File) error {
	self.done_files = append(self.done_files, f)
	if f.err_msg != "" {
		self.failed_files = append(self.failed_files, f)
	}
	return self.refresh_progress(0)
}

func (self *SendHandler) send_payload(payload string) loop.IdType {
	self.lp.QueueWriteString(self.manager.prefix)
	self.lp.QueueWriteString(payload)
	return self.lp.QueueWriteString(self.manager.suffix)
}

func (self *File) metadata_command(use_rsync bool) *FileTransmissionCommand {
	if use_rsync && self.rsync_capable {
		self.ttype = TransmissionType_rsync
	}
	if self.compression_capable {
		self.compression = Compression_zlib
		self.compressor = NewZlibCompressor()
	} else {
		self.compressor = &IdentityCompressor{}
	}
	return &FileTransmissionCommand{
		Action: Action_file, Compression: self.compression, Ftype: self.file_type,
		Name: self.remote_path, Permissions: self.permissions, Mtime: time.Duration(self.mtime.UnixNano()),
		File_id: self.file_id, Ttype: self.ttype,
	}
}

func (self *SendManager) send_file_metadata(send func(string) loop.IdType) {
	for _, f := range self.files {
		ftc := f.metadata_command(self.use_rsync)
		send(ftc.Serialize())
	}
}

func (self *SendHandler) send_file_metadata() {
	if !self.file_metadata_sent {
		self.file_metadata_sent = true
		self.manager.send_file_metadata(self.send_payload)
	}
}

func (self *SendManager) update_collective_statuses() {
	var found_not_started, found_not_done, has_rsync, has_transmitting bool
	for _, f := range self.files {
		if f.state != ACKNOWLEDGED {
			found_not_done = true
		}
		if f.state == WAITING_FOR_START {
			found_not_started = true
		} else if f.state == TRANSMITTING {
			has_transmitting = true
		}
		if f.ttype == TransmissionType_rsync {
			has_rsync = true
		}
	}
	self.all_acknowledged = !found_not_done
	self.all_started = !found_not_started
	self.has_rsync = has_rsync
	self.has_transmitting = has_transmitting
}

func (self *SendManager) on_file_status_update(ftc *FileTransmissionCommand) error {
	file := self.fid_map[ftc.File_id]
	if file == nil {
		return nil
	}
	switch ftc.Status {
	case `STARTED`:
		file.remote_final_path = ftc.Name
		file.remote_initial_size = int64(ftc.Size)
		if file.file_type == FileType_directory {
			file.state = FINISHED
		} else {
			if ftc.Ttype == TransmissionType_rsync {
				file.state = WAITING_FOR_DATA
			} else {
				file.state = TRANSMITTING
			}
			if file.state == WAITING_FOR_DATA {
				file.differ = rsync.NewDiffer()
			}
			self.update_collective_statuses()
		}
	case `PROGRESS`:
		self.last_progress_file = file
		change := int64(ftc.Size) - file.reported_progress
		file.reported_progress = int64(ftc.Size)
		self.progress_tracker.on_file_progress(file, change)
		self.file_progress(file, int(change))
	default:
		if ftc.Name != "" && file.remote_final_path == "" {
			file.remote_final_path = ftc.Name
		}
		file.state = ACKNOWLEDGED
		if ftc.Status == `OK` {
			if ftc.Size > 0 {
				change := int64(ftc.Size) - file.reported_progress
				file.reported_progress = int64(ftc.Size)
				self.progress_tracker.on_file_progress(file, change)
				self.file_progress(file, int(change))
			}
		} else {
			file.err_msg = ftc.Status
		}
		self.progress_tracker.on_file_done(file)
		if err := self.file_done(file); err != nil {
			return err
		}
		if self.active_idx > -1 && file == self.files[self.active_idx] {
			self.active_idx = -1
		}
		self.update_collective_statuses()
	}
	return nil
}

func (self *File) start_delta_calculation() (err error) {
	self.state = TRANSMITTING
	if self.actual_file == nil {
		self.actual_file, err = os.Open(self.expanded_local_path)
		if err != nil {
			return
		}
	}
	self.deltabuf = bytes.NewBuffer(make([]byte, 0, 32+rsync.DataSizeMultiple*self.differ.BlockSize()))
	self.delta_loader = self.differ.CreateDelta(self.actual_file, self.deltabuf)
	return nil
}

func (self *SendManager) on_signature_data_received(ftc *FileTransmissionCommand) error {
	file := self.fid_map[ftc.File_id]
	if file == nil || file.state != WAITING_FOR_DATA {
		return nil
	}
	if file.differ == nil {
		file.differ = rsync.NewDiffer()
	}
	if err := file.differ.AddSignatureData(ftc.Data); err != nil {
		return err
	}
	self.progress_tracker.signature_bytes += len(ftc.Data)
	if ftc.Action == Action_end_data {
		if err := file.differ.FinishSignatureData(); err != nil {
			return err
		}
		return file.start_delta_calculation()
	}
	return nil
}

func (self *SendManager) on_file_transfer_response(ftc *FileTransmissionCommand) error {
	switch ftc.Action {
	case Action_status:
		if ftc.File_id != "" {
			return self.on_file_status_update(ftc)
		}
		if ftc.Status == "OK" {
			self.state = SEND_PERMISSION_GRANTED
		} else {
			self.state = SEND_PERMISSION_DENIED
		}
	case Action_data, Action_end_data:
		if ftc.File_id != "" {
			return self.on_signature_data_received(ftc)
		}
	}
	return nil
}

func (self *SendHandler) on_file_transfer_response(ftc *FileTransmissionCommand) error {
	if ftc.Id != self.manager.request_id {
		return nil
	}
	if ftc.Action == Action_status && ftc.Status == "CANCELED" {
		self.lp.Quit(1)
		return nil
	}
	if self.quit_after_write_code > -1 || self.manager.state == SEND_CANCELED {
		return nil
	}
	before := self.manager.state
	err := self.manager.on_file_transfer_response(ftc)
	if err != nil {
		return err
	}
	if before == SEND_WAITING_FOR_PERMISSION {
		switch self.manager.state {
		case SEND_PERMISSION_DENIED:
			self.lp.Println(self.ctx.Err("Permission denied for this transfer"))
			self.lp.Quit(1)
			return nil
		case SEND_PERMISSION_GRANTED:
			self.lp.Println(self.ctx.Green("Permission granted for this transfer"))
			self.send_file_metadata()
		}
	}
	if !self.transmit_started {
		return self.check_for_transmit_ok()
	}
	if self.manager.all_acknowledged {
		self.transfer_finished()
	} else if ftc.Action == Action_end_data && ftc.File_id != "" {
		return self.transmit_next_chunk()
	}
	return nil
}

func (self *SendHandler) check_for_transmit_ok() (err error) {
	if self.transmit_ok_checked {
		return self.start_transfer()
	}
	if self.manager.state != SEND_PERMISSION_GRANTED {
		return
	}
	if self.opts.ConfirmPaths {
		if self.manager.all_started {
			self.print_check_paths()
		}
		return
	}
	self.transmit_ok_checked = true
	return self.start_transfer()
}

func (self *SendHandler) print_check_paths() {
	if self.check_paths_printed {
		return
	}
	self.check_paths_printed = true
	self.lp.Println(`The following file transfers will be performed. A red destination means an existing file will be overwritten.`)
	for _, df := range self.manager.files {
		fn := df.remote_final_path
		if df.remote_initial_size > -1 {
			fn = self.ctx.Red(fn)
		}
		self.lp.Println(
			self.ctx.Prettify(fmt.Sprintf(":%s:`%s` ", df.file_type.Color(), df.file_type.ShortText())),
			df.display_name, ` → `, fn)
	}
	hsize := humanize.Size(self.manager.progress_tracker.total_bytes_to_transfer)
	if n := len(self.manager.files); n == 1 {
		self.lp.Println(fmt.Sprintf(`Transferring %d file of total size: %s`, n, hsize))
	} else {
		self.lp.Println(fmt.Sprintf(`Transferring %d files of total size: %s`, n, hsize))
	}
	self.print_continue_msg()
}

func (self *SendManager) activate_next_ready_file() *File {
	if self.active_idx > -1 && self.active_idx < len(self.files) {
		self.files[self.active_idx].transmit_ended_at = time.Now()
	}
	for i, f := range self.files {
		if f.state == TRANSMITTING {
			self.active_idx = i
			self.update_collective_statuses()
			self.progress_tracker.change_active_file(f)
			return f
		}
	}
	self.active_idx = -1
	self.update_collective_statuses()
	return nil
}

func (self *SendManager) active_file() *File {
	if self.active_idx > -1 && self.active_idx < len(self.files) {
		return self.files[self.active_idx]
	}
	return nil
}

func (self *File) next_chunk() (ans string, asz int, err error) {
	const sz = 1024 * 1024
	switch self.file_type {
	case FileType_symlink:
		self.state = FINISHED
		ans, asz = self.symbolic_link_target, len(self.symbolic_link_target)
		return
	case FileType_link:
		self.state = FINISHED
		ans, asz = self.hard_link_target, len(self.hard_link_target)
		return
	}
	is_last := false
	var chunk []byte
	if self.delta_loader != nil {
		for !is_last && self.deltabuf.Len() < sz {
			if err = self.delta_loader(); err != nil {
				if err == io.EOF {
					is_last = true
				} else {
					return
				}
			}
		}
		chunk = slices.Clone(self.deltabuf.Bytes())
		self.deltabuf.Reset()
	} else {
		if self.actual_file == nil {
			self.actual_file, err = os.Open(self.expanded_local_path)
			if err != nil {
				return
			}
		}
		chunk = make([]byte, sz)
		var n int
		n, err = self.actual_file.Read(chunk)
		if err != nil && !errors.Is(err, io.EOF) {
			return
		}
		if n <= 0 {
			is_last = true
		} else if pos, _ := self.actual_file.Seek(0, io.SeekCurrent); pos >= self.file_size {
			is_last = true
		}
		chunk = chunk[:n]
	}
	uncompressed_sz := len(chunk)
	cchunk := self.compressor.Compress(chunk)
	if is_last {
		trail := self.compressor.Flush()
		if len(trail) >= 0 {
			cchunk = append(cchunk, trail...)
		}
		self.state = FINISHED
		if self.actual_file != nil {
			err = self.actual_file.Close()
			self.actual_file = nil
			if err != nil {
				return
			}
		}
		self.delta_loader = nil
		self.deltabuf = nil
	}
	ans, asz = utils.UnsafeBytesToString(cchunk), uncompressed_sz
	return
}

func (self *SendManager) next_chunks(callback func(string) loop.IdType) error {
	if self.active_file() == nil {
		self.activate_next_ready_file()
	}
	af := self.active_file()
	if af == nil {
		return nil
	}
	chunk := ""
	self.current_chunk_uncompressed_sz = 0
	for af.state != FINISHED && len(chunk) == 0 {
		c, usz, err := af.next_chunk()
		if err != nil {
			return err
		}
		self.current_chunk_uncompressed_sz += int64(usz)
		self.current_chunk_for_file_id = af.file_id
		chunk = c
	}
	is_last := af.state == FINISHED
	if len(chunk) > 0 {
		split_for_transfer(utils.UnsafeStringToBytes(chunk), af.file_id, is_last, func(ftc *FileTransmissionCommand) {
			self.current_chunk_write_id = callback(ftc.Serialize())
		})
	} else if is_last {
		self.current_chunk_write_id = callback(FileTransmissionCommand{Action: Action_end_data, File_id: af.file_id}.Serialize())
	}
	if is_last {
		self.activate_next_ready_file()
		if self.active_file() == nil {
			return nil
		}
	}
	return nil
}

func (self *SendHandler) transmit_next_chunk() (err error) {
	found_chunk := false
	for !found_chunk {
		if err = self.manager.next_chunks(func(chunk string) loop.IdType {
			found_chunk = true
			return self.send_payload(chunk)
		}); err != nil {
			return err
		}
		if !found_chunk {
			if self.manager.all_acknowledged {
				self.transfer_finished()
				return
			}
			self.manager.update_collective_statuses()
			if !self.manager.has_transmitting {
				return
			}
		}
	}
	return
}

func (self *SendHandler) start_transfer() (err error) {
	if self.manager.active_file() == nil {
		self.manager.activate_next_ready_file()
	}
	if self.manager.active_file() != nil {
		self.transmit_started = true
		self.manager.progress_tracker.start_transfer()
		if err = self.transmit_next_chunk(); err != nil {
			return
		}
		self.draw_progress()
	}
	return
}

func (self *SendHandler) initialize() error {
	self.manager.initialize()
	self.spinner = tui.NewSpinner("dots")
	self.ctx = markup.New(true)
	self.send_payload(self.manager.start_transfer())
	if self.opts.PermissionsBypass != "" {
		// dont wait for permission, not needed with a bypass and avoids a roundtrip
		self.send_file_metadata()
	}
	return nil
}

func (self *SendHandler) transfer_finished() {
	if self.transfer_finish_sent {
		return
	}
	self.transfer_finish_sent = true
	self.finish_cmd_write_id = self.send_payload(FileTransmissionCommand{Action: Action_finish}.Serialize())
}

func (self *SendHandler) on_text(text string, from_key_event, in_bracketed_paste bool) error {
	if self.quit_after_write_code > -1 {
		return nil
	}
	if self.check_paths_printed && !self.transmit_started {
		switch strings.ToLower(text) {
		case "y":
			err := self.start_transfer()
			if err != nil {
				return err
			}
			if self.manager.all_acknowledged {
				if err = self.refresh_progress(0); err != nil {
					return err
				}
				self.transfer_finished()
			}
			return nil
		case "n":
			self.failed_files = nil
			self.abort_transfer()
			self.lp.Println(`Sending cancel request to terminal`)
			return nil
		}
		self.print_continue_msg()
	}
	return nil
}

func (self *SendHandler) print_continue_msg() {
	self.lp.Println(
		`Press`, self.ctx.Green(`y`), `to continue or`, self.ctx.BrightRed(`n`), `to abort`)
}

func (self *SendHandler) abort_transfer(delay ...time.Duration) {
	d := 5 * time.Second
	if len(delay) > 0 {
		d = delay[0]
	}
	self.send_payload(FileTransmissionCommand{Action: Action_cancel}.Serialize())
	self.manager.state = SEND_CANCELED
	_, _ = self.lp.AddTimer(d, false, func(loop.IdType) error {
		self.lp.Quit(1)
		return nil
	})
}

func (self *SendHandler) on_resize(old_size, new_size loop.ScreenSize) error {
	if self.progress_drawn {
		return self.refresh_progress(0)
	}
	return nil
}

func (self *SendHandler) on_key_event(ev *loop.KeyEvent) error {
	if self.quit_after_write_code > -1 {
		return nil
	}
	if ev.MatchesPressOrRepeat("esc") {
		ev.Handled = true
		if self.check_paths_printed && !self.transmit_started {
			self.failed_files = nil
			self.abort_transfer()
			self.lp.Println(`Sending cancel request to terminal`)
			return nil
		} else {
			self.on_interrupt()
		}
	} else if ev.MatchesPressOrRepeat("ctrl+c") {
		self.on_interrupt()
		ev.Handled = true
	}
	return nil
}

func (self *SendHandler) on_writing_finished(msg_id loop.IdType, has_pending_writes bool) (err error) {
	chunk_transmitted := self.manager.current_chunk_uncompressed_sz >= 0 && msg_id == self.manager.current_chunk_write_id
	if chunk_transmitted {
		self.manager.progress_tracker.on_transmit(self.manager.current_chunk_uncompressed_sz, self.manager.fid_map[self.manager.current_chunk_for_file_id])
		self.manager.current_chunk_uncompressed_sz = -1
		self.manager.current_chunk_write_id = 0
		self.manager.current_chunk_for_file_id = ""
	}
	if self.finish_cmd_write_id > 0 && msg_id == self.finish_cmd_write_id {
		if len(self.failed_files) > 0 {
			self.quit_after_write_code = 1
		} else {
			self.quit_after_write_code = 0
		}
		if err = self.refresh_progress(0); err != nil {
			return err
		}
	}
	if self.quit_after_write_code > -1 && !has_pending_writes {
		self.lp.Quit(self.quit_after_write_code)
		return
	}
	if self.manager.state == SEND_PERMISSION_GRANTED && !self.transmit_started {
		return self.check_for_transmit_ok()
	}
	if chunk_transmitted {
		if err = self.refresh_progress(0); err != nil {
			return err
		}
		return self.transmit_next_chunk()
	}
	return
}

func (self *SendHandler) on_interrupt() {
	if self.quit_after_write_code > -1 {
		return
	}
	if self.manager.state == SEND_CANCELED {
		self.lp.Println(`Waiting for canceled acknowledgement from terminal, will abort in a few seconds if no response received`)
		return
	}
	self.lp.Println(self.ctx.BrightRed(`Interrupt requested, cancelling transfer, transferred files are in undefined state`))
	self.abort_transfer()
}

func send_loop(opts *Options, files []*File) (err error, rc int) {
	lp, err := loop.New(loop.NoAlternateScreen, loop.NoRestoreColors)
	if err != nil {
		return err, 1
	}

	handler := &SendHandler{
		opts: opts, files: files, lp: lp, quit_after_write_code: -1,
		max_name_length: utils.Max(0, utils.Map(func(f *File) int { return wcswidth.Stringwidth(f.display_name) }, files)...),
		progress_drawn:  true, done_file_ids: utils.NewSet[string](),
		manager: &SendManager{
			request_id: random_id(), files: files, bypass: opts.PermissionsBypass, use_rsync: opts.TransmitDeltas,
		},
	}
	handler.manager.file_progress = handler.on_file_progress
	handler.manager.file_done = handler.on_file_done

	lp.OnInitialize = func() (string, error) {
		lp.SetCursorVisible(false)
		return "", handler.initialize()
	}
	lp.OnFinalize = func() string {
		lp.SetCursorVisible(true)
		return ""
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
	lp.OnText = handler.on_text
	lp.OnKeyEvent = handler.on_key_event
	lp.OnResize = handler.on_resize
	lp.OnWriteComplete = handler.on_writing_finished

	err = lp.Run()
	if err != nil {
		return err, 1
	}
	if lp.DeathSignalName() != "" {
		lp.KillIfSignalled()
		return
	}
	p := handler.manager.progress_tracker
	if handler.manager.has_rsync && p.total_transferred+int64(p.signature_bytes) > 0 && lp.ExitCode() == 0 {
		var tsf int64
		for _, f := range files {
			if f.ttype == TransmissionType_rsync {
				tsf += f.file_size
			}
		}
		if tsf > 0 {
			print_rsync_stats(tsf, p.total_transferred, int64(p.signature_bytes))
		}
	}
	if len(handler.failed_files) > 0 {
		fmt.Fprintf(os.Stderr, "Transfer of %d out of %d files failed\n", len(handler.failed_files), len(handler.manager.files))
		for _, f := range handler.failed_files {
			fmt.Println(handler.ctx.BrightRed(f.display_name))
			fmt.Println(` `, f.err_msg)
		}
		rc = 1
	}
	if lp.ExitCode() != 0 {
		rc = lp.ExitCode()
	}
	return
}

func send_main(opts *Options, args []string) (err error, rc int) {
	fmt.Println("Scanning files…")
	files, err := files_for_send(opts, args)
	if err != nil {
		return err, 1
	}
	fmt.Printf("Found %d files and directories, requesting transfer permission…", len(files))
	fmt.Println()
	err, rc = send_loop(opts, files)

	return
}
