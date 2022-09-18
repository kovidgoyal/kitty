// License: GPLv3 Copyright: 2022, Kovid Goyal, <kovid at kovidgoyal.net>

package completion

import (
	"bufio"
	"fmt"
	"strings"
)

var _ = fmt.Print

func zsh_input_parser(data []byte, shell_state map[string]string) ([][]string, error) {
	matcher := shell_state["_matcher"]
	q := strings.Split(strings.ToLower(matcher), ":")[0][:1]
	if strings.Contains("lrbe", q) {
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

func zsh_output_serializer(completions []*Completions, shell_state map[string]string) ([]byte, error) {
	return nil, nil
}

func init() {
	input_parsers["zsh"] = zsh_input_parser
	output_serializers["zsh"] = zsh_output_serializer
}
