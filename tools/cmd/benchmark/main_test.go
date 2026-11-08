// License: GPLv3 Copyright: 2026, Kovid Goyal, <kovid at kovidgoyal.net>

package benchmark

import (
	"strings"
	"testing"

	"github.com/kovidgoyal/kitty/tools/wcswidth"
)

func line_widths(t *testing.T, text string) (widths []int, tabs []int) {
	lines := strings.Split(strings.TrimSuffix(text, "\r\n"), "\r\n")
	for _, line := range lines {
		tab := -1
		if i := strings.IndexByte(line, '\t'); i > -1 {
			tab = wcswidth.Stringwidth(line[:i])
			line = line[:i] + line[i+1:]
		}
		if strings.ContainsAny(line, "\t\r\n") {
			t.Fatalf("Unexpected control characters in line: %q", line)
		}
		widths = append(widths, wcswidth.Stringwidth(line))
		tabs = append(tabs, tab)
	}
	return
}

func TestBenchmarkTextPayloadsAreComparable(t *testing.T) {
	a, acells := ascii_text()
	u, ucells := unicode_text()
	if acells != ucells {
		t.Fatalf("The payloads have different numbers of cells: %d != %d", acells, ucells)
	}
	aw, at := line_widths(t, a)
	uw, ut := line_widths(t, u)
	if len(aw) != num_text_lines || len(uw) != num_text_lines {
		t.Fatalf("Wrong number of lines: %d %d", len(aw), len(uw))
	}
	total := 0
	for i := range aw {
		if aw[i] != uw[i] || at[i] != ut[i] {
			t.Fatalf("Line %d differs: width %d != %d or tab %d != %d", i, aw[i], uw[i], at[i], ut[i])
		}
		total += aw[i]
	}
	if total != acells {
		t.Fatalf("Cell count %d does not match the widths of the lines: %d", acells, total)
	}
	// Every character except spaces and control characters must be non-ASCII,
	// letters with combining marks are allowed to have an ASCII base
	for _, g := range wcswidth.SplitIntoGraphemes(u) {
		switch g {
		case " ", "\t", "\r", "\n", "\r\n":
			continue
		}
		if strings.IndexFunc(g, func(r rune) bool { return r >= 0x80 }) < 0 {
			t.Fatalf("The unicode payload contains the ASCII character: %q", g)
		}
	}
}
