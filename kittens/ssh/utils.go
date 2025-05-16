// License: GPLv3 Copyright: 2023, Kovid Goyal, <kovid at kovidgoyal.net>

package ssh

import (
	"bytes"
	"fmt"
	"os/exec"
	"regexp"
	"strconv"
	"strings"
	"sync"

	"github.com/kovidgoyal/kitty"
	"github.com/kovidgoyal/kitty/tools/config"
	"github.com/kovidgoyal/kitty/tools/utils"
)

var _ = fmt.Print

var SSHExe = sync.OnceValue(func() string {
	return utils.FindExe("ssh")
})

var SSHOptions = sync.OnceValue(func() (ssh_options map[string]string) {
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
	cmd := exec.Command(SSHExe())
	var stdout, stderr bytes.Buffer
	cmd.Stdout = &stdout
	cmd.Stderr = &stderr
	_ = cmd.Run()

	text := stderr.String()
	if text == "" || strings.Contains(text, "OpenSSL version mismatch.") {
		// https://bugzilla.mindrot.org/show_bug.cgi?id=3548
		return
	}
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
	return
})

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
	return map[string]bool{"-N": true, "-n": true, "-f": true, "-G": true, "-T": true, "-V": true}
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

type SSHVersion struct{ Major, Minor int }

func (self SSHVersion) SupportsAskpassRequire() bool {
	return self.Major > 8 || (self.Major == 8 && self.Minor >= 4)
}

var GetSSHVersion = sync.OnceValue(func() SSHVersion {
	b, err := exec.Command(SSHExe(), "-V").CombinedOutput()
	if err != nil {
		return SSHVersion{}
	}
	m := regexp.MustCompile(`OpenSSH_(\d+).(\d+)`).FindSubmatch(b)
	if len(m) == 3 {
		maj, _ := strconv.Atoi(utils.UnsafeBytesToString(m[1]))
		min, _ := strconv.Atoi(utils.UnsafeBytesToString(m[2]))
		return SSHVersion{Major: maj, Minor: min}
	}
	return SSHVersion{}
})

type KittyOpts struct {
	Term, Shell_integration string
}

func read_relevant_kitty_opts(override_conf_path ...string) KittyOpts {
	ans := KittyOpts{Term: kitty.KittyConfigDefaults.Term, Shell_integration: kitty.KittyConfigDefaults.Shell_integration}
	handle_line := func(key, val string) error {
		switch key {
		case "term":
			ans.Term = strings.TrimSpace(val)
		case "shell_integration":
			ans.Shell_integration = strings.TrimSpace(val)
		}
		return nil
	}
	config.ReadKittyConfig(handle_line, override_conf_path...)
	return ans
}

var RelevantKittyOpts = sync.OnceValue(func() KittyOpts {
	return read_relevant_kitty_opts()
})
