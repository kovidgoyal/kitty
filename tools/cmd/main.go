// License: GPLv3 Copyright: 2022, Kovid Goyal, <kovid at kovidgoyal.net>

package main

import (
	"kitty/tools/cli"
	"kitty/tools/cli/completion"
	"kitty/tools/cmd/at"
)

func completion_entry_point(tool_root *cli.Command) {
	tool_root.AddSubCommand(&cli.Command{
		Name: "__complete__", Hidden: true,
		Usage:            "output_type [shell state...]",
		ShortDescription: "Generate completions for kitty commands",
		HelpText:         "Generate completion candidates for kitty commands. The command line is read from STDIN. output_type can be one of the supported  shells or 'json' for JSON output.",
		Run: func(cmd *cli.Command, args []string) (ret int, err error) {
			return ret, completion.Main(args)
		},
	})
}
func main() {
	root := cli.NewRootCommand()
	root.ShortDescription = "Fast, statically compiled implementations for various kitty command-line tools"
	root.Usage = "command [command options] [command args]"

	at.EntryPoint(root)
	completion_entry_point(root)

	root.Exec()
}
