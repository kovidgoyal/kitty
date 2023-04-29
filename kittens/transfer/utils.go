// License: GPLv3 Copyright: 2023, Kovid Goyal, <kovid at kovidgoyal.net>

package transfer

import (
	"crypto/rand"
	"crypto/sha256"
	"encoding/hex"
	"fmt"
	"os"
	"path/filepath"
	"strings"

	"kitty/tools/utils"
)

var _ = fmt.Print

var global_cwd, global_home string

func cwd_path() string {
	if global_cwd == "" {
		ans, _ := os.Getwd()
		return ans
	}
	return global_cwd
}

func home_path() string {
	if global_home == "" {
		return utils.Expanduser("~")
	}
	return global_home
}

func encode_bypass(request_id string, bypass string) string {
	q := request_id + ";" + bypass
	sum := sha256.Sum256(utils.UnsafeStringToBytes(q))
	return fmt.Sprintf("%x", sum)
}

func abspath(path string, use_home ...bool) string {
	if filepath.IsAbs(path) {
		return path
	}
	var base string
	if len(use_home) > 0 && use_home[0] {
		base = home_path()
	} else {
		base = cwd_path()
	}
	return filepath.Join(base, path)
}

func expand_home(path string) string {
	if strings.HasPrefix(path, "~"+string(os.PathSeparator)) {
		path = strings.TrimLeft(path[2:], string(os.PathSeparator))
		path = filepath.Join(home_path(), path)
	} else if path == "~" {
		path = home_path()
	}
	return path
}

func random_id() string {
	bytes := []byte{0, 0}
	rand.Read(bytes)
	return fmt.Sprintf("%x%s", os.Getpid(), hex.EncodeToString(bytes))
}

func run_with_paths(cwd, home string, f func()) {
	global_cwd, global_home = cwd, home
	defer func() { global_cwd, global_home = "", "" }()
	f()
}

func should_be_compressed(path string) bool {
	ext := strings.ToLower(filepath.Ext(path))
	if ext != "" {
		switch ext[1:] {
		case "zip", "odt", "odp", "pptx", "docx", "gz", "bz2", "xz", "svgz":
			return false
		}
	}
	mt := utils.GuessMimeType(path)
	if strings.HasSuffix(mt, "+zip") || (strings.HasPrefix(mt, "image/") && mt != "image/svg+xml") || strings.HasPrefix(mt, "video/") {
		return false
	}
	return true
}
