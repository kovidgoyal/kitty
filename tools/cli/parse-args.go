// License: GPLv3 Copyright: 2022, Kovid Goyal, <kovid at kovidgoyal.net>

package cli

import (
	"fmt"
	"strings"
)

var _ = fmt.Print

func (self *Command) parse_args(ctx *Context, args []string) error {
	args_to_parse := make([]string, len(args))
	copy(args_to_parse, args)
	ctx.SeenCommands = append(ctx.SeenCommands, self)

	var expecting_arg_for *Option
	options_allowed := true

	consume_arg := func() string { ans := args_to_parse[0]; args_to_parse = args_to_parse[1:]; return ans }

	handle_option := func(opt_str string, has_val bool, opt_val string, val_not_allowed bool) error {
		possible_options := self.FindOptions(opt_str)
		var opt *Option
		if len(possible_options) == 1 {
			opt = possible_options[0]
			opt_str = opt.MatchingAlias(NormalizeOptionName(opt_str), !strings.HasPrefix(opt_str, "--"))
		} else if len(possible_options) == 0 {
			possibles := self.SuggestionsForOption(opt_str, 2)
			if len(possibles) > 0 {
				return &ParseError{Message: fmt.Sprintf("Unknown option: :yellow:`%s`. Did you mean:\n\t%s", opt_str, strings.Join(possibles, "\n\t"))}
			}
			return &ParseError{Message: fmt.Sprintf("Unknown option: :yellow:`%s`", opt_str)}
		} else {
			ambi := make([]string, len(possible_options))
			for i, o := range possible_options {
				ambi[i] = o.MatchingAlias(NormalizeOptionName(opt_str), !strings.HasPrefix(opt_str, "--"))
			}
			return &ParseError{Message: fmt.Sprintf("Ambiguous option: :yellow:`%s` could be any of: %s", opt_str, strings.Join(ambi, ", "))}
		}
		opt.seen_option = opt_str
		needs_arg := opt.needs_argument()
		if needs_arg && val_not_allowed {
			return &ParseError{Message: fmt.Sprintf("The option : :yellow:`%s` must be followed by a value not another option", opt_str)}
		}
		if has_val {
			if !needs_arg {
				return &ParseError{Message: fmt.Sprintf("The option: :yellow:`%s` does not take values", opt_str)}
			}
			return opt.add_value(opt_val)
		} else if needs_arg {
			expecting_arg_for = opt
		} else {
			opt.add_value("")
		}
		return nil
	}

	for len(args_to_parse) > 0 {
		arg := consume_arg()

		if expecting_arg_for == nil {
			if options_allowed && strings.HasPrefix(arg, "-") && arg != "-" {
				// handle option arg
				if arg == "--" {
					options_allowed = false
					continue
				}
				opt_str := arg
				opt_val := ""
				has_val := false
				if strings.HasPrefix(opt_str, "--") {
					parts := strings.SplitN(arg, "=", 2)
					if len(parts) > 1 {
						has_val = true
						opt_val = parts[1]
					}
					opt_str = parts[0]
					err := handle_option(opt_str, has_val, opt_val, false)
					if err != nil {
						return err
					}
				} else {
					runes := []rune(opt_str[1:])
					for i, sl := range runes {
						err := handle_option("-"+string(sl), false, "", i < len(runes)-1)
						if err != nil {
							return err
						}
					}
				}
			} else {
				// handle non option arg
				if self.AllowOptionsAfterArgs <= len(self.Args) {
					options_allowed = false
				}
				if self.HasSubCommands() {
					sc := self.FindSubCommand(arg)
					if sc == nil {
						if !self.SubCommandIsOptional {
							return &ParseError{Message: fmt.Sprintf(":yellow:`%s` is not a known subcommand for :emph:`%s`. Use --help to get a list of valid subcommands.", arg, self.Name)}
						}
					} else {
						return sc.parse_args(ctx, args_to_parse)
					}
				}
				self.Args = append(self.Args, arg)
			}
		} else {
			// handle option value
			err := expecting_arg_for.add_value(arg)
			if err != nil {
				return err
			}
			expecting_arg_for = nil
		}
	}
	return nil
}
