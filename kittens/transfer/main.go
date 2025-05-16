// License: GPLv3 Copyright: 2023, Kovid Goyal, <kovid at kovidgoyal.net>

package transfer

import (
	"fmt"
	"io"
	"os"
	"strconv"
	"strings"

	"github.com/kovidgoyal/kitty/tools/cli"
	"github.com/kovidgoyal/kitty/tools/utils"
)

var _ = fmt.Print

func read_bypass(loc string) (string, error) {
	if loc == "" {
		return "", nil
	}
	fdnum, err := strconv.Atoi(loc)
	if err == nil && fdnum >= 0 && fdnum < 256 && loc[0] >= '0' && loc[0] <= '9' {
		file := os.NewFile(uintptr(fdnum), loc)
		defer file.Close()
		raw, err := io.ReadAll(file)
		return utils.UnsafeBytesToString(raw), err
	}
	if loc == "-" {
		raw, err := io.ReadAll(os.Stdin)
		defer os.Stdin.Close()
		return utils.UnsafeBytesToString(raw), err
	}
	switch loc[0] {
	case '.', '~', '/':
		if loc[0] == '~' {
			loc = utils.Expanduser(loc)
		}
		raw, err := os.ReadFile(loc)
		return utils.UnsafeBytesToString(raw), err
	default:
		return loc, nil
	}
}

func main(cmd *cli.Command, opts *Options, args []string) (rc int, err error) {
	if opts.PermissionsBypass != "" {
		val, err := read_bypass(opts.PermissionsBypass)
		if err != nil {
			return 1, err
		}
		opts.PermissionsBypass = strings.TrimSpace(val)
	}
	if len(args) == 0 {
		return 1, fmt.Errorf("Must specify at least one file to transfer")
	}
	switch opts.Direction {
	case "send", "download":
		err, rc = send_main(opts, args)
	default:
		err, rc = receive_main(opts, args)
	}
	if err != nil {
		rc = 1
	}
	return
}

func EntryPoint(parent *cli.Command) {
	create_cmd(parent, main)
}
