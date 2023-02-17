// License: GPLv3 Copyright: 2023, Kovid Goyal, <kovid at kovidgoyal.net>

package utils

import (
	"bufio"
	"fmt"
	"io"
	"strings"
)

var _ = fmt.Print

func StringToBool(x string) bool {
	x = strings.ToLower(x)
	return x == "y" || x == "yes" || x == "true"
}

func ParseConfData(src io.Reader, callback func(key, val string, line int)) error {
	scanner := bufio.NewScanner(src)
	lnum := 0
	for scanner.Scan() {
		line := strings.TrimLeft(scanner.Text(), " ")
		lnum++
		if line == "" || strings.HasPrefix(line, "#") {
			continue
		}
		key, val, _ := strings.Cut(line, " ")
		callback(key, val, lnum)
	}
	return scanner.Err()
}
