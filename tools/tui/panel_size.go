// License: GPLv3 Copyright: 2026, Kovid Goyal, <kovid at kovidgoyal.net>

package tui

import (
	"fmt"
	"strconv"
	"strings"
)

var _ = fmt.Print

// The minimum size of a centered panel, in cells
const (
	min_panel_lines   = 10
	min_panel_columns = 40
)

// CenteredPanelArgs returns the arguments for the panel kitten to create a
// centered overlay panel of the specified size. The size is of the form:
// lines columns. An empty size means a full screen panel. Returns the
// arguments for a full screen panel and an error if the size is invalid.
func CenteredPanelArgs(size string) (args []string, err error) {
	full_screen := []string{"--edge=center"}
	if size = strings.TrimSpace(size); size == "" {
		return full_screen, nil
	}
	parts := strings.Fields(size)
	if len(parts) != 2 {
		return full_screen, fmt.Errorf("the panel size %#v must be of the form: lines columns", size)
	}
	lines, err := strconv.Atoi(parts[0])
	if err != nil {
		return full_screen, fmt.Errorf("the number of lines in the panel size %#v is invalid: %w", size, err)
	}
	columns, err := strconv.Atoi(parts[1])
	if err != nil {
		return full_screen, fmt.Errorf("the number of columns in the panel size %#v is invalid: %w", size, err)
	}
	if lines < min_panel_lines || columns < min_panel_columns {
		return full_screen, fmt.Errorf("the panel size %#v is too small, it must be at least %d lines and %d columns", size, min_panel_lines, min_panel_columns)
	}
	return []string{"--edge=center-sized", "--lines=" + parts[0], "--columns=" + parts[1]}, nil
}
