// License: GPLv3 Copyright: 2022, Kovid Goyal, <kovid at kovidgoyal.net>

package cli

import (
	"fmt"
	"github.com/kovidgoyal/kitty/tools/cli/markup"
	"github.com/kovidgoyal/kitty/tools/tty"
	"github.com/kovidgoyal/kitty/tools/utils"
	"github.com/kovidgoyal/kitty/tools/utils/style"
	"github.com/kovidgoyal/kitty/tools/wcswidth"
	"strings"
)

var _ = fmt.Print

func zsh_completion_script(commands []string) (string, error) {
	return `#compdef kitty

_kitty() {
    (( ${+commands[kitten]} )) || builtin return
    builtin local src cmd=${(F)words:0:$CURRENT}
    # Send all words up to the word the cursor is currently on.
    src=$(builtin command kitten __complete__ zsh "_matcher=$_matcher" <<<$cmd) || builtin return
    builtin eval "$src"
}

if (( $+functions[compdef] )); then
    compdef _kitty kitty
    compdef _kitty clone-in-kitty
    compdef _kitty kitten
fi
`, nil
}

func shell_input_parser(data []byte, shell_state map[string]string) ([][]string, error) {
	raw := string(data)
	new_word := strings.HasSuffix(raw, "\n\n")
	raw = strings.TrimRight(raw, "\n \t")
	scanner := utils.NewLineScanner(raw)
	words := make([]string, 0, 32)
	for scanner.Scan() {
		words = append(words, scanner.Text())
	}
	if new_word {
		words = append(words, "")
	}
	return [][]string{words}, nil
}

var debugprintln = tty.DebugPrintln
var _ = debugprintln

func zsh_input_parser(data []byte, shell_state map[string]string) ([][]string, error) {
	matcher := shell_state["_matcher"]
	q := ""
	if matcher != "" {
		q = strings.Split(strings.ToLower(matcher), ":")[0][:1]
	}
	if q != "" && strings.Contains("lrbe", q) {
		// this is zsh anchor based matching
		// https://zsh.sourceforge.io/Doc/Release/Completion-Widgets.html#Completion-Matching-Control
		// can be specified with matcher-list and some systems do it by default,
		// for example, Debian, which adds the following to zshrc
		// zstyle ':completion:*' matcher-list '' 'm:{a-z}={A-Z}' 'm:{a-zA-Z}={A-Za-z}' 'r:|[._-]=* r:|=* l:|=*'
		// For some reason that I dont have the
		// time/interest to figure out, returning completion candidates for
		// these matcher types break completion, so just abort in this case.
		return nil, fmt.Errorf("ZSH anchor based matching active, cannot complete")
	}
	return shell_input_parser(data, shell_state)
}

func (self *Match) FormatForCompletionList(max_word_len int, f *markup.Context, screen_width int) string {
	word := self.Word
	desc := self.Description
	if desc == "" {
		return word
	}
	word_len := wcswidth.Stringwidth(word)
	line, _, _ := strings.Cut(strings.TrimSpace(desc), "\n")
	desc = f.Prettify(line)

	multiline := false
	max_desc_len := screen_width - max_word_len - 3
	if word_len > max_word_len {
		multiline = true
	} else {
		word += strings.Repeat(" ", max_word_len-word_len)
	}
	if wcswidth.Stringwidth(desc) > max_desc_len {
		desc = style.WrapTextAsLines(desc, max_desc_len-2, style.WrapOptions{})[0] + "…"
	}
	if multiline {
		return word + "\n" + strings.Repeat(" ", max_word_len+2) + desc
	}
	return word + "  " + desc
}

func serialize(completions *Completions, f *markup.Context, screen_width int) ([]byte, error) {
	output := strings.Builder{}
	if completions.Delegate.NumToRemove > 0 {
		for i := 0; i < completions.Delegate.NumToRemove; i++ {
			fmt.Fprintln(&output, "shift words")
			fmt.Fprintln(&output, "(( CURRENT-- ))")
		}
		service := utils.QuoteStringForSH(completions.Delegate.Command)
		fmt.Fprintln(&output, "words[1]="+service)
		fmt.Fprintln(&output, "_normal -p", service)
	} else {
		for _, mg := range completions.Groups {
			cmd := strings.Builder{}
			escape_ourselves := mg.IsFiles // zsh quoting quotes a leading ~/ in filenames which is wrong
			cmd.WriteString("compadd -U ")
			if escape_ourselves {
				cmd.WriteString("-Q ")
			}
			cmd.WriteString("-J ")
			cmd.WriteString(utils.QuoteStringForSH(mg.Title))
			cmd.WriteString(" -X ")
			cmd.WriteString(utils.QuoteStringForSH("%B" + mg.Title + "%b"))
			if mg.NoTrailingSpace {
				cmd.WriteString(" -S ''")
			}
			if mg.IsFiles {
				cmd.WriteString(" -f")
			}
			lcp := mg.remove_common_prefix()
			if lcp != "" {
				cmd.WriteString(" -p ")
				cmd.WriteString(utils.QuoteStringForSH(lcp))
			}
			if mg.has_descriptions() {
				fmt.Fprintln(&output, "compdescriptions=(")
				limit := mg.max_visual_word_length(16)
				for _, m := range mg.Matches {
					fmt.Fprintln(&output, utils.QuoteStringForSH(wcswidth.StripEscapeCodes(m.FormatForCompletionList(limit, f, screen_width))))
				}
				fmt.Fprintln(&output, ")")
				cmd.WriteString(" -l -d compdescriptions")
			}
			cmd.WriteString(" --")
			for _, m := range mg.Matches {
				cmd.WriteString(" ")
				w := m.Word
				if escape_ourselves {
					w = utils.EscapeSHMetaCharacters(m.Word)
				}
				cmd.WriteString(utils.QuoteStringForSH(w))
			}
			fmt.Fprintln(&output, cmd.String(), ";")
		}
	}
	// debugf("%#v", output.String())
	return []byte(output.String()), nil
}

func zsh_output_serializer(completions []*Completions, shell_state map[string]string) ([]byte, error) {
	var f *markup.Context
	screen_width := 80
	ctty, err := tty.OpenControllingTerm()
	if err == nil {
		sz, err := ctty.GetSize()
		ctty.Close()
		if err == nil {
			screen_width = int(sz.Col)
		}
	}
	f = markup.New(false) // ZSH freaks out if there are escape codes in the description strings
	return serialize(completions[0], f, screen_width)
}

func init() {
	completion_scripts["zsh"] = zsh_completion_script
	input_parsers["zsh"] = zsh_input_parser
	output_serializers["zsh"] = zsh_output_serializer
}
