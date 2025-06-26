// License: GPLv3 Copyright: 2023, Kovid Goyal, <kovid at kovidgoyal.net>

package tui

import (
	"fmt"
	"github.com/kovidgoyal/kitty"
	"os"
	"os/exec"
	"os/signal"
	"path/filepath"
	"runtime"
	"strings"
	"sync"

	"github.com/shirou/gopsutil/v3/process"
	"golang.org/x/sys/unix"

	"github.com/kovidgoyal/kitty/tools/config"
	"github.com/kovidgoyal/kitty/tools/tty"
	"github.com/kovidgoyal/kitty/tools/tui/loop"
	"github.com/kovidgoyal/kitty/tools/tui/shell_integration"
	"github.com/kovidgoyal/kitty/tools/utils"
	"github.com/kovidgoyal/kitty/tools/utils/shlex"
)

var _ = fmt.Print

type KittyOpts struct {
	Shell, Shell_integration string
}

func read_relevant_kitty_opts() KittyOpts {
	ans := KittyOpts{Shell: kitty.KittyConfigDefaults.Shell, Shell_integration: kitty.KittyConfigDefaults.Shell_integration}
	handle_line := func(key, val string) error {
		switch key {
		case "shell":
			ans.Shell = strings.TrimSpace(val)
		case "shell_integration":
			ans.Shell_integration = strings.TrimSpace(val)
		}
		return nil
	}
	config.ReadKittyConfig(handle_line)
	if ans.Shell == "" {
		ans.Shell = kitty.KittyConfigDefaults.Shell
	}
	return ans
}

func get_effective_ksi_env_var(x string) string {
	parts := strings.Split(strings.TrimSpace(strings.ToLower(x)), " ")
	current := utils.NewSetWithItems(parts...)
	if current.Has("disabled") {
		return ""
	}
	allowed := utils.NewSetWithItems(kitty.AllowedShellIntegrationValues...)
	if !current.IsSubsetOf(allowed) {
		return relevant_kitty_opts().Shell_integration
	}
	return x
}

var relevant_kitty_opts = sync.OnceValue(func() KittyOpts {
	return read_relevant_kitty_opts()
})

func get_shell_from_kitty_conf() (shell string) {
	shell = relevant_kitty_opts().Shell
	if shell == "." {
		s, e := utils.LoginShellForCurrentUser()
		if e != nil {
			shell = "/bin/sh"
		} else {
			shell = s
		}
	}
	return
}

func find_shell_parent_process() string {
	var p *process.Process
	var err error
	for {
		if p == nil {
			p, err = process.NewProcess(int32(os.Getppid()))
		} else {
			p, err = p.Parent()
		}
		if err != nil {
			return ""
		}
		if cmdline, err := p.CmdlineSlice(); err == nil && len(cmdline) > 0 {
			exe := get_shell_name(filepath.Base(cmdline[0]))
			if shell_integration.IsSupportedShell(exe) {
				return exe
			}
		}
	}
}

func ResolveShell(shell string) []string {
	switch shell {
	case "":
		shell = get_shell_from_kitty_conf()
	case ".":
		if shell = find_shell_parent_process(); shell == "" {
			shell = get_shell_from_kitty_conf()
		}
	}
	shell_cmd, err := shlex.Split(shell)
	if err != nil {
		shell_cmd = []string{shell}
	}
	exe := utils.FindExe(shell_cmd[0])
	if unix.Access(exe, unix.X_OK) != nil {
		shell_cmd = []string{"/bin/sh"}
	}
	return shell_cmd
}

func ResolveShellIntegration(shell_integration string) string {
	if shell_integration == "" {
		shell_integration = relevant_kitty_opts().Shell_integration
	}
	return get_effective_ksi_env_var(shell_integration)
}

func get_shell_name(argv0 string) (ans string) {
	ans = filepath.Base(argv0)
	if strings.HasSuffix(strings.ToLower(ans), ".exe") {
		ans = ans[:len(ans)-4]
	}
	return strings.TrimPrefix(ans, "-")
}

func rc_modification_allowed(ksi string) (allowed bool, set_ksi_env_var bool) {
	allowed = ksi != ""
	set_ksi_env_var = true
	for _, x := range strings.Split(ksi, " ") {
		switch x {
		case "disabled":
			allowed = false
			set_ksi_env_var = false
		case "no-rc":
			allowed = false
		}
	}
	return
}

