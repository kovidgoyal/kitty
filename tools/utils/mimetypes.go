// License: GPLv3 Copyright: 2022, Kovid Goyal, <kovid at kovidgoyal.net>

package utils

import (
	"bufio"
	"errors"
	"fmt"
	"io/fs"
	"mime"
	"os"
	"path/filepath"
	"strings"
	"sync"

	"golang.org/x/sys/unix"
)

var _ = fmt.Print

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

var UserMimeMap = sync.OnceValue(func() map[string]string {
	conf_path := filepath.Join(ConfigDir(), "mime.types")
	ans := make(map[string]string, 32)
	err := load_mime_file(conf_path, ans)
	if err != nil && !errors.Is(err, fs.ErrNotExist) {
		fmt.Fprintln(os.Stderr, "Failed to parse", conf_path, "for MIME types with error:", err)
	}
	return ans
})

func is_special_file(path string) string {
	name := filepath.Base(path)
	lname := strings.ToLower(name)
	if lname == "makefile" || strings.HasPrefix(lname, "makefile.") {
		return "text/makefile"
	}
	if strings.HasSuffix(name, "rc") && !strings.Contains(name, ".") {
		return "text/plain"
	}
	return ""
}

func GuessMimeType(filename string) string {
	ext := filepath.Ext(filename)
	mime_with_parameters := UserMimeMap()[ext]
	if mime_with_parameters == "" {
		mime_with_parameters = mime.TypeByExtension(ext)
	}
	if mime_with_parameters == "" {
		only_once.Do(set_builtins)
		mime_with_parameters = builtin_types_map[ext]
		if mime_with_parameters == "" {
			lext := strings.ToLower(ext)
			mime_with_parameters = builtin_types_map[lext]
			if mime_with_parameters == "" {
				mime_with_parameters = KnownExtensions[lext]
			}
			if mime_with_parameters == "" {
				mime_with_parameters = is_special_file(filename)
			}
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

func GuessMimeTypeWithFileSystemAccess(filename string) string {
	is_dir, is_exe := false, false
	s, err := os.Stat(filename)
	if err == nil {
		is_dir = s.IsDir()
		if !is_dir && s.Mode().Perm()&0o111 != 0 && unix.Access(filename, unix.X_OK) == nil {
			is_exe = true
		}
	}
	if is_dir {
		return "inode/directory"
	}
	mt := GuessMimeType(filename)
	if mt == "" {
		if is_exe {
			mt = "inode/executable"
		}
	}
	return mt
}
