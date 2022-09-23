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

func OptionsFromStruct(pointer_to_options_struct any) ([]*Option, error) {
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

func option_from_spec(spec OptionSpec) (*Option, error) {
	ans := Option{
		Help:                       spec.Help,
		values_from_cmdline:        make([]string, 0, 1),
		parsed_values_from_cmdline: make([]any, 0, 1),
	}
	parts := strings.Split(spec.Name, " ")
	ans.Name = camel_case_dest(parts[0])
	ans.Aliases = make([]Alias, len(parts))
	for i, x := range parts {
		ans.Aliases[i] = Alias{NameWithoutHyphens: strings.TrimLeft(x, "-"), IsShort: !strings.HasPrefix(x, "--")}
	}
	if spec.Dest != "" {
		ans.Name = spec.Dest
	}
	ans.Depth = spec.Depth
	if spec.Choices != "" {
		parts := strings.Split(spec.Choices, ",")
		if len(parts) == 1 {
			parts = strings.Split(spec.Choices, " ")
		} else {
			for i, x := range parts {
				parts[i] = strings.TrimSpace(x)
			}
		}
		ans.Choices = parts
		ans.OptionType = StringOption
		if ans.Default == "" {
			ans.Default = parts[0]
		}
	} else {
		switch spec.Type {
		case "choice", "choices":
			ans.OptionType = StringOption
		case "int":
			ans.OptionType = IntegerOption
			ans.Default = "0"
		case "float":
			ans.OptionType = FloatOption
			ans.Default = "0"
		case "count":
			ans.OptionType = CountOption
			ans.Default = "0"
		case "bool-set":
			ans.OptionType = BoolOption
			ans.Default = "false"
		case "bool-reset":
			ans.OptionType = BoolOption
			ans.Default = "true"
			for _, a := range ans.Aliases {
				a.IsUnset = true
			}
		case "list":
			ans.IsList = true
			fallthrough
		case "str", "string", "":
			ans.OptionType = StringOption
		default:
			return nil, fmt.Errorf("Unknown option type: %s", spec.Type)
		}
	}
	if spec.Default != "" {
		ans.Default = spec.Default
	}
	ans.Help = spec.Help
	ans.Hidden = spec.Help == "!"
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

func indent_of_line(x string) int {
	return len(x) - len(strings.TrimLeft(x, " \n\t\v\f"))
}

func prepare_help_text_for_display(raw string) string {
	help := strings.Builder{}
	help.Grow(len(raw) + 256)
	prev_indent := 0
	for _, line := range utils.Splitlines(raw) {
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
			if help.Len() > 0 && !strings.HasSuffix(help.String(), "\n") {
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
	}
	return help.String()
}

func option_from_string(overrides map[string]string, entries ...string) (*Option, error) {
	if mpat == nil {
		mpat = regexp.MustCompile("^([a-z]+)=(.+)")
	}
	spec := OptionSpec{}
	scanner := utils.NewScanLines(entries...)
	in_help := false
	help := strings.Builder{}
	help.Grow(2048)

	if dq, found := overrides["type"]; found {
		spec.Type = dq
	}
	if dq, found := overrides["dest"]; found {
		spec.Dest = dq
	}
	for scanner.Scan() {
		line := scanner.Text()
		if spec.Name == "" {
			if strings.HasPrefix(line, "--") {
				spec.Name = line
			}
		} else if in_help {
			spec.Help += line + "\n"
		} else {
			line = strings.TrimSpace(line)
			matches := mpat.FindStringSubmatch(line)
			if matches == nil {
				continue
			}
			k, v := matches[1], matches[2]
			switch k {
			case "choices":
				spec.Choices = v
			case "default":
				if overrides["default"] == "" {
					spec.Default = v
				}
			case "dest":
				if overrides["dest"] == "" {
					spec.Dest = v
				}
			case "depth":
				depth, err := strconv.ParseInt(v, 0, 0)
				if err != nil {
					return nil, err
				}
				spec.Depth = int(depth)
			case "condition", "completion":
			default:
				return nil, fmt.Errorf("Unknown option metadata key: %s", k)
			case "type":
				spec.Type = v
			}
		}
	}
	return option_from_spec(spec)
}
