// License: GPLv3 Copyright: 2022, Kovid Goyal, <kovid at kovidgoyal.net>

package completion

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
	group := self.add_match_group("Options")
	if strings.HasPrefix(word, "--") {
		if word == "--" {
			group.Matches = append(group.Matches, &Match{Word: "--", Description: "End of options"})
		}
		prefix := word[2:]
		for _, opt := range options {
			for _, q := range opt.Aliases {
				if len(q) > 1 && strings.HasPrefix(q, prefix) {
					group.Matches = append(group.Matches, &Match{Word: "--" + q, Description: opt.Description})
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
					if len(q) == 1 {
						group.add_match("-"+q, opt.Description)
						has_single_letter_alias = true
						break
					}
				}
				if !has_single_letter_alias {
					group.add_match("--"+opt.Aliases[0], opt.Description)
				}
			}
		} else {
			runes := []rune(word)
			last_letter := string(runes[len(runes)-1])
			for _, opt := range options {
				for _, q := range opt.Aliases {
					if q == last_letter {
						group.add_match(word, opt.Description)
						return
					}
				}
			}
		}
	}
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
					option.Completion_for_arg(completions, word[idx+1:], arg_num)
					completions.add_prefix_to_all_matches(word[:idx+1])
				}
			}
		} else {
			completions.add_options_group(cmd.Options, word)
		}
		return
	}
	if cmd.has_subcommands() && cmd.sub_command_allowed_at(completions, arg_num) {
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

func default_parse_args(cmd *Command, words []string, completions *Completions) {
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
		if only_args_allowed || (expecting_arg_for == nil && !strings.HasPrefix(word, "-")) {
			arg_num++
			if arg_num == 1 {
				cmd.index_of_first_arg = completions.current_word_idx
			}
		}
		if is_last_word {
			if completions.split_on_equals && word == "=" {
				word = ""
			}
			complete_word(word, completions, only_args_allowed, expecting_arg_for, arg_num)
		} else {
			if expecting_arg_for != nil {
				if completions.split_on_equals && word == "=" {
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
					option := cmd.find_option(word)
					if option != nil && option.Has_following_arg {
						expecting_arg_for = option
					}
				}
				continue
			}
			if cmd.has_subcommands() && cmd.sub_command_allowed_at(completions, arg_num) {
				sc := cmd.find_subcommand_with_name(word)
				if sc == nil {
					only_args_allowed = true
					continue
				}
				completions.current_cmd = sc
				cmd = sc
				arg_num = 0
				completions.current_word_idx_in_parent = 0
				only_args_allowed = false
				if cmd.Parse_args != nil {
					cmd.Parse_args(cmd, words[i+1:], completions)
					return
				}
			} else if cmd.Stop_processing_at_arg > 0 && arg_num >= cmd.Stop_processing_at_arg {
				return
			} else {
				only_args_allowed = true
				continue
			}
		}
	}
}
