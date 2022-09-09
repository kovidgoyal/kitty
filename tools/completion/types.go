// License: GPLv3 Copyright: 2022, Kovid Goyal, <kovid at kovidgoyal.net>

package completion

type Match struct {
	Word        string `json:"word,omitempty"`
	FullForm    string `json:"full_form,omitempty"`
	Description string `json:"description,omitempty"`
}

type MatchGroup struct {
	Title           string   `json:"title,omitempty"`
	NoTrailingSpace bool     `json:"no_trailing_space,omitempty"`
	IsFiles         bool     `json:"is_files,omitempty"`
	Matches         []*Match `json:"matches,omitempty"`
	WordPrefix      string   `json:"word_prefix,omitempty"`
}

type Completions struct {
	Groups     []*MatchGroup `json:"groups,omitempty"`
	WordPrefix string        `json:"word_prefix,omitempty"`

	current_cmd *Command
}

type completion_func func(completions *Completions, partial_word string, arg_num int)

type Option struct {
	Name               string
	Aliases            []string
	Description        string
	Has_following_arg  bool
	Completion_for_arg completion_func
}

type CommandGroup struct {
	Title    string
	Commands []*Command
}

type Command struct {
	Name        string
	Description string

	Options []*Option
	Groups  []*CommandGroup

	Completion_for_arg     completion_func
	Stop_processing_at_arg int
}

func (self *Command) add_group(name string) *CommandGroup {
	for _, g := range self.Groups {
		if g.Title == name {
			return g
		}
	}
	g := CommandGroup{Title: name, Commands: make([]*Command, 0, 8)}
	self.Groups = append(self.Groups, &g)
	return &g
}

func (self *Command) add_command(name string, group_title string) *Command {
	ans := Command{Name: name}
	ans.Options = make([]*Option, 0, 8)
	ans.Groups = make([]*CommandGroup, 0, 2)
	g := self.add_group(group_title)
	g.Commands = append(g.Commands, &ans)
	return &ans
}

func (self *Command) add_clone(name string, group_title string, clone_of *Command) *Command {
	ans := *clone_of
	ans.Name = name
	g := self.add_group(group_title)
	g.Commands = append(g.Commands, &ans)
	return &ans
}

func (self *Command) find_subcommand(is_ok func(cmd *Command) bool) *Command {
	for _, g := range self.Groups {
		for _, q := range g.Commands {
			if is_ok(q) {
				return q
			}
		}
	}
	return nil
}

func (self *Command) find_subcommand_with_name(name string) *Command {
	return self.find_subcommand(func(cmd *Command) bool { return cmd.Name == name })
}

func (self *Command) has_subcommands() bool {
	for _, g := range self.Groups {
		if len(g.Commands) > 0 {
			return true
		}
	}
	return false
}

func (self *Command) GetCompletions(argv []string) *Completions {
	ans := Completions{Groups: make([]*MatchGroup, 0, 4)}
	if len(argv) > 0 {
		exe := argv[0]
		cmd := self.find_subcommand_with_name(exe)
		if cmd != nil {
			cmd.parse_args(argv[1:], &ans)
		}
	}
	return &ans
}
