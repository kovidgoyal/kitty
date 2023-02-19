// License: GPLv3 Copyright: 2023, Kovid Goyal, <kovid at kovidgoyal.net>

package ssh

import (
	"encoding/json"
	"errors"
	"fmt"
	"io/fs"
	"os"
	"path/filepath"
	"strings"

	"kitty/tools/config"
	"kitty/tools/utils"
	"kitty/tools/utils/paths"
	"kitty/tools/utils/shlex"

	"golang.org/x/sys/unix"
)

var _ = fmt.Print

type EnvInstruction struct {
	key, val                                         string
	delete_on_remote, copy_from_local, literal_quote bool
}

func quote_for_sh(val string, literal_quote bool) string {
	if literal_quote {
		return utils.QuoteStringForSH(val)
	}
	// See https://www.gnu.org/software/bash/manual/html_node/Double-Quotes.html
	b := strings.Builder{}
	b.Grow(len(val) + 16)
	b.WriteRune('"')
	runes := []rune(val)
	for i, ch := range runes {
		if ch == '\\' || ch == '`' || ch == '"' || (ch == '$' && i+1 < len(runes) && runes[i+1] == '(') {
			// special chars are escaped
			// $( is escaped to prevent execution
			b.WriteRune('\\')
		}
		b.WriteRune(ch)
	}
	b.WriteRune('"')
	return b.String()
}

func (self *EnvInstruction) Serialize(for_python bool, get_local_env func(string) (string, bool)) string {
	var unset func() string
	var export func(string) string
	if for_python {
		dumps := func(x ...any) string {
			ans, _ := json.Marshal(x)
			return utils.UnsafeBytesToString(ans)
		}
		export = func(val string) string {
			if val == "" {
				return fmt.Sprintf("export %s", dumps(self.key))
			}
			return fmt.Sprintf("export %s", dumps(self.key, val, self.literal_quote))
		}
		unset = func() string {
			return fmt.Sprintf("unset %s", dumps(self.key))
		}
	} else {
		kq := utils.QuoteStringForSH(self.key)
		unset = func() string {
			return fmt.Sprintf("unset %s", kq)
		}
		export = func(val string) string {
			return fmt.Sprintf("export %s=%s", kq, quote_for_sh(val, self.literal_quote))
		}
	}
	if self.delete_on_remote {
		return unset()
	}
	if self.copy_from_local {
		val, found := get_local_env(self.key)
		if !found {
			return ""
		}
		return export(val)
	}
	return export(self.val)
}

func (self *Config) final_env_instructions(for_python bool, get_local_env func(string) (string, bool)) string {
	seen := make(map[string]int, len(self.Env))
	ans := make([]string, 0, len(self.Env))
	for _, ei := range self.Env {
		q := ei.Serialize(for_python, get_local_env)
		if q != "" {
			if pos, found := seen[ei.key]; found {
				ans[pos] = q
			} else {
				seen[ei.key] = len(ans)
				ans = append(ans, q)
			}
		}
	}
	return strings.Join(ans, "\n")
}

type CopyInstruction struct {
	local_path, arcname string
	exclude_patterns    []string
}

func ParseEnvInstruction(spec string) (ans []*EnvInstruction, err error) {
	const COPY_FROM_LOCAL string = "_kitty_copy_env_var_"
	ei := &EnvInstruction{}
	found := false
	ei.key, ei.val, found = strings.Cut(spec, "=")
	ei.key = strings.TrimSpace(ei.key)
	if found {
		ei.val = strings.TrimSpace(ei.val)
		if ei.val == COPY_FROM_LOCAL {
			ei.val = ""
			ei.copy_from_local = true
		}
	} else {
		ei.delete_on_remote = true
	}
	if ei.key == "" {
		err = fmt.Errorf("The env directive must not be empty")
	}
	ans = []*EnvInstruction{ei}
	return
}

var paths_ctx *paths.Ctx

