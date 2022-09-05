// License: GPLv3 Copyright: 2022, Kovid Goyal, <kovid at kovidgoyal.net>

package completion

import (
	"strings"
)

func complete_word(word string, completions *Completions, only_args_allowed bool, expecting_arg_for *option) {
	cmd := Completions.current_cmd
	if expecting_arg_for != nil {
		if expecting_arg_for.completion_for_arg != nil {
			expecting_arg_for.completion_for_arg(completions, word)
		}
		return
	}
	if !only_args_allowed && strings.HasPrefix(word, "-") {
		// handle single letter multiple options -abcd
		// handle standalone --long-opt
		// handle long opt ends with =
		// handle long opt containing =
		completions.add_options_group(cmd.options, word)
		return
	}
	if cmd.completion_for_arg != nil {
		cmd.completion_for_arg(completions, word)
	}
	return
}

func parse_args(cmd *command, words []string, completions *Completions) {
	completions.current_cmd = cmd
	if len(words) == 0 {
		complete_word("", completions, false, nil)
		return
	}

	var expecting_arg_for *option
	only_args_allowed := false
	arg_num := 0

	for i, word := range words {
		cmd = completions.current_cmd
		is_last_word := i == len(words)-1
		if is_last_word {
			complete_word(word, completions, only_args_allowed, expecting_arg_for)
		} else {
			if expecting_arg_for != nil {
				expecting_arg_for = nil
				continue
			}
			if word == "--" {
				only_args_allowed = true
				continue
			}
			arg_num++
			if !only_args_allowed && strings.HasPrefix(word, "-") {
				// handle single letter multiple options -abcd
				// handle standalone --long-opt
				// handle long opt ends with =
				// handle long opt containing =
				continue
			}
			if len(cmd.subcommands) > 0 && arg_num == 1 {
				sc := cmd.find_subcommand(word)
				if sc == nil {
					only_args_allowed = true
					continue
				}
				completions.current_cmd = sc
				cmd = sc
				arg_num = 0
				only_args_allowed = false
			} else if cmd.stop_processing_at_arg > 0 && arg_num >= cmd.stop_processing_at_arg {
				return
			} else {
				only_args_allowed = true
				continue
			}
		}
	}
}
