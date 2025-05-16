// License: GPLv3 Copyright: 2023, Kovid Goyal, <kovid at kovidgoyal.net>

package tui

import (
	"errors"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"strconv"
	"strings"
	"sync"
	"time"

	"github.com/shirou/gopsutil/v3/process"
	"golang.org/x/sys/unix"

	"github.com/kovidgoyal/kitty/tools/utils"
)

var _ = fmt.Print

var TmuxExe = sync.OnceValue(func() string {
	return utils.FindExe("tmux")
})

func tmux_socket_address() (socket string) {
	socket = os.Getenv("TMUX")
	if socket == "" {
		return ""
	}
	addr, pid_str, found := strings.Cut(socket, ",")
	if !found {
		return ""
	}
	if unix.Access(addr, unix.R_OK|unix.W_OK) != nil {
		return ""
	}
	pid_str, _, _ = strings.Cut(pid_str, ",")
	pid, err := strconv.ParseInt(pid_str, 10, 32)
	if err != nil {
		return ""
	}
	p, err := process.NewProcess(int32(pid))
	if err != nil {
		return ""
	}
	cmd, err := p.CmdlineSlice()
	if err != nil {
		return ""
	}
	if len(cmd) > 0 && strings.ToLower(filepath.Base(cmd[0])) != "tmux" {
		return ""
	}
	return socket
}

var TmuxSocketAddress = sync.OnceValue(tmux_socket_address)

func tmux_command(args ...string) (c *exec.Cmd, stderr *strings.Builder) {
	c = exec.Command(TmuxExe(), args...)
	stderr = &strings.Builder{}
	c.Stderr = stderr
	return c, stderr
}

func tmux_allow_passthrough() error {
	c, stderr := tmux_command("show", "-Ap", "allow-passthrough")
	allowed, not_allowed := errors.New("allowed"), errors.New("not allowed")
	get_result := make(chan error)
	go func() {
		output, err := c.Output()
		if err != nil {
			get_result <- fmt.Errorf("Running %#v failed with error: %w. STDERR: %s", c.Args, err, stderr.String())
		} else {
			q := strings.TrimSpace(utils.UnsafeBytesToString(output))
			if strings.HasSuffix(q, " on") || strings.HasSuffix(q, " all") {
				get_result <- allowed
			} else {
				get_result <- not_allowed
			}
		}
	}()
	select {
	case r := <-get_result:
		if r == allowed {
			return nil
		}
		if r != not_allowed {
			return r
		}
		c, stderr = tmux_command("set", "-p", "allow-passthrough", "on")
		err := c.Run()
		if err != nil {
			err = fmt.Errorf("Running %#v failed with error: %w. STDERR: %s", c.Args, err, stderr.String())
		}
		return err
	case <-time.After(2 * time.Second):
		return fmt.Errorf("Tmux command timed out. This often happens when the version of tmux on your PATH is older than the version of the running tmux server")
	}
}

var TmuxAllowPassthrough = sync.OnceValue(tmux_allow_passthrough)