func resolve_file_spec(spec string, is_glob bool) ([]string, error) {
	if paths_ctx == nil {
		paths_ctx = &paths.Ctx{}
	}
	ans := os.ExpandEnv(paths_ctx.ExpandHome(spec))
	if !filepath.IsAbs(ans) {
		ans = paths_ctx.AbspathFromHome(ans)
	}
	if is_glob {
		files, err := filepath.Glob(ans)
		if err != nil {
			return nil, err
		}
		if len(files) == 0 {
			return nil, fmt.Errorf("%s does not exist", spec)
		}
		return files, nil
	}
	err := unix.Access(ans, unix.R_OK)
	if err != nil {
		if errors.Is(err, os.ErrNotExist) {
			return nil, fmt.Errorf("%s does not exist", spec)
		}
		return nil, fmt.Errorf("Cannot read from: %s with error: %w", spec, err)
	}
	return []string{ans}, nil
}

func get_arcname(loc, dest, home string) (arcname string) {
	if dest != "" {
		arcname = dest
	} else {
		arcname = filepath.Clean(loc)
		if filepath.HasPrefix(arcname, home) {
			ra, err := filepath.Rel(home, arcname)
			if err == nil {
				arcname = ra
			}
		}
	}
	prefix := "home/"
	if strings.HasPrefix(arcname, "/") {
		prefix = "root"
	}
	return prefix + arcname
}

func ParseCopyInstruction(spec string) (ans []*CopyInstruction, err error) {
	args, err := shlex.Split("copy " + spec)
	if err != nil {
		return nil, err
	}
	opts, args, err := parse_copy_args(args)
	if err != nil {
		return nil, err
	}
	locations := make([]string, 0, len(args))
	for _, arg := range args {
		locs, err := resolve_file_spec(arg, opts.Glob)
		if err != nil {
			return nil, err
		}
		locations = append(locations, locs...)
	}
	if len(locations) == 0 {
		return nil, fmt.Errorf("No files to copy specified")
	}
	if len(locations) > 1 && opts.Dest != "" {
		return nil, fmt.Errorf("Specifying a remote location with more than one file is not supported")
	}
	home := paths_ctx.HomePath()
	ans = make([]*CopyInstruction, 0, len(locations))
	for _, loc := range locations {
		ci := CopyInstruction{local_path: loc, exclude_patterns: opts.Exclude}
		if opts.SymlinkStrategy != "preserve" {
			ci.local_path, err = filepath.EvalSymlinks(loc)
			if err != nil {
				return nil, fmt.Errorf("Failed to resolve symlinks in %#v with error: %w", loc, err)
			}
		}
		if opts.SymlinkStrategy == "resolve" {
			ci.arcname = get_arcname(ci.local_path, opts.Dest, home)
		} else {
			ci.arcname = get_arcname(loc, opts.Dest, home)
		}
		ans = append(ans, &ci)
	}
	return
}

type ConfigSet struct {
	all_configs []*Config
}

func config_for_hostname(hostname_to_match, username_to_match string, cs *ConfigSet) *Config {
	matcher := func(q *Config) bool {
		for _, pat := range strings.Split(q.Hostname, " ") {
			upat := "*"
			if strings.Contains(pat, "@") {
				upat, pat, _ = strings.Cut(pat, "@")
			}
			var host_matched, user_matched bool
			if matched, err := filepath.Match(pat, hostname_to_match); matched && err == nil {
				host_matched = true
			}
			if matched, err := filepath.Match(upat, username_to_match); matched && err == nil {
				user_matched = true
			}
			if host_matched && user_matched {
				return true
			}
		}
		return false
	}
	for _, c := range utils.Reversed(cs.all_configs) {
		if matcher(c) {
			return c
		}
	}
	return cs.all_configs[0]
}

func (self *ConfigSet) line_handler(key, val string) error {
	c := self.all_configs[len(self.all_configs)-1]
	if key == "hostname" {
		c = NewConfig()
		self.all_configs = append(self.all_configs, c)
	}
	return c.Parse(key, val)
}

func load_config(hostname_to_match string, username_to_match string, overrides []string, paths ...string) (*Config, error) {
	ans := &ConfigSet{all_configs: []*Config{NewConfig()}}
	p := config.ConfigParser{LineHandler: ans.line_handler}
	if len(paths) == 0 {
		paths = []string{filepath.Join(utils.ConfigDir(), "ssh.conf")}
	}
	err := p.ParseFiles(paths...)
	if err != nil && !errors.Is(err, fs.ErrNotExist) {
		return nil, err
	}
	if len(overrides) > 0 {
		err = p.ParseOverrides(overrides...)
		if err != nil {
			return nil, err
		}
	}
	return config_for_hostname(hostname_to_match, username_to_match, ans), nil
}
