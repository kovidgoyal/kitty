// License: GPLv3 Copyright: 2023, Kovid Goyal, <kovid at kovidgoyal.net>

package mouse_demo

import (
	"bytes"
	"crypto/hmac"
	"crypto/sha256"
	"encoding/base64"
	"encoding/hex"
	"fmt"
	"net/url"
	"path/filepath"
	"strconv"
	"strings"

	"github.com/kovidgoyal/kitty"
	"github.com/kovidgoyal/kitty/tools/tty"
	"github.com/kovidgoyal/kitty/tools/tui/loop"
	"github.com/kovidgoyal/kitty/tools/utils"
	"github.com/kovidgoyal/kitty/tools/utils/machine_id"
)

var _ = fmt.Print
var debugprintln = tty.DebugPrintln
var _ = debugprintln

const dnd_accepted_mimes = "text/plain text/uri-list"

func dnd_escape(metadata, payload string) string {
	b := strings.Builder{}
	fmt.Fprintf(&b, "\x1b]%d;", kitty.DndCode)
	b.WriteString(metadata)
	if payload != "" {
		b.WriteByte(';')
		b.WriteString(payload)
	}
	b.WriteString("\x1b\\")
	return b.String()
}

// get_machine_id returns the machine id in the format expected by the DnD
// protocol ("1:" followed by HMAC-SHA256 of /etc/machine-id).
func get_machine_id() string {
	ans, err := machine_id.MachineId()
	if err != nil {
		return ""
	}
	mac := hmac.New(sha256.New, []byte("tty-dnd-protocol-machine-id"))
	mac.Write(utils.UnsafeStringToBytes(ans))
	return "1:" + hex.EncodeToString(mac.Sum(nil))
}

func dnd_start_accepting(machine_id string) string {
	result := dnd_escape("t=a", dnd_accepted_mimes)
	if machine_id != "" {
		result += dnd_escape("t=a:x=1", machine_id)
	}
	return result
}

func dnd_stop_accepting() string {
	return dnd_escape("t=A", "")
}

func dnd_accept_drag(mimes string) string {
	return dnd_escape("t=m:o=1", mimes)
}

func dnd_reject_drag() string {
	return dnd_escape("t=m:o=0", "")
}

// dnd_request_mime_data requests MIME type data by 1-based index.
func dnd_request_mime_data(idx int) string {
	return dnd_escape(fmt.Sprintf("t=r:x=%d", idx), "")
}

// dnd_request_file requests individual file data by MIME index and file subindex.
func dnd_request_file(mime_idx, file_idx int) string {
	return dnd_escape(fmt.Sprintf("t=r:x=%d:y=%d", mime_idx, file_idx), "")
}

// dnd_close_dir closes a directory handle by sending t=r:Y=handle.
func dnd_close_dir(handle int) string {
	return dnd_escape(fmt.Sprintf("t=r:Y=%d", handle), "")
}

func dnd_finish() string {
	return dnd_escape("t=r", "")
}

// file_info holds metadata about a dropped file.
type file_info struct {
	name    string
	size    int64
	is_dir  bool
	is_link bool
	err_msg string
}

type dnd_state struct {
	dragging   bool
	drag_mimes []string
	// Current drag cell position (set from t=m events).
	drag_cell_x   int
	drag_cell_y   int
	drag_over_box bool // true when the drag is currently over the drop region

	// Drop handling.
	drop_mimes        []string
	uri_list_mime_idx int  // 1-based index of text/uri-list in drop_mimes (0 = not present)
	is_remote         bool // X=1 received in URI list response (client is on different machine)

	// Collection state: what we're currently collecting.
	// Values: "", "text/plain", "text/uri-list", "file"
	collecting  string
	collect_buf strings.Builder

	// Results of drop.
	plain_text    string
	uri_list      []string    // parsed file:// URIs from text/uri-list
	file_infos    []file_info // one entry per uri_list entry
	has_drop_data bool

	// File reading state.
	file_read_idx  int   // 1-based index of file currently being read (0 = not reading files)
	file_read_size int64 // bytes accumulated so far for current file

	// Layout: drop box position on screen (set during draw_screen).
	drop_box_start_row int
	drop_box_end_row   int
	drop_box_width     int
}

func (d *dnd_state) reset_drag() {
	d.dragging = false
	d.drag_over_box = false
	d.drag_mimes = nil
}

func (d *dnd_state) reset_drop_data() {
	d.drop_mimes = nil
	d.uri_list_mime_idx = 0
	d.is_remote = false
	d.collecting = ""
	d.collect_buf.Reset()
	d.plain_text = ""
	d.uri_list = nil
	d.file_infos = nil
	d.has_drop_data = false
	d.file_read_idx = 0
	d.file_read_size = 0
}

