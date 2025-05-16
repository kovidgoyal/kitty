// License: GPLv3 Copyright: 2023, Kovid Goyal, <kovid at kovidgoyal.net>

package show_key

import (
	"errors"
	"fmt"
	"github.com/kovidgoyal/kitty/tools/cli/markup"
	"github.com/kovidgoyal/kitty/tools/tty"
	"io"
	"os"

	"golang.org/x/sys/unix"
)

var _ = fmt.Print

func print_key(buf []byte, ctx *markup.Context) {
	const ctrl_keys = "@ABCDEFGHIJKLMNOPQRSTUVWXYZ[\\]^_"
	unix := ""
	send_text := ""
	for _, ch := range buf {
		switch {
		case int(ch) < len(ctrl_keys):
			unix += "^" + ctrl_keys[ch:ch+1]
		case ch == 127:
			unix += "^?"
		default:
			unix += string(rune(ch))
		}
	}
	for _, ch := range string(buf) {
		q := fmt.Sprintf("%#v", string(ch))
		send_text += q[1 : len(q)-1]
	}
	os.Stdout.WriteString(unix + "\t\t")
	os.Stdout.WriteString(ctx.Yellow(send_text) + "\r\n")
}

func run_legacy_loop(opts *Options) (err error) {
	term, err := tty.OpenControllingTerm(tty.SetRaw)
	if err != nil {
		return err
	}
	defer func() {
		term.RestoreAndClose()
	}()
	if opts.KeyMode != "unchanged" {
		os.Stdout.WriteString("\x1b[?1")
		switch opts.KeyMode {
		case "normal":
			os.Stdout.WriteString("l")
		default:
			os.Stdout.WriteString("h")
		}
		defer func() {
			os.Stdout.WriteString("\x1b[?1l")
		}()
	}
	fmt.Print("Press any keys - Ctrl+D will terminate this program\r\n")
	ctx := markup.New(true)
	fmt.Print(ctx.Green("UNIX\t\tsend_text\r\n"))
	buf := make([]byte, 64)
	for {
		n, err := term.Read(buf)
		if err != nil {
			if errors.Is(err, io.EOF) {
				break
			}
			if !(errors.Is(err, unix.EAGAIN) || errors.Is(err, unix.EBUSY)) {
				return err
			}
		}
		if n > 0 {
			print_key(buf[:n], ctx)
			if n == 1 && buf[0] == 4 {
				break
			}
		}
	}
	return
}
