// License: GPLv3 Copyright: 2022, Kovid Goyal, <kovid at kovidgoyal.net>

package cli

import (
	"fmt"
	"slices"
	"strconv"
	"strings"
)

var _ = fmt.Print

type OptionType int

const (
	StringOption OptionType = iota
	IntegerOption
	FloatOption
	BoolOption
	CountOption
)

type Alias struct {
	NameWithoutHyphens string
	IsShort            bool
	IsUnset            bool
}

func (self *Alias) String() string {
	if self.IsShort {
		return "-" + self.NameWithoutHyphens
	}
	return "--" + self.NameWithoutHyphens
}

type OptionSpec struct {
	Name      string
	Type      string
	Dest      string
	Choices   string
	Depth     int
	Default   string
	Help      string
	Completer CompletionFunc
}

type Option struct {
	Name       string
	Aliases    []Alias
	Choices    []string
	Default    string
	OptionType OptionType
	Hidden     bool
	Depth      int
	Help       string
	IsList     bool
	Parent     *Command
	Completer  CompletionFunc

	values_from_cmdline        []string
	parsed_values_from_cmdline []any
	parsed_default             any
	seen_option                string
}

func (self *Option) reset() {
	self.values_from_cmdline = self.values_from_cmdline[:0]
	self.parsed_values_from_cmdline = self.parsed_values_from_cmdline[:0]
	self.seen_option = ""
}

func (self *Option) needs_argument() bool {
	return self.OptionType != BoolOption && self.OptionType != CountOption
}

func (self *Option) MatchingAlias(prefix_without_hyphens string, is_short bool) string {
	for _, a := range self.Aliases {
		if a.IsShort == is_short && strings.HasPrefix(a.NameWithoutHyphens, prefix_without_hyphens) {
			return a.String()
		}
	}
	return ""
}

func (self *Option) HasAlias(name_without_hyphens string, is_short bool) bool {
	for _, a := range self.Aliases {
		if a.IsShort == is_short && a.NameWithoutHyphens == name_without_hyphens {
			return true
		}
	}
	return false
}

type ParseError struct {
	Option  *Option
	Message string
}

func (self *ParseError) Error() string { return self.Message }

func NormalizeOptionName(name string) string {
	return strings.ReplaceAll(strings.TrimLeft(name, "-"), "_", "-")
}

func (self *Option) parsed_value() any {
	if len(self.values_from_cmdline) == 0 {
		if self.IsList {
			if self.parsed_default == nil {
				return []string{}
			}
		}
		return self.parsed_default
	}
	switch self.OptionType {
	case CountOption:
		return len(self.parsed_values_from_cmdline)
	case StringOption:
		if self.IsList {
			ans := make([]string, 0, len(self.parsed_values_from_cmdline)+2)
			if self.parsed_default != nil {
				ans = append(ans, self.parsed_default.([]string)...)
			}
			for _, x := range self.parsed_values_from_cmdline {
				ans = append(ans, x.(string))
			}
			return ans
		}
		fallthrough
	default:
		return self.parsed_values_from_cmdline[len(self.parsed_values_from_cmdline)-1]
	}
}

func (self *Option) parse_value(val string) (any, error) {
	switch self.OptionType {
	case BoolOption:
		switch val {
		case "y", "yes", "true":
			return true, nil
		case "n", "no", "false":
			return false, nil
		default:
			return nil, &ParseError{Option: self, Message: fmt.Sprintf(":yellow:`%s` is not a valid value for :bold:`%s`.", val, self.seen_option)}
		}
	case StringOption:
		return val, nil
	case IntegerOption, CountOption:
		pval, err := strconv.ParseInt(val, 0, 0)
		if err != nil {
			return nil, &ParseError{Option: self, Message: fmt.Sprintf(
				":yellow:`%s` is not a valid number for :bold:`%s`. Only integers in decimal, hexadecimal, binary or octal notation are accepted.", val, self.seen_option)}
		}
		return int(pval), nil
	case FloatOption:
		pval, err := strconv.ParseFloat(val, 64)
		if err != nil {
			return nil, &ParseError{Option: self, Message: fmt.Sprintf(
				":yellow:`%s` is not a valid number for :bold:`%s`. Only floats in decimal and hexadecimal notation are accepted.", val, self.seen_option)}
		}
		return pval, nil
	default:
		return nil, &ParseError{Option: self, Message: fmt.Sprintf("Unknown option type for %s", self.Name)}
	}
}

func (self *Option) add_value(val string) error {
	name_without_hyphens := NormalizeOptionName(self.seen_option)
	switch self.OptionType {
	case BoolOption:
		if val == "" {
			for _, x := range self.Aliases {
				if x.NameWithoutHyphens == name_without_hyphens {
					if x.IsUnset {
						self.values_from_cmdline = append(self.values_from_cmdline, "false")
						self.parsed_values_from_cmdline = append(self.parsed_values_from_cmdline, false)
					} else {
						self.values_from_cmdline = append(self.values_from_cmdline, "true")
						self.parsed_values_from_cmdline = append(self.parsed_values_from_cmdline, true)
					}
					return nil
				}
			}
		} else {
			switch val {
			case "y", "yes", "true":
				self.values_from_cmdline = append(self.values_from_cmdline, "true")
				self.parsed_values_from_cmdline = append(self.parsed_values_from_cmdline, true)
			case "n", "no", "false":
				self.values_from_cmdline = append(self.values_from_cmdline, "false")
				self.parsed_values_from_cmdline = append(self.parsed_values_from_cmdline, false)
			default:
				return &ParseError{Option: self, Message: fmt.Sprintf(":yellow:`%s` is not a valid value for :bold:`%s`. Valid values: %s",
					val, self.seen_option, "y, yes, true, n, no and false",
				)}

			}
		}
	case StringOption:
		if self.Choices != nil && !slices.Contains(self.Choices, val) {
			return &ParseError{Option: self, Message: fmt.Sprintf(":yellow:`%s` is not a valid value for :bold:`%s`. Valid values: %s",
				val, self.seen_option, strings.Join(self.Choices, ", "),
			)}
		}
		self.values_from_cmdline = append(self.values_from_cmdline, val)
		self.parsed_values_from_cmdline = append(self.parsed_values_from_cmdline, val)
	case IntegerOption, FloatOption:
		pval, err := self.parse_value(val)
		if err != nil {
			return err
		}
		self.values_from_cmdline = append(self.values_from_cmdline, val)
		self.parsed_values_from_cmdline = append(self.parsed_values_from_cmdline, pval)
	case CountOption:
		self.values_from_cmdline = append(self.values_from_cmdline, val)
		self.parsed_values_from_cmdline = append(self.parsed_values_from_cmdline, 1)
	}
	return nil
}
