// License: GPLv3 Copyright: 2026, Kovid Goyal, <kovid at kovidgoyal.net>

package choose_files

import (
	"strings"
	"unicode/utf8"

	"github.com/kovidgoyal/kitty/tools/utils"
	"github.com/kovidgoyal/kitty/tools/wcswidth"
)

// replace_c1_controls replaces the UTF-8 encoded C1 control characters
// (U+0080 to U+009F) with U+FFFD. Some terminals interpret these as escape
// code introducers, for example U+009B as CSI. Each control is replaced by
// exactly one rune so that rune offsets into the text remain valid.
func replace_c1_controls(text string) string {
	// All C1 controls are encoded as 0xc2 followed by a byte in 0x80-0x9f
	idx := strings.IndexByte(text, 0xc2)
	if idx < 0 {
		return text
	}
	var buf strings.Builder
	for idx > -1 {
		if idx+1 < len(text) && text[idx+1] >= 0x80 && text[idx+1] <= 0x9f {
			if buf.Cap() == 0 {
				buf.Grow(len(text) + 16)
			}
			buf.WriteString(text[:idx])
			buf.WriteRune(utf8.RuneError)
			text = text[idx+2:]
			idx = strings.IndexByte(text, 0xc2)
		} else if n := strings.IndexByte(text[idx+1:], 0xc2); n > -1 {
			idx += n + 1
		} else {
			break
		}
	}
	if buf.Cap() == 0 {
		return text
	}
	buf.WriteString(text)
	return buf.String()
}

// sanitize replaces control codes in untrusted multi-line text, such as file
// contents, before it is written to the terminal. Newlines are preserved.
func sanitize(text string) string {
	return replace_c1_controls(utils.ReplaceControlCodes(text, "    ", "\n"))
}

// sanitize_name replaces control codes, including newlines and tabs, in
// untrusted text that must occupy a single line, such as file names. Every
// control character is replaced by exactly one rune, so rune offsets into the
// original text, such as match positions, remain valid.
func sanitize_name(text string) string {
	return replace_c1_controls(utils.ReplaceControlCodes(text, "␉", "␤"))
}

// keep_only_sgr removes all escape codes other than SGR (formatting) codes
// from a single line of untrusted text, and sanitizes the remaining text.
func keep_only_sgr(text string) string {
	var buf, pending strings.Builder
	buf.Grow(len(text))
	flush := func() {
		if pending.Len() > 0 {
			buf.WriteString(sanitize_name(pending.String()))
			pending.Reset()
		}
	}
	p := wcswidth.EscapeCodeParser{ReplaceInvalidUtf8Bytes: true}
	p.HandleRune = func(ch rune) error {
		pending.WriteRune(ch)
		return nil
	}
	p.HandleCSI = func(data []byte) error {
		if len(data) == 0 || data[len(data)-1] != 'm' {
			return nil
		}
		for _, b := range data[:len(data)-1] {
			if !(b >= '0' && b <= '9') && b != ';' && b != ':' {
				return nil
			}
		}
		flush()
		buf.WriteString("\x1b[")
		buf.Write(data)
		return nil
	}
	if err := p.ParseString(text); err != nil {
		// The callbacks never fail, so this cannot happen, but be safe and
		// drop any escape codes entirely.
		return sanitize_name(wcswidth.StripEscapeCodes(text))
	}
	flush()
	return buf.String()
}