// is_over_drop_box returns true if the given cell coordinates are within the
// drop box region as tracked from the last draw_screen call.
func (d *dnd_state) is_over_drop_box(cell_x, cell_y int) bool {
	// Before the first draw, drop_box_end_row equals drop_box_start_row (both zero).
	if d.drop_box_end_row <= d.drop_box_start_row {
		return false
	}
	return cell_y >= d.drop_box_start_row && cell_y <= d.drop_box_end_row &&
		cell_x >= 0 && cell_x < d.drop_box_width
}

// filename_from_uri extracts the base filename from a file:// URI.
func filename_from_uri(uri string) string {
	u, err := url.Parse(uri)
	if err != nil || u.Scheme != "file" {
		return uri
	}
	return filepath.Base(u.Path)
}

// format_size formats a byte count as a human-readable size string.
func format_size(n int64) string {
	switch {
	case n < 1024:
		return fmt.Sprintf("%d B", n)
	case n < 1024*1024:
		return fmt.Sprintf("%.1f KiB", float64(n)/1024)
	case n < 1024*1024*1024:
		return fmt.Sprintf("%.1f MiB", float64(n)/(1024*1024))
	default:
		return fmt.Sprintf("%.1f GiB", float64(n)/(1024*1024*1024))
	}
}

func draw_rounded_box(lp *loop.Loop, width int, lines []string) {
	if width < 4 {
		width = 4
	}
	inner_width := width - 2
	// Top border
	lp.QueueWriteString("╭" + strings.Repeat("─", inner_width) + "╮\r\n")
	for _, line := range lines {
		// Truncate to inner_width runes (not bytes) to handle multi-byte chars safely.
		runes := []rune(line)
		if len(runes) > inner_width {
			runes = runes[:inner_width]
		}
		padding := inner_width - len(runes)
		lp.QueueWriteString("│" + string(runes) + strings.Repeat(" ", padding) + "│\r\n")
	}
	// Bottom border
	lp.QueueWriteString("╰" + strings.Repeat("─", inner_width) + "╯\r\n")
}

