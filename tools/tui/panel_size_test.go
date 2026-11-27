// License: GPLv3 Copyright: 2026, Kovid Goyal, <kovid at kovidgoyal.net>

package tui

import (
	"testing"

	"github.com/google/go-cmp/cmp"
)

func TestCenteredPanelArgs(t *testing.T) {
	full := []string{"--edge=center"}
	for size, expected := range map[string][]string{
		"":         full,
		"  ":       full,
		"25 80":    {"--edge=center-sized", "--lines=25", "--columns=80"},
		" 30  100": {"--edge=center-sized", "--lines=30", "--columns=100"},
	} {
		actual, err := CenteredPanelArgs(size)
		if err != nil {
			t.Fatalf("Valid size %#v rejected: %s", size, err)
		}
		if diff := cmp.Diff(expected, actual); diff != "" {
			t.Fatalf("Incorrect args for %#v:\n%s", size, diff)
		}
	}
	for _, size := range []string{"5 80", "25 30", "x 80", "25", "25 80 3", "25 y"} {
		actual, err := CenteredPanelArgs(size)
		if err == nil {
			t.Fatalf("Invalid size %#v accepted", size)
		}
		if diff := cmp.Diff(full, actual); diff != "" {
			t.Fatalf("Invalid size %#v does not give a full screen panel:\n%s", size, diff)
		}
	}
}
