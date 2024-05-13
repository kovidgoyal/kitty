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

type ScanLines struct {
	entries []string

	scanner *StringScanner
}

func NewScanLines(entries ...string) *ScanLines {
	return &ScanLines{entries: entries}
}

func (self *ScanLines) Scan() bool {
	if self.scanner == nil {
		if len(self.entries) == 0 {
			return false
		}
		self.scanner = NewLineScanner(self.entries[0])
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

type StringScannerScanFunc = func(data string) (remaining_data, token string)
type StringScannerPostprocessFunc = func(token string) string

func ScanFuncForSeparator(sep string) StringScannerScanFunc {
	if len(sep) == 1 {
		sb := sep[0]
		return func(data string) (remaining_data, token string) {
			idx := strings.IndexByte(data, sb)
			if idx < 0 {
				return "", data
			}
			return data[idx+len(sep):], data[:idx]
		}

	}
	return func(data string) (remaining_data, token string) {
		idx := strings.Index(data, sep)
		if idx < 0 {
			return "", data
		}
		return data[idx+len(sep):], data[:idx]
	}
}

// Faster, better designed, zero-allocation version of bufio.Scanner for strings
type StringScanner struct {
	ScanFunc             StringScannerScanFunc
	PostProcessTokenFunc StringScannerPostprocessFunc

	data  string
	token string
}

func (self *StringScanner) Scan() bool {
	if self.data == "" {
		self.token = ""
		return false
	}
	self.data, self.token = self.ScanFunc(self.data)
	if self.PostProcessTokenFunc != nil {
		self.token = self.PostProcessTokenFunc(self.token)
	}
	return true
}

func (self *StringScanner) Err() error { return nil }

func (self *StringScanner) Text() string {
	return self.token
}

func (self *StringScanner) Split(data string, expected_number ...int) (ans []string) {
	if len(expected_number) != 0 {
		ans = make([]string, 0, expected_number[0])
	} else {
		ans = []string{}
	}
	self.data = data
	for self.Scan() {
		ans = append(ans, self.Text())
	}
	return
}

func NewLineScanner(text string) *StringScanner {
	return &StringScanner{
		data: text, ScanFunc: ScanFuncForSeparator("\n"),
		PostProcessTokenFunc: func(s string) string {
			if len(s) > 0 && s[len(s)-1] == '\r' {
				s = s[:len(s)-1]
			}
			return s
		},
	}
}

func NewSeparatorScanner(text, separator string) *StringScanner {
	return &StringScanner{
		data: text, ScanFunc: ScanFuncForSeparator(separator),
	}
}

func Splitlines(x string, expected_number_of_lines ...int) (ans []string) {
	return NewLineScanner("").Split(x, expected_number_of_lines...)
}

// Return a function that can be called sequentially with rune based offsets
// converting them to byte based offsets. The rune offsets must be monotonic,
// otherwise the function returns -1
func RuneOffsetsToByteOffsets(text string) func(int) int {
	self := struct {
		char_offset, byte_offset, last int
		bytes                          []byte
	}{bytes: UnsafeStringToBytes(text)}
	return func(x int) (sz int) {
		switch {
		case x == self.last:
			return self.byte_offset
		case x < self.last:
			return -1
		}
		self.last = x
		x -= self.char_offset
		for x > 0 {
			_, d := utf8.DecodeRune(self.bytes)
			sz += d
			self.bytes = self.bytes[d:]
			x--
			self.char_offset++
		}
		self.byte_offset += sz
		return self.byte_offset
	}
}

func Repr(x any) string { return fmt.Sprintf("%#v", x) }
