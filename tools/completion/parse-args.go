// License: GPLv3 Copyright: 2022, Kovid Goyal, <kovid at kovidgoyal.net>

package completion

import (
	"strings"
)

func (self *Completions) add_group(group *MatchGroup) {
	if len(group.Matches) > 0 {
		self.Groups = append(self.Groups, group)
	}
}

func (self *command) find_option(name_including_leading_dash string) *option {
	q := strings.TrimLeft(name_including_leading_dash, "-")
	for _, opt := range self.options {
		for _, alias := range opt.aliases {
			if alias == q {
				return &opt
			}
		}
	}
	return nil
}

func (self *Completions) add_options_group(options []option, word string) {
	group := MatchGroup{Title: "Options"}
	group.Matches = make([]*Match, 0, 8)
	seen_flags := make(map[string]bool)
	if strings.HasPrefix(word, "--") {
		prefix := word[2:]
		for _, opt := range options {
			for _, q := range opt.aliases {
				if len(q) > 1 && strings.HasPrefix(q, prefix) {
					seen_flags[q] = true
					group.Matches = append(group.Matches, &Match{Word: "--" + q, Description: opt.description})
				}
			}
		}
	} else {
		if word == "-" {
			group.Matches = append(group.Matches, &Match{Word: "--"})
		} else {
			for _, letter := range []rune(word[1:]) {
				seen_flags[string(letter)] = true
			}
		}
		group.WordPrefix = word
		for _, opt := range options {
			for _, q := range opt.aliases {
				if len(q) == 1 && !seen_flags[q] {
					seen_flags[q] = true
					group.Matches = append(group.Matches, &Match{Word: q, FullForm: "-" + q, Description: opt.description})
				}
			}
		}
	}
	self.add_group(&group)
}

func complete_word(word string, completions *Completions, only_args_allowed bool, expecting_arg_for *option, arg_num int) {
	cmd := Completions.current_cmd
	if expecting_arg_for != nil {
		if expecting_arg_for.completion_for_arg != nil {
			expecting_arg_for.completion_for_arg(completions, word)
		}
		return
	}
	if !only_args_allowed && strings.HasPrefix(word, "-") {
		if strings.HasPrefix(word, "--") && strings.Contains(word, "=") {
			idx := strings.Index(word, "=")
			option := cmd.find_option(word[:idx])
			if option != nil {
				if option.completion_for_arg != nil {
					completions.WordPrefix = word[:idx+1]
					option.completion_for_arg(completions, word[idx+1:])
				}
			}
		} else {
			completions.add_options_group(cmd.options, word)
		}
		return
	}
	if arg_num == 1 && len(cmd.subcommands) > 0 {
		for _, sc := range cmd.subcommands {
			if strings.HasPrefix(sc.name, word) {
				title := cmd.subcommands_title
				if title == "" {
					title = "Sub-commands"
				}
				group := MatchGroup{Title: title}
				group.Matches = make([]*Match, 0, len(cmd.subcommands))
				if strings.HasPrefix(sc, word) {
					group.Matches = append(group.Matches, &Match{Word: sc.name, Description: sc.description})
				}
				completions.add_group(&group)
			}
		}
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
		complete_word("", completions, false, nil, 0)
		return
	}

	var expecting_arg_for *option
	only_args_allowed := false
	arg_num := 0

	for i, word := range words {
		cmd = completions.current_cmd
		is_last_word := i == len(words)-1
		if expecting_arg_for == nil && word != "--" {
			arg_num++
		}
		if is_last_word {
			complete_word(word, completions, only_args_allowed, expecting_arg_for, arg_num)
		} else {
			if expecting_arg_for != nil {
				expecting_arg_for = nil
				continue
			}
			if word == "--" {
				only_args_allowed = true
				continue
			}
			if !only_args_allowed && strings.HasPrefix(word, "-") {
				// TODO:
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
