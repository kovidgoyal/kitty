// License: GPLv3 Copyright: 2022, Kovid Goyal, <kovid at kovidgoyal.net>

package utils

import (
	"fmt"
	"os"
	"sync"
)

var _ = fmt.Print

var hostname string = "*"

var Hostname = sync.OnceValue(func() string {
	h, err := os.Hostname()
	if err == nil {
		return h
	}
	return ""
})
