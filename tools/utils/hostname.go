// License: GPLv3 Copyright: 2022, Kovid Goyal, <kovid at kovidgoyal.net>

package utils

import (
	"fmt"
	"os"
)

var _ = fmt.Print

var hostname string = "*"

func CachedHostname() string {
	if hostname == "*" {
		h, err := os.Hostname()
		if err != nil {
			hostname = h
		} else {
			hostname = ""
		}
	}
	return hostname
}
