// License: GPLv3 Copyright: 2022, Kovid Goyal, <kovid at kovidgoyal.net>

package cli

import (
	"fmt"
	"os"
	"path/filepath"
	"reflect"
	"strings"

	"github.com/kovidgoyal/kitty/tools/utils"
)

var _ = fmt.Print

type RunFunc = func(cmd *Command, args []string) (int, error)

type Command struct {
	Name, Group                       string
	Usage, ShortDescription, HelpText string
	Hidden                            bool

	// Number of non-option arguments after which to stop parsing options. 0 means no options after the first non-option arg.
	AllowOptionsAfterArgs int
	// If true does not fail if the first non-option arg is not a sub-command
	SubCommandIsOptional bool
	// If true subcommands are ignored unless they are the first non-option argument
	SubCommandMustBeFirst bool
	// The entry point for this command
	Run RunFunc
	// The completer for args
	ArgCompleter CompletionFunc
	// Stop completion processing at this arg num
	StopCompletingAtArg int
	// Consider all args as non-options args when parsing for completion
	OnlyArgsAllowed bool
	// Pass through all args, useful for wrapper commands
	IgnoreAllArgs bool
	// Specialised arg parsing
	ParseArgsForCompletion func(cmd *Command, args []string, completions *Completions)
	// Callback that is called on error
	CallbackOnError func(cmd *Command, err error, during_parsing bool, exit_code int) (final_exit_code int)

	SubCommandGroups []*CommandGroup
	OptionGroups     []*OptionGroup
	Parent           *Command

	Args []string

	option_map      map[string]*Option
	IndexOfFirstArg int
}

func (self *Command) Clone(parent *Command) *Command {
	ans := *self
	ans.Args = make([]string, 0, 8)
	ans.Parent = parent
	ans.SubCommandGroups = make([]*CommandGroup, len(self.SubCommandGroups))
	ans.OptionGroups = make([]*OptionGroup, len(self.OptionGroups))
	ans.option_map = nil

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
	c.Group = g.Title
	g.SubCommands = append(g.SubCommands, c)
	return c
}

func init_cmd(c *Command) {
	c.SubCommandGroups = make([]*CommandGroup, 0, 8)
	c.OptionGroups = make([]*OptionGroup, 0, 8)
	c.Args = make([]string, 0, 8)
	c.option_map = nil
}

func NewRootCommand() *Command {
	ans := Command{
		Name: filepath.Base(os.Args[0]),
	}
	init_cmd(&ans)
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

func (self *Command) AddSubCommand(ans *Command) *Command {
	g := self.AddSubCommandGroup(ans.Group)
	g.SubCommands = append(g.SubCommands, ans)
	init_cmd(ans)
	ans.Parent = self
	return ans
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
	self.option_map = nil
	self.IndexOfFirstArg = 0
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

func (self *Command) AllOptions() []*Option {
	ans := make([]*Option, 0, 64)
	_ = self.VisitAllOptions(func(o *Option) error { ans = append(ans, o); return nil })
	return ans
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

func sort_levenshtein_matches(q string, matches []string) {
	utils.StableSort(matches, func(a, b string) int {
		la, lb := utils.LevenshteinDistance(a, q, true), utils.LevenshteinDistance(b, q, true)
		if la != lb {
			return la - lb
		}
		return strings.Compare(a, b)
	})

}

func (self *Command) SuggestionsForCommand(name string, max_distance int /* good default is 2 */) []string {
	ans := make([]string, 0, 8)
	q := strings.ToLower(name)
	for _, g := range self.SubCommandGroups {
		for _, sc := range g.SubCommands {
			if utils.LevenshteinDistance(sc.Name, q, true) <= max_distance {
				ans = append(ans, sc.Name)
			}
		}
	}
	sort_levenshtein_matches(q, ans)
	return ans
}

func (self *Command) SuggestionsForOption(name_with_hyphens string, max_distance int /* good default is 2 */) []string {
	ans := make([]string, 0, 8)
	q := strings.ToLower(name_with_hyphens)
	_ = self.VisitAllOptions(func(opt *Option) error {
		for _, a := range opt.Aliases {
			as := a.String()
			if utils.LevenshteinDistance(as, q, true) <= max_distance {
				ans = append(ans, as)
			}
		}
		return nil
	})
	sort_levenshtein_matches(q, ans)
	return ans
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

func (self *Command) FindSubCommands(prefix string) []*Command {
	c := self.FindSubCommand(prefix)
	if c != nil {
		return []*Command{c}
	}
	ans := make([]*Command, 0, 4)
	for _, g := range self.SubCommandGroups {
		ans = g.FindSubCommands(prefix, ans)
	}
	return ans
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

func (self *Command) FindOptions(name_with_hyphens string) []*Option {
	ans := make([]*Option, 0, 4)
	for _, g := range self.OptionGroups {
		x := g.FindOptions(name_with_hyphens)
		if x != nil {
			ans = append(ans, x...)
		}
	}
	depth := 0
	for p := self.Parent; p != nil; p = p.Parent {
		depth++
		for _, po := range p.FindOptions(name_with_hyphens) {
			if po.Depth >= depth {
				ans = append(ans, po)
			}
		}
	}
	return ans

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

func (self *Command) OptionsSeenOnCommandLine() map[string]bool {
	ans := make(map[string]bool)
	for name, opt := range self.option_map {
		ans[name] = opt != nil && len(opt.values_from_cmdline) > 0
	}
	return ans
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

func (self *Command) ExecArgs(args []string) (exit_code int) {
	root := self
	for root.Parent != nil {
		root = root.Parent
	}
	cmd, err := root.ParseArgs(args)
	if err != nil {
		if self.CallbackOnError != nil {
			return self.CallbackOnError(cmd, err, true, 1)
		}
		ShowError(err)
		return 1
	}
	help_opt := cmd.option_map["Help"]
	version_opt := root.option_map["Version"]
	if help_opt != nil && help_opt.parsed_value().(bool) {
		cmd.ShowHelp()
		return
	} else if version_opt != nil && version_opt.parsed_value().(bool) {
		root.ShowVersion()
		return
	} else if cmd.Run != nil {
		exit_code, err = cmd.Run(cmd, cmd.Args)
		if err != nil {
			if exit_code == 0 {
				exit_code = 1
			}
			if self.CallbackOnError != nil {
				return self.CallbackOnError(cmd, err, false, exit_code)
			}
			ShowError(err)
		}
	}
	return
}

func (self *Command) Exec(args ...string) {
	if len(args) == 0 {
		args = os.Args
	}
	os.Exit(self.ExecArgs(args))
}

func (self *Command) GetCompletions(argv []string, init_completions func(*Completions)) *Completions {
	ans := NewCompletions()
	if init_completions != nil {
		init_completions(ans)
	}
	if len(argv) > 0 {
		exe := argv[0]
		exe = filepath.Base(exe) // zsh completion script passes full path to exe when using aliases
		cmd := self.FindSubCommand(exe)
		if cmd != nil {
			if cmd.ParseArgsForCompletion != nil {
				cmd.ParseArgsForCompletion(cmd, argv[1:], ans)
			} else {
				completion_parse_args(cmd, argv[1:], ans)
			}
		}
	}
	non_empty_groups := make([]*MatchGroup, 0, len(ans.Groups))
	for _, gr := range ans.Groups {
		if len(gr.Matches) > 0 {
			non_empty_groups = append(non_empty_groups, gr)
		}
	}
	ans.Groups = non_empty_groups
	return ans
}
