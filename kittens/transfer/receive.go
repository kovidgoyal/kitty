// License: GPLv3 Copyright: 2023, Kovid Goyal, <kovid at kovidgoyal.net>

package transfer

import (
	"bytes"
	"compress/zlib"
	"fmt"
	"io"
	"io/fs"
	"os"
	"strconv"
	"strings"
	"time"

	"kitty"
	"kitty/tools/cli/markup"
	"kitty/tools/tui/loop"
	"kitty/tools/utils"
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
	write([]byte) error
	close() error
	tell() (int64, error)
}

type filesystem_file struct {
	f *os.File
}

func (ff *filesystem_file) tell() int64 {
	pos, _ := ff.f.Seek(0, os.SEEK_CUR)
	return pos
}

func (ff *filesystem_file) close() error {
	return ff.f.Close()
}

func (ff *filesystem_file) write(data []byte) error {
	n, err := ff.f.Write(data)
	if err == nil && n < len(data) {
		err = io.ErrShortWrite
	}
	return err
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
	transfered_stats_interval float64
	started_at                time.Time
	transfers                 []Transfer
	active_file               *remote_file
	done_files                []*remote_file
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

func (self *receive_progress_tracker) start_transfer() {
	self.started_at = time.Now()
	self.transfers = append(self.transfers, Transfer{})
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
		self.manager.collect_files(self.cli_opts)
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
