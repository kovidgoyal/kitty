// License: GPLv3 Copyright: 2022, Kovid Goyal, <kovid at kovidgoyal.net>

package utils

import (
	"bufio"
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

type ScanLines struct {
	entries []string

	scanner *bufio.Scanner
}

func NewScanLines(entries ...string) *ScanLines {
	return &ScanLines{entries: entries}
}

func (self *ScanLines) Scan() bool {
	if self.scanner == nil {
		if len(self.entries) == 0 {
			return false
		}
		self.scanner = bufio.NewScanner(strings.NewReader(self.entries[0]))
		self.entries = self.entries[1:]
		return self.Scan()
	} else {
		if self.scanner.Scan() {
			return true
		}
		self.scanner = nil
		return self.Scan()
	}
}

func (self *ScanLines) Text() string {
	if self.scanner == nil {
		return ""
	}
	return self.scanner.Text()
}

func Splitlines(x string, expected_number_of_lines ...int) (ans []string) {
	if len(expected_number_of_lines) > 0 {
		ans = make([]string, 0, expected_number_of_lines[0])
	} else {
		ans = make([]string, 0, 8)
	}
	scanner := bufio.NewScanner(strings.NewReader(x))
	for scanner.Scan() {
		ans = append(ans, scanner.Text())
	}
	return ans
}
