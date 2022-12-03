// License: GPLv3 Copyright: 2022, Kovid Goyal, <kovid at kovidgoyal.net>

package utils

import (
	"fmt"
	"mime"
	"path/filepath"
)

var _ = fmt.Print

func GuessMimeType(filename string) string {
	ext := filepath.Ext(filename)
	mime_with_parameters := mime.TypeByExtension(ext)
	if mime_with_parameters == "" {
		return mime_with_parameters
	}
	ans, _, err := mime.ParseMediaType(mime_with_parameters)
	if err != nil {
		return ""
	}
	return ans
}
