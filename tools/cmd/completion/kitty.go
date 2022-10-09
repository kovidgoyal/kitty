// License: GPLv3 Copyright: 2022, Kovid Goyal, <kovid at kovidgoyal.net>

package completion

import (
	"bufio"
	"bytes"
	"fmt"
	"os/exec"
	"strings"

	"kitty/tools/cli"
	"kitty/tools/utils"
)

var _ = fmt.Print

func complete_kitty_override(completions *cli.Completions, word string, arg_num int) {
	mg := completions.AddMatchGroup("Config directives")
	mg.NoTrailingSpace = true
	for _, q := range kitty_option_names_for_completion {
		if strings.HasPrefix(q, word) {
			mg.AddMatch(q + "=")
		}
	}
}

func complete_kitty_listen_on(completions *cli.Completions, word string, arg_num int) {
	if !strings.Contains(word, ":") {
		mg := completions.AddMatchGroup("Address family")
		mg.NoTrailingSpace = true
		for _, q := range []string{"unix:", "tcp:"} {
			if strings.HasPrefix(q, word) {
				mg.AddMatch(q)
			}
		}
	} else if strings.HasPrefix(word, "unix:") && !strings.HasPrefix(word, "unix:@") {
		cli.FnmatchCompleter("UNIX sockets", cli.CWD, "*")(completions, word[len("unix:"):], arg_num)
		completions.AddPrefixToAllMatches("unix:")
	}
}

func complete_plus_launch(completions *cli.Completions, word string, arg_num int) {
	if arg_num == 1 {
		cli.FnmatchCompleter("Python scripts", cli.CWD, "*.py")(completions, word, arg_num)
		if strings.HasPrefix(word, ":") {
			exes := cli.CompleteExecutablesInPath(word[1:])
			mg := completions.AddMatchGroup("Python scripts in PATH")
			for _, exe := range exes {
				mg.AddMatch(":" + exe)
			}
		}
	} else {
		cli.FnmatchCompleter("Files", cli.CWD, "*")(completions, word, arg_num)
	}
}

func complete_plus_runpy(completions *cli.Completions, word string, arg_num int) {
	if arg_num > 1 {
		cli.FnmatchCompleter("Files", cli.CWD, "*")(completions, word, arg_num)
	}
}

func complete_plus_open(completions *cli.Completions, word string, arg_num int) {
	cli.FnmatchCompleter("Files", cli.CWD, "*")(completions, word, arg_num)
}

func complete_themes(completions *cli.Completions, word string, arg_num int) {
	kitty, err := utils.KittyExe()
	if err == nil {
		out, err := exec.Command(kitty, "+runpy", "from kittens.themes.collection import *; print_theme_names()").Output()
		if err == nil {
			mg := completions.AddMatchGroup("Themes")
			scanner := bufio.NewScanner(bytes.NewReader(out))
			for scanner.Scan() {
				theme_name := strings.TrimSpace(scanner.Text())
				if theme_name != "" && strings.HasPrefix(theme_name, word) {
					mg.AddMatch(theme_name)
				}
			}
		}
	}
}

func EntryPoint(tool_root *cli.Command) {
	tool_root.AddSubCommand(&cli.Command{
		Name: "__complete__", Hidden: true,
		Usage:            "output_type [shell state...]",
		ShortDescription: "Generate completions for kitty commands",
		HelpText:         "Generate completion candidates for kitty commands. The command line is read from STDIN. output_type can be one of the supported  shells or 'json' for JSON output.",
		Run: func(cmd *cli.Command, args []string) (ret int, err error) {
			return ret, cli.GenerateCompletions(args)
		},
	})

}
