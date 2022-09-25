// License: GPLv3 Copyright: 2022, Kovid Goyal, <kovid at kovidgoyal.net>

package cli

import (
	"bufio"
	"bytes"
	"fmt"
	"kitty/tools/utils"
	"os"
	"os/exec"
	"path/filepath"
	"strings"

	"golang.org/x/sys/unix"
)

var _ = fmt.Print

func complete_kitty(completions *Completions, word string, arg_num int) {
	if arg_num > 1 {
		completions.Delegate.NumToRemove = completions.current_cmd.index_of_first_arg + 1 // +1 because the first word is not present in all_words
		completions.Delegate.Command = completions.all_words[completions.current_cmd.index_of_first_arg]
		return
	}
	exes := complete_executables_in_path(word)
	if len(exes) > 0 {
		mg := completions.add_match_group("Executables in PATH")
		for _, exe := range exes {
			mg.add_match(exe)
		}
	}

	if len(word) > 0 {
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

func complete_kitty_override(title string, names []string) CompletionFunc {
	return func(completions *Completions, word string, arg_num int) {
		mg := completions.add_match_group(title)
		mg.NoTrailingSpace = true
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
		mg.NoTrailingSpace = true
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

func complete_themes(completions *Completions, word string, arg_num int) {
	kitty, err := utils.KittyExe()
	if err == nil {
		out, err := exec.Command(kitty, "+runpy", "from kittens.themes.collection import *; print_theme_names()").Output()
		if err == nil {
			mg := completions.add_match_group("Themes")
			scanner := bufio.NewScanner(bytes.NewReader(out))
			for scanner.Scan() {
				theme_name := strings.TrimSpace(scanner.Text())
				if theme_name != "" && strings.HasPrefix(theme_name, word) {
					mg.add_match(theme_name)
				}
			}
		}
	}
}

func completion_for_wrapper(wrapped_cmd string) func(*Command, []string, *Completions) {
	return func(cmd *Command, args []string, completions *Completions) {
		completions.Delegate.NumToRemove = completions.current_word_idx + 1
		completions.Delegate.Command = wrapped_cmd
	}
}
