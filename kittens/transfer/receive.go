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
	"time"

	"kitty"
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

type decompressor = func([]byte, bool) ([]byte, error)

func identity_decompressor(data []byte, is_last bool) ([]byte, error) { return data, nil }

type zlib_decompressor struct {
	z   io.ReadCloser
	b   bytes.Buffer
	buf []byte
}

func (self *zlib_decompressor) add_bytes(b []byte, is_last bool) (ans []byte, err error) {
	self.b.Write(b)
	pos, n := 0, 0
	for {
		if cap(self.buf) < pos+1024 {
			newcap := utils.Max(2*cap(self.buf), pos+8192)
			self.buf = append(self.buf[:pos], make([]byte, newcap-pos)...)
		}
		n, err = self.z.Read(self.buf[pos:cap(self.buf)])
		pos += n
		switch err {
		case io.EOF:
			n = 0
		case nil:
		default:
			return nil, err
		}
		if n == 0 {
			break
		}
	}
	if is_last {
		if err = self.z.Close(); err != nil {
			return nil, err
		}
	}
	return self.buf[:pos], nil
}

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
	decompressor                 decompressor
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
		remote_id: ftc.Status, remote_target: string(ftc.Data), parent: ftc.Parent, decompressor: identity_decompressor,
	}
	compression_capable := ftc.Ftype == FileType_regular && ftc.Size > 4096 && should_be_compressed(ftc.Name, opts.Compress)
	if compression_capable {
		z := &zlib_decompressor{}
		if z.z, err = zlib.NewReader(&z.b); err != nil {
			return nil, err
		}
		ans.decompressor = z.add_bytes
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
	request_id       string
	spec             []string
	dest             string
	bypass           string
	use_rsync        bool
	failed_specs     map[int]string
	spec_counts      map[int]int
	remote_home      string
	prefix, suffix   string
	transfer_done    bool
	files            []*remote_file
	state            state
	progress_tracker receive_progress_tracker
}

type handler struct {
	lp                    *loop.Loop
	manager               manager
	quit_after_write_code int
	check_paths_printed   bool
	transmit_started      bool
	progress_drawn        bool
	max_name_length       int
}

func receive_loop(opts *Options, spec []string, dest string) (err error, rc int) {
	lp, err := loop.New(loop.NoAlternateScreen, loop.NoRestoreColors)
	if err != nil {
		return err, 1
	}

	handler := handler{
		lp: lp, quit_after_write_code: -1,
		manager: manager{
			request_id: random_id(), spec: spec, dest: dest, bypass: opts.PermissionsBypass, use_rsync: opts.TransmitDeltas,
			failed_specs: make(map[int]string, len(spec)), spec_counts: make(map[int]int, len(spec)),
			suffix: "\x1b\\",
		},
	}
	handler.manager.prefix = fmt.Sprintf("\x1b]{%d};id=%s;", kitty.FileTransferCode, handler.manager.request_id)
	if handler.manager.bypass != `` {
		if handler.manager.bypass, err = encode_bypass(handler.manager.request_id, handler.manager.bypass); err != nil {
			return err, 1
		}
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
