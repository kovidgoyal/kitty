// License: GPLv3 Copyright: 2026, Kovid Goyal, <kovid at kovidgoyal.net>

package loop

import (
	"fmt"
	"strconv"
	"strings"
)

var _ = fmt.Print

// TextSizingPartsQuery detects support for drawing part of a character with
// the text sizing protocol, the x, y, c and r keys of SizedText, using the
// method described in the text sizing protocol docs: the cursor position is
// reported before and after drawing one cell of a space that is two cells
// wide.
type TextSizingPartsQuery struct {
	// Whether both replies were received and whether drawing parts is supported
	Done, Supported bool
	first_x         int
	num_replies     int
}

// Query sends the query. The terminal draws a space at the start of the line
// of the cursor, programs should draw over it. The cursor is restored
// afterwards. The replies are delivered to OnEscapeCode, pass them to
// HandleEscapeCode().
func (q *TextSizingPartsQuery) Query(lp *Loop) {
	*q = TextSizingPartsQuery{}
	// The private form of the cursor position report is used, as the reply to
	// the other form can be confused with the F3 key with modifiers
	const report = "\x1b[?6n"
	lp.QueueWriteString("\x1b7\r" + report + SizedTextEscapeCode(" ", SizedText{Width: 2, Part_columns: 1}) + report + "\x1b8")
}

// parse_private_cursor_position_report returns the zero based column in a
// reply to CSI ? 6 n, the CSI escape code without its introducer
func parse_private_cursor_position_report(raw []byte) (x int, ok bool) {
	s := string(raw)
	if !strings.HasPrefix(s, "?") || !strings.HasSuffix(s, "R") {
		return 0, false
	}
	parts := strings.Split(s[1:len(s)-1], ";")
	if len(parts) < 2 {
		return 0, false
	}
	col, err := strconv.Atoi(parts[1])
	if err != nil || col < 1 {
		return 0, false
	}
	return col - 1, true
}

// HandleEscapeCode handles the replies to the query, returning true if the
// escape code was one of them. When it returns true, check Done.
func (q *TextSizingPartsQuery) HandleEscapeCode(etype EscapeCodeType, raw []byte) bool {
	if q.Done || etype != CSI {
		return false
	}
	x, ok := parse_private_cursor_position_report(raw)
	if !ok {
		return false
	}
	q.num_replies++
	if q.num_replies == 1 {
		q.first_x = x
	} else {
		// Terminals that do not support the keys either ignore the escape
		// code, not moving the cursor, or the keys, moving it by two cells
		q.Done, q.Supported = true, x-q.first_x == 1
	}
	return true
}
