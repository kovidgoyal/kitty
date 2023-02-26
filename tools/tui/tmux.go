// License: GPLv3 Copyright: 2023, Kovid Goyal, <kovid at kovidgoyal.net>

package tui

import (
	"fmt"
	"kitty/tools/utils"
	"os"
	"os/exec"
	"path/filepath"
	"strconv"
	"strings"

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
	return exec.Command("tmux", "set", "-p", "allow-passthrough", "on").Run()
}

var TmuxAllowPassthrough = (&utils.Once[error]{Run: tmux_allow_passthrough}).Get
