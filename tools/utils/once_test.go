// License: GPLv3 Copyright: 2023, Kovid Goyal, <kovid at kovidgoyal.net>

package utils

import (
	"fmt"
	"testing"
)

var _ = fmt.Print

func TestOnce(t *testing.T) {
	num := 0
	var G = (&Once[string]{Run: func() string {
		num++
		return fmt.Sprintf("%d", num)
	}}).Get
	G()
	G()
	G()
	if num != 1 {
		t.Fatalf("num unexpectedly: %d", num)
	}
}
