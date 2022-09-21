// License: GPLv3 Copyright: 2022, Kovid Goyal, <kovid at kovidgoyal.net>

package cli

import (
	"bufio"
	"fmt"
	"kitty/tools/utils"
	"regexp"
	"strconv"
	"strings"
)

var _ = fmt.Print

func camel_case_dest(x string) string {
	x = strings.ReplaceAll(strings.ReplaceAll(x, "-", "_"), ",", "")
	parts := strings.Split(x, "_")
	for i, p := range parts {
		parts[i] = utils.Capitalize(p)
	}
	return strings.Join(parts, "")
}

/*
Create an [Option] from a string. Syntax is:

	--option-name, --option-alias, -s
	type: string
	dest: destination
	choices: choice1, choice2, choice 3
	depth: 0
	Help text on multiple lines. Indented lines are preserved as indented blocks. Blank lines
	are preserved as blank lines. #placeholder_for_formatting# is replaced by the empty string.

Available types are: string, str, list, int, float, count, bool-set, bool-reset, choices
The default dest is the first --option-name which must be a long option. The destination is automatically CamelCased from snake_case.
If choices are specified type is set to choices automatically.
If depth is negative option is added to all subcommands. If depth is positive option is added to sub-commands upto
the specified depth.
Set the help text to "!" to have an option hidden.
*/
func OptionFromString(entries ...string) (*Option, error) {
	if mpat == nil {
		mpat = regexp.MustCompile("^([a-z]+)=(.+)")
	}
	ans := Option{
		values_from_cmdline:        make([]string, 0, 1),
		parsed_values_from_cmdline: make([]interface{}, 0, 1),
	}
	scanner := bufio.NewScanner(strings.NewReader(strings.Join(entries, "\n")))
	in_help := false
	prev_indent := 0
	help := strings.Builder{}
	help.Grow(2048)
	default_was_set := false

	indent_of_line := func(x string) int {
		return len(x) - len(strings.TrimLeft(x, " \n\t\v\f"))
	}

	set_default := func(x string) {
		if !default_was_set {
			ans.Default = x
			default_was_set = true
		}
	}

	for scanner.Scan() {
		line := scanner.Text()
		if ans.Aliases == nil {
			if strings.HasPrefix(line, "--") {
				parts := strings.Split(line, " ")
				ans.Name = camel_case_dest(parts[0])
				ans.Aliases = make([]Alias, 0, len(parts))
				for i, x := range parts {
					ans.Aliases[i] = Alias{NameWithoutHyphens: strings.TrimLeft(x, "-"), IsShort: !strings.HasPrefix(x, "--")}
				}
			}
		} else if in_help {
			if line != "" {
				current_indent := indent_of_line(line)
				if current_indent > 1 {
					if prev_indent == 0 {
						help.WriteString("\n")
					} else {
						line = strings.TrimSpace(line)
					}
				}
				prev_indent = current_indent
				if !strings.HasSuffix(help.String(), "\n") {
					help.WriteString(" ")
				}
				help.WriteString(line)
			} else {
				prev_indent = 0
				help.WriteString("\n")
				if !strings.HasSuffix(help.String(), "::") {
					help.WriteString("\n")
				}
			}
		} else {
			matches := mpat.FindStringSubmatch(line)
			if matches == nil {
				continue
			}
			k, v := matches[1], matches[2]
			switch k {
			case "choices":
				parts := strings.Split(v, ",")
				ans.Choices = make(map[string]bool, len(parts))
				ans.OptionType = StringOption
				for i, x := range parts {
					x = strings.TrimSpace(x)
					ans.Choices[x] = true
					if i == 0 && ans.Default == "" {
						ans.Default = x
					}
				}
			case "default":
				ans.Default = v
			case "dest":
				ans.Name = camel_case_dest(v)
			case "depth":
				depth, err := strconv.ParseInt(v, 0, 0)
				if err != nil {
					return nil, err
				}
				ans.Depth = int(depth)
			case "condition", "completion":
			default:
				return nil, fmt.Errorf("Unknown option metadata key: %s", k)
			case "type":
				switch v {
				case "choice", "choices":
					ans.OptionType = StringOption
				case "int":
					ans.OptionType = IntegerOption
					set_default("0")
				case "float":
					ans.OptionType = FloatOption
					set_default("0")
				case "count":
					ans.OptionType = CountOption
					set_default("0")
				case "bool-set":
					ans.OptionType = BoolOption
					set_default("false")
				case "bool-reset":
					ans.OptionType = BoolOption
					set_default("true")
					for _, a := range ans.Aliases {
						a.IsUnset = true
					}
				case "list":
					ans.IsList = true
					fallthrough
				case "str", "string":
					ans.OptionType = StringOption
				default:
					return nil, fmt.Errorf("Unknown option type: %s", v)
				}
			}
		}
	}
	ans.HelpText = help.String()
	ans.Hidden = ans.HelpText == "!"
	pval, err := ans.parse_value(ans.Default)
	if err != nil {
		return nil, err
	}
	ans.parsed_default = pval
	if ans.IsList {
		ans.parsed_default = []string{}
	}
	return &ans, nil
}
