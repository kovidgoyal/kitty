// License: GPLv3 Copyright: 2022, Kovid Goyal, <kovid at kovidgoyal.net>

package cli

import (
	"fmt"
	"os"
	"path/filepath"
	"reflect"
	"strconv"
	"strings"

	"kitty/tools/utils"

	"golang.org/x/exp/slices"
)

var _ = fmt.Print

// Option {{{
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
	Name    string
	Type    string
	Dest    string
	Choices string
	Depth   int
	Default string
	Help    string
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
		return self.parsed_default
	}
	switch self.OptionType {
	case CountOption:
		return len(self.parsed_values_from_cmdline)
	case StringOption:
		if self.IsList {
			ans := make([]string, len(self.parsed_values_from_cmdline))
			for i, x := range self.parsed_values_from_cmdline {
				ans[i] = x.(string)
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

// }}}

// Groups {{{
type CommandGroup struct {
	SubCommands []*Command
	Title       string
}

func (self *CommandGroup) HasVisibleSubCommands() bool {
	for _, c := range self.SubCommands {
		if !c.Hidden {
			return true
		}
	}
	return false
}

func (self *CommandGroup) Clone(parent *Command) *CommandGroup {
	ans := CommandGroup{Title: self.Title, SubCommands: make([]*Command, 0, len(self.SubCommands))}
	for i, o := range self.SubCommands {
		self.SubCommands[i] = o.Clone(parent)
	}
	return &ans
}

func (self *CommandGroup) AddSubCommand(parent *Command, name string) *Command {
	ans := NewRootCommand()
	ans.Parent = parent
	ans.Name = name
	self.SubCommands = append(self.SubCommands, ans)
	return ans
}

func (self *CommandGroup) FindSubCommand(name string) *Command {
	for _, c := range self.SubCommands {
		if c.Name == name {
			return c
		}
	}
	return nil
}

type OptionGroup struct {
	Options []*Option
	Title   string
}

func (self *OptionGroup) Clone(parent *Command) *OptionGroup {
	ans := OptionGroup{Title: self.Title, Options: make([]*Option, len(self.Options))}
	for i, o := range self.Options {
		c := *o
		c.Parent = parent
		ans.Options[i] = &c
	}
	return &ans
}

func (self *OptionGroup) AddOption(parent *Command, spec OptionSpec) (*Option, error) {
	ans, err := option_from_spec(spec)
	if err == nil {
		ans.Parent = parent
		self.Options = append(self.Options, ans)
	}
	return ans, err
}

func (self *OptionGroup) AddOptionFromString(parent *Command, items ...string) (*Option, error) {
	ans, err := OptionFromString(items...)
	if err == nil {
		ans.Parent = parent
		self.Options = append(self.Options, ans)
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

type Command struct { // {{{
	Name                              string
	Usage, ShortDescription, HelpText string
	Hidden                            bool

	// Number of non-option arguments after which to stop parsing options. 0 means no options after the first non-option arg.
	AllowOptionsAfterArgs int
	// If true does not fail if the first non-option arg is not a sub-command
	SubCommandIsOptional bool

	SubCommandGroups []*CommandGroup
	OptionGroups     []*OptionGroup
	Parent           *Command

	Args []string
	Run  func(cmd *Command, args []string) (int, error)

	option_map map[string]*Option
}

func (self *Command) Clone(parent *Command) *Command {
	ans := *self
	ans.Args = make([]string, 0, 8)
	ans.Parent = parent
	ans.SubCommandGroups = make([]*CommandGroup, len(self.SubCommandGroups))
	ans.OptionGroups = make([]*OptionGroup, len(self.OptionGroups))

	for i, o := range self.OptionGroups {
		ans.OptionGroups[i] = o.Clone(&ans)
	}
	for i, g := range self.SubCommandGroups {
		ans.SubCommandGroups[i] = g.Clone(&ans)
	}
	return &ans
}

func (self *Command) AddClone(group string, src *Command) *Command {
	c := src.Clone(self)
	g := self.AddSubCommandGroup(group)
	g.SubCommands = append(g.SubCommands, c)
	return c
}

func NewRootCommand() *Command {
	ans := Command{
		Name:             filepath.Base(os.Args[0]),
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

func (self *Command) AddSubCommand(group string, name string) *Command {
	return self.AddSubCommandGroup(group).AddSubCommand(self, name)
}

func (self *Command) Validate() error {
	seen_sc := make(map[string]bool)
	for _, g := range self.SubCommandGroups {
		for _, sc := range g.SubCommands {
			if seen_sc[sc.Name] {
				return &ParseError{Message: fmt.Sprintf("The sub-command :yellow:`%s` occurs twice inside %s", sc.Name, self.Name)}
			}
			seen_sc[sc.Name] = true
			err := sc.Validate()
			if err != nil {
				return err
			}
		}
	}
	seen_flags := make(map[string]bool)

	self.option_map = make(map[string]*Option, 128)
	validate_options := func(opt *Option) error {
		if self.option_map[opt.Name] != nil {
			return &ParseError{Message: fmt.Sprintf("The option :yellow:`%s` occurs twice inside %s", opt.Name, self.Name)}
		}
		for _, a := range opt.Aliases {
			q := a.String()
			if seen_flags[q] {
				return &ParseError{Message: fmt.Sprintf("The option :yellow:`%s` occurs twice inside %s", q, self.Name)}
			}
			seen_flags[q] = true
		}
		self.option_map[opt.Name] = opt
		return nil
	}
	err := self.VisitAllOptions(validate_options)
	if err != nil {
		return err
	}

	if self.option_map["Help"] == nil {
		if seen_flags["-h"] || seen_flags["--help"] {
			return &ParseError{Message: fmt.Sprintf("The --help or -h flags are assigned to an option other than Help in %s", self.Name)}
		}
		self.option_map["Help"] = self.Add(OptionSpec{Name: "--help -h", Type: "bool-set", Help: "Show help for this command"})
	}

	if self.Parent == nil && self.option_map["Version"] == nil {
		if seen_flags["--version"] {
			return &ParseError{Message: fmt.Sprintf("The --version flag is assigned to an option other than Version in %s", self.Name)}
		}
		self.option_map["Version"] = self.Add(OptionSpec{Name: "--version", Type: "bool-set", Help: "Show version"})
	}

	return nil
}

func (self *Command) Root() *Command {
	p := self
	for p.Parent != nil {
		p = p.Parent
	}
	return p
}

func (self *Command) CommandStringForUsage() string {
	names := make([]string, 0, 8)
	p := self
	for p != nil {
		if p.Name != "" {
			names = append(names, p.Name)
		}
		p = p.Parent
	}
	return strings.Join(utils.Reverse(names), " ")
}

func (self *Command) ParseArgs(args []string) (*Command, error) {
	for ; self.Parent != nil; self = self.Parent {
	}
	err := self.Validate()
	if err != nil {
		return nil, err
	}
	if args == nil {
		args = os.Args
	}
	if len(args) < 1 {
		return nil, &ParseError{Message: "At least one arg must be supplied"}
	}
	ctx := Context{SeenCommands: make([]*Command, 0, 4)}
	err = self.parse_args(&ctx, args[1:])
	if err != nil {
		return nil, err
	}
	return ctx.SeenCommands[len(ctx.SeenCommands)-1], nil
}

func (self *Command) ResetAfterParseArgs() {
	for _, g := range self.SubCommandGroups {
		for _, sc := range g.SubCommands {
			sc.ResetAfterParseArgs()
		}
	}

	for _, g := range self.OptionGroups {
		for _, o := range g.Options {
			o.reset()
		}
	}
	self.Args = make([]string, 0, 8)
}

func (self *Command) HasSubCommands() bool {
	for _, g := range self.SubCommandGroups {
		if len(g.SubCommands) > 0 {
			return true
		}
	}
	return false
}

func (self *Command) HasVisibleSubCommands() bool {
	for _, g := range self.SubCommandGroups {
		if g.HasVisibleSubCommands() {
			return true
		}
	}
	return false
}

func (self *Command) VisitAllOptions(callback func(*Option) error) error {
	depth := 0
	iter_opts := func(cmd *Command) error {
		for _, g := range cmd.OptionGroups {
			for _, o := range g.Options {
				if o.Depth >= depth {
					err := callback(o)
					if err != nil {
						return err
					}
				}
			}
		}
		return nil
	}
	for p := self; p != nil; p = p.Parent {
		err := iter_opts(p)
		if err != nil {
			return err
		}
		depth++
	}
	return nil
}

func (self *Command) GetVisibleOptions() ([]string, map[string][]*Option) {
	group_titles := make([]string, 0, len(self.OptionGroups))
	gmap := make(map[string][]*Option)

	add_options := func(group_title string, opts []*Option) {
		if len(opts) == 0 {
			return
		}
		x := gmap[group_title]
		if x == nil {
			group_titles = append(group_titles, group_title)
			gmap[group_title] = opts
		} else {
			gmap[group_title] = append(x, opts...)
		}
	}

	depth := 0
	process_cmd := func(cmd *Command) {
		for _, g := range cmd.OptionGroups {
			gopts := make([]*Option, 0, len(g.Options))
			for _, o := range g.Options {
				if !o.Hidden && o.Depth >= depth {
					gopts = append(gopts, o)
				}
			}
			add_options(g.Title, gopts)
		}
	}
	for p := self; p != nil; p = p.Parent {
		process_cmd(p)
		depth++
	}
	return group_titles, gmap
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

func (self *Command) AddOptionToGroupFromString(group string, items ...string) *Option {
	ans, err := self.AddOptionGroup(group).AddOptionFromString(self, items...)
	if err != nil {
		panic(err)
	}
	return ans

}

func (self *Command) AddToGroup(group string, s OptionSpec) *Option {
	ans, err := self.AddOptionGroup(group).AddOption(self, s)
	if err != nil {
		panic(err)
	}
	return ans
}

func (self *Command) AddOptionFromString(items ...string) *Option {
	return self.AddOptionToGroupFromString("", items...)
}

func (self *Command) Add(s OptionSpec) *Option {
	return self.AddToGroup("", s)
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

func GetOptionValue[T any](self *Command, name string) (ans T, err error) {
	opt := self.option_map[name]
	if opt == nil {
		err = fmt.Errorf("No option with the name: %s", name)
		return
	}
	ans, ok := opt.parsed_value().(T)
	if !ok {
		err = fmt.Errorf("The option %s is not of the correct type", name)
	}
	return
}

func (self *Command) GetOptionValues(pointer_to_options_struct any) error {
	val := reflect.ValueOf(pointer_to_options_struct).Elem()
	if val.Kind() != reflect.Struct {
		return fmt.Errorf("Need a pointer to a struct to set option values on")
	}
	for i := 0; i < val.NumField(); i++ {
		f := val.Field(i)
		field_name := val.Type().Field(i).Name
		if utils.Capitalize(field_name) != field_name || !f.CanSet() {
			continue
		}
		opt := self.option_map[field_name]
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
				if !is_string_slice(f) {
					return fmt.Errorf("The field: %s must be a []string", field_name)
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

func (self *Command) Exec(args ...string) {
	root := self
	for root.Parent != nil {
		root = root.Parent
	}
	if len(args) == 0 {
		args = os.Args
	}
	cmd, err := root.ParseArgs(args)
	if err != nil {
		ShowError(err)
		os.Exit(1)
	}
	help_opt := cmd.option_map["Help"]
	version_opt := root.option_map["Version"]
	exit_code := 0
	if help_opt != nil && help_opt.parsed_value().(bool) {
		cmd.ShowHelp()
		os.Exit(exit_code)
	} else if version_opt != nil && version_opt.parsed_value().(bool) {
		root.ShowVersion()
		os.Exit(exit_code)
	} else if cmd.Run != nil {
		exit_code, err = cmd.Run(cmd, cmd.Args)
		if err != nil {
			ShowError(err)
			if exit_code == 0 {
				exit_code = 1
			}
		}
	}
	os.Exit(exit_code)
}

// }}}
