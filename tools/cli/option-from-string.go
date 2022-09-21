// License: GPLv3 Copyright: 2022, Kovid Goyal, <kovid at kovidgoyal.net>

package cli

import (
	"fmt"
	"reflect"
	"regexp"
	"strconv"
	"strings"

	"kitty/tools/utils"
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
	return option_from_string(map[string]string{}, entries...)
}

func is_string_slice(f reflect.Value) bool {
	if f.Kind() != reflect.Slice {
		return false
	}
	return f.Type().Elem().Kind() == reflect.String
}

func OptionsFromStruct(pointer_to_options_struct interface{}) ([]*Option, error) {
	val := reflect.ValueOf(pointer_to_options_struct).Elem()
	if val.Kind() != reflect.Struct {
		return nil, fmt.Errorf("Need a pointer to a struct to set option values on")
	}
	ans := make([]*Option, 0, val.NumField())
	for i := 0; i < val.NumField(); i++ {
		f := val.Field(i)
		field_name := val.Type().Field(i).Name
		tag := val.Type().Field(i).Tag
		if utils.Capitalize(field_name) != field_name || !f.CanSet() {
			continue
		}
		typ := "str"
		switch f.Kind() {
		case reflect.Slice:
			if !is_string_slice(f) {
				return nil, fmt.Errorf("The field %s is not a slice of strings", field_name)
			}
			typ = "list"
		case reflect.Int:
			typ = "int"
		case reflect.Float64:
			typ = "float"
		case reflect.Bool:
			typ = "bool-set"
		}
		overrides := map[string]string{"dest": field_name, "type": typ}
		opt, err := option_from_string(overrides, string(tag))
		if err != nil {
			return nil, err
		}
		if opt.OptionType == CountOption && f.Kind() != reflect.Int {
			return nil, fmt.Errorf("The field %s is of count type but in the options struct it does not have type int", field_name)
		}
		ans = append(ans, opt)
	}

	return ans, nil
}

type multi_scan struct {
	entries []string
}

var mpat *regexp.Regexp

func option_from_string(overrides map[string]string, entries ...string) (*Option, error) {
	if mpat == nil {
		mpat = regexp.MustCompile("^([a-z]+)=(.+)")
	}
	ans := Option{
		values_from_cmdline:        make([]string, 0, 1),
		parsed_values_from_cmdline: make([]interface{}, 0, 1),
	}
	scanner := utils.NewScanLines(entries...)
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

	set_type := func(v string) error {
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
			return fmt.Errorf("Unknown option type: %s", v)
		}
		return nil
	}

	if dq, found := overrides["type"]; found {
		err := set_type(dq)
		if err != nil {
			return nil, err
		}
	}
	for scanner.Scan() {
		line := scanner.Text()
		if ans.Aliases == nil {
			if strings.HasPrefix(line, "--") {
				parts := strings.Split(line, " ")
				if dq, found := overrides["dest"]; found {
					ans.Name = camel_case_dest(dq)
				} else {
					ans.Name = camel_case_dest(parts[0])
				}
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
				if dq, found := overrides["dest"]; found {
					ans.Name = camel_case_dest(dq)
				} else {
					ans.Name = camel_case_dest(v)
				}
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
				err := set_type(v)
				if err != nil {
					return nil, err
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
	if ans.Aliases == nil || len(ans.Aliases) == 0 {
		return nil, fmt.Errorf("No --aliases specified for option")
	}
	if ans.Name == "" {
		return nil, fmt.Errorf("No dest specified for option")
	}
	return &ans, nil
}
