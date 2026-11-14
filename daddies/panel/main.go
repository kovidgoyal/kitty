package panel

import (
	"fmt"
	"os"
	"path/filepath"
	"runtime"
	"strings"

	"github.com/kovidgoyal/datty/tools/cli"
	"github.com/kovidgoyal/datty/tools/utils"

	"golang.org/x/sys/unix"
)

var _ = fmt.Print

func complete_datty_listen_on(completions *cli.Completions, word string, arg_num int) {
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

var CompleteDattyListenOn = complete_datty_listen_on

func GetQuickAccessDattyExe() (datty_exe string, err error) {
	if datty_exe, err = filepath.EvalSymlinks(utils.DattyExe()); err != nil {
		return "", fmt.Errorf("Failed to find path to the datty executable, this daddy requires the datty executable to function. The datty executable or a symlink to it must be placed in the same directory as the daddy executable. Error: %w", err)
	}
	if runtime.GOOS == "darwin" {
		q := filepath.Join(filepath.Dir(filepath.Dir(datty_exe)), "datty-quick-access.app", "Contents", "MacOS", "datty-quick-access")
		if err := unix.Access(q, unix.X_OK); err == nil {
			datty_exe = q
		}
	}
	return datty_exe, nil

}

func main(cmd *cli.Command, o *Options, args []string) (rc int, err error) {
	datty_exe, err := GetQuickAccessDattyExe()
	if err != nil {
		return 1, err
	}
	argv := []string{datty_exe, "+daddy", "panel"}
	argv = append(argv, o.AsCommandLine()...)
	err = unix.Exec(datty_exe, append(argv, args...), os.Environ())
	rc = 1
	return
}

func EntryPoint(parent *cli.Command) {
	create_cmd(parent, main)
}
