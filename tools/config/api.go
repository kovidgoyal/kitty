// License: GPLv3 Copyright: 2023, Kovid Goyal, <kovid at kovidgoyal.net>

package config

import (
	"bufio"
	"bytes"
	"errors"
	"fmt"
	"io"
	"io/fs"
	"os"
	"os/exec"
	"path/filepath"
	"regexp"
	"runtime"
	"strconv"
	"strings"
	"sync"

	"github.com/kovidgoyal/kitty"
	"github.com/kovidgoyal/kitty/tools/utils"

	"github.com/shirou/gopsutil/v3/process"
	"golang.org/x/sys/unix"
)

var _ = fmt.Print

func StringToBool(x string) bool {
	x = strings.ToLower(x)
	return x == "y" || x == "yes" || x == "true"
}

type ConfigLine struct {
	Src_file, Line string
	Line_number    int
	Err            error
}

type ConfigParser struct {
	LineHandler     func(key, val string) error
	CommentsHandler func(line string) error
	SourceHandler   func(text, path string)

	bad_lines     []ConfigLine
	seen_includes map[string]bool
	override_env  []string
}

type Scanner interface {
	Scan() bool
	Text() string
	Err() error
}

func (self *ConfigParser) BadLines() []ConfigLine {
	return self.bad_lines
}

var key_pat = sync.OnceValue(func() *regexp.Regexp {
	return regexp.MustCompile(`([a-zA-Z][a-zA-Z0-9_-]*)\s+(.+)$`)
})

var kitty_os = sync.OnceValue(func() string {
	switch runtime.GOOS {
	case "linux":
		return "linux"
	case "freebsd", "netbsd", "openbsd":
		return "bsd"
	case "darwin":
		return "macos"
	}
	return "unknown"
})

func geninclude(path string) (string, error) {
	cmd := exec.Command(path)
	cmd.Env = os.Environ()
	cmd.Env = append(cmd.Env, "KITTY_OS="+kitty_os())
	if strings.HasSuffix(path, ".py") && unix.Access(path, unix.X_OK) != nil {
		if utils.KittyExe() == "" || strings.HasPrefix(path, ":") {
			cmd = exec.Command("python", path)
		} else {
			cmd = exec.Command(utils.KittyExe(), "+launch", path)
		}
	}
	stdout, err := cmd.StdoutPipe()
	if err != nil {
		return "", err
	}
	if err = cmd.Start(); err != nil {
		return "", err
	}
	data, err := io.ReadAll(stdout)
	if err != nil {
		return "", err
	}
	if err = cmd.Wait(); err != nil {
		return "", err
	}
	return utils.UnsafeBytesToString(data), nil
}

func ExpandVars(x string) string {
	return os.Expand(x, func(k string) string {
		if k == "KITTY_OS" {
			return kitty_os()
		}
		return os.Getenv(k)
	})
}

