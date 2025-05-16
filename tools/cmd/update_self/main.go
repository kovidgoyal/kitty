// License: GPLv3 Copyright: 2022, Kovid Goyal, <kovid at kovidgoyal.net>

package update_self

import (
	"fmt"
	"os"
	"path/filepath"
	"runtime"

	"github.com/kovidgoyal/kitty"
	"github.com/kovidgoyal/kitty/tools/cli"
	"github.com/kovidgoyal/kitty/tools/tty"
	"github.com/kovidgoyal/kitty/tools/tui"
	"github.com/kovidgoyal/kitty/tools/utils"

	"golang.org/x/sys/unix"
)

var _ = fmt.Print

type Options struct {
	FetchVersion string
}

func update_self(version string) (err error) {
	exe := ""
	exe, err = os.Executable()
	if err != nil {
		return fmt.Errorf("Failed to determine path to kitten: %w", err)
	}
	exe, err = filepath.EvalSymlinks(exe)
	if err != nil {
		return err
	}
	if kitty.IsStandaloneBuild == "" {
		return fmt.Errorf("This is not a standalone kitten executable. You must update all of kitty instead.")
	}
	rv := "v" + version
	if version == "nightly" {
		rv = version
	}
	url_base := fmt.Sprintf("https://github.com/kovidgoyal/kitty/releases/download/%s", rv)
	if version == "latest" {
		url_base = "https://github.com/kovidgoyal/kitty/releases/latest/download"
	}
	url := fmt.Sprintf("%s/kitten-%s-%s", url_base, runtime.GOOS, runtime.GOARCH)
	dest, err := os.CreateTemp(filepath.Dir(exe), "kitten.")
	if err != nil {
		return err
	}
	defer func() { os.Remove(dest.Name()) }()

	if !tty.IsTerminal(os.Stdout.Fd()) {
		fmt.Println("Downloading:", url)
		err = utils.DownloadToFile(exe, url, nil, nil)
		if err != nil {
			return err
		}
		fmt.Println("Downloaded to:", exe)
	} else {
		err = tui.DownloadFileWithProgress(exe, url, true)
		if err != nil {
			return err
		}
	}
	fmt.Print("Updated to: ")
	return unix.Exec(exe, []string{"kitten", "--version"}, os.Environ())
}

func EntryPoint(root *cli.Command) *cli.Command {
	sc := root.AddSubCommand(&cli.Command{
		Name:             "update-self",
		Usage:            "[options]",
		ShortDescription: "Update this kitten binary",
		HelpText:         "Update this kitten binary in place to the latest available version.",
		Run: func(cmd *cli.Command, args []string) (ret int, err error) {
			if len(args) != 0 {
				return 1, fmt.Errorf("No command line arguments are allowed")
			}
			opts := &Options{}
			err = cmd.GetOptionValues(opts)
			if err != nil {
				return 1, err
			}
			return 0, update_self(opts.FetchVersion)
		},
	})
	sc.Add(cli.OptionSpec{
		Name:    "--fetch-version",
		Default: "latest",
		Help:    fmt.Sprintf("The version to fetch. The special words :code:`latest` and :code:`nightly` fetch the latest stable and nightly release respectively. Other values can be, for example: :code:`%s`.", kitty.VersionString),
	})
	return sc
}
