// License: GPLv3 Copyright: 2022, Kovid Goyal, <kovid at kovidgoyal.net>

package cli

import (
	"fmt"
	"strings"

	"kitty/tools/cli/markup"
	"kitty/tools/utils"
)

var _ = fmt.Print

func fish_output_serializer(completions []*Completions, shell_state map[string]string) ([]byte, error) {
	output := strings.Builder{}
	f := func(format string, args ...any) { fmt.Fprintf(&output, format+"\n", args...) }
	n := completions[0].Delegate.NumToRemove
	fm := markup.New(false) // fish freaks out if there are escape codes in the description strings
	if n > 0 {
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
	input_parsers["fish"] = shell_input_parser
	output_serializers["fish"] = fish_output_serializer
}
