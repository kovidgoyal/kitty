// License: GPLv3 Copyright: 2026, Kovid Goyal, <kovid at kovidgoyal.net>

package cli

import (
	"strings"
	"testing"
)

func TestFishCompletionMultilineDescription(t *testing.T) {
	completions := []*Completions{{Groups: []*MatchGroup{{Title: "Options", Matches: []*Match{
		{Word: "--config", Description: "Specify a path to the configuration file.\n\nIf it is not specified, config files are searched for."},
	}}}}}
	for _, shell_state := range []map[string]string{{}, {"_legacy_completion": "fish2"}} {
		data, err := fish_output_serializer(completions, shell_state)
		if err != nil {
			t.Fatal(err)
		}
		// each candidate must be a single line, since fish splits the output of the
		// completion function on newlines to get the candidate list
		if q := strings.TrimRight(string(data), "\n"); strings.Contains(q, "\n") {
			t.Fatalf("A multi line description produced more than one candidate with shell state %#v:\n%s", shell_state, q)
		}
	}
}
