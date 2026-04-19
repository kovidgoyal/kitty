// License: GPLv3 Copyright: 2022, Kovid Goyal, <kovid at kovidgoyal.net>

package dnd

import (
	"bytes"
	"encoding/base64"
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

	"github.com/kovidgoyal/kitty"
	"github.com/kovidgoyal/kitty/tools/cli"
	"github.com/kovidgoyal/kitty/tools/tty"
	"github.com/kovidgoyal/kitty/tools/tui/loop"
	"github.com/kovidgoyal/kitty/tools/utils"
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
}

// button_pos tracks the 0-based cell bounding box of a UI button
type button_pos struct {
	col0, row0, width, height int
}

func (b button_pos) contains(cell_x, cell_y int) bool {
	return cell_x >= b.col0 && cell_x < b.col0+b.width &&
		cell_y >= b.row0 && cell_y < b.row0+b.height
}

// remote_dir holds state for one directory being traversed during a remote drop
type remote_dir struct {
	handle        int
	entries       []string // null-separated filenames, already split
	local_path    string   // local destination directory
	x_key         int      // 'x' key for requests (1-based MIME idx for top-level, 1-based uri sub-idx for files)
	parent_Y      int      // 'Y' (directory handle) for parent; 0 means this is accessed via y_key
	parent_y      int      // 'y' (entry number in parent) for children of a parent dir
	dirs_to_close []int    // handles of sub-directories opened in this dir
}

// decode_b64 decodes base64-encoded data, tolerating optional padding.
func decode_b64(data []byte) ([]byte, error) {
	if len(data) == 0 {
		return nil, nil
	}
	s := strings.TrimRight(string(data), "= \t\r\n")
	if s == "" {
		return nil, nil
	}
	return base64.RawStdEncoding.DecodeString(s)
}

// safe_dest_path returns a destination path for filename under dest_dir, verifying
// that the result stays within dest_dir. Returns ("", false) if unsafe.
func safe_dest_path(dest_dir, filename string) (string, bool) {
	base := filepath.Base(filename)
	if base == "." || base == ".." || base == "" || base == string(filepath.Separator) {
		return "", false
	}
	p := filepath.Join(dest_dir, base)
	abs_dest, _ := filepath.Abs(dest_dir)
	abs_p, _ := filepath.Abs(p)
	sep := string(filepath.Separator)
	if abs_p != abs_dest && !strings.HasPrefix(abs_p, abs_dest+sep) {
		return "", false
	}
	return p, true
}

// copy_file_to copies the file at src to dst, creating parent directories as needed.
func copy_file_to(src, dst string) error {
	if err := os.MkdirAll(filepath.Dir(dst), 0o755); err != nil {
		return err
	}
	in, err := os.Open(src)
	if err != nil {
		return err
	}
	defer in.Close()
	out, err := os.Create(dst)
	if err != nil {
		return err
	}
	defer out.Close()
	_, err = io.Copy(out, in)
	return err
}

// copy_dir_to recursively copies directory src to dst (symlinks are skipped for safety).
func copy_dir_to(src, dst string) error {
	entries, err := os.ReadDir(src)
	if err != nil {
		return err
	}
	if err := os.MkdirAll(dst, 0o755); err != nil {
		return err
	}
	for _, entry := range entries {
		if entry.Type()&os.ModeSymlink != 0 {
			continue // skip symlinks for security
		}
		src_path := filepath.Join(src, entry.Name())
		dst_path := filepath.Join(dst, entry.Name())
		if entry.IsDir() {
			if err := copy_dir_to(src_path, dst_path); err != nil {
				return err
			}
		} else if entry.Type().IsRegular() {
			if err := copy_file_to(src_path, dst_path); err != nil {
				return err
			}
		}
	}
	return nil
}

// read_drag_source reads all data from a drag_source (from memory, file, or path).
func read_drag_source(ds drag_source) ([]byte, error) {
	if ds.data != nil {
		return ds.data, nil
	}
	if ds.file != nil {
		_, _ = ds.file.Seek(0, io.SeekStart)
		return io.ReadAll(ds.file)
	}
	if ds.path != "" {
		return os.ReadFile(ds.path)
	}
	return nil, nil
}

// draw_button draws a button with rounded corner box and triple-scale text.
// Returns the button_pos so callers can track its location for hit testing.
// row and col are 0-based; the button uses 5 rows total.
func draw_button(lp *loop.Loop, text string, col0, row0 int) button_pos {
	text_cells := wcswidth.Stringwidth(text) * 3 // scale=3
	inner_width := text_cells + 2                // 1-cell padding each side
	box_width := inner_width + 2                 // frame borders
	hbar := strings.Repeat("─", inner_width)

	// Top frame
	lp.MoveCursorTo(col0+1, row0+1)
	lp.QueueWriteString("╭" + hbar + "╮")

	// Text row with side borders
	lp.MoveCursorTo(col0+1, row0+2)
	lp.QueueWriteString("│ ")
	lp.DrawSizedText(text, loop.SizedText{Scale: 3})
	lp.QueueWriteString(" │")

	// Bottom frame (scale=3 text visually spans 3 rows; bottom frame is 4 rows below top)
	lp.MoveCursorTo(col0+1, row0+5)
	lp.QueueWriteString("╰" + hbar + "╯")

	return button_pos{col0: col0, row0: row0, width: box_width, height: 5}
}

// drag_action_flags converts the DragAction option to protocol operation flags.
func drag_action_flags(action string) int {
	switch action {
	case "move":
		return 2
	case "either":
		return 3
	default:
		return 1
	}
}

// send_drag_data_response sends drag data for MIME index idx (0-based) in response
// to a t=e:x=5:y=idx request.
func send_drag_data_response(lp *loop.Loop, idx int, data []byte) {
	idx_str := strconv.Itoa(idx)
	if len(data) > 0 {
		lp.QueueDnDData(map[string]string{"t": "e", "y": idx_str},
			utils.UnsafeBytesToString(data), true)
	}
	// End-of-data signal: empty payload with m=0
	lp.QueueDnDData(map[string]string{"t": "e", "y": idx_str, "m": "0"}, "", false)
}

