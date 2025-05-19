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
	parent.AddSubCommand(&cli.Command{
		Name:             "enable-portal",
		ShortDescription: "This will create or edit the various files needed so that the portal from this kitten is used by xdg-desktop-portal",
		Run: func(cmd *cli.Command, args []string) (rc int, err error) {
			err = enable_portal()
			return utils.IfElse(err == nil, 0, 1), err
		},
	})
	parent.AddSubCommand(&cli.Command{
		Name:             "set-color-scheme",
		ShortDescription: "Change the color scheme",
		Usage:            " light|dark|no-preference|toggle",
		Run: func(cmd *cli.Command, args []string) (rc int, err error) {
			if len(args) != 1 {
				cmd.ShowHelp()
				return 1, fmt.Errorf("must specify the new color scheme value")
			}
			err = set_color_scheme(args[0])
			return utils.IfElse(err == nil, 0, 1), err
		},
	})
	ss := parent.AddSubCommand(&cli.Command{
		Name:             "show-settings",
		ShortDescription: "Print the current values of the desktop settings",
		Run: func(cmd *cli.Command, args []string) (rc int, err error) {
			if len(args) != 0 {
				cmd.ShowHelp()
				return 1, fmt.Errorf("no arguments allowed")
			}
			opts := ShowSettingsOptions{}
			err = cmd.GetOptionValues(&opts)
			if err == nil {
				err = show_settings(&opts)
			}
			return utils.IfElse(err == nil, 0, 1), err
		},
	})
	ss.Add(cli.OptionSpec{
		Name: "--as-json",
		Help: "Show the settings as JSON for machine consumption",
		Type: "bool-set",
	})
	ss.Add(cli.OptionSpec{
		Name: "--in-namespace",
		Help: "Show only settings in the specified names. Can be specified multiple times. When unspecified all namespaces are returned.",
		Type: "list",
	})
	ss.Add(cli.OptionSpec{
		Name: "--allow-other-backends",
		Help: "Normally, after printing the settings, if the settings did not come from the desktop-ui kitten the command prints an error and exits. This prevents that.",
		Type: "bool-set",
	})

}
