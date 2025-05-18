package desktop_ui

import (
	"fmt"

	"github.com/kovidgoyal/kitty/tools/cli"
	"github.com/kovidgoyal/kitty/tools/utils"
)

var _ = fmt.Print

type Options struct {
	Color_scheme string
}

func run_server(opts *Options) (err error) {
	portal := NewPortal(opts)
	if err = portal.Start(); err != nil {
		return
	}
	c := make(chan string)
	<-c
	return
}

func EntryPoint(root *cli.Command) {
	parent := root.AddSubCommand(&cli.Command{
		Name:             "desktop-ui",
		ShortDescription: "Implement various desktop components for use with lightweight compositors/window managers on Linux",
		Run: func(cmd *cli.Command, args []string) (int, error) {
			cmd.ShowHelp()
			return 1, nil
		},
	})
	rs := parent.AddSubCommand(&cli.Command{
		Name:             "run-server",
		ShortDescription: "Start the various servers used to integrate with the Linux desktop",
		HelpText:         "This should be run very early in the startup sequence of your window manager, before any other programs are run.",
		Run: func(cmd *cli.Command, args []string) (rc int, err error) {
			opts := Options{}
			err = cmd.GetOptionValues(&opts)
			if err == nil {
				err = run_server(&opts)
			}
			return utils.IfElse(err == nil, 0, 1), err
		},
	})
	rs.Add(cli.OptionSpec{
		Name: `--color-scheme`, Type: "choices", Dest: `Color_scheme`, Choices: "no-preference, light, dark",
		Completer: cli.NamesCompleter("Choices for color-scheme", "no-preference", "light", "dark"),
		Help:      "The color scheme for your system. This sets the initial value of the color scheme. It can be changed subsequently by using the color-scheme sub-command.",
	})

}