func (self *ConfigParser) parse(scanner Scanner, name, base_path_for_includes string, depth int) error {
	if self.seen_includes[name] { // avoid include loops
		return nil
	}
	self.seen_includes[name] = true

	recurse := func(r io.Reader, nname, base_path_for_includes string) error {
		if depth > 32 {
			return fmt.Errorf("Too many nested include directives while processing config file: %s", name)
		}
		escanner := bufio.NewScanner(r)
		return self.parse(escanner, nname, base_path_for_includes, depth+1)
	}

	make_absolute := func(path string) (string, error) {
		if path == "" {
			return "", fmt.Errorf("Empty include paths not allowed")
		}
		if !filepath.IsAbs(path) {
			path = filepath.Join(base_path_for_includes, path)
		}
		return path, nil
	}

	lnum := 0
	next_line_num := 0
	next_line := ""
	var line string

	add_bad_line := func(err error) {
		self.bad_lines = append(self.bad_lines, ConfigLine{Src_file: name, Line: line, Line_number: lnum, Err: err})
	}

	for {
		if next_line != "" {
			line = next_line
		} else {
			if scanner.Scan() {
				line = strings.TrimLeft(scanner.Text(), " \t")
				next_line_num++
			} else {
				break
			}
			if line == "" {
				continue
			}
		}
		lnum = next_line_num
		if scanner.Scan() {
			next_line = strings.TrimLeft(scanner.Text(), " \t")
			next_line_num++

			for strings.HasPrefix(next_line, `\`) {
				line += next_line[1:]
				if scanner.Scan() {
					next_line = strings.TrimLeft(scanner.Text(), " \t")
					next_line_num++
				} else {
					next_line = ""
				}
			}
		} else {
			next_line = ""
		}

		if line[0] == '#' {
			if self.CommentsHandler != nil {
				if err := self.CommentsHandler(line); err != nil {
					add_bad_line(err)
				}
			}
			continue
		}
		m := key_pat().FindStringSubmatch(line)
		if len(m) < 3 {
			add_bad_line(fmt.Errorf("Invalid config line: %#v", line))
			continue
		}
		key, val := m[1], m[2]
		for i, ch := range line {
			if ch == ' ' || ch == '\t' {
				key = line[:i]
				val = strings.TrimSpace(line[i+1:])
				break
			}
		}
		switch key {
		default:
			if err := self.LineHandler(key, val); err != nil {
				add_bad_line(err)
			}
		case "include", "globinclude", "envinclude", "geninclude":
			var includes []string
			val = ExpandVars(val)
			switch key {
			case "include":
				if aval, err := make_absolute(val); err == nil {
					includes = []string{aval}
				} else {
					add_bad_line(err)
				}
			case "globinclude":
				aval, err := make_absolute(val)
				if err == nil {
					matches, err := filepath.Glob(aval)
					if err == nil {
						includes = matches
					} else {
						add_bad_line(err)
					}
				} else {
					add_bad_line(err)
				}
			case "geninclude":
				if aval, err := make_absolute(val); err == nil {
					if g, err := geninclude(aval); err == nil {
						if err := recurse(strings.NewReader(g), "<gen: "+val+">", base_path_for_includes); err != nil {
							return err
						}
					} else {
						add_bad_line(err)
					}
				} else {
					add_bad_line(err)
				}
			case "envinclude":
				env := utils.IfElse(self.override_env == nil, os.Environ(), self.override_env)
				for _, x := range env {
					key, eval, _ := strings.Cut(x, "=")
					is_match, err := filepath.Match(val, key)
					if is_match && err == nil {
						err := recurse(strings.NewReader(eval), "<env var: "+key+">", base_path_for_includes)
						if err != nil {
							return err
						}
					}
				}
			}
			if len(includes) > 0 {
				for _, incpath := range includes {
					if raw, err := os.ReadFile(incpath); err == nil {
						if err := recurse(bytes.NewReader(raw), incpath, filepath.Dir(incpath)); err != nil {
							return err
						}
					} else if !errors.Is(err, fs.ErrNotExist) {
						add_bad_line(err)
					}
				}
			}
		}
	}
	return nil
}

func (self *ConfigParser) ParseFiles(paths ...string) error {
	for _, path := range paths {
		apath, err := filepath.Abs(path)
		if err == nil {
			path = apath
		}
		raw, err := os.ReadFile(path)
		if err != nil {
			return err
		}
		scanner := utils.NewLineScanner(utils.UnsafeBytesToString(raw))
		self.seen_includes = make(map[string]bool)
		err = self.parse(scanner, path, filepath.Dir(path), 0)
		if err != nil {
			return err
		}
		if self.SourceHandler != nil {
			self.SourceHandler(utils.UnsafeBytesToString(raw), path)
		}
	}
	return nil
}

func (self *ConfigParser) LoadConfig(name string, paths []string, overrides []string) (err error) {
	const SYSTEM_CONF = "/etc/xdg/kitty"
	system_conf := filepath.Join(SYSTEM_CONF, name)
	add_if_exists := func(q string) {
		err = self.ParseFiles(q)
		if err != nil && errors.Is(err, fs.ErrNotExist) {
			err = nil
		}
	}
	if add_if_exists(system_conf); err != nil {
		return err
	}
	if len(paths) > 0 {
		for _, path := range paths {
			if add_if_exists(path); err != nil {
				return err
			}
		}
	} else {
		if add_if_exists(filepath.Join(utils.ConfigDirForName(name), name)); err != nil {
			return err
		}
	}
	if len(overrides) > 0 {
		err = self.ParseOverrides(overrides...)
		if err != nil {
			return err
		}
	}
	return
}

type LinesScanner struct {
	lines []string
}

func (self *LinesScanner) Scan() bool {
	return len(self.lines) > 0
}

func (self *LinesScanner) Text() string {
	ans := self.lines[0]
	self.lines = self.lines[1:]
	return ans
}

func (self *LinesScanner) Err() error {
	return nil
}

func (self *ConfigParser) ParseOverrides(overrides ...string) error {
	s := LinesScanner{lines: utils.Map(func(x string) string {
		return strings.Replace(x, "=", " ", 1)
	}, overrides)}
	self.seen_includes = make(map[string]bool)
	return self.parse(&s, "<overrides>", utils.ConfigDir(), 0)
}

func is_kitty_gui_cmdline(exe string, cmd ...string) bool {
	if len(cmd) == 0 {
		return false
	}
	if filepath.Base(exe) != "kitty" {
		return false
	}
	if len(cmd) == 1 {
		return true
	}
	s := cmd[1][:1]
	switch s {
	case `@`:
		return false
	case `+`:
		if cmd[1] == `+` {
			return len(cmd) > 2 && cmd[2] == `open`
		}
		return cmd[1] == `+open`
	}
	return true
}

type Patcher struct {
	Write_backup bool
	Mode         fs.FileMode
}

func (self Patcher) Patch(path, sentinel, content string, settings_to_comment_out ...string) (updated bool, err error) {
	if self.Mode == 0 {
		self.Mode = 0o644
	}
	backup_path := path
	if q, err := filepath.EvalSymlinks(path); err == nil {
		path = q
	}
	raw, err := os.ReadFile(path)
	if err != nil && !errors.Is(err, fs.ErrNotExist) {
		return false, err
	}
	add_at_top := ""
	backup := true
	if raw == nil {
		cc := kitty.CommentedOutDefaultConfig
		if idx := strings.Index(cc, "\n\n"); idx > 0 {
			add_at_top = cc[:idx+2]
			raw = []byte(cc[idx+2:])
			backup = false
		}
	}
	pat := utils.MustCompile(fmt.Sprintf(`(?m)^\s*(%s)\b`, strings.Join(settings_to_comment_out, "|")))
	text := pat.ReplaceAllString(utils.UnsafeBytesToString(raw), `# $1`)

	pat = utils.MustCompile(fmt.Sprintf(`(?ms)^# BEGIN_%s.+?# END_%s`, sentinel, sentinel))
	replaced := false
	addition := fmt.Sprintf("# BEGIN_%s\n%s\n# END_%s", sentinel, content, sentinel)
	ntext := pat.ReplaceAllStringFunc(text, func(string) string {
		replaced = true
		return addition
	})
	if !replaced {
		if add_at_top != "" {
			ntext = add_at_top + addition
			if text != "" {
				ntext += "\n\n" + text
			}
		} else {
			if text != "" {
				text += "\n\n"
			}
			ntext = text + addition
		}
	}
	nraw := utils.UnsafeStringToBytes(ntext)
	if !bytes.Equal(raw, nraw) {
		if len(raw) > 0 && self.Write_backup && backup {
			_ = os.WriteFile(backup_path+".bak", raw, self.Mode)
		}

		return true, utils.AtomicUpdateFile(path, bytes.NewReader(nraw), self.Mode)
	}
	return false, nil
}

func ReloadConfigInKitty(in_parent_only bool) error {
	if in_parent_only {
		if pid, err := strconv.ParseInt(os.Getenv("KITTY_PID"), 10, 32); err == nil {
			if p, err := process.NewProcess(int32(pid)); err == nil {
				if exe, eerr := p.Exe(); eerr == nil {
					if c, err := p.CmdlineSlice(); err == nil && is_kitty_gui_cmdline(exe, c...) {
						return p.SendSignal(unix.SIGUSR1)
					}
				}
			}
		}
		return nil
	}
	// process.Processes() followed by filtering by getting the process
	// exe and cmdline is very slow on non-Linux systems as CGO is not allowed
	// which means getting exe works by calling lsof on every process. So instead do
	// initial filtering based on ps output.
	if ps_out, err := exec.Command("ps", "-x", "-o", "pid=,comm=").Output(); err == nil {
		for _, line := range utils.Splitlines(utils.UnsafeBytesToString(ps_out)) {
			line = strings.TrimSpace(line)
			if pid_string, argv0, found := strings.Cut(line, " "); found {
				if pid, err := strconv.ParseInt(strings.TrimSpace(pid_string), 10, 32); err == nil && strings.Contains(argv0, "kitty") {
					if p, err := process.NewProcess(int32(pid)); err == nil {
						if cmdline, err := p.CmdlineSlice(); err == nil {
							if exe, err := p.Exe(); err == nil && is_kitty_gui_cmdline(exe, cmdline...) {
								_ = p.SendSignal(unix.SIGUSR1)
							}
						}
					}
				}
			}
		}
	}
	return nil
}

var OverrideEffectiveConfigPath string

func ReadKittyConfig(line_handler func(key, val string) error, override_effective_config_path ...string) error {
	kp := os.Getenv("KITTY_PID")
	kitty_conf_path := ""
	if len(override_effective_config_path) > 0 {
		kitty_conf_path = override_effective_config_path[0]
	}
	if _, err := strconv.Atoi(kp); err == nil && kitty_conf_path == "" {
		effective_config_path := filepath.Join(utils.CacheDir(), "effective-config", kp)
		if unix.Access(effective_config_path, unix.R_OK) == nil {
			kitty_conf_path = effective_config_path
		}
	}
	if kitty_conf_path == "" {
		kitty_conf_path = filepath.Join(utils.ConfigDir(), "kitty.conf")
	}
	cp := ConfigParser{LineHandler: line_handler}
	return cp.ParseFiles(kitty_conf_path)
}