func Run(args []string) (rc int, err error) {
	all_pointer_shapes := []loop.PointerShape{
		// start all pointer shapes (auto generated by gen-key-constants.py do not edit)
		loop.DEFAULT_POINTER,
		loop.TEXT_POINTER,
		loop.POINTER_POINTER,
		loop.HELP_POINTER,
		loop.WAIT_POINTER,
		loop.PROGRESS_POINTER,
		loop.CROSSHAIR_POINTER,
		loop.CELL_POINTER,
		loop.VERTICAL_TEXT_POINTER,
		loop.MOVE_POINTER,
		loop.E_RESIZE_POINTER,
		loop.NE_RESIZE_POINTER,
		loop.NW_RESIZE_POINTER,
		loop.N_RESIZE_POINTER,
		loop.SE_RESIZE_POINTER,
		loop.SW_RESIZE_POINTER,
		loop.S_RESIZE_POINTER,
		loop.W_RESIZE_POINTER,
		loop.EW_RESIZE_POINTER,
		loop.NS_RESIZE_POINTER,
		loop.NESW_RESIZE_POINTER,
		loop.NWSE_RESIZE_POINTER,
		loop.ZOOM_IN_POINTER,
		loop.ZOOM_OUT_POINTER,
		loop.ALIAS_POINTER,
		loop.COPY_POINTER,
		loop.NOT_ALLOWED_POINTER,
		loop.NO_DROP_POINTER,
		loop.GRAB_POINTER,
		loop.GRABBING_POINTER,
		// end all pointer shapes
	}
	all_pointer_shape_names := make([]string, len(all_pointer_shapes))
	col_width := 0
	for i, p := range all_pointer_shapes {
		all_pointer_shape_names[i] = p.String()
		col_width = max(col_width, len(all_pointer_shape_names[i]))
	}
	col_width += 1

	lp, err := loop.New()
	if err != nil {
		return 1, err
	}
	lp.MouseTrackingMode(loop.FULL_MOUSE_TRACKING)
	var current_mouse_event *loop.MouseEvent
	var dnd dnd_state

	machine_id := get_machine_id()

	// build_box_lines computes the drop box content lines based on current state.
	build_box_lines := func() []string {
		if dnd.drag_over_box {
			lines := []string{"Drop here! MIME types:"}
			for _, m := range dnd.drag_mimes {
				lines = append(lines, "  "+m)
			}
			return lines
		}
		if dnd.dragging {
			return []string{"Drag in window — move over this box to drop"}
		}
		if dnd.has_drop_data {
			lines := []string{}
			if dnd.plain_text != "" {
				lines = append(lines, "text/plain: "+dnd.plain_text)
			}
			if len(dnd.file_infos) > 0 {
				for i, fi := range dnd.file_infos {
					if i >= len(dnd.uri_list) {
						break
					}
					name := filename_from_uri(dnd.uri_list[i])
					if fi.err_msg != "" {
						lines = append(lines, name+": error: "+fi.err_msg)
					} else if fi.is_dir {
						lines = append(lines, name+"/  [directory]")
					} else if fi.is_link {
						lines = append(lines, name+"  [symlink]")
					} else {
						lines = append(lines, name+"  "+format_size(fi.size))
					}
				}
			} else if len(dnd.uri_list) > 0 {
				for _, u := range dnd.uri_list {
					lines = append(lines, "  "+u)
				}
			}
			if len(lines) == 0 {
				lines = []string{"Drop received (no recognized content)"}
			}
			return lines
		}
		return []string{"Drop files here"}
	}

	draw_screen := func() {
		lp.StartAtomicUpdate()
		defer lp.EndAtomicUpdate()
		lp.AllowLineWrapping(false)
		defer lp.AllowLineWrapping(true)
		lp.ClearScreen()

		sw := 80
		sh := 24
		if s, err := lp.ScreenSize(); err == nil {
			sw = int(s.WidthCells)
			sh = int(s.HeightCells)
		}

		// y tracks the next row to be printed; used for both content drawing
		// and computing the drop box position.
		y := 0

		if current_mouse_event == nil {
			lp.Println(`Move the mouse or click to see mouse events`)
			y++
			lp.Println("Hover the mouse over the names below to see the shapes")
			y++
			lp.Println()
			y++
			num_cols := max(1, sw/col_width)
			colfmt := "%-" + strconv.Itoa(col_width) + "s"
			for pos := 0; pos < len(all_pointer_shapes); {
				for c := 0; c < num_cols && pos < len(all_pointer_shapes); c++ {
					lp.Printf(colfmt, all_pointer_shape_names[pos])
					pos++
				}
				lp.Println()
				y++
			}
		} else if current_mouse_event.Event_type == loop.MOUSE_LEAVE {
			lp.Println("Mouse has left the window")
			y++
		} else {
			lp.Printf("Position: %d, %d (pixels)\r\n", current_mouse_event.Pixel.X, current_mouse_event.Pixel.Y)
			y++
			lp.Printf("Cell    : %d, %d\r\n", current_mouse_event.Cell.X, current_mouse_event.Cell.Y)
			y++
			lp.Printf("Type    : %s\r\n", current_mouse_event.Event_type)
			y++
			if current_mouse_event.Buttons != loop.NO_MOUSE_BUTTON {
				lp.Println(current_mouse_event.Buttons.String())
				y++
			}
			if mods := current_mouse_event.Mods.String(); mods != "" {
				lp.Printf("Modifiers: %s\r\n", mods)
				y++
			}
			lp.Println("Hover the mouse over the names below to see the shapes")
			y++

			num_cols := max(1, sw/col_width)
			pos := 0
			colfmt := "%-" + strconv.Itoa(col_width) + "s"
			is_on_name := false
			var ps loop.PointerShape
			for y < sh && pos < len(all_pointer_shapes) {
				is_row := y == current_mouse_event.Cell.Y
				for c := 0; c < num_cols && pos < len(all_pointer_shapes); c++ {
					name := all_pointer_shape_names[pos]
					is_hovered := false
					if is_row {
						start_x := c * col_width
						x := current_mouse_event.Cell.X
						if x < start_x+len(name) && x >= start_x {
							is_on_name = true
							is_hovered = true
							ps = all_pointer_shapes[pos]
						}
					}
					if is_hovered {
						lp.QueueWriteString("\x1b[31m")
					}
					lp.Printf(colfmt, name)
					lp.QueueWriteString("\x1b[m")
					pos++
				}
				y++
				lp.Println()
			}
			lp.PopPointerShape()
			if is_on_name {
				lp.PushPointerShape(ps)
			}
		}

		// Draw the drop area below the pointer shapes list.
		// y is now the row where the blank separator will be printed.
		lp.Println()
		y++ // blank separator line

		box_width := min(sw, 60)
		dnd.drop_box_width = box_width
		box_lines := build_box_lines()
		dnd.drop_box_start_row = y
		dnd.drop_box_end_row = y + len(box_lines) + 1 // top border + lines + bottom border

		if dnd.drag_over_box {
			// Highlight the box in green when drag is over it.
			lp.QueueWriteString("\x1b[32m")
			draw_rounded_box(lp, box_width, box_lines)
			lp.QueueWriteString("\x1b[m")
		} else {
			draw_rounded_box(lp, box_width, box_lines)
		}
	}

	// start_next_file_request sends a request for the next unread file URI,
	// or finishes the drop if all files have been read.
	var start_next_file_request func()
	start_next_file_request = func() {
		for dnd.file_read_idx < len(dnd.uri_list) {
			uri := dnd.uri_list[dnd.file_read_idx]
			if strings.HasPrefix(uri, "file://") {
				// Request this file via the protocol.
				dnd.file_read_size = 0
				dnd.collecting = "file"
				lp.QueueWriteString(dnd_request_file(dnd.uri_list_mime_idx, dnd.file_read_idx+1))
				return
			}
			// Non-file URI: record as-is with no size info.
			dnd.file_infos = append(dnd.file_infos, file_info{name: uri})
			dnd.file_read_idx++
		}
		// All files processed; finish the drop.
		dnd.collecting = ""
		lp.QueueWriteString(dnd_finish())
		dnd.has_drop_data = true
		draw_screen()
	}

	handle_dnd_osc := func(raw []byte) error {
		// raw is the OSC payload after ESC ] and before ST.
		// Format: DND_CODE;metadata[;payload]
		prefix := fmt.Sprintf("%d;", kitty.DndCode)
		if !bytes.HasPrefix(raw, []byte(prefix)) {
			return nil
		}
		rest := string(raw[len(prefix):])
		// Split into metadata and optional payload.
		meta, payload, _ := strings.Cut(rest, ";")
		// Parse metadata key=value pairs separated by ':'.
		meta_map := make(map[string]string)
		for kv := range strings.SplitSeq(meta, ":") {
			k, v, _ := strings.Cut(kv, "=")
			if k != "" {
				meta_map[k] = v
			}
		}
		t := meta_map["t"]
		switch t {
		case "m":
			// Drag move event from terminal.
			// Check if drag has left the window (x=-1, y=-1).
			if meta_map["x"] == "-1" || meta_map["y"] == "-1" {
				dnd.reset_drag()
				draw_screen()
				return nil
			}
			mimes := strings.Fields(payload)
			if len(mimes) > 0 {
				dnd.drag_mimes = mimes
			}
			dnd.dragging = true
			cx, _ := strconv.Atoi(meta_map["x"])
			cy, _ := strconv.Atoi(meta_map["y"])
			dnd.drag_cell_x = cx
			dnd.drag_cell_y = cy

			over_box := dnd.is_over_drop_box(cx, cy)
			dnd.drag_over_box = over_box

			if over_box {
				// Accept the drag with copy operation for supported MIME types.
				accepted_mimes := []string{}
				for _, m := range dnd.drag_mimes {
					if m == "text/plain" || m == "text/uri-list" {
						accepted_mimes = append(accepted_mimes, m)
					}
				}
				if len(accepted_mimes) > 0 {
					lp.QueueWriteString(dnd_accept_drag(strings.Join(accepted_mimes, " ")))
				}
			} else {
				// Not over drop region; reject the drag.
				lp.QueueWriteString(dnd_reject_drag())
			}
			draw_screen()
		case "M":
			// Drop event from terminal.
			dnd.reset_drag()
			dnd.reset_drop_data()
			mimes := strings.Fields(payload)
			dnd.drop_mimes = mimes

			// Find the MIME indices we need.
			for i, m := range mimes {
				if m == "text/uri-list" {
					dnd.uri_list_mime_idx = i + 1
				}
			}

			// Request data: text/plain first, then text/uri-list.
			for idx, m := range mimes {
				if m == "text/plain" {
					dnd.collecting = "text/plain"
					lp.QueueWriteString(dnd_request_mime_data(idx + 1))
					return nil
				}
			}
			if dnd.uri_list_mime_idx > 0 {
				dnd.collecting = "text/uri-list"
				lp.QueueWriteString(dnd_request_mime_data(dnd.uri_list_mime_idx))
				return nil
			}
			// Nothing to collect; signal done.
			lp.QueueWriteString(dnd_finish())
			dnd.has_drop_data = true
			draw_screen()
		case "r":
			// Data response from terminal.
			resp_y, _ := strconv.Atoi(meta_map["y"])
			resp_X, _ := strconv.Atoi(meta_map["X"])

			is_file_response := resp_y != 0
			if is_file_response {
				// Response for an individual file request (t=r:x=idx:y=subidx).
				if payload == "" {
					// End of file data.
					fi := file_info{}
					if resp_X > 1 {
						// Directory: close the handle.
						fi.is_dir = true
						lp.QueueWriteString(dnd_close_dir(resp_X))
					} else if resp_X == 1 {
						fi.is_link = true
						fi.size = dnd.file_read_size
					} else {
						fi.size = dnd.file_read_size
					}
					dnd.file_infos = append(dnd.file_infos, fi)
					dnd.file_read_idx++
					draw_screen()
					start_next_file_request()
				} else {
					decoded, err := base64.RawStdEncoding.DecodeString(payload)
					if err == nil {
						dnd.file_read_size += int64(len(decoded))
					}
				}
				return nil
			}

			// Response for a MIME type data request.
			if payload == "" {
				// End of MIME type data.
				switch dnd.collecting {
				case "text/plain":
					text := dnd.collect_buf.String()
					text = strings.TrimRight(text, "\r\n")
					if before, _, ok := strings.Cut(text, "\n"); ok {
						dnd.plain_text = strings.TrimRight(before, "\r")
					} else {
						dnd.plain_text = text
					}
					dnd.collect_buf.Reset()
					// Now request text/uri-list if available.
					if dnd.uri_list_mime_idx > 0 {
						dnd.collecting = "text/uri-list"
						lp.QueueWriteString(dnd_request_mime_data(dnd.uri_list_mime_idx))
						return nil
					}
				case "text/uri-list":
					text := dnd.collect_buf.String()
					dnd.collect_buf.Reset()
					// Check if terminal indicated remote files (X=1 in URI list response).
					if resp_X == 1 {
						dnd.is_remote = true
					}
					// Parse URI list: lines starting with # are comments.
					for line := range strings.SplitSeq(text, "\n") {
						line = strings.TrimRight(line, "\r")
						if line != "" && !strings.HasPrefix(line, "#") {
							dnd.uri_list = append(dnd.uri_list, line)
						}
					}
					// Start reading individual files.
					if len(dnd.uri_list) > 0 && dnd.uri_list_mime_idx > 0 {
						dnd.file_read_idx = 0
						start_next_file_request()
						return nil
					}
				}
				dnd.collecting = ""
				lp.QueueWriteString(dnd_finish())
				dnd.has_drop_data = true
				draw_screen()
			} else {
				decoded, err := base64.RawStdEncoding.DecodeString(payload)
				if err == nil {
					dnd.collect_buf.Write(decoded)
					// Capture X from URI list response (may be in first chunk).
					if dnd.collecting == "text/uri-list" && resp_X != 0 {
						dnd.is_remote = resp_X == 1
					}
				}
			}
		case "R":
			// Error response from terminal.
			resp_y, _ := strconv.Atoi(meta_map["y"])
			is_file_response := resp_y != 0
			if is_file_response && dnd.collecting == "file" {
				// Record the error for this file.
				dnd.file_infos = append(dnd.file_infos, file_info{err_msg: payload})
				dnd.file_read_idx++
				draw_screen()
				start_next_file_request()
			} else if !is_file_response {
				// Error getting MIME data; finish the drop with what we have.
				dnd.collecting = ""
				lp.QueueWriteString(dnd_finish())
				dnd.has_drop_data = true
				draw_screen()
			}
		}
		return nil
	}

	lp.OnInitialize = func() (string, error) {
		lp.SetWindowTitle("kitty mouse features demo")
		lp.SetCursorVisible(false)
		lp.QueueWriteString(dnd_start_accepting(machine_id))
		draw_screen()
		return "", nil
	}
	lp.OnFinalize = func() string {
		lp.SetCursorVisible(true)
		return dnd_stop_accepting()
	}

	lp.OnMouseEvent = func(ev *loop.MouseEvent) error {
		current_mouse_event = ev
		draw_screen()
		return nil
	}
	lp.OnKeyEvent = func(ev *loop.KeyEvent) error {
		if ev.MatchesPressOrRepeat("esc") || ev.MatchesPressOrRepeat("ctrl+c") {
			lp.Quit(0)
		}
		return nil
	}
	lp.OnResize = func(old_size loop.ScreenSize, new_size loop.ScreenSize) error {
		draw_screen()
		return nil
	}
	lp.OnEscapeCode = func(etype loop.EscapeCodeType, raw []byte) error {
		if etype == loop.OSC {
			return handle_dnd_osc(raw)
		}
		return nil
	}
	err = lp.Run()
	if err != nil {
		rc = 1
	}
	return
}
