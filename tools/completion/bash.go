// License: GPLv3 Copyright: 2022, Kovid Goyal, <kovid at kovidgoyal.net>

package completion

import (
	"fmt"
	"strings"

	"kitty/tools/utils"
)

var _ = fmt.Print

func bash_output_serializer(completions []*Completions, shell_state map[string]string) ([]byte, error) {
	output := strings.Builder{}
	f := func(format string, args ...interface{}) { fmt.Fprintf(&output, format+"\n", args...) }
	n := completions[0].Delegate.NumToRemove
	if n > 0 {
		n--
		f("compopt +o nospace")
		f("COMP_WORDS[%d]=%s", n, utils.QuoteStringForSH(completions[0].Delegate.Command))
		f("_command_offset %d", n)
	} else {
		for _, mg := range completions[0].Groups {
			mg.remove_common_prefix()
			if mg.NoTrailingSpace {
				f("compopt -o nospace")
			} else {
				f("compopt +o nospace")
			}
			if mg.IsFiles {
				f("compopt -o filenames")
				for _, m := range mg.Matches {
					if strings.HasSuffix(m.Word, utils.Sep) {
						m.Word = m.Word[:len(m.Word)-1]
					}
				}
			} else {
				f("compopt +o filenames")
			}
			for _, m := range mg.Matches {
				f("COMPREPLY+=(%s)", utils.QuoteStringForSH(m.Word))
			}
		}
	}
	// debugf("%#v", output.String())
	return []byte(output.String()), nil
}

func bash_init_completions(completions *Completions) {
	completions.split_on_equals = true
}

func init() {
	input_parsers["bash"] = shell_input_parser
	output_serializers["bash"] = bash_output_serializer
	init_completions["bash"] = bash_init_completions
}
