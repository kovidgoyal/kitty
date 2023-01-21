// License: GPLv3 Copyright: 2022, Kovid Goyal, <kovid at kovidgoyal.net>

package utils

import (
	"fmt"
	"mime"
	"path/filepath"
	"strings"
)

var _ = fmt.Print

func GuessMimeType(filename string) string {
	ext := filepath.Ext(filename)
	mime_with_parameters := mime.TypeByExtension(ext)
	if mime_with_parameters == "" {
		only_once.Do(set_builtins)
		mime_with_parameters = builtin_types_map[ext]
		if mime_with_parameters == "" {
			mime_with_parameters = builtin_types_map[strings.ToLower(ext)]
			if mime_with_parameters == "" {
				return ""
			}
		}
	}
	ans, _, err := mime.ParseMediaType(mime_with_parameters)
	if err != nil {
		return ""
	}
	return ans
}