func copy_os_env_as_dict() map[string]string {
	oenv := os.Environ()
	env := make(map[string]string, len(oenv))
	for _, x := range oenv {
		if k, v, found := strings.Cut(x, "="); found {
			env[k] = v
		}
	}
	return env
}

func RunShell(shell_cmd []string, shell_integration_env_var_val, cwd string) (err error) {
	shell_name := get_shell_name(shell_cmd[0])
	var shell_env map[string]string
	if shell_integration.IsSupportedShell(shell_name) {
		rc_mod_allowed, set_ksi_env_var := rc_modification_allowed(shell_integration_env_var_val)
		if rc_mod_allowed {
			// KITTY_SHELL_INTEGRATION is always set by this function
			argv, env, err := shell_integration.Setup(shell_name, shell_integration_env_var_val, shell_cmd, copy_os_env_as_dict())
			if err != nil {
				return err
			}
			shell_cmd = argv
			shell_env = env
		} else if set_ksi_env_var {
			shell_env = copy_os_env_as_dict()
			shell_env["KITTY_SHELL_INTEGRATION"] = shell_integration_env_var_val
		}
	}
	exe := shell_cmd[0]
	if runtime.GOOS == "darwin" && (os.Getenv("KITTY_RUNNING_SHELL_INTEGRATION_TEST") != "1" || os.Getenv("KITTY_RUNNING_BASH_INTEGRATION_TEST") != "") {
		// ensure shell runs in login mode. On macOS lots of people use ~/.bash_profile instead of ~/.bashrc
		// which means they expect the shell to run in login mode always. Le Sigh.
		shell_cmd[0] = "-" + filepath.Base(shell_cmd[0])
	}
	var env []string
	if shell_env != nil {
		env = make([]string, 0, len(shell_env))
		for k, v := range shell_env {
			env = append(env, fmt.Sprintf("%s=%s", k, v))
		}
	} else {
		env = os.Environ()
	}
	// fmt.Println(fmt.Sprintf("%s %v\n%#v", utils.FindExe(exe), shell_cmd, env))
	if cwd != "" {
		_ = os.Chdir(cwd)
	}
	return unix.Exec(utils.FindExe(exe), shell_cmd, env)
}

var debugprintln = tty.DebugPrintln
var _ = debugprintln

func RunCommandRestoringTerminalToSaneStateAfter(cmd []string) {
	exe := utils.FindExe(cmd[0])
	c := exec.Command(exe, cmd[1:]...)
	c.Stdout = os.Stdout
	c.Stdin = os.Stdin
	c.Stderr = os.Stderr
	term, err := tty.OpenControllingTerm()
	if err == nil {
		var state_before unix.Termios
		if term.Tcgetattr(&state_before) == nil {
			if _, err = term.WriteString(loop.SAVE_PRIVATE_MODE_VALUES); err != nil {
				fmt.Fprintln(os.Stderr, "failed to write to controlling terminal with error:", err)
				return
			}
			defer func() {
				_, _ = term.WriteString(strings.Join([]string{
					loop.RESTORE_PRIVATE_MODE_VALUES,
					"\x1b[=u", // reset kitty keyboard protocol to legacy
					"\x1bP@kitty-restore-cursor-appearance|\a",
				}, ""))
				_ = term.Tcsetattr(tty.TCSANOW, &state_before)
				term.Close()
			}()
		} else {
			defer term.Close()
		}
	}
	// Ignore SIGINT as the kernel tends to send it to us as well as the
	// subprocess on Ctrl+C. We cant use signal.Ignore as it doesnt reset
	// sigprocmask so subsequent unix.Exec will inherit blocked SIGINT
	ignore_sigint_channel := make(chan os.Signal, 512)
	if err = c.Start(); err != nil {
		fmt.Fprintln(os.Stderr, cmd[0], "failed to start with error:", err)
		return
	}
	signal.Notify(ignore_sigint_channel, os.Interrupt)
	err = c.Wait()
	signal.Reset(os.Interrupt)
	if err != nil {
		fmt.Fprintln(os.Stderr, cmd[0], "failed with error:", err)
	}
}
