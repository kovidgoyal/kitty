// License: GPLv3 Copyright: 2022, Kovid Goyal, <kovid at kovidgoyal.net>

package completion

import (
	"fmt"
	"strings"
)

var _ = fmt.Print

func (self *Completions) add_group(group *MatchGroup) {
	if len(group.Matches) > 0 {
		self.Groups = append(self.Groups, group)
	}
}

func (self *Command) find_option(name_including_leading_dash string) *Option {
	var q string
	if strings.HasPrefix(name_including_leading_dash, "--") {
		q = name_including_leading_dash[2:]
	} else if strings.HasPrefix(name_including_leading_dash, "-") {
		q = name_including_leading_dash[len(name_including_leading_dash)-1:]
	} else {
		q = name_including_leading_dash
	}
	for _, opt := range self.Options {
		for _, alias := range opt.Aliases {
			if alias == q {
				return opt
			}
		}
	}
	return nil
}

func (self *Completions) add_options_group(options []*Option, word string) {
	group := MatchGroup{Title: "Options"}
	group.Matches = make([]*Match, 0, 8)
	seen_flags := make(map[string]bool)
	if strings.HasPrefix(word, "--") {
		prefix := word[2:]
		for _, opt := range options {
			for _, q := range opt.Aliases {
				if len(q) > 1 && strings.HasPrefix(q, prefix) {
					seen_flags[q] = true
					group.Matches = append(group.Matches, &Match{Word: "--" + q, Description: opt.Description})
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
			for _, q := range opt.Aliases {
				if len(q) == 1 && !seen_flags[q] {
					seen_flags[q] = true
					group.add_match(q, opt.Description).FullForm = "-" + q
				}
			}
		}
	}
	self.add_group(&group)
}

func complete_word(word string, completions *Completions, only_args_allowed bool, expecting_arg_for *Option, arg_num int) {
	cmd := completions.current_cmd
	if expecting_arg_for != nil {
		if expecting_arg_for.Completion_for_arg != nil {
			expecting_arg_for.Completion_for_arg(completions, word, arg_num)
		}
		return
	}
	if !only_args_allowed && strings.HasPrefix(word, "-") {
		if strings.HasPrefix(word, "--") && strings.Contains(word, "=") {
			idx := strings.Index(word, "=")
			option := cmd.find_option(word[:idx])
			if option != nil {
				if option.Completion_for_arg != nil {
					completions.WordPrefix = word[:idx+1]
					option.Completion_for_arg(completions, word[idx+1:], arg_num)
				}
			}
		} else {
			completions.add_options_group(cmd.Options, word)
		}
		return
	}
	if arg_num == 1 && cmd.has_subcommands() {
		for _, cg := range cmd.Groups {
			group := completions.add_match_group(cg.Title)
			if group.Title == "" {
				group.Title = "Sub-commands"
			}
			for _, sc := range cg.Commands {
				if strings.HasPrefix(sc.Name, word) {
					group.add_match(sc.Name, sc.Description)
				}
			}
		}
		if cmd.First_arg_may_not_be_subcommand && cmd.Completion_for_arg != nil {
			cmd.Completion_for_arg(completions, word, arg_num)
		}
		return
	}

	if cmd.Completion_for_arg != nil {
		cmd.Completion_for_arg(completions, word, arg_num)
	}
	return
}

func (cmd *Command) parse_args(words []string, completions *Completions) {
	completions.current_cmd = cmd
	if len(words) == 0 {
		complete_word("", completions, false, nil, 0)
		return
	}
	completions.all_words = words

	var expecting_arg_for *Option
	only_args_allowed := false
	arg_num := 0

	for i, word := range words {
		cmd = completions.current_cmd
		completions.current_word_idx = i
		is_last_word := i == len(words)-1
		if expecting_arg_for == nil && !strings.HasPrefix(word, "-") {
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
				idx := strings.Index(word, "=")
				if idx > -1 {
					continue
				}
				option := cmd.find_option(word[:idx])
				if option != nil && option.Has_following_arg {
					expecting_arg_for = option
				}
				continue
			}
			if cmd.has_subcommands() && arg_num == 1 {
				sc := cmd.find_subcommand_with_name(word)
				if sc == nil {
					only_args_allowed = true
					continue
				}
				completions.current_cmd = sc
				cmd = sc
				arg_num = 0
				only_args_allowed = false
			} else if cmd.Stop_processing_at_arg > 0 && arg_num >= cmd.Stop_processing_at_arg {
				return
			} else {
				only_args_allowed = true
				continue
			}
		}
	}
}
