// License: GPLv3 Copyright: 2022, Kovid Goyal, <kovid at kovidgoyal.net>

package utils

import (
	"bufio"
	"errors"
	"fmt"
	"mime"
	"os"
	"path/filepath"
	"strings"
	"sync"
)

var _ = fmt.Print
var user_mime_only_once sync.Once
var user_defined_mime_map map[string]string

func load_mime_file(filename string, mime_map map[string]string) error {
	f, err := os.Open(filename)
	if err != nil {
		return err
	}
	defer f.Close()

	scanner := bufio.NewScanner(f)
	for scanner.Scan() {
		fields := strings.Fields(scanner.Text())
		if len(fields) <= 1 || fields[0][0] == '#' {
			continue
		}
		mime_type := fields[0]
		for _, ext := range fields[1:] {
			if ext[0] == '#' {
				break
			}
			mime_map["."+ext] = mime_type
		}
	}
	if err := scanner.Err(); err != nil {
		return err
	}
	return nil
}

func load_user_mime_maps() {
	conf_path := filepath.Join(ConfigDir(), "mime.types")
	err := load_mime_file(conf_path, user_defined_mime_map)
	if err != nil && !errors.Is(err, os.ErrNotExist) {
		fmt.Fprintln(os.Stderr, "Failed to parse", conf_path, "for MIME types with error:", err)
	}
}

func GuessMimeType(filename string) string {
	user_mime_only_once.Do(load_user_mime_maps)
	ext := filepath.Ext(filename)
	mime_with_parameters := user_defined_mime_map[ext]
	if mime_with_parameters == "" {
		mime_with_parameters = mime.TypeByExtension(ext)
	}
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