// send_dnd_k_small sends a small, memory-resident payload (e.g. symlink target or
// directory entry list) via t=k. meta_suffix contains all key=val pairs after "t=k",
// including the leading colon (e.g. ":x=1:X=2:Y=3:y=4").
// The full header (including x, X, Y, y) is included in every chunk so the terminal
// can route each chunk to the correct item even when the payload spans multiple chunks.
func send_dnd_k_small(lp *loop.Loop, meta_suffix string, data []byte) {
	hdr := fmt.Sprintf("\x1b]%d;t=k%s", kitty.DndCode, meta_suffix)
	if len(data) > 0 {
		b64 := base64.RawStdEncoding.EncodeToString(data)
		const chunk = 4096
		for i := 0; i < len(b64); i += chunk {
			end := i + chunk
			if end > len(b64) {
				end = len(b64)
			}
			m_val := "1"
			if end >= len(b64) {
				m_val = "0"
			}
			// Include the full header in every chunk: the terminal uses x, X, Y, y
			// to route each chunk to the correct DragRemoteItem.
			lp.QueueWriteString(hdr + ":m=" + m_val + ";")
			lp.QueueWriteString(b64[i:end])
			lp.QueueWriteString("\x1b\\")
		}
	}
	// End-of-data signal: empty payload
	lp.QueueWriteString(hdr + ";\x1b\\")
}

const (
	// remote_drag_limit matches DEFAULT_REMOTE_DRAG_LIMIT in dnd.c (1 GiB).
	remote_drag_limit int64 = 1024 * 1024 * 1024
	// dnd_raw_chunk_size matches FILE_CHUNK_SIZE in dnd.c (3072 bytes raw → 4096 base64 chars).
	dnd_raw_chunk_size = 3072
)

// stream_dnd_k_file streams the content of r as t=k escape codes in 3072-byte raw
// chunks (matching FILE_CHUNK_SIZE in dnd.c). meta_suffix is appended after "t=k"
// (e.g. ":x=1" or ":x=2:Y=3:y=1"). total_sent is updated with raw bytes sent; if
// the cumulative total exceeds remote_drag_limit an error is returned without sending
// any more data or the end-of-data signal — the caller must send t=E on error.
func stream_dnd_k_file(lp *loop.Loop, meta_suffix string, r io.Reader, total_sent *int64) error {
	hdr := fmt.Sprintf("\x1b]%d;t=k%s", kitty.DndCode, meta_suffix)
	raw := make([]byte, dnd_raw_chunk_size)
	b64 := make([]byte, base64.RawStdEncoding.EncodedLen(dnd_raw_chunk_size))
	for {
		n, err := io.ReadFull(r, raw)
		is_last := err == io.ErrUnexpectedEOF || err == io.EOF
		if n > 0 {
			*total_sent += int64(n)
			if *total_sent > remote_drag_limit {
				return fmt.Errorf("remote drag data exceeds the 1 GiB limit; use a local drag instead")
			}
			b64n := base64.RawStdEncoding.EncodedLen(n)
			base64.RawStdEncoding.Encode(b64[:b64n], raw[:n])
			m_val := "1"
			if is_last {
				m_val = "0"
			}
			lp.QueueWriteString(hdr + ":m=" + m_val + ";")
			lp.QueueWriteBytesCopy(b64[:b64n])
			lp.QueueWriteString("\x1b\\")
		}
		if is_last {
			break
		}
		if err != nil {
			return err
		}
	}
	// End-of-data signal: empty payload
	lp.QueueWriteString(hdr + ";\x1b\\")
	return nil
}

// send_remote_files sends all file:// URI content for a remote drag via t=k escape
// codes. File data is streamed in 3072-byte chunks so large files are never fully
// loaded into memory. Symlink targets and directory entry lists are small and may be
// accumulated. Returns an error if the total exceeds the 1 GiB remote drag limit.
func send_remote_files(lp *loop.Loop, uri_list []uri_list_item) error {
	handle_counter := 2 // 0=file, 1=symlink; directories start at 2
	var total_sent int64

	type dir_work struct {
		path          string
		handle        int
		parent_handle int
		entry_num     int
		uri_idx       int
	}

	for uri_idx, item := range uri_list {
		x := uri_idx + 1 // 1-based
		st, err := os.Stat(item.path)
		if err != nil {
			// Unreadable item: send empty end-of-data to mark absence
			lp.QueueWriteString(fmt.Sprintf("\x1b]%d;t=k:x=%d;\x1b\\", kitty.DndCode, x))
			continue
		}
		if st.IsDir() {
			queue := []dir_work{{path: item.path, handle: handle_counter, parent_handle: 0, entry_num: 0, uri_idx: x}}
			handle_counter++
			for len(queue) > 0 {
				work := queue[0]
				queue = queue[1:]
				entries, err := os.ReadDir(work.path)
				if err != nil {
					continue
				}
				names := make([]string, 0, len(entries))
				for _, e := range entries {
					names = append(names, e.Name())
				}
				entry_bytes := []byte(strings.Join(names, "\x00"))
				var dir_meta string
				if work.parent_handle != 0 {
					dir_meta = fmt.Sprintf(":x=%d:X=%d:Y=%d:y=%d", work.uri_idx, work.handle, work.parent_handle, work.entry_num)
				} else {
					dir_meta = fmt.Sprintf(":x=%d:X=%d", work.uri_idx, work.handle)
				}
				send_dnd_k_small(lp, dir_meta, entry_bytes)

				for i, e := range entries {
					child_path := filepath.Join(work.path, e.Name())
					child_num := i + 1 // 1-based
					if e.Type()&os.ModeSymlink != 0 {
						target, _ := os.Readlink(child_path)
						sym_meta := fmt.Sprintf(":x=%d:X=1:Y=%d:y=%d", work.uri_idx, work.handle, child_num)
						send_dnd_k_small(lp, sym_meta, []byte(target))
					} else if e.IsDir() {
						child_handle := handle_counter
						handle_counter++
						queue = append(queue, dir_work{
							path:          child_path,
							handle:        child_handle,
							parent_handle: work.handle,
							entry_num:     child_num,
							uri_idx:       work.uri_idx,
						})
					} else {
						f, err := os.Open(child_path)
						if err != nil {
							lp.QueueWriteString(fmt.Sprintf("\x1b]%d;t=k:x=%d:Y=%d:y=%d;\x1b\\",
								kitty.DndCode, work.uri_idx, work.handle, child_num))
							continue
						}
						file_meta := fmt.Sprintf(":x=%d:Y=%d:y=%d", work.uri_idx, work.handle, child_num)
						err = stream_dnd_k_file(lp, file_meta, f, &total_sent)
						f.Close()
						if err != nil {
							return err
						}
					}
				}
			}
		} else {
			// Top-level regular file: stream in chunks
			f, err := os.Open(item.path)
			if err != nil {
				lp.QueueWriteString(fmt.Sprintf("\x1b]%d;t=k:x=%d;\x1b\\", kitty.DndCode, x))
				continue
			}
			file_meta := fmt.Sprintf(":x=%d", x)
			err = stream_dnd_k_file(lp, file_meta, f, &total_sent)
			f.Close()
			if err != nil {
				return err
			}
		}
	}
	// All data transmitted: send completion signal
	lp.QueueWriteString(fmt.Sprintf("\x1b]%d;t=k;\x1b\\", kitty.DndCode))
	return nil
}

