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

func ssh_exe() string {
	ans := utils.Which("ssh")
	if ans != "" {
		return ans
	}
	ans = utils.Which("ssh", "/usr/local/bin", "/opt/bin", "/opt/homebrew/bin", "/usr/bin", "/bin")
	if ans == "" {
		ans = "ssh"
	}
	return ans
}

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
	cmd := exec.Command(ssh_exe())
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

func GetSSHCLI() (boolean_ssh_args *utils.Set[string], other_ssh_args *utils.Set[string]) {
	other_ssh_args, boolean_ssh_args = utils.NewSet[string](32), utils.NewSet[string](32)
	for k, v := range SSHOptions() {
		k = "-" + k
		if v == "" {
			boolean_ssh_args.Add(k)
		} else {
			other_ssh_args.Add(k)
		}
	}
	return
}

func is_extra_arg(arg string, extra_args []string) string {
	for _, x := range extra_args {
		if arg == x || strings.HasPrefix(arg, x+"=") {
			return x
		}
	}
	return ""
}

type ErrInvalidSSHArgs struct {
	Msg string
}

func (self *ErrInvalidSSHArgs) Error() string {
	return self.Msg
}

func PassthroughArgs() map[string]bool {
	return map[string]bool{"-N": true, "-n": true, "-f": true, "-G": true, "-T": true}
}

func ParseSSHArgs(args []string, extra_args ...string) (ssh_args []string, server_args []string, passthrough bool, found_extra_args []string, err error) {
	if extra_args == nil {
		extra_args = []string{}
	}
	if len(args) == 0 {
		passthrough = true
		return
	}
	passthrough_args := PassthroughArgs()
	boolean_ssh_args, other_ssh_args := GetSSHCLI()
	ssh_args, server_args, found_extra_args = make([]string, 0, 16), make([]string, 0, 16), make([]string, 0, 16)
	expecting_option_val := false
	stop_option_processing := false
	expecting_extra_val := ""
	for _, argument := range args {
		if len(server_args) > 1 || stop_option_processing {
			server_args = append(server_args, argument)
			continue
		}
		if strings.HasPrefix(argument, "-") && !expecting_option_val {
			if argument == "--" {
				stop_option_processing = true
				continue
			}
			if len(extra_args) > 0 {
				matching_ex := is_extra_arg(argument, extra_args)
				if matching_ex != "" {
					_, exval, found := strings.Cut(argument, "=")
					if found {
						found_extra_args = append(found_extra_args, matching_ex, exval)
					} else {
						expecting_extra_val = matching_ex
						expecting_option_val = true
					}
					continue
				}
			}
			// could be a multi-character option
			all_args := []rune(argument[1:])
			for i, ch := range all_args {
				arg := "-" + string(ch)
				if passthrough_args[arg] {
					passthrough = true
				}
				if boolean_ssh_args.Has(arg) {
					ssh_args = append(ssh_args, arg)
					continue
				}
				if other_ssh_args.Has(arg) {
					ssh_args = append(ssh_args, arg)
					if i+1 < len(all_args) {
						ssh_args = append(ssh_args, string(all_args[i+1:]))
					} else {
						expecting_option_val = true
					}
					break
				}
				err = &ErrInvalidSSHArgs{Msg: "unknown option -- " + arg[1:]}
				return
			}
			continue
		}
		if expecting_option_val {
			if expecting_extra_val != "" {
				found_extra_args = append(found_extra_args, expecting_extra_val, argument)
			} else {
				ssh_args = append(ssh_args, argument)
			}
			expecting_option_val = false
			continue
		}
		server_args = append(server_args, argument)
	}
	if len(server_args) == 0 && !passthrough {
		err = &ErrInvalidSSHArgs{Msg: ""}
	}
	return
}
