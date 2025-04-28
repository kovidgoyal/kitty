package quick_access_terminal

import (
	"fmt"
	"os"

	"kitty/kittens/panel"
	"kitty/tools/cli"

	"golang.org/x/sys/unix"
)

var _ = fmt.Print

var complete_kitty_listen_on = panel.CompleteKittyListenOn

func main(cmd *cli.Command, o *Options, args []string) (rc int, err error) {
	kitty_exe, err := panel.GetQuickAccessKittyExe()
	if err != nil {
		return 1, err
	}
	argv := []string{kitty_exe, "+kitten", "panel"}
	argv = append(argv, o.AsCommandLine()...)
	argv = append(argv, args...)
	err = unix.Exec(kitty_exe, argv, os.Environ())
	rc = 1
	return
}

func EntryPoint(parent *cli.Command) {
	create_cmd(parent, main)
}
