// License: GPLv3 Copyright: 2022, Kovid Goyal, <kovid at kovidgoyal.net>

package cli

import (
	"fmt"
	"strings"
)

var _ = fmt.Print

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
	ans := CommandGroup{Title: self.Title, SubCommands: make([]*Command, len(self.SubCommands))}
	for i, o := range self.SubCommands {
		ans.SubCommands[i] = o.Clone(parent)
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

func (self *CommandGroup) FindSubCommands(prefix string, matches []*Command) []*Command {
	for _, c := range self.SubCommands {
		if strings.HasPrefix(c.Name, prefix) {
			matches = append(matches, c)
		}
	}
	return matches
}

type OptionGroup struct {
	Options []*Option
	Title   string
}

func (self *OptionGroup) Clone(parent *Command) *OptionGroup {
	ans := OptionGroup{Title: self.Title, Options: make([]*Option, len(self.Options))}
	for i, o := range self.Options {
		c := *o
		c.init_option()
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

func (self *OptionGroup) FindOptions(prefix_with_hyphens string) []*Option {
	is_short := !strings.HasPrefix(prefix_with_hyphens, "--")
	option_name := NormalizeOptionName(prefix_with_hyphens)
	ans := make([]*Option, 0, 4)
	for _, q := range self.Options {
		if q.MatchingAlias(option_name, is_short) != "" {
			ans = append(ans, q)
		}
	}
	return ans

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
