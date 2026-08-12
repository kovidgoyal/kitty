// License: GPLv3 Copyright: 2026, Kovid Goyal, <kovid at kovidgoyal.net>

package remote_file

import (
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"time"

	"github.com/kovidgoyal/kitty/tools/utils/shlex"
)

type ControlMaster struct {
	conn         *SSHConnectionData
	remote_path  string
	tdir         string
	Dest         string
	LastErrorLog string
}

func new_control_master(conn *SSHConnectionData, remote_path, dest string) *ControlMaster {
	return &ControlMaster{conn: conn, remote_path: remote_path, Dest: dest}
}

func (m *ControlMaster) check_call(argv []string) error {
	cmd := exec.Command(argv[0], argv[1:]...)
	cmd.Stdin = nil
	out, err := cmd.CombinedOutput()
	if err != nil {
		return fmt.Errorf("the ssh command: %s failed: %w with output: %s", strings.Join(argv, " "), err, string(out))
	}
	return nil
}

func (m *ControlMaster) Start() (err error) {
	if !m.conn.IsSSHKitten {
		if err = m.check_call(append(m.conn.cmd_prefix(), "-o", "ControlMaster=auto", "-fN", m.conn.Hostname)); err != nil {
			return err
		}
		if err = m.check_call(append(m.conn.batch_cmd_prefix(), "-O", "check", m.conn.Hostname)); err != nil {
			return err
		}
	}
	if m.Dest == "" {
		if m.tdir, err = os.MkdirTemp("", "kitty-remote-file"); err != nil {
			return err
		}
		m.Dest = filepath.Join(m.tdir, filepath.Base(m.remote_path))
	}
	return nil
}

func (m *ControlMaster) Close() {
	if !m.conn.IsSSHKitten {
		argv := append(m.conn.batch_cmd_prefix(), "-O", "exit", m.conn.Hostname)
		cmd := exec.Command(argv[0], argv[1:]...)
		cmd.Stdin, cmd.Stdout, cmd.Stderr = nil, nil, nil
		_ = cmd.Run()
	}
	if m.tdir != "" {
		_ = os.RemoveAll(m.tdir)
	}
}

func (m *ControlMaster) IsAlive() bool {
	if m.conn.IsSSHKitten {
		return true
	}
	argv := append(m.conn.batch_cmd_prefix(), "-O", "check", m.conn.Hostname)
	return exec.Command(argv[0], argv[1:]...).Run() == nil
}

func (m *ControlMaster) Download() error {
	argv := append(m.conn.batch_cmd_prefix(), m.conn.Hostname, "cat", shlex.Quote(m.remote_path))
	f, err := os.Create(m.Dest)
	if err != nil {
		return err
	}
	defer f.Close()
	cmd := exec.Command(argv[0], argv[1:]...)
	cmd.Stdout = f
	var stderr strings.Builder
	cmd.Stderr = &stderr
	if err := cmd.Run(); err != nil {
		m.LastErrorLog = fmt.Sprintf("The command: %s failed\n%s", strings.Join(argv, " "), stderr.String())
		return err
	}
	return nil
}

func (m *ControlMaster) Upload(suppress_output bool) error {
	prefix := m.conn.cmd_prefix()
	if !suppress_output {
		prefix = m.conn.batch_cmd_prefix()
	}
	argv := append(prefix, m.conn.Hostname, "cat", ">", shlex.Quote(m.remote_path))
	if !suppress_output {
		fmt.Println(strings.Join(argv, " "))
	}
	f, err := os.Open(m.Dest)
	if err != nil {
		return err
	}
	defer f.Close()
	cmd := exec.Command(argv[0], argv[1:]...)
	cmd.Stdin = f
	if suppress_output {
		out, err := cmd.CombinedOutput()
		if err != nil {
			m.LastErrorLog = fmt.Sprintf("The command: %s failed\n%s", strings.Join(argv, " "), string(out))
			return err
		}
		return nil
	}
	cmd.Stdout, cmd.Stderr = os.Stdout, os.Stderr
	return cmd.Run()
}

// remote_hostname returns the remote machine's `hostname -f` output, or "" on failure.
// Mirrors Python's check_hostname_matches: strip the combined output, split on
// lines, drop empty lines, and take the last non-empty line.
func (m *ControlMaster) remote_hostname() string {
	if m.conn.IsSSHKitten {
		return ""
	}
	argv := append(m.conn.batch_cmd_prefix(), m.conn.Hostname, "hostname", "-f")
	out, err := exec.Command(argv[0], argv[1:]...).Output()
	if err != nil {
		return ""
	}
	last := ""
	for _, line := range strings.Split(strings.TrimSpace(string(out)), "\n") {
		line = strings.TrimSpace(line)
		if line != "" {
			last = line
		}
	}
	return last
}

// get_editor mirrors kitty/utils.py:get_editor_from_env_vars: check $VISUAL then
// $EDITOR (shlex-split), then fall back to the first available editor from the
// exact candidate list used there, defaulting to "vim" if none are found on PATH.
func get_editor() []string {
	for _, env := range []string{"VISUAL", "EDITOR"} {
		if v := os.Getenv(env); v != "" {
			if parts, err := shlex.Split(v); err == nil && len(parts) > 0 {
				return parts
			}
		}
	}
	// Exact candidate list from kitty/utils.py get_editor_from_env_vars.
	for _, e := range []string{"vim", "nvim", "vi", "emacs", "hx", "kak", "micro", "nano", "vis"} {
		if p, err := exec.LookPath(e); err == nil {
			return []string{p}
		}
	}
	return []string{"vim"}
}

func edit_loop(master *ControlMaster, editor []string) error {
	st, err := os.Stat(master.Dest)
	if err != nil {
		return err
	}
	mtime := st.ModTime()
	argv := append(append([]string{}, editor...), master.Dest)
	cmd := exec.Command(argv[0], argv[1:]...)
	cmd.Stdin, cmd.Stdout, cmd.Stderr = os.Stdin, os.Stdout, os.Stderr
	if err := cmd.Start(); err != nil {
		return err
	}
	done := make(chan error, 1)
	go func() { done <- cmd.Wait() }()
	for {
		select {
		case <-done:
			if master.IsAlive() {
				if err := master.Upload(false); err != nil {
					return fmt.Errorf("failed to upload %s: %w", master.remote_path, err)
				}
				return nil
			}
			return fmt.Errorf("failed to upload %s, SSH master process died", master.remote_path)
		case <-time.After(100 * time.Millisecond):
			if st, err := os.Stat(master.Dest); err == nil && st.ModTime().After(mtime) {
				mtime = st.ModTime()
				if master.IsAlive() {
					_ = master.Upload(true)
				}
			}
		}
	}
}
