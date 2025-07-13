// License: GPLv3 Copyright: 2022, Kovid Goyal, <kovid at kovidgoyal.net>

package clipboard

import (
	"fmt"
	"io"
	"os"
	"strconv"
	"strings"
	"unicode"

	"github.com/kovidgoyal/kitty/tools/cli"
)

func run_mime_loop(opts *Options, args []string) (err error) {
	cwd, err = os.Getwd()
	if err != nil {
		return err
	}
	if opts.GetClipboard {
		return run_get_loop(opts, args)
	}
	return run_set_loop(opts, args)
}

func clipboard_main(cmd *cli.Command, opts *Options, args []string) (rc int, err error) {
	if opts.Password != "" {
		if opts.HumanName == "" {
			return 1, fmt.Errorf("must specify --human-name when using a password")
		}
		ptype, val, found := strings.Cut(opts.Password, ":")
		if !found {
			return 1, fmt.Errorf("invalid password: %#v no password type specified", opts.Password)
		}
		switch ptype {
		case "text":
			opts.Password = val
		case "fd":
			if fd, err := strconv.Atoi(val); err == nil {
				if f := os.NewFile(uintptr(fd), "password-fd"); f == nil {
					return 1, fmt.Errorf("invalid file descriptor: %d", fd)
				} else {
					data, err := io.ReadAll(f)
					f.Close()
					if err != nil {
						return 1, fmt.Errorf("failed to read from file descriptor: %d with error: %w", fd, err)
					}
					opts.Password = strings.TrimRightFunc(string(data), unicode.IsSpace)
				}

			} else {
				return 1, fmt.Errorf("not a valid file descriptor number: %#v", val)
			}
		case "file":
			if data, err := os.ReadFile(val); err == nil {
				opts.Password = strings.TrimRightFunc(string(data), unicode.IsSpace)
			} else {
				return 1, fmt.Errorf("failed to read from file: %#v with error: %w", val, err)
			}
		}
	}
	if len(args) > 0 {
		return 0, run_mime_loop(opts, args)
	}
	if opts.Password != "" || opts.HumanName != "" {
		return 1, fmt.Errorf("cannot use --human-name or --password in filter mode")
	}
	return 0, run_plain_text_loop(opts)
}

func EntryPoint(parent *cli.Command) {
	create_cmd(parent, clipboard_main)
}
