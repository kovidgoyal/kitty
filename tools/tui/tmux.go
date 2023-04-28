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
	"time"

	"github.com/shirou/gopsutil/v3/process"
	"golang.org/x/sys/unix"

	"kitty/tools/utils"
)

var _ = fmt.Print

var TmuxExe = (&utils.Once[string]{Run: func() string {
	return utils.FindExe("tmux")
}}).Get

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

var TmuxSocketAddress = (&utils.Once[string]{Run: tmux_socket_address}).Get

func tmux_allow_passthrough() error {
	cmd := []string{TmuxExe(), "show", "-Ap", "allow-passthrough"}
	c := exec.Command(cmd[0], cmd[1:]...)
	allowed, not_allowed := errors.New("allowed"), errors.New("not allowed")
	get_result := make(chan error)
	go func() {
		output, err := c.Output()
		if err != nil {
			get_result <- fmt.Errorf("Running %s failed with error: %w", strings.Join(cmd, " "), err)
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
		cmd := []string{TmuxExe(), "set", "-p", "allow-passthrough", "on"}
		err := exec.Command(cmd[0], cmd[1:]...).Run()
		if err != nil {
			err = fmt.Errorf("Running %s failed with error: %w", strings.Join(cmd, " "), err)
		}
		return err
	case <-time.After(2 * time.Second):
		return fmt.Errorf("Tmux command timed out. This often happens when the version of tmux on your PATH is older than the version of the running tmux server")
	}
}

var TmuxAllowPassthrough = (&utils.Once[error]{Run: tmux_allow_passthrough}).Get
