package dnd

import (
	"fmt"
	"strings"

	"github.com/kovidgoyal/kitty/tools/tui/loop"
	"github.com/kovidgoyal/kitty/tools/wcswidth"
)

var _ = fmt.Print

type button_region struct {
	left, width, top, height int
}

func (r button_region) has(x, y int) bool {
	return r.left <= x && x < r.left+r.width && r.top <= y && y < r.top+r.height
}

func truncate_at_space(text string, width int) (string, string) {
	truncated, p := wcswidth.TruncateToVisualLengthWithWidth(text, width)
	if len(truncated) == len(text) {
		return text, ""
	}
	i := strings.LastIndexByte(truncated, ' ')
	if i > 0 && p-i < 12 {
		p = i + 1
	}
	return text[:p], text[p:]
}

func paragraph_as_lines(text string, width int) (ans []string) {
	for text != "" {
		var line string
		if line, text = truncate_at_space(text, width); line != "" {
			ans = append(ans, line)
		}
	}
	return
}

func (dnd *dnd) render_screen() error {
	lp := dnd.lp
	if !dnd.in_test_mode {
		lp.StartAtomicUpdate()
		defer lp.EndAtomicUpdate()
	}
	lp.ClearScreen()
	dnd.copy_button_region, dnd.move_button_region = button_region{}, button_region{}
	if dnd.drag_started {
		lp.Println("Dragging data...")
		return nil
	}
	if dnd.drop_status.reading_data {
		lp.Println("Reading dropped data, please wait...")
		return nil
	}
	y := 0
	sz, _ := lp.ScreenSize()
	render_paragraph := func(text string) {
		for _, line := range paragraph_as_lines(text, int(sz.WidthCells)) {
			lp.Println(line)
			y++
		}
	}
	next_line := func() {
		lp.Println()
		y++
	}

	if len(dnd.confirm_drop.overwrites) > 0 {
		render_paragraph("Some of the dropped files will overwrite existing files, listed below. Press \x1b[32mEnter\x1b[39m to drop anyway or \x1b[31mEsc\x1b[39m to cancel the drop.")
		sz, _ := lp.ScreenSize()
		next_line()
		next_line()
		overwrites := dnd.confirm_drop.overwrites[:min(int(sz.HeightCells)-y-1, len(dnd.confirm_drop.overwrites))]
		for _, x := range overwrites {
			lp.Println(x)
		}
		if left := len(dnd.confirm_drop.overwrites) - len(overwrites); left > 0 {
			lp.Printf("... (%d more)", left)
		}
		return nil
	}

	if dnd.drop_status.in_window {
		if dnd.drop_status.action == 0 {
			render_paragraph("A drag is active. Drop it into one of the boxes below to perform that action on the dragged data. Available MIME types in the drag:")
			next_line()
			render_paragraph(strings.Join(dnd.drop_status.offered_mimes, " "))
		} else {
			render_paragraph("The drag can be dropped. Supported MIME types:")
			next_line()
			render_paragraph(strings.Join(dnd.drop_status.accepted_mimes, " "))
		}
	} else {
		// Neither active drag nor drop over window
		if dnd.allow_drags {
			render_paragraph(`Start dragging anywhere in this window to initiate a drag and drop. If you start the drag in one of the Copy or Move boxes below, only that action will be allowed when dropping, otherwise, the drop destination can pick either copy or move.`)
			next_line()
		}
		if dnd.allow_drops {
			if dnd.data_has_been_dropped {
				render_paragraph(`Data has been successfully dropped. You can drop more data or press Esc to quit.`)
			} else {
				render_paragraph(`Drag some data from another application into this window to transfer the files here.`)
			}
		}
	}
	frame_width, padding_width := 4, 8
	text_width := len("copymove")
	scale := 5
	for scale > 1 && frame_width+padding_width+text_width*scale > int(sz.WidthCells) {
		scale--
	}
	height := scale + 4
	boxy := 1 + max(0, int(sz.HeightCells)-height)
	lp.MoveCursorTo(1, boxy)
	lp.ClearToEndOfScreen()

	render_box := func(x int, text string, r *button_region) {
		width := scale*wcswidth.Stringwidth(text) + 6
		r.left = x - 1
		r.top = boxy - 1
		r.width = width
		r.height = height
		lp.MoveCursorTo(x, boxy)
		for i := range height {
			lp.SaveCursorPosition()
			switch i {
			case 0:
				lp.QueueWriteString("╭")
				lp.QueueWriteString(strings.Repeat("─", width-2))
				lp.QueueWriteString("╮")
			case height - 1:
				lp.QueueWriteString("╰")
				lp.QueueWriteString(strings.Repeat("─", width-2))
				lp.QueueWriteString("╯")
			default:
				lp.QueueWriteString("│")
				if i == 2 {
					lp.MoveCursorHorizontally(2)
					lp.DrawSizedText(text, loop.SizedText{Scale: scale})
				}
				lp.MoveCursorTo(x+width-1, boxy+i)
				lp.QueueWriteString("│")
			}
			lp.RestoreCursorPosition()
			lp.MoveCursorVertically(1)
		}
	}
	const fg = 32
	if dnd.drop_status.action == copy_on_drop {
		lp.Printf("\x1b[%dm", fg)
	}
	render_box(1, "Copy", &dnd.copy_button_region)
	lp.QueueWriteString("\x1b[39m")
	box_width := 6 + len("move")*scale
	if dnd.drop_status.action == move_on_drop {
		lp.Printf("\x1b[%dm", fg)
	}
	render_box(1+int(sz.WidthCells)-box_width, "Move", &dnd.move_button_region)
	lp.QueueWriteString("\x1b[39m")
	return nil
}
