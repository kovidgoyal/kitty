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
	if arg_num > 1 {
		return
	}
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
		}, "")
	}
}

func complete_kitty_override(title string, names []string) completion_func {
	return func(completions *Completions, word string, arg_num int) {
		mg := completions.add_match_group(title)
		for _, q := range names {
			if strings.HasPrefix(q, word) {
				mg.add_match(q + "=")
			}
		}
	}
}

func complete_kitty_listen_on(completions *Completions, word string, arg_num int) {
	if !strings.Contains(word, ":") {
		mg := completions.add_match_group("Address family")
		for _, q := range []string{"unix:", "tcp:"} {
			if strings.HasPrefix(q, word) {
				mg.add_match(q)
			}
		}
	} else if strings.HasPrefix(word, "unix:") && !strings.HasPrefix(word, "unix:@") {
		fnmatch_completer("UNIX sockets", CWD, "*")(completions, word[len("unix:"):], arg_num)
		completions.add_prefix_to_all_matches("unix:")
	}
}

func complete_plus_launch(completions *Completions, word string, arg_num int) {
	if arg_num == 1 {
		fnmatch_completer("Python scripts", CWD, "*.py")(completions, word, arg_num)
		if strings.HasPrefix(word, ":") {
			exes := complete_executables_in_path(word[1:])
			mg := completions.add_match_group("Python scripts in PATH")
			for _, exe := range exes {
				mg.add_match(":" + exe)
			}
		}
	} else {
		fnmatch_completer("Files", CWD, "*")(completions, word, arg_num)
	}
}

func complete_plus_runpy(completions *Completions, word string, arg_num int) {
	if arg_num > 1 {
		fnmatch_completer("Files", CWD, "*")(completions, word, arg_num)
	}
}

func complete_plus_open(completions *Completions, word string, arg_num int) {
	fnmatch_completer("Files", CWD, "*")(completions, word, arg_num)
}
