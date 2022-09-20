// License: GPLv3 Copyright: 2022, Kovid Goyal, <kovid at kovidgoyal.net>

package cli

import (
	"fmt"
	"os"
	"reflect"
	"regexp"
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

type Option struct {
	Name       string
	Aliases    []Alias
	Choices    map[string]bool
	Default    string
	OptionType OptionType
	Hidden     bool
	Depth      int
	HelpText   string
	IsList     bool
	Parent     *Command

	values_from_cmdline        []string
	parsed_values_from_cmdline []interface{}
	parsed_default             interface{}
	seen_option                string
}

func (self *Option) needs_argument() bool {
	return self.OptionType != BoolOption && self.OptionType != CountOption
}

func (self *Option) HasAlias(name_without_hyphens string, is_short bool) bool {
	for _, a := range self.Aliases {
		if a.IsShort == is_short && a.NameWithoutHyphens == name_without_hyphens {
			return true
		}
	}
	return false
}

var mpat *regexp.Regexp

type ParseError struct {
	Option  *Option
	Message string
}

func (self *ParseError) Error() string { return self.Message }

func NormalizeOptionName(name string) string {
	return strings.ReplaceAll(strings.TrimLeft(name, "-"), "_", "-")
}

func (self *Option) parsed_value() interface{} {
	if len(self.values_from_cmdline) == 0 {
		return self.parsed_default
	}
	switch self.OptionType {
	case CountOption:
		return len(self.parsed_values_from_cmdline)
	case StringOption:
		if self.IsList {
			return self.parsed_values_from_cmdline
		}
		fallthrough
	default:
		return self.parsed_values_from_cmdline[len(self.parsed_values_from_cmdline)-1]
	}
}

func (self *Option) parse_value(val string) (interface{}, error) {
	switch self.OptionType {
	case BoolOption:
		switch val {
		case "true":
			return true, nil
		case "false":
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
		return pval, nil
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
	case StringOption:
		if self.Choices != nil && !self.Choices[val] {
			c := make([]string, len(self.Choices))
			for k := range self.Choices {
				c = append(c, k)
			}
			return &ParseError{Option: self, Message: fmt.Sprintf(":yellow:`%s` is not a valid value for :bold:`%s`. Valid values: %s",
				val, self.seen_option, strings.Join(c, ", "),
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

type CommandGroup struct {
	SubCommands []*Command
	Title       string
}

func (self *CommandGroup) Clone(parent *Command) *CommandGroup {
	ans := CommandGroup{Title: self.Title, SubCommands: make([]*Command, 0, len(self.SubCommands))}
	for i, o := range self.SubCommands {
		self.SubCommands[i] = o.Clone(parent)
	}
	return &ans
}

func (self *CommandGroup) AddSubCommand(parent *Command, name string) (*Command, error) {
	for _, c := range self.SubCommands {
		if c.Name == name {
			return nil, fmt.Errorf("A subcommand with the name %#v already exists in the parent command: %#v", name, parent.Name)
		}
	}
	ans := NewRootCommand()
	ans.Parent = parent
	self.SubCommands = append(self.SubCommands, ans)
	return ans, nil
}

func (self *CommandGroup) FindSubCommand(name string) *Command {
	for _, c := range self.SubCommands {
		if c.Name == name {
			return c
		}
	}
	return nil
}

type OptionGroup struct { // {{{
	Options []*Option
	Title   string
}

func (self *OptionGroup) Clone(parent *Command) *OptionGroup {
	ans := OptionGroup{Title: self.Title, Options: make([]*Option, 0, len(self.Options))}
	for i, o := range self.Options {
		c := *o
		c.Parent = parent
		self.Options[i] = &c
	}
	return &ans
}

func (self *OptionGroup) AddOption(parent *Command, items ...string) (*Option, error) {
	ans, err := OptionFromString(items...)
	if err == nil {
		ans.Parent = parent
	}
	return ans, err
}

func (self *OptionGroup) FindOption(name_with_hyphens string) *Option {
	is_short := !strings.HasPrefix(name_with_hyphens, "--")
	option_name := NormalizeOptionName(name_with_hyphens)
	for _, q := range self.Options {
		if q.HasAlias(option_name, is_short) {
			return q
		}
	}
	return nil
}

// }}}

type Command struct {
	Name                  string
	Usage, HelpText       string
	Hidden                bool
	AllowOptionsAfterArgs int
	SubCommandIsOptional  bool

	SubCommandGroups []*CommandGroup
	OptionGroups     []*OptionGroup
	Parent           *Command

	Args []string
}

func (self *Command) Clone(parent *Command) *Command {
	ans := *self
	ans.Args = make([]string, 0, 8)
	ans.Parent = parent
	ans.SubCommandGroups = make([]*CommandGroup, 0, len(self.SubCommandGroups))
	ans.OptionGroups = make([]*OptionGroup, 0, len(self.OptionGroups))

	for i, o := range self.OptionGroups {
		ans.OptionGroups[i] = o.Clone(&ans)
	}
	for i, g := range self.SubCommandGroups {
		ans.SubCommandGroups[i] = g.Clone(&ans)
	}
	return &ans
}

func (self *Command) AddClone(group string, src *Command) (*Command, error) {
	c := src.Clone(self)
	g := self.AddSubCommandGroup(group)
	if g.FindSubCommand(c.Name) != nil {
		return nil, fmt.Errorf("A sub command with the name: %s already exists in %s", c.Name, self.Name)
	}
	g.SubCommands = append(g.SubCommands, c)
	return c, nil
}

func NewRootCommand() *Command {
	ans := Command{
		SubCommandGroups: make([]*CommandGroup, 0, 8),
		OptionGroups:     make([]*OptionGroup, 0, 8),
		Args:             make([]string, 0, 8),
	}
	return &ans
}

func (self *Command) AddSubCommandGroup(title string) *CommandGroup {
	for _, g := range self.SubCommandGroups {
		if g.Title == title {
			return g
		}
	}
	ans := CommandGroup{Title: title, SubCommands: make([]*Command, 0, 8)}
	self.SubCommandGroups = append(self.SubCommandGroups, &ans)
	return &ans
}

func (self *Command) AddSubCommand(group string, name string) (*Command, error) {
	return self.AddSubCommandGroup(group).AddSubCommand(self, name)
}

func (self *Command) ParseArgs(args []string) (*Command, error) {
	if args == nil {
		args = os.Args
	}
	ctx := Context{SeenCommands: make([]*Command, 0, 4)}
	err := self.parse_args(&ctx, args[1:])
	if err != nil {
		return nil, err
	}
	return ctx.SeenCommands[len(ctx.SeenCommands)-1], nil
}

func (self *Command) HasSubCommands() bool {
	for _, g := range self.SubCommandGroups {
		if len(g.SubCommands) > 0 {
			return true
		}
	}
	return false
}

func (self *Command) FindSubCommand(name string) *Command {
	for _, g := range self.SubCommandGroups {
		c := g.FindSubCommand(name)
		if c != nil {
			return c
		}
	}
	return nil
}

func (self *Command) AddOptionGroup(title string) *OptionGroup {
	for _, g := range self.OptionGroups {
		if g.Title == title {
			return g
		}
	}
	ans := OptionGroup{Title: title, Options: make([]*Option, 0, 8)}
	self.OptionGroups = append(self.OptionGroups, &ans)
	return &ans
}

func (self *Command) AddOption(items ...string) (*Option, error) {
	return self.AddOptionGroup("").AddOption(self, items...)
}

func (self *Command) AddOptionToGroup(group string, items ...string) (*Option, error) {
	return self.AddOptionGroup(group).AddOption(self, items...)
}

func (self *Command) FindOption(name_with_hyphens string) *Option {
	for _, g := range self.OptionGroups {
		q := g.FindOption(name_with_hyphens)
		if q != nil {
			return q
		}
	}
	depth := 0
	for p := self.Parent; p != nil; p = p.Parent {
		depth++
		q := p.FindOption(name_with_hyphens)
		if q != nil && q.Depth >= depth {
			return q
		}
	}
	return nil
}

type Context struct {
	SeenCommands []*Command
}

func (self *Command) GetOptionValues(pointer_to_options_struct interface{}) error {
	m := make(map[string]*Option, 128)
	for _, g := range self.OptionGroups {
		for _, o := range g.Options {
			field_name := strings.ReplaceAll(strings.ToUpper(o.Name[:1]+o.Name[1:]), "-", "_")
			m[field_name] = o
		}
	}
	val := reflect.ValueOf(pointer_to_options_struct).Elem()
	if val.Kind() != reflect.Struct {
		return fmt.Errorf("Need a pointer to a struct to set option values on")
	}
	for i := 0; i < val.NumField(); i++ {
		f := val.Field(i)
		field_name := val.Type().Field(i).Name
		if strings.ToUpper(field_name[:1]) != field_name[:1] || !f.CanSet() {
			continue
		}
		opt := m[field_name]
		if opt == nil {
			return fmt.Errorf("No option with the name: %s", field_name)
		}
		switch opt.OptionType {
		case IntegerOption, CountOption:
			if f.Kind() != reflect.Int {
				return fmt.Errorf("The field: %s must be an integer", field_name)
			}
			v := int64(opt.parsed_value().(int))
			if f.OverflowInt(v) {
				return fmt.Errorf("The value: %d is too large for the integer type used for the option: %s", v, field_name)
			}
			f.SetInt(v)
		case FloatOption:
			if f.Kind() != reflect.Float64 {
				return fmt.Errorf("The field: %s must be a float64", field_name)
			}
			v := opt.parsed_value().(float64)
			if f.OverflowFloat(v) {
				return fmt.Errorf("The value: %f is too large for the integer type used for the option: %s", v, field_name)
			}
			f.SetFloat(v)
		case BoolOption:
			if f.Kind() != reflect.Bool {
				return fmt.Errorf("The field: %s must be a boolean", field_name)
			}
			v := opt.parsed_value().(bool)
			f.SetBool(v)
		case StringOption:
			if opt.IsList {
				if f.Kind() != reflect.Slice {
					return fmt.Errorf("The field: %s must be a slice", field_name)
				}
				v := opt.parsed_value().([]string)
				f.Set(reflect.ValueOf(v))
			} else {
				if f.Kind() != reflect.String {
					return fmt.Errorf("The field: %s must be a string", field_name)
				}
				v := opt.parsed_value().(string)
				f.SetString(v)
			}
		}
	}
	return nil
}