// parse_uri_list parses a text/uri-list payload, returning file:// URI paths.
func parse_uri_list(data []byte) []string {
	var paths []string
	for _, line := range strings.Split(string(data), "\n") {
		line = strings.TrimRight(line, "\r")
		if line == "" || strings.HasPrefix(line, "#") {
			continue
		}
		u, err := url.Parse(line)
		if err != nil || u.Scheme != "file" {
			continue
		}
		p := u.Path
		if runtime.GOOS == "windows" {
			p = strings.TrimPrefix(p, "/")
		}
		paths = append(paths, p)
	}
	return paths
}

// handle_local_uri_list copies files from a local URI list drop into dest_dir.
func handle_local_uri_list(data []byte, dest_dir string, confirm_overwrite bool) error {
	paths := parse_uri_list(data)
	if len(paths) == 0 {
		return nil
	}
	var overwrite_pairs [][2]string // [src, dst]
	var normal_pairs [][2]string

	for _, src := range paths {
		if _, err := os.Stat(src); err != nil {
			continue
		}
		base := filepath.Base(src)
		dst, ok := safe_dest_path(dest_dir, base)
		if !ok {
			continue
		}
		_, dst_err := os.Stat(dst)
		if dst_err == nil && confirm_overwrite {
			overwrite_pairs = append(overwrite_pairs, [2]string{src, dst})
		} else {
			normal_pairs = append(normal_pairs, [2]string{src, dst})
		}
	}

	// Copy non-conflicting files
	for _, pair := range normal_pairs {
		src, dst := pair[0], pair[1]
		st, err := os.Stat(src)
		if err != nil {
			continue
		}
		if st.IsDir() {
			_ = copy_dir_to(src, dst)
		} else {
			_ = copy_file_to(src, dst)
		}
	}

	if len(overwrite_pairs) > 0 {
		// Copy to temp files and rename
		for _, pair := range overwrite_pairs {
			src, dst := pair[0], pair[1]
			tmp := dst + ".kitty_dnd_tmp"
			st, err := os.Stat(src)
			if err != nil {
				continue
			}
			var copy_err error
			if st.IsDir() {
				copy_err = copy_dir_to(src, tmp)
			} else {
				copy_err = copy_file_to(src, tmp)
			}
			if copy_err != nil {
				continue
			}
			_ = os.Rename(tmp, dst)
		}
	}
	return nil
}

// remote_drop_state tracks sequential fetching of remote files during a drop
type remote_drop_state struct {
	// The list of file paths (from text/uri-list) being fetched
	file_paths []string
	// Current fetch index (1-based into file_paths), 0 = not started
	current_subidx int
	// x key for text/uri-list MIME in drop_mime_list (1-based)
	uri_list_x int
	// Local destination directory for writing files
	dest_dir string
	// Directory traversal: stack of open directories
	dir_stack []*remote_dir_fetch
}

type remote_dir_fetch struct {
	local_path    string
	handle        int // the handle from the terminal
	entries       []string
	current_entry int // 0-based index into entries, -1 = not started
	x_key         int // x= key for requests
}

