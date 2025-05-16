package panel

import (
	"fmt"
	"os"
	"path/filepath"
	"runtime"
	"strings"

	"github.com/kovidgoyal/kitty/tools/cli"
	"github.com/kovidgoyal/kitty/tools/utils"

	"golang.org/x/sys/unix"
)

var _ = fmt.Print

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

var CompleteKittyListenOn = complete_kitty_listen_on

func GetQuickAccessKittyExe() (kitty_exe string, err error) {
	if kitty_exe, err = filepath.EvalSymlinks(utils.KittyExe()); err != nil {
		return "", fmt.Errorf("Failed to find path to the kitty executable, this kitten requires the kitty executable to function. The kitty executable or a symlink to it must be placed in the same directory as the kitten executable. Error: %w", err)
	}
	if runtime.GOOS == "darwin" {
		q := filepath.Join(filepath.Dir(filepath.Dir(kitty_exe)), "kitty-quick-access.app", "Contents", "MacOS", "kitty-quick-access")
		if err := unix.Access(q, unix.X_OK); err == nil {
			kitty_exe = q
		}
	}
	return kitty_exe, nil

}

func main(cmd *cli.Command, o *Options, args []string) (rc int, err error) {
	kitty_exe, err := GetQuickAccessKittyExe()
	if err != nil {
		return 1, err
	}
	argv := []string{kitty_exe, "+kitten", "panel"}
	argv = append(argv, o.AsCommandLine()...)
	err = unix.Exec(kitty_exe, append(argv, args...), os.Environ())
	rc = 1
	return
}

func EntryPoint(parent *cli.Command) {
	create_cmd(parent, main)
}
