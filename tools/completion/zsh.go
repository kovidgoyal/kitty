// License: GPLv3 Copyright: 2022, Kovid Goyal, <kovid at kovidgoyal.net>

package completion

import (
	"bufio"
	"fmt"
	"kitty/tools/cli/markup"
	"kitty/tools/tty"
	"kitty/tools/utils"
	"kitty/tools/wcswidth"
	"path/filepath"
	"strings"
)

var _ = fmt.Print

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
	raw := string(data)
	new_word := strings.HasSuffix(raw, "\n\n")
	raw = strings.TrimRight(raw, "\n \t")
	scanner := bufio.NewScanner(strings.NewReader(raw))
	words := make([]string, 0, 32)
	for scanner.Scan() {
		words = append(words, scanner.Text())
	}
	if new_word {
		words = append(words, "")
	}
	return [][]string{words}, nil
}

func fmt_desc(word, desc string, max_word_len int, f *markup.Context, screen_width int) string {
	if desc == "" {
		return word
	}
	line, _, _ := utils.Cut(strings.TrimSpace(desc), "\n")
	desc = f.Prettify(line)

	multiline := false
	max_desc_len := screen_width - 2
	word_len := wcswidth.Stringwidth(word)
	if word_len > max_word_len {
		multiline = true
	} else {
		word += strings.Repeat(" ", max_word_len-word_len)
		max_desc_len = screen_width - max_word_len - 3
	}
	if wcswidth.Stringwidth(desc) > max_desc_len {
		desc = wcswidth.TruncateToVisualLength(desc, max_desc_len-2) + "…"
	}

	if multiline {
		return word + "\n  " + desc
	}
	return word + "  " + desc
}

func serialize(completions *Completions, f *markup.Context, screen_width int) ([]byte, error) {
	cmd := strings.Builder{}
	output := strings.Builder{}
	for _, mg := range completions.Groups {
		cmd.WriteString("compadd -U -J ")
		cmd.WriteString(utils.QuoteStringForSH(mg.Title))
		cmd.WriteString(" -X ")
		cmd.WriteString(utils.QuoteStringForSH("%B" + mg.Title + "%b"))
		if mg.NoTrailingSpace {
			cmd.WriteString(" -S ''")
		}
		if mg.IsFiles {
			cmd.WriteString(" -f")
			if len(mg.Matches) > 1 {
				lcp := mg.longest_common_prefix()
				if strings.Contains(lcp, utils.Sep) {
					lcp = strings.TrimRight(filepath.Dir(lcp), utils.Sep) + utils.Sep
					cmd.WriteString(" -p ")
					cmd.WriteString(utils.QuoteStringForSH(lcp))
					mg.remove_prefix_from_all_matches(lcp)
				}
			}
		} else if len(mg.Matches) > 1 && strings.HasPrefix(mg.Matches[0].Word, "--") && strings.Contains(mg.Matches[0].Word, "=") {
			lcp, _, _ := utils.Cut(mg.longest_common_prefix(), "=")
			lcp += "="
			if len(lcp) > 3 {
				cmd.WriteString(" -p ")
				cmd.WriteString(utils.QuoteStringForSH(lcp))
				mg.remove_prefix_from_all_matches(lcp)
			}
		}
		if mg.has_descriptions() {
			fmt.Fprintln(&output, "compdescriptions=(")
			limit := mg.max_visual_word_length(16)
			for _, m := range mg.Matches {
				fmt.Fprintln(&output, utils.QuoteStringForSH(fmt_desc(m.Word, m.Description, limit, f, screen_width)))
			}
			fmt.Fprintln(&output, ")")
			cmd.WriteString(" -l -d compdescriptions")
		}
		cmd.WriteString(" --")
		for _, m := range mg.Matches {
			cmd.WriteString(" ")
			cmd.WriteString(utils.QuoteStringForSH(m.Word))
		}
		fmt.Fprintln(&output, cmd.String(), ";")
	}
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
			f = markup.New(true)
		}
	}
	if f == nil {
		f = markup.New(false)
	}
	return serialize(completions[0], f, screen_width)
}

func init() {
	input_parsers["zsh"] = zsh_input_parser
	output_serializers["zsh"] = zsh_output_serializer
}
