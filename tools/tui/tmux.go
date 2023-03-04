// License: GPLv3 Copyright: 2023, Kovid Goyal, <kovid at kovidgoyal.net>

package tui

import (
	"errors"
	"fmt"
	"kitty/tools/utils"
	"os"
	"os/exec"
	"path/filepath"
	"strconv"
	"strings"
	"time"

	"github.com/shirou/gopsutil/v3/process"
	"golang.org/x/sys/unix"
)

var _ = fmt.Print

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
	c := exec.Command("tmux", "show", "-Ap", "allow-passthrough")
	allowed, not_allowed := errors.New("allowed"), errors.New("not allowed")
	get_result := make(chan error)
	go func() {
		output, err := c.Output()
		if err != nil {
			get_result <- err
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
		return exec.Command("tmux", "set", "-p", "allow-passthrough", "on").Run()
	case <-time.After(2 * time.Second):
		return fmt.Errorf("Tmux command timed out. This often happens when the version of tmux on your PATH is older than the version of the running tmux server")
	}
}

var TmuxAllowPassthrough = (&utils.Once[error]{Run: tmux_allow_passthrough}).Get
