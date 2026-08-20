// License: GPLv3 Copyright: 2026, Kovid Goyal, <kovid at kovidgoyal.net>

package remote_file

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"strings"
)

// Must match kittens/remote_file/main.py is_ssh_kitten_sentinel
const is_ssh_kitten_sentinel = `!#*&$#($ssh-kitten)(##$`

type SSHConnectionData struct {
	Binary           string
	Hostname         string
	Port             int
	IdentityFile     string
	IsSSHKitten      bool
	SSHKittenCmdline []string
}

func parse_conn_data(raw string) (*SSHConnectionData, error) {
	var items []any
	if err := json.Unmarshal([]byte(raw), &items); err != nil {
		return nil, fmt.Errorf("invalid --ssh-connection-data: %w", err)
	}
	if len(items) < 2 {
		return nil, fmt.Errorf("invalid --ssh-connection-data: need at least binary and hostname")
	}
	first, _ := items[0].(string)
	ans := &SSHConnectionData{}
	if first == is_ssh_kitten_sentinel {
		// Python: SSHConnectionData(sentinel, cli_data[-1], -1, identity_file=json.dumps(cli_data[1:]))
		// with the cmdline stripped of -t flags and its last two items.
		ans.IsSSHKitten = true
		ans.Hostname, _ = items[len(items)-1].(string)
		cmdline := make([]string, 0, len(items)-1)
		for _, x := range items[1:] {
			s, _ := x.(string)
			if s != "-t" {
				cmdline = append(cmdline, s)
			}
		}
		// Python: sk_cmdline[:-2] always removes last 2, or returns empty if fewer items
		if len(cmdline) >= 2 {
			cmdline = cmdline[:len(cmdline)-2]
		} else {
			cmdline = cmdline[:0]
		}
		ans.SSHKittenCmdline = cmdline
		return ans, nil
	}
	ans.Binary = first
	ans.Hostname, _ = items[1].(string)
	if len(items) > 2 {
		if p, ok := items[2].(float64); ok {
			ans.Port = int(p)
		}
	}
	if len(items) > 3 {
		ans.IdentityFile, _ = items[3].(string)
	}
	return ans, nil
}

func (c *SSHConnectionData) cmd_prefix() []string {
	if c.IsSSHKitten {
		return append([]string{}, c.SSHKittenCmdline...)
	}
	ans := []string{
		c.Binary, "-o", fmt.Sprintf("ControlPath=~/.ssh/kitty-rf-%d-%%C", os.Getpid()),
		"-o", "TCPKeepAlive=yes", "-o", "ControlPersist=yes",
	}
	if c.Port > 0 {
		ans = append(ans, "-p", fmt.Sprint(c.Port))
	}
	if c.IdentityFile != "" {
		ans = append(ans, "-i", c.IdentityFile)
	}
	return ans
}

func (c *SSHConnectionData) batch_cmd_prefix() []string {
	if c.IsSSHKitten {
		return c.cmd_prefix()
	}
	return append(c.cmd_prefix(), "-o", "BatchMode=yes")
}

func hostname_matches(from_hyperlink, actual string) bool {
	if from_hyperlink == actual {
		return true
	}
	fl, _, _ := strings.Cut(from_hyperlink, ".")
	al, _, _ := strings.Cut(actual, ".")
	return fl == al
}

// pythonSplitExt mirrors Python's os.path.splitext behavior exactly.
// Algorithm: skip all leading dots in basename; find last dot in remainder;
// if found, split at that dot; otherwise no extension.
// Examples:
//   "/x/.bashrc" → ("/x/.bashrc", "")          [1 leading dot, no dot in remainder]
//   "/x/.bashrc.bak" → ("/x/.bashrc", ".bak") [1 leading dot, 1 dot in remainder]
//   "/x/a.b.c" → ("/x/a.b", ".c")             [0 leading dots, last dot at position 3]
//   "....txt" → ("....txt", "")                [4 leading dots, no dot in remainder]
func pythonSplitExt(path string) (string, string) {
	basename := filepath.Base(path)
	dir := filepath.Dir(path)

	// Skip all leading dots in basename
	i := 0
	for i < len(basename) && basename[i] == '.' {
		i++
	}

	// Find the last dot in the remainder (after leading dots)
	remainder := basename[i:]
	idx := strings.LastIndex(remainder, ".")

	if idx == -1 {
		// No extension found
		return path, ""
	}

	// Extension starts at position i + idx in the original basename
	extStart := i + idx
	baseName := basename[:extStart]
	ext := basename[extStart:]

	// Reconstruct the full path
	if dir == "." {
		return baseName, ext
	}
	return filepath.Join(dir, baseName), ext
}

func auto_rename_dest(dest string, exists func(string) bool) string {
	q := dest
	base, ext := pythonSplitExt(dest)
	for c := 1; exists(q); c++ {
		q = fmt.Sprintf("%s-%d%s", base, c, ext)
	}
	return q
}
