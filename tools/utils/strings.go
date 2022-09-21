// License: GPLv3 Copyright: 2022, Kovid Goyal, <kovid at kovidgoyal.net>

package utils

import (
	"fmt"
	"strings"
	"unicode/utf8"
)

var _ = fmt.Print

func Capitalize(x string) string {
	if x == "" {
		return x
	}
	s, sz := utf8.DecodeRuneInString(x)
	cr := strings.ToUpper(string(s))
	return cr + x[sz:]
}