func run_loop(opts *Options, drop_dests map[string]drop_dest, drag_sources map[string]drag_source, uri_list_buffer *bytes.Buffer) (err error) {
	allow_drops, allow_drags := len(drop_dests) > 0, len(drag_sources) > 0

	// ---- Drop state -------------------------------------------------------
	var drop_mime_list []string // MIME types offered in the current drag
	drop_accepted := false
	drop_copy_allowed := false
	drop_move_allowed := false
	drop_in_progress := false
	drop_is_remote := false
	drop_uri_list_x := 0 // 1-based index of text/uri-list in drop_mime_list (0=absent)

	// Sequential MIME fetch state
	var drop_pending_mime_xs []int // 1-based MIME indexes still to fetch
	drop_current_mime_x := 0       // currently fetching (1-based), 0=none
	drop_current_xp := 0           // Xp from first data chunk (e.g., X=1 for remote uri-list)
	var drop_chunks bytes.Buffer

	// Streaming receive state: for regular files, write chunks directly to a destination
	// file rather than accumulating in drop_chunks.  nil means accumulate.
	var drop_streaming_file *os.File  // open file for streaming writes; closed on end signal
	var drop_streaming_dest io.Writer // destination for streaming (may be file or io.WriteCloser)

	// Remote file fetch state (used when drop_is_remote)
	var remote_drop *remote_drop_state

	// Button positions (0-based cell coords)
	var copy_btn, move_btn button_pos

	// ---- Drag state -------------------------------------------------------
	var drag_mime_list []string
	drag_started := false
	drag_action_final := 0 // 0=unknown, 1=copy, 2=move

	lp, err := loop.New()
	if err != nil {
		return err
	}

	// ---- Screen rendering -------------------------------------------------
	render_screen := func() error {
		sz, err := lp.ScreenSize()
		if err != nil {
			return err
		}
		W := int(sz.WidthCells)
		if W < 1 {
			W = 80
		}

		lp.StartAtomicUpdate()
		defer lp.EndAtomicUpdate()
		lp.ClearScreen()
		lp.SetCursorVisible(false)

		if allow_drags && drag_started {
			lp.MoveCursorTo(1, 1)
			lp.QueueWriteString("Dragging data...")
			return nil
		}

		if allow_drags && !drag_started {
			lp.MoveCursorTo(1, 1)
			mimes := make([]string, 0, len(drag_sources))
			for m := range drag_sources {
				mimes = append(mimes, m)
			}
			slices.Sort(mimes)
			lp.QueueWriteString("Drag anywhere in this window to start a drag-and-drop operation.")
			lp.MoveCursorTo(1, 2)
			lp.QueueWriteString("MIME types: " + strings.Join(mimes, ", "))
		}

		if allow_drops && drop_in_progress {
			lp.MoveCursorTo(1, 1)
			lp.QueueWriteString("Drop in progress, reading data...")
			return nil
		}

		if allow_drops && drop_accepted {
			// Message
			msg := "Drop onto a button below:"
			lp.MoveCursorTo((W-wcswidth.Stringwidth(msg))/2+1, 1)
			lp.QueueWriteString(msg)

			// Button dimensions: scale=3 text, 4 chars wide = 12 cells + 2 padding + 2 frame = 16
			btn_width := 16
			btn_height := 5
			gap := 4
			n_btns := 0
			if drop_copy_allowed {
				n_btns++
			}
			if drop_move_allowed {
				n_btns++
			}

			total_width := n_btns*btn_width + (n_btns-1)*gap
			start_col := (W - total_width) / 2
			if start_col < 0 {
				start_col = 0
			}
			row0 := 2 // 0-based

			col := start_col
			if drop_copy_allowed {
				copy_btn = draw_button(lp, "Copy", col, row0)
				col += btn_width + gap
			}
			if drop_move_allowed {
				move_btn = draw_button(lp, "Move", col, row0)
			}

			// MIME list below buttons
			mime_row := row0 + btn_height + 2
			if len(drop_mime_list) > 0 {
				mime_msg := "Offered types: " + strings.Join(drop_mime_list, ", ")
				if wcswidth.Stringwidth(mime_msg) > W {
					mime_msg = "Offered types: " + strings.Join(drop_mime_list[:min(len(drop_mime_list), 3)], ", ") + "..."
				}
				lp.MoveCursorTo((W-wcswidth.Stringwidth(mime_msg))/2+1, mime_row+1)
				lp.QueueWriteString(mime_msg)
			}
		}
		return nil
	}

	// ---- Drop helpers -----------------------------------------------------

	// finish_drop signals the terminal that we're done receiving drop data.
	finish_drop := func() error {
		if drop_streaming_file != nil {
			_ = drop_streaming_file.Close()
			drop_streaming_file = nil
		}
		drop_streaming_dest = nil
		lp.QueueDnDData(map[string]string{"t": "r"}, "", false)
		drop_in_progress = false
		drop_accepted = false
		drop_mime_list = nil
		drop_current_mime_x = 0
		drop_pending_mime_xs = nil
		remote_drop = nil
		drop_is_remote = false
		return render_screen()
	}

	// write_mime_data writes received MIME data to the appropriate destination.
	// If it's text/uri-list, it processes the URI list (local or remote).
	var start_next_drop_fetch func() error
	write_mime_data := func(mime_x int, data []byte, xp int) error {
		// Find which MIME type this is
		if mime_x < 1 || mime_x > len(drop_mime_list) {
			return nil
		}
		mime_type := drop_mime_list[mime_x-1]

		if mime_type == "text/uri-list" {
			// xp==1 means the files are on a remote machine
			if xp == 1 {
				drop_is_remote = true
			}
			// Write URI list to the configured destination
			dd, ok := drop_dests[mime_type]
			if ok && dd.dest != nil {
				_, _ = dd.dest.Write(data)
			}
			if drop_is_remote {
				// Set up remote file fetching
				file_paths := parse_uri_list(data)
				cwd, _ := os.Getwd()
				dest_dir := cwd
				if dd.path != "" {
					dest_dir = dd.path
				}
				remote_drop = &remote_drop_state{
					file_paths:     file_paths,
					current_subidx: 0,
					uri_list_x:     mime_x,
					dest_dir:       dest_dir,
				}
				// Queue fetches for each file:// URI
				for i := range file_paths {
					drop_pending_mime_xs = append(drop_pending_mime_xs, -(i + 1)) // negative = remote file subidx
				}
			} else {
				// Local drop: copy files via filesystem
				cwd, _ := os.Getwd()
				dest_dir := cwd
				dd, ok := drop_dests[mime_type]
				if ok && dd.path != "" {
					dest_dir = dd.path
				}
				if err := handle_local_uri_list(data, dest_dir, opts.ConfirmDropOverwrite); err != nil {
					return err
				}
			}
		} else {
			// Non-URI-list: write directly to destination
			dd, ok := drop_dests[mime_type]
			if !ok {
				return nil
			}
			if dd.dest != nil {
				_, _ = dd.dest.Write(data)
			} else if dd.path != "" {
				f, err := os.OpenFile(dd.path, os.O_CREATE|os.O_WRONLY|os.O_TRUNC, 0o644)
				if err != nil {
					return err
				}
				_, _ = f.Write(data)
				_ = f.Close()
			}
		}
		return nil
	}

	// start_remote_file_fetch requests a single remote file from the terminal.
	start_remote_file_fetch := func(subidx int) {
		// subidx is 1-based into remote_drop.file_paths
		if remote_drop == nil {
			return
		}
		remote_drop.current_subidx = subidx
		drop_chunks.Reset()
		lp.QueueDnDData(map[string]string{
			"t": "r",
			"x": strconv.Itoa(remote_drop.uri_list_x),
			"y": strconv.Itoa(subidx),
		}, "", false)
	}

	// start_dir_entry_fetch requests a directory entry from the terminal.
	start_dir_entry_fetch := func(rd *remote_dir_fetch) {
		rd.current_entry++
		drop_chunks.Reset()
		meta := map[string]string{
			"t": "r",
			"Y": strconv.Itoa(rd.handle),
			"x": strconv.Itoa(rd.current_entry + 1), // 1-based
		}
		lp.QueueDnDData(meta, "", false)
	}

	close_dir_handle := func(handle int) {
		lp.QueueDnDData(map[string]string{"t": "r", "Y": strconv.Itoa(handle)}, "", false)
	}

	start_next_drop_fetch = func() error {
		// Process the next item in drop_pending_mime_xs
		for {
			if len(drop_pending_mime_xs) == 0 {
				// Check if there are open directory entries to continue
				if remote_drop != nil && len(remote_drop.dir_stack) > 0 {
					top := remote_drop.dir_stack[len(remote_drop.dir_stack)-1]
					if top.current_entry+1 < len(top.entries) {
						start_dir_entry_fetch(top)
						return nil
					}
					// Done with this directory
					close_dir_handle(top.handle)
					remote_drop.dir_stack = remote_drop.dir_stack[:len(remote_drop.dir_stack)-1]
					continue
				}
				return finish_drop()
			}
			next := drop_pending_mime_xs[0]
			drop_pending_mime_xs = drop_pending_mime_xs[1:]
			if next < 0 {
				// Remote file fetch (subidx = -next)
				subidx := -next
				if remote_drop != nil && subidx <= len(remote_drop.file_paths) {
					start_remote_file_fetch(subidx)
					return nil
				}
			} else {
				// Normal MIME fetch
				drop_current_mime_x = next
				drop_current_xp = 0
				drop_chunks.Reset()
				lp.QueueDnDData(map[string]string{"t": "r", "x": strconv.Itoa(next)}, "", false)
				return nil
			}
		}
	}

	// handle_dir_entry_response processes a terminal response for a directory entry.
	handle_dir_entry_response := func(xp int, data []byte) error {
		if remote_drop == nil || len(remote_drop.dir_stack) == 0 {
			return nil
		}
		top := remote_drop.dir_stack[len(remote_drop.dir_stack)-1]
		entry_idx := top.current_entry // 0-based
		if entry_idx < 0 || entry_idx >= len(top.entries) {
			return start_next_drop_fetch()
		}
		entry_name := top.entries[entry_idx]
		dst, ok := safe_dest_path(top.local_path, entry_name)
		if !ok {
			return start_next_drop_fetch()
		}
		if xp == 0 {
			// Regular file
			if err := os.MkdirAll(filepath.Dir(dst), 0o755); err == nil {
				_ = os.WriteFile(dst, data, 0o644)
			}
		} else if xp == 1 {
			// Symlink — create local symlink only if target stays within dest_dir
			target := string(data)
			abs_target := target
			if !filepath.IsAbs(abs_target) {
				abs_target = filepath.Join(top.local_path, target)
			}
			abs_target = filepath.Clean(abs_target)
			abs_dest, _ := filepath.Abs(remote_drop.dest_dir)
			sep := string(filepath.Separator)
			if strings.HasPrefix(abs_target, abs_dest+sep) || abs_target == abs_dest {
				_ = os.MkdirAll(filepath.Dir(dst), 0o755)
				_ = os.Symlink(target, dst)
			}
		} else {
			// Sub-directory
			_ = os.MkdirAll(dst, 0o755)
			entries_raw := bytes.Split(data, []byte{0})
			entries := make([]string, 0, len(entries_raw))
			for _, e := range entries_raw {
				if len(e) > 0 {
					entries = append(entries, string(e))
				}
			}
			rd := &remote_dir_fetch{
				local_path:    dst,
				handle:        xp,
				entries:       entries,
				current_entry: -1,
				x_key:         top.x_key,
			}
			remote_drop.dir_stack = append(remote_drop.dir_stack, rd)
			return start_next_drop_fetch()
		}
		return start_next_drop_fetch()
	}

	// ---- DnD event handler ------------------------------------------------
	lp.OnDnDData = func(cmd loop.DndCommand) error {
		switch cmd.Type {
		// ----------------------------------------------------------------
		// Drag source events (terminal → us when we are a drag source)
		// ----------------------------------------------------------------
		case 'o':
			// Terminal tells us a drag gesture started: start our drag.
			if !allow_drags {
				return nil
			}
			// Build ordered MIME list from drag_sources
			drag_mime_list = slices.Collect(maps.Keys(drag_sources))
			slices.Sort(drag_mime_list)

			// Send our MIME offer
			flags := drag_action_flags(opts.DragAction)
			lp.QueueDnDData(map[string]string{"t": "o", "o": strconv.Itoa(flags)},
				strings.Join(drag_mime_list, " "), false)

			// Presend small data payloads (≤ 1 MiB)
			for i, mime := range drag_mime_list {
				ds := drag_sources[mime]
				if ds.data != nil && len(ds.data) <= 1024*1024 {
					lp.QueueDnDData(map[string]string{"t": "p", "x": strconv.Itoa(i)},
						utils.UnsafeBytesToString(ds.data), true)
				}
			}

			// Start the drag
			lp.QueueDnDData(map[string]string{"t": "P", "x": "-1"}, "", false)
			drag_started = true
			return render_screen()

		case 'e':
			// Drag offer events from the terminal
			switch cmd.X {
			case 1:
				// Drag accepted by drop client; no action needed
			case 2:
				// Action changed
				drag_action_final = cmd.Operation
			case 3:
				// Dropped onto client; no action needed
			case 4:
				// Drag finished (cmd.Y==1 means canceled by user)
				was_canceled := cmd.Y == 1
				action := drag_action_final
				if action == 0 {
					action = drag_action_flags(opts.DragAction)
				}
				drag_started = false
				drag_action_final = 0
				if err := render_screen(); err != nil {
					return err
				}
				if !was_canceled && action == 2 {
					// Move: delete source files
					for _, item := range drag_sources["text/uri-list"].uri_list {
						st, err := os.Stat(item.path)
						if err != nil {
							continue
						}
						if st.IsDir() {
							_ = os.RemoveAll(item.path)
						} else {
							_ = os.Remove(item.path)
						}
					}
					lp.Quit(0)
				}
			case 5:
				// Terminal requests data for MIME at index cmd.Y (0-based)
				idx := cmd.Y
				if idx < 0 || idx >= len(drag_mime_list) {
					lp.QueueDnDData(map[string]string{"t": "E", "y": strconv.Itoa(idx)}, "ENOENT", false)
					return nil
				}
				mime := drag_mime_list[idx]
				ds, ok := drag_sources[mime]
				if !ok {
					lp.QueueDnDData(map[string]string{"t": "E", "y": strconv.Itoa(idx)}, "ENOENT", false)
					return nil
				}
				data, err := read_drag_source(ds)
				if err != nil {
					lp.QueueDnDData(map[string]string{"t": "E", "y": strconv.Itoa(idx)}, "EIO", false)
					return nil
				}
				send_drag_data_response(lp, idx, data)

				// If the terminal requests remote file data (Yp == 1 for text/uri-list),
				// stream file content via t=k after the URI list data.
				if cmd.Yp == 1 && mime == "text/uri-list" && len(ds.uri_list) > 0 {
					if err := send_remote_files(lp, ds.uri_list); err != nil {
						lp.QueueDnDData(map[string]string{"t": "E"}, "EMFILE", false)
						return fmt.Errorf("remote drag failed: %w", err)
					}
				}
			}

		case 'E':
			// Error from terminal (e.g., response to t=P:x=-1 or drag errors)
			payload := strings.TrimSpace(string(cmd.Payload))
			if payload == "OK" {
				// Drag started successfully; state already set
			} else {
				// EPERM or other error: cancel drag
				drag_started = false
				drag_action_final = 0
				return render_screen()
			}

		// ----------------------------------------------------------------
		// Drop destination events (terminal → us when we are a drop target)
		// ----------------------------------------------------------------
		case 'm':
			// A drag is moving over our window.
			// If payload is non-empty, it's a new MIME list.
			if !allow_drops {
				return nil
			}
			if cmd.X == -1 && cmd.Y == -1 {
				// Drag left the window
				if drop_accepted {
					drop_accepted = false
					drop_mime_list = nil
					if err := render_screen(); err != nil {
						return err
					}
				}
				return nil
			}

			payload := strings.TrimSpace(string(cmd.Payload))
			if payload != "" {
				// New MIME list
				drop_mime_list = strings.Fields(payload)
			}

			if drag_started {
				// Don't accept drops from our own drag
				lp.QueueDnDData(map[string]string{"t": "m", "o": "0"}, "", false)
				return nil
			}

			// Determine which MIME types we accept and allowed operations
			accepted := []string{}
			drop_copy_allowed = false
			drop_move_allowed = false
			drop_uri_list_x = 0
			for i, m := range drop_mime_list {
				if _, ok := drop_dests[m]; ok {
					accepted = append(accepted, m)
					if m == "text/uri-list" {
						drop_uri_list_x = i + 1 // 1-based
					}
				}
			}

			if len(accepted) == 0 {
				// Nothing we want
				if drop_accepted {
					drop_accepted = false
					_ = render_screen()
				}
				lp.QueueDnDData(map[string]string{"t": "m", "o": "0"}, "", false)
				return nil
			}

			// Determine allowed operations from the drag flags
			op_flags := cmd.Operation // o= key from terminal's t=m event (if present)
			if op_flags == 0 {
				op_flags = 3 // assume both if not specified
			}
			drop_copy_allowed = (op_flags & 1) != 0
			drop_move_allowed = (op_flags & 2) != 0

			// Determine operation based on where the cursor is (button hit test)
			chosen_op := 0
			if drop_copy_allowed && copy_btn.height > 0 && copy_btn.contains(cmd.X, cmd.Y) {
				chosen_op = 1
			} else if drop_move_allowed && move_btn.height > 0 && move_btn.contains(cmd.X, cmd.Y) {
				chosen_op = 2
			} else if drop_copy_allowed {
				chosen_op = 1 // default to copy
			} else if drop_move_allowed {
				chosen_op = 2
			}

			if chosen_op == 0 {
				lp.QueueDnDData(map[string]string{"t": "m", "o": "0"}, "", false)
			} else {
				lp.QueueDnDData(
					map[string]string{"t": "m", "o": strconv.Itoa(chosen_op)},
					strings.Join(accepted, " "), false)
			}

			// Update UI if acceptance state changed
			newly_accepted := chosen_op != 0 && !drop_accepted
			newly_rejected := chosen_op == 0 && drop_accepted
			if newly_accepted || newly_rejected {
				drop_accepted = chosen_op != 0
				return render_screen()
			}

		case 'M':
			// User dropped something onto our window.
			if !allow_drops || drag_started {
				// Signal the terminal that we're done (reject)
				lp.QueueDnDData(map[string]string{"t": "r"}, "", false)
				return nil
			}
			// Refresh MIME list from payload (mandatory for t=M)
			payload := strings.TrimSpace(string(cmd.Payload))
			if payload != "" {
				drop_mime_list = strings.Fields(payload)
			}

			// Build list of MIME indexes to fetch (in order of preference)
			drop_pending_mime_xs = nil
			for i, m := range drop_mime_list {
				if _, ok := drop_dests[m]; ok {
					drop_pending_mime_xs = append(drop_pending_mime_xs, i+1) // 1-based
				}
			}
			// Move text/uri-list to last so we handle remote detection properly
			uri_last := []int{}
			non_uri := []int{}
			for _, x := range drop_pending_mime_xs {
				if x == drop_uri_list_x {
					uri_last = append(uri_last, x)
				} else {
					non_uri = append(non_uri, x)
				}
			}
			drop_pending_mime_xs = append(non_uri, uri_last...)

			if len(drop_pending_mime_xs) == 0 {
				// Nothing we want; signal done immediately
				lp.QueueDnDData(map[string]string{"t": "r"}, "", false)
				return nil
			}
			drop_in_progress = true
			if err := render_screen(); err != nil {
				return err
			}
			return start_next_drop_fetch()

		case 'r':
			// Data from terminal in response to our t=r request.
			// For regular files, write decoded chunks directly to the destination
			// (streaming mode). For symlinks, directories, and text/uri-list,
			// accumulate in drop_chunks and process on the end-of-data signal.
			if len(cmd.Payload) > 0 {
				data, err := decode_b64(cmd.Payload)
				if err != nil {
					return nil
				}
				// Record X= type from the first non-empty chunk.
				if cmd.Xp != 0 && drop_current_xp == 0 {
					drop_current_xp = cmd.Xp
				}
				if drop_streaming_dest != nil {
					// Already in streaming mode: write directly.
					_, _ = drop_streaming_dest.Write(data)
				} else if drop_current_mime_x != 0 {
					// Normal MIME response: stream to destination if it's not text/uri-list.
					mime_type := drop_mime_list[drop_current_mime_x-1]
					dd := drop_dests[mime_type]
					if mime_type != "text/uri-list" && dd.dest != nil {
						// io.WriteCloser destination: stream directly.
						drop_streaming_dest = dd.dest
						_, _ = drop_streaming_dest.Write(data)
					} else if mime_type != "text/uri-list" && dd.path != "" {
						// File path destination: open file and start streaming.
						_ = os.MkdirAll(filepath.Dir(dd.path), 0o755)
						if f, ferr := os.OpenFile(dd.path, os.O_CREATE|os.O_WRONLY|os.O_TRUNC, 0o644); ferr == nil {
							drop_streaming_file = f
							drop_streaming_dest = f
							_, _ = drop_streaming_dest.Write(data)
						} else {
							drop_chunks.Write(data)
						}
					} else {
						// text/uri-list or no configured destination: accumulate.
						drop_chunks.Write(data)
					}
				} else if remote_drop != nil && cmd.Xp == 0 {
					// Regular file in a remote fetch (top-level URI or dir entry).
					// Determine the local destination path from context.
					var dst_path string
					var dst_ok bool
					if cmd.Yp != 0 && len(remote_drop.dir_stack) > 0 {
						top := remote_drop.dir_stack[len(remote_drop.dir_stack)-1]
						if top.current_entry >= 0 && top.current_entry < len(top.entries) {
							dst_path, dst_ok = safe_dest_path(top.local_path, top.entries[top.current_entry])
						}
					} else if cmd.X == remote_drop.uri_list_x && cmd.Y > 0 {
						subidx := cmd.Y
						if subidx >= 1 && subidx <= len(remote_drop.file_paths) {
							filename := filepath.Base(remote_drop.file_paths[subidx-1])
							dst_path, dst_ok = safe_dest_path(remote_drop.dest_dir, filename)
						}
					}
					if dst_ok && dst_path != "" {
						_ = os.MkdirAll(filepath.Dir(dst_path), 0o755)
						if f, ferr := os.OpenFile(dst_path, os.O_CREATE|os.O_WRONLY|os.O_TRUNC, 0o644); ferr == nil {
							drop_streaming_file = f
							drop_streaming_dest = f
							_, _ = drop_streaming_dest.Write(data)
						} else {
							drop_chunks.Write(data)
						}
					} else {
						drop_chunks.Write(data)
					}
				} else {
					// Symlink, directory, or unknown item type: accumulate.
					drop_chunks.Write(data)
				}
				return nil
			}
			// Empty payload: end-of-data signal.

			// If we were streaming, the file is already fully written.
			if drop_streaming_dest != nil || drop_streaming_file != nil {
				if drop_streaming_file != nil {
					_ = drop_streaming_file.Close()
					drop_streaming_file = nil
				}
				drop_streaming_dest = nil
				drop_chunks.Reset()
				drop_current_xp = 0
				if drop_current_mime_x != 0 {
					drop_current_mime_x = 0
					return start_next_drop_fetch()
				}
				// Remote file or dir entry: advance to next fetch.
				return start_next_drop_fetch()
			}

			if remote_drop != nil {
				// Directory entry response: Y=handle matches top of dir stack
				if len(remote_drop.dir_stack) > 0 && cmd.Yp != 0 {
					top := remote_drop.dir_stack[len(remote_drop.dir_stack)-1]
					if cmd.Yp == top.handle {
						full_data := make([]byte, drop_chunks.Len())
						copy(full_data, drop_chunks.Bytes())
						drop_chunks.Reset()
						return handle_dir_entry_response(cmd.Xp, full_data)
					}
				}
				// Remote file response: x=uri_list_x, y=current_subidx
				if cmd.X == remote_drop.uri_list_x && cmd.Y > 0 && cmd.Y == remote_drop.current_subidx {
					full_data := make([]byte, drop_chunks.Len())
					copy(full_data, drop_chunks.Bytes())
					drop_chunks.Reset()

					subidx := cmd.Y // 1-based
					if subidx >= 1 && subidx <= len(remote_drop.file_paths) {
						raw_path := remote_drop.file_paths[subidx-1]
						filename := filepath.Base(raw_path)
						dst, ok := safe_dest_path(remote_drop.dest_dir, filename)
						if ok {
							xp := cmd.Xp
							if xp == 0 {
								// Regular file (empty data case, e.g. 0-byte file)
								_ = os.MkdirAll(filepath.Dir(dst), 0o755)
								_ = os.WriteFile(dst, full_data, 0o644)
							} else if xp == 1 {
								// Symlink — only create if target stays within dest_dir
								target := string(full_data)
								abs_target := target
								if !filepath.IsAbs(abs_target) {
									abs_target = filepath.Join(remote_drop.dest_dir, target)
								}
								abs_target = filepath.Clean(abs_target)
								abs_dest, _ := filepath.Abs(remote_drop.dest_dir)
								sep := string(filepath.Separator)
								if strings.HasPrefix(abs_target, abs_dest+sep) || abs_target == abs_dest {
									_ = os.MkdirAll(filepath.Dir(dst), 0o755)
									_ = os.Symlink(target, dst)
								}
							} else {
								// Directory: create local dir, parse entries, push dir fetch
								_ = os.MkdirAll(dst, 0o755)
								entries_raw := bytes.Split(full_data, []byte{0})
								entries := make([]string, 0, len(entries_raw))
								for _, e := range entries_raw {
									if len(e) > 0 {
										entries = append(entries, string(e))
									}
								}
								rd := &remote_dir_fetch{
									local_path:    dst,
									handle:        xp,
									entries:       entries,
									current_entry: -1,
									x_key:         remote_drop.uri_list_x,
								}
								remote_drop.dir_stack = append(remote_drop.dir_stack, rd)
							}
						}
					}
					return start_next_drop_fetch()
				}
			}

			// Normal MIME data response
			if drop_current_mime_x == 0 || cmd.X != drop_current_mime_x {
				// Stale or unexpected end signal; discard accumulated data
				drop_chunks.Reset()
				drop_current_xp = 0
				return nil
			}
			xp := drop_current_xp
			full_data := make([]byte, drop_chunks.Len())
			copy(full_data, drop_chunks.Bytes())
			drop_chunks.Reset()
			drop_current_xp = 0
			if err := write_mime_data(drop_current_mime_x, full_data, xp); err != nil {
				return err
			}
			drop_current_mime_x = 0
			return start_next_drop_fetch()
		case 'R':
			// Error from terminal for a data request; skip this item.
			if drop_streaming_file != nil {
				_ = drop_streaming_file.Close()
				drop_streaming_file = nil
			}
			drop_streaming_dest = nil
			drop_chunks.Reset()
			drop_current_mime_x = 0
			drop_current_xp = 0
			if remote_drop != nil {
				remote_drop.current_subidx = 0
			}
			return start_next_drop_fetch()
		}
		return nil
	}

	lp.OnInitialize = func() (string, error) {
		lp.AllowLineWrapping(false)
		if allow_drops {
			lp.StartAcceptingDrops(slices.Collect(maps.Keys(drop_dests))...)
		}
		if allow_drags {
			lp.StartOfferingDrags()
		}
		return "", render_screen()
	}
	lp.OnFinalize = func() string {
		lp.AllowLineWrapping(true)
		if allow_drops {
			lp.StopAcceptingDrops()
		}
		if allow_drags {
			lp.StopOfferingDrags()
		}
		return ""
	}
	lp.OnKeyEvent = func(e *loop.KeyEvent) (err error) {
		e.Handled = true
		if e.MatchesPressOrRepeat("ctrl+c") || e.MatchesPressOrRepeat("esc") {
			lp.Quit(0)
			return
		}
		return nil
	}
	lp.OnResize = func(old_size loop.ScreenSize, new_size loop.ScreenSize) error {
		return render_screen()
	}
	err = lp.Run()
	if err != nil {
		return
	}
	ds := lp.DeathSignalName()
	if ds != "" {
		fmt.Println("Killed by signal: ", ds)
		lp.KillIfSignalled()
		return
	}
	return
}

func dnd_main(cmd *cli.Command, opts *Options, args []string) (rc int, err error) {
	drop_dests := make(map[string]drop_dest)
	if os.Stdout != nil && !tty.IsTerminal(os.Stdout.Fd()) {
		drop_dests["text/plain"] = drop_dest{human_name: "STDOUT", dest: os.Stdout, mime_type: "text/plain"}
	}
	uri_list_buffer := &bytes.Buffer{}
	drop_dests["text/uri-list"] = drop_dest{
		human_name: "Files", mime_type: "text/uri-list", dest: &bufferWriteCloser{uri_list_buffer}}
	for _, spec := range opts.Drop {
		mime, dest, _ := strings.Cut(spec, ":")
		if dest == "" {
			delete(drop_dests, mime)
		} else {
			path, err := filepath.Abs(dest)
			if err != nil {
				return 1, err
			}
			drop_dests[mime] = drop_dest{human_name: dest, path: path, mime_type: mime}
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
	err = run_loop(opts, drop_dests, drag_sources, uri_list_buffer)
	if err != nil {
		return 1, err
	}
	return 0, nil
}

func EntryPoint(parent *cli.Command) {
	create_cmd(parent, dnd_main)
}
