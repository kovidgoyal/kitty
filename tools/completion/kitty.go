// License: GPLv3 Copyright: 2022, Kovid Goyal, <kovid at kovidgoyal.net>

package completion

import (
	"fmt"
	"os"
	"path/filepath"
	"strings"

	"golang.org/x/sys/unix"
)

var _ = fmt.Print

func complete_kitty(completions *Completions, word string, arg_num int) {
	exes := complete_executables_in_path(word)
	if len(exes) > 0 {
		mg := completions.add_match_group("Executables in PATH")
		for _, exe := range exes {
			mg.add_match(exe)
		}
	}

	if len(word) > 0 && (filepath.IsAbs(word) || strings.HasPrefix(word, "./") || strings.HasPrefix(word, "~")) {
		mg := completions.add_match_group("Executables")
		mg.IsFiles = true

		complete_files(word, func(entry *FileEntry) {
			if entry.is_dir && !entry.is_empty_dir {
				// only allow directories that have sub-dirs or executable files in them
				entries, err := os.ReadDir(entry.abspath)
				if err == nil {
					for _, x := range entries {
						if x.IsDir() || unix.Access(filepath.Join(entry.abspath, x.Name()), unix.X_OK) == nil {
							mg.add_match(entry.completion_candidate)
							break
						}
					}
				}
			} else if unix.Access(entry.abspath, unix.X_OK) == nil {
				mg.add_match(entry.completion_candidate)
			}
		})
	}
}
