// License: GPLv3 Copyright: 2022, Kovid Goyal, <kovid at kovidgoyal.net>

package tui

import (
	"fmt"
	"github.com/kovidgoyal/datty/tools/cli/markup"
	"strings"
)

var _ = fmt.Print

func RepeatChar(char string, count int) string {
	if count <= 5 {
		return strings.Repeat(char, count)
	}
	return fmt.Sprintf("%s\x1b[%db", char, count-1)
}

func RenderProgressBar(frac float64, width int) string {
	fc := markup.New(true)
	if frac >= 1 {
		return fc.Green(RepeatChar("🬋", width))
	}
	if frac <= 0 {
		return fc.Dim(RepeatChar("🬋", width))
	}
	w := frac * float64(width)
	fl := int(w)
	overhang := w - float64(fl)
	filled := RepeatChar("🬋", fl)
	needs_break := false
	if overhang < 0.2 {
		needs_break = true
	} else if overhang < 0.8 {
		filled += "🬃"
		fl += 1
	} else {
		if fl < width-1 {
			filled += "🬋"
			fl += 1
			needs_break = true
		} else {
			filled += "🬃"
			fl += 1
		}
	}
	ans := fc.Blue(filled)
	unfilled := ""
	ul := 0
	if width > fl && needs_break {
		unfilled = "🬇"
		ul = 1
	}
	filler := width - fl - ul
	if filler > 0 {
		unfilled += RepeatChar("🬋", filler)
	}
	if unfilled != "" {
		ans += fc.Dim(unfilled)
	}
	return ans
}
