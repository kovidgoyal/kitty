// License: GPLv3 Copyright: 2023, Kovid Goyal, <kovid at kovidgoyal.net>

package ssh

import (
	"fmt"
	"io"
	"kitty/tools/utils"
	"os/exec"
	"strings"
	"sync"
)

var _ = fmt.Print

var ssh_options map[string]string
var query_ssh_for_options_once sync.Once

func get_ssh_options() {
	defer func() {
		if ssh_options == nil {
			ssh_options = map[string]string{
				"4": "", "6": "", "A": "", "a": "", "C": "", "f": "", "G": "", "g": "", "K": "", "k": "",
				"M": "", "N": "", "n": "", "q": "", "s": "", "T": "", "t": "", "V": "", "v": "", "X": "",
				"x": "", "Y": "", "y": "", "B": "bind_interface", "b": "bind_address", "c": "cipher_spec",
				"D": "[bind_address:]port", "E": "log_file", "e": "escape_char", "F": "configfile", "I": "pkcs11",
				"i": "identity_file", "J": "[user@]host[:port]", "L": "address", "l": "login_name", "m": "mac_spec",
				"O": "ctl_cmd", "o": "option", "p": "port", "Q": "query_option", "R": "address",
				"S": "ctl_path", "W": "host:port", "w": "local_tun[:remote_tun]",
			}
		}
	}()
	cmd := exec.Command("ssh")
	stderr, err := cmd.StderrPipe()
	if err != nil {
		return
	}
	if err := cmd.Start(); err != nil {
		return
	}
	raw, err := io.ReadAll(stderr)
	if err != nil {
		return
	}
	text := utils.UnsafeBytesToString(raw)
	ssh_options = make(map[string]string, 32)
	for {
		pos := strings.IndexByte(text, '[')
		if pos < 0 {
			break
		}
		num := 1
		epos := pos
		for num > 0 {
			epos++
			switch text[epos] {
			case '[':
				num += 1
			case ']':
				num -= 1
			}
		}
		q := text[pos+1 : epos]
		text = text[epos:]
		if len(q) < 2 || !strings.HasPrefix(q, "-") {
			continue
		}
		opt, desc, found := strings.Cut(q, " ")
		if found {
			ssh_options[opt[1:]] = desc
		} else {
			for _, ch := range opt[1:] {
				ssh_options[string(ch)] = ""
			}
		}
	}
}

func SSHOptions() map[string]string {
	query_ssh_for_options_once.Do(get_ssh_options)
	return ssh_options
}
