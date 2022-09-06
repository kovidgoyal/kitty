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

type completion_func func(completions *Completions, partial_word string)

type Option struct {
	Name               string
	Aliases            []string
	Description        string
	Has_following_arg  bool
	Completion_for_arg completion_func
}

type Command struct {
	Name        string
	Description string

	// List of options for this command
	Options []*Option

	// List of subcommands
	Subcommands []*Command
	// Optional title used as a header when displaying the list of matching sub-commands for a completion
	Subcommands_title string

	Completion_for_arg     completion_func
	Stop_processing_at_arg int
}

var Root = Command{Options: make([]*Option, 0), Subcommands: make([]*Command, 0, 32)}

func GetCompletions(argv []string) *Completions {
	ans := Completions{Groups: make([]*MatchGroup, 0, 4)}
	if len(argv) > 0 {
		exe := argv[0]
		cmd := Root.find_subcommand(exe)
		if cmd != nil {
			cmd.parse_args(argv[1:], &ans)
		}
	}
	return &ans
}
