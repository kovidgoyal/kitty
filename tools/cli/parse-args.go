// License: GPLv3 Copyright: 2022, Kovid Goyal, <kovid at kovidgoyal.net>

package cli

import (
	"fmt"
	"strings"
)

var _ = fmt.Print

func (self *Command) parse_args(ctx *Context, args []string) error {
	args_to_parse := make([]string, 0, len(args))
	copy(args_to_parse, args)
	ctx.SeenCommands = append(ctx.SeenCommands, self)

	var expecting_arg_for *Option
	options_allowed := true

	consume_arg := func() string { ans := args_to_parse[0]; args_to_parse = args_to_parse[1:]; return ans }

	handle_option := func(opt_str string, has_val bool, opt_val string) error {
		opt := self.FindOption(opt_str)
		if opt == nil {
			return &ParseError{Message: fmt.Sprintf("Unknown option: :yellow:`%s`", opt_str)}
		}
		opt.seen_option = opt_str
		if has_val {
			if !opt.needs_argument() {
				return &ParseError{Message: fmt.Sprintf("The option: :yellow:`%s` does not take values", opt_str)}
			}
			return opt.add_value(opt_val)
		} else if opt.needs_argument() {
			expecting_arg_for = opt
		}
		return nil
	}

	for len(self.args) > 0 {
		arg := consume_arg()

		if expecting_arg_for == nil {
			if options_allowed && strings.HasPrefix(arg, "-") && arg != "-" {
				// handle option arg
				if arg == "--" {
					options_allowed = false
					continue
				}
				opt_str := ""
				opt_val := ""
				has_val := false
				if strings.HasPrefix(opt_str, "--") || len(opt_str) == 2 {
					parts := strings.SplitN(arg, "=", 2)
					if len(parts) > 1 {
						has_val = true
						opt_val = parts[1]
					}
					opt_str = parts[0]
					handle_option(opt_str, has_val, opt_val)
				} else {
					for _, sl := range opt_str[1:] {
						err := handle_option("-"+string(sl), false, "")
						if err != nil {
							return err
						}
					}
				}
			} else {
				// handle non option arg
				if self.AllowOptionsAfterArgs <= len(self.args) {
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
				self.args = append(self.args, arg)
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
