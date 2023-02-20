// License: GPLv3 Copyright: 2023, Kovid Goyal, <kovid at kovidgoyal.net>

package ssh

import (
	"encoding/json"
	"errors"
	"fmt"
	"io/fs"
	"net/url"
	"os"
	"os/user"
	"strings"

	"kitty/tools/cli"
	"kitty/tools/tty"
	"kitty/tools/utils/shm"

	"golang.org/x/exp/maps"
	"golang.org/x/sys/unix"
)

var _ = fmt.Print

func get_destination(hostname string) (username, hostname_for_match string) {
	u, err := user.Current()
	if err == nil {
		username = u.Username
	}
	hostname_for_match = hostname
	if strings.HasPrefix(hostname, "ssh://") {
		p, err := url.Parse(hostname)
		if err == nil {
			hostname_for_match = p.Hostname()
			if p.User.Username() != "" {
				username = p.User.Username()
			}
		}
	} else if strings.Contains(hostname, "@") && hostname[0] != '@' {
		username, hostname_for_match, _ = strings.Cut(hostname, "@")
	}
	if strings.Contains(hostname, "@") && hostname[0] != '@' {
		_, hostname_for_match, _ = strings.Cut(hostname_for_match, "@")
	}
	hostname_for_match, _, _ = strings.Cut(hostname_for_match, ":")
	return
}

func read_data_from_shared_memory(shm_name string) ([]byte, error) {
	data, err := shm.ReadWithSizeAndUnlink(shm_name, func(f *os.File) error {
		s, err := f.Stat()
		if err != nil {
			return fmt.Errorf("Failed to stat SHM file with error: %w", err)
		}
		if stat, ok := s.Sys().(unix.Stat_t); ok {
			if os.Getuid() != int(stat.Uid) || os.Getgid() != int(stat.Gid) {
				return fmt.Errorf("Incorrect owner on SHM file")
			}
		}
		if s.Mode().Perm() != 0o600 {
			return fmt.Errorf("Incorrect permissions on SHM file")
		}
		return nil
	})
	return data, err
}

func add_cloned_env(val string) (ans map[string]string, err error) {
	data, err := read_data_from_shared_memory(val)
	if err != nil {
		return nil, err
	}
	err = json.Unmarshal(data, &ans)
	return ans, err
}

func parse_kitten_args(found_extra_args []string, username, hostname_for_match string) (overrides []string, literal_env map[string]string, ferr error) {
	literal_env = make(map[string]string)
	overrides = make([]string, 0, 4)
	for i, a := range found_extra_args {
		if i%2 == 0 {
			continue
		}
		if key, val, found := strings.Cut(a, "="); found {
			if key == "clone_env" {
				le, err := add_cloned_env(val)
				if err != nil {
					if !errors.Is(err, fs.ErrNotExist) {
						return nil, nil, ferr
					}
				} else if le != nil {
					literal_env = le
				}
			} else if key != "hostname" {
				overrides = append(overrides, key+" "+val)
			}
		}
	}
	if len(overrides) > 0 {
		overrides = append([]string{"hostname " + username + "@" + hostname_for_match}, overrides...)
	}
	return
}

func run_ssh(ssh_args, server_args, found_extra_args []string) (rc int, err error) {
	cmd := append([]string{ssh_exe()}, ssh_args...)
	hostname, remote_args := server_args[0], server_args[1:]
	if len(remote_args) == 0 {
		cmd = append(cmd, "-t")
	}
	insertion_point := len(cmd)
	cmd = append(cmd, "--", hostname)
	uname, hostname_for_match := get_destination(hostname)
	overrides, literal_env, err := parse_kitten_args(found_extra_args, uname, hostname_for_match)
	if err != nil {
		return 1, err
	}
	if insertion_point > 0 && overrides != nil && literal_env != nil {
	}
	// TODO: Implement me
	return
}

func main(cmd *cli.Command, o *Options, args []string) (rc int, err error) {
	if len(args) > 0 {
		switch args[0] {
		case "use-python":
			args = args[1:] // backwards compat from when we had a python implementation
		case "-h", "--help":
			cmd.ShowHelp()
			return
		}
	}
	ssh_args, server_args, passthrough, found_extra_args, err := ParseSSHArgs(args, "--kitten")
	if err != nil {
		var invargs *ErrInvalidSSHArgs
		switch {
		case errors.As(err, &invargs):
			if invargs.Msg != "" {
				fmt.Fprintln(os.Stderr, invargs.Msg)
			}
			return 1, unix.Exec(ssh_exe(), []string{"ssh"}, os.Environ())
		}
		return 1, err
	}
	if passthrough {
		if len(found_extra_args) > 0 {
			return 1, fmt.Errorf("The SSH kitten cannot work with the options: %s", strings.Join(maps.Keys(PassthroughArgs()), " "))
		}
		return 1, unix.Exec(ssh_exe(), append([]string{"ssh"}, args...), os.Environ())
	}
	if os.Getenv("KITTY_WINDOW_ID") == "" || os.Getenv("KITTY_PID") == "" {
		return 1, fmt.Errorf("The SSH kitten is meant to run inside a kitty window")
	}
	if !tty.IsTerminal(os.Stdin.Fd()) {
		return 1, fmt.Errorf("The SSH kitten is meant for interactive use only, STDIN must be a terminal")
	}
	return run_ssh(ssh_args, server_args, found_extra_args)
}

func EntryPoint(parent *cli.Command) {
	create_cmd(parent, main)
}

func specialize_command(ssh *cli.Command) {
	ssh.Usage = "arguments for the ssh command"
	ssh.ShortDescription = "Truly convenient SSH"
	ssh.HelpText = "The ssh kitten is a thin wrapper around the ssh command. It automatically enables shell integration on the remote host, re-uses existing connections to reduce latency, makes the kitty terminfo database available, etc. It's invocation is identical to the ssh command. For details on its usage, see :doc:`/kittens/ssh`."
	ssh.IgnoreAllArgs = true
	ssh.OnlyArgsAllowed = true
	ssh.ArgCompleter = cli.CompletionForWrapper("ssh")
}
