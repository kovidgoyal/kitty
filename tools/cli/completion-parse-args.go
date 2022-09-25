// License: GPLv3 Copyright: 2022, Kovid Goyal, <kovid at kovidgoyal.net>

package cli

import (
	"fmt"
	"os"
	"strings"
)

var _ = fmt.Print
var _ = os.Getenv

func (self *Completions) add_group(group *MatchGroup) {
	if len(group.Matches) > 0 {
		self.Groups = append(self.Groups, group)
	}
}

func (self *Completions) add_options_group(options []*Option, word string) {
	group := self.add_match_group("Options")
	if strings.HasPrefix(word, "--") {
		if word == "--" {
			group.Matches = append(group.Matches, &Match{Word: "--", Description: "End of options"})
		}
		for _, opt := range options {
			for _, q := range opt.Aliases {
				if strings.HasPrefix(q.String(), word) {
					group.Matches = append(group.Matches, &Match{Word: q.String(), Description: opt.Help})
					break
				}
			}
		}
	} else {
		if word == "-" {
			group.Matches = append(group.Matches, &Match{Word: "--", Description: "End of options"})
			for _, opt := range options {
				has_single_letter_alias := false
				for _, q := range opt.Aliases {
					if q.IsShort {
						group.add_match("-"+q.NameWithoutHyphens, opt.Help)
						has_single_letter_alias = true
						break
					}
				}
				if !has_single_letter_alias {
					for _, q := range opt.Aliases {
						if !q.IsShort {
							group.add_match(q.String(), opt.Help)
							break
						}
					}
				}
			}
		} else {
			runes := []rune(word)
			last_letter := string(runes[len(runes)-1])
			for _, opt := range options {
				for _, q := range opt.Aliases {
					if q.IsShort && q.NameWithoutHyphens == last_letter {
						group.add_match(word, opt.Help)
						return
					}
				}
			}
		}
	}
}

func (self *Command) sub_command_allowed_at(completions *Completions, arg_num int) bool {
	if self.SubCommandMustBeFirst {
		return arg_num == 1 && completions.current_word_idx_in_parent == 1
	}
	return arg_num == 1
}

func complete_word(word string, completions *Completions, only_args_allowed bool, expecting_arg_for *Option, arg_num int) {
	cmd := completions.current_cmd
	if expecting_arg_for != nil {
		if expecting_arg_for.Completer != nil {
			expecting_arg_for.Completer(completions, word, arg_num)
		}
		return
	}
	if !only_args_allowed && strings.HasPrefix(word, "-") {
		if strings.HasPrefix(word, "--") && strings.Contains(word, "=") {
			idx := strings.Index(word, "=")
			option := cmd.FindOption(word[:idx])
			if option != nil {
				if option.Completer != nil {
					option.Completer(completions, word[idx+1:], arg_num)
					completions.add_prefix_to_all_matches(word[:idx+1])
				}
			}
		} else {
			completions.add_options_group(cmd.AllOptions(), word)
		}
		return
	}
	if cmd.HasVisibleSubCommands() && cmd.sub_command_allowed_at(completions, arg_num) {
		for _, cg := range cmd.SubCommandGroups {
			group := completions.add_match_group(cg.Title)
			if group.Title == "" {
				group.Title = "Sub-commands"
			}
			for _, sc := range cg.SubCommands {
				if strings.HasPrefix(sc.Name, word) {
					group.add_match(sc.Name, sc.HelpText)
				}
			}
		}
		if !cmd.SubCommandMustBeFirst && cmd.ArgCompleter != nil {
			cmd.ArgCompleter(completions, word, arg_num)
		}
		return
	}

	if cmd.ArgCompleter != nil {
		cmd.ArgCompleter(completions, word, arg_num)
	}
	return
}

func completion_parse_args(cmd *Command, words []string, completions *Completions) {
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
		completions.current_word_idx_in_parent++
		is_last_word := i == len(words)-1
		is_option_equal := completions.split_on_equals && word == "=" && expecting_arg_for != nil
		if only_args_allowed || (expecting_arg_for == nil && !strings.HasPrefix(word, "-")) {
			if !is_option_equal {
				arg_num++
			}
			if arg_num == 1 {
				cmd.index_of_first_arg = completions.current_word_idx
			}
		}
		if is_last_word {
			if is_option_equal {
				word = ""
			}
			complete_word(word, completions, only_args_allowed, expecting_arg_for, arg_num)
		} else {
			if expecting_arg_for != nil {
				if is_option_equal {
					continue
				}
				expecting_arg_for = nil
				continue
			}
			if word == "--" {
				only_args_allowed = true
				continue
			}
			if !only_args_allowed && strings.HasPrefix(word, "-") {
				if !strings.Contains(word, "=") {
					option := cmd.FindOption(word)
					if option != nil && option.needs_argument() {
						expecting_arg_for = option
					}
				}
				continue
			}
			if cmd.HasVisibleSubCommands() && cmd.sub_command_allowed_at(completions, arg_num) {
				sc := cmd.FindSubCommand(word)
				if sc == nil {
					only_args_allowed = true
					continue
				}
				completions.current_cmd = sc
				cmd = sc
				arg_num = 0
				completions.current_word_idx_in_parent = 0
				only_args_allowed = false
				if cmd.ParseArgsForCompletion != nil {
					cmd.ParseArgsForCompletion(cmd, words[i+1:], completions)
					return
				}
			} else if cmd.StopCompletingAtArg > 0 && arg_num >= cmd.StopCompletingAtArg {
				return
			} else {
				only_args_allowed = true
				continue
			}
		}
	}
}
