// License: GPLv3 Copyright: 2022, Kovid Goyal, <kovid at kovidgoyal.net>

package cli

import (
	"fmt"
	"slices"
	"strings"

	"github.com/kovidgoyal/kitty/tools/cli/markup"
	"github.com/kovidgoyal/kitty/tools/utils"
)

var _ = fmt.Print

func fish_completion_script(commands []string) (string, error) {
	// One command in fish requires one completion script.
	// Usage: kitten __complete__ setup fish [kitty|kitten|clone-in-kitty]
	all_commands := map[string]bool{
		"kitty":          true,
		"clone-in-kitty": true,
		"kitten":         true,
	}
	if len(commands) == 0 {
		commands = append(commands, utils.Keys(all_commands)...)
	}
	script := strings.Builder{}
	script.WriteString(`function __ksi_completions
    set --local ct (commandline --current-token)
    set --local tokens (commandline --tokenize --cut-at-cursor --current-process)
    printf "%s\n" $tokens $ct | command kitten __complete__ fish | source -
end

`)
	slices.Sort(commands)
	for _, cmd := range commands {
		if all_commands[cmd] {
			fmt.Fprintf(&script, "complete -f -c %s -a \"(__ksi_completions)\"\n", cmd)
		} else if strings.Contains(cmd, "=") {
			// Reserved for `setup SHELL [KEY=VALUE ...]`, not used now.
			continue
		} else {
			return "", fmt.Errorf("No fish completion script for command: %s", cmd)
		}
	}
	return script.String(), nil
}

func fish_output_serializer(completions []*Completions, shell_state map[string]string) ([]byte, error) {
	output := strings.Builder{}
	f := func(format string, args ...any) { fmt.Fprintf(&output, format+"\n", args...) }
	n := completions[0].Delegate.NumToRemove
	fm := markup.New(false) // fish freaks out if there are escape codes in the description strings
	legacy_completion := shell_state["_legacy_completion"]
	if legacy_completion == "fish2" {
		for _, mg := range completions[0].Groups {
			for _, m := range mg.Matches {
				f("%s", strings.ReplaceAll(m.Word+"\t"+fm.Prettify(m.Description), "\n", " "))
			}
		}
	} else if n > 0 {
		words := make([]string, len(completions[0].AllWords)-n+1)
		words[0] = completions[0].Delegate.Command
		copy(words[1:], completions[0].AllWords[n:])
		for i, w := range words {
			words[i] = fmt.Sprintf("(string escape -- %s)", utils.QuoteStringForFish(w))
		}
		cmdline := strings.Join(words, " ")
		f("set __ksi_cmdline " + cmdline)
		f("complete -C \"$__ksi_cmdline\"")
		f("set --erase __ksi_cmdline")
	} else {
		for _, mg := range completions[0].Groups {
			for _, m := range mg.Matches {
				f("echo -- %s", utils.QuoteStringForFish(m.Word+"\t"+fm.Prettify(m.Description)))
			}
		}
	}
	// debugf("%#v", output.String())
	return []byte(output.String()), nil
}

func init() {
	completion_scripts["fish"] = fish_completion_script
	input_parsers["fish"] = shell_input_parser
	output_serializers["fish"] = fish_output_serializer
}
