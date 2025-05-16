// License: GPLv3 Copyright: 2023, Kovid Goyal, <kovid at kovidgoyal.net>

package ssh

import (
	"archive/tar"
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"path"
	"path/filepath"
	"strings"
	"time"

	"github.com/kovidgoyal/kitty/tools/config"
	"github.com/kovidgoyal/kitty/tools/utils"
	"github.com/kovidgoyal/kitty/tools/utils/paths"
	"github.com/kovidgoyal/kitty/tools/utils/shlex"

	"github.com/bmatcuk/doublestar/v4"
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

func final_env_instructions(for_python bool, get_local_env func(string) (string, bool), env ...*EnvInstruction) string {
	seen := make(map[string]int, len(env))
	ans := make([]string, 0, len(env))
	for _, ei := range env {
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
		files, err := doublestar.FilepathGlob(ans)
		if err != nil {
			return nil, fmt.Errorf("%s is not a valid glob pattern with error: %w", spec, err)
		}
		if len(files) == 0 {
			return nil, fmt.Errorf("%s matches no files", spec)
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
		if strings.HasPrefix(arcname, home) {
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

type file_unique_id struct {
	dev, inode uint64
}

func excluded(pattern, path string) bool {
	if !strings.ContainsRune(pattern, '/') {
		path = filepath.Base(path)
	}
	if matched, err := doublestar.PathMatch(pattern, path); matched && err == nil {
		return true
	}
	return false
}

func get_file_data(callback func(h *tar.Header, data []byte) error, seen map[file_unique_id]string, local_path, arcname string, exclude_patterns []string) error {
	var s unix.Stat_t
	if err := unix.Lstat(local_path, &s); err != nil {
		return err
	}
	cb := func(h *tar.Header, data []byte, arcname string) error {
		h.Name = arcname
		if h.Typeflag == tar.TypeDir {
			h.Name = strings.TrimRight(h.Name, "/") + "/"
		}
		h.Size = int64(len(data))
		h.Mode = int64(s.Mode & 0777) // discard the setuid, setgid and sticky bits
		h.ModTime = time.Unix(s.Mtim.Unix())
		h.AccessTime = time.Unix(s.Atim.Unix())
		h.ChangeTime = time.Unix(s.Ctim.Unix())
		h.Format = tar.FormatPAX
		return callback(h, data)
	}
	// we only copy regular files, directories and symlinks
	switch s.Mode & unix.S_IFMT {
	case unix.S_IFBLK, unix.S_IFIFO, unix.S_IFCHR, unix.S_IFSOCK: // ignored
	case unix.S_IFLNK: // symlink
		target, err := os.Readlink(local_path)
		if err != nil {
			return err
		}
		err = cb(&tar.Header{
			Typeflag: tar.TypeSymlink,
			Linkname: target,
		}, nil, arcname)
		if err != nil {
			return err
		}
	case unix.S_IFDIR: // directory
		local_path = filepath.Clean(local_path)
		type entry struct {
			path, arcname string
		}
		stack := []entry{{local_path, arcname}}
		for len(stack) > 0 {
			x := stack[0]
			stack = stack[1:]
			entries, err := os.ReadDir(x.path)
			if err != nil {
				if x.path == local_path {
					return err
				}
				continue
			}
			err = cb(&tar.Header{Typeflag: tar.TypeDir}, nil, x.arcname)
			if err != nil {
				return err
			}
			for _, e := range entries {
				entry_path := filepath.Join(x.path, e.Name())
				aname := path.Join(x.arcname, e.Name())
				ok := true
				for _, pat := range exclude_patterns {
					if excluded(pat, entry_path) {
						ok = false
						break
					}
				}
				if !ok {
					continue
				}
				if e.IsDir() {
					stack = append(stack, entry{entry_path, aname})
				} else {
					err = get_file_data(callback, seen, entry_path, aname, exclude_patterns)
					if err != nil {
						return err
					}
				}
			}
		}
	case unix.S_IFREG: // Regular file
		fid := file_unique_id{dev: uint64(s.Dev), inode: uint64(s.Ino)}
		if prev, ok := seen[fid]; ok { // Hard link
			return cb(&tar.Header{Typeflag: tar.TypeLink, Linkname: prev}, nil, arcname)
		}
		seen[fid] = arcname
		data, err := os.ReadFile(local_path)
		if err != nil {
			return err
		}
		err = cb(&tar.Header{Typeflag: tar.TypeReg}, data, arcname)
		if err != nil {
			return err
		}
	}
	return nil
}

func (ci *CopyInstruction) get_file_data(callback func(h *tar.Header, data []byte) error, seen map[file_unique_id]string) (err error) {
	ep := ci.exclude_patterns
	for _, folder_name := range []string{"__pycache__", ".DS_Store"} {
		ep = append(ep, "**/"+folder_name, "**/"+folder_name+"/**")
	}
	return get_file_data(callback, seen, ci.local_path, ci.arcname, ep)
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

func load_config(hostname_to_match string, username_to_match string, overrides []string, paths ...string) (*Config, []config.ConfigLine, error) {
	ans := &ConfigSet{all_configs: []*Config{NewConfig()}}
	p := config.ConfigParser{LineHandler: ans.line_handler}
	err := p.LoadConfig("ssh.conf", paths, nil)
	if err != nil {
		return nil, nil, err
	}
	final_conf := config_for_hostname(hostname_to_match, username_to_match, ans)
	bad_lines := p.BadLines()
	if len(overrides) > 0 {
		h := final_conf.Hostname
		override_parser := config.ConfigParser{LineHandler: final_conf.Parse}
		if err = override_parser.ParseOverrides(overrides...); err != nil {
			return nil, nil, err
		}
		bad_lines = append(bad_lines, override_parser.BadLines()...)
		final_conf.Hostname = h
	}
	return final_conf, bad_lines, nil
}
