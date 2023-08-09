// License: GPLv3 Copyright: 2023, Kovid Goyal, <kovid at kovidgoyal.net>

package utils

import (
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"sync"

	"golang.org/x/sys/unix"
)

var _ = fmt.Print

var DefaultExeSearchPaths = sync.OnceValue(func() []string {
	candidates := [...]string{"/usr/local/bin", "/opt/bin", "/opt/homebrew/bin", "/usr/bin", "/bin", "/usr/sbin", "/sbin"}
	ans := make([]string, 0, len(candidates))
	for _, x := range candidates {
		if s, err := os.Stat(x); err == nil && s.IsDir() {
			ans = append(ans, x)
		}
	}
	return ans
})

func Which(cmd string, paths ...string) string {
	if strings.Contains(cmd, string(os.PathSeparator)) {
		return ""
	}
	if len(paths) == 0 {
		path := os.Getenv("PATH")
		if path == "" {
			return ""
		}
		paths = strings.Split(path, string(os.PathListSeparator))
	}
	for _, dir := range paths {
		q := filepath.Join(dir, cmd)
		if unix.Access(q, unix.X_OK) == nil {
			s, err := os.Stat(q)
			if err == nil && !s.IsDir() {
				return q
			}
		}

	}
	return ""
}

func FindExe(name string) string {
	ans := Which(name)
	if ans != "" {
		return ans
	}
	ans = Which(name, DefaultExeSearchPaths()...)
	if ans == "" {
		ans = name
	}
	return ans
}
