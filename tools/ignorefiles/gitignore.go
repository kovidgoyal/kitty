package ignorefiles

import (
	"fmt"
	"io"
	"io/fs"
	"os"
	"path/filepath"
	"slices"
	"strings"

	"github.com/kovidgoyal/kitty/tools/utils"
)

var _ = fmt.Print

type GitPattern struct {
	line_number int
	only_dirs   bool
	negated     bool
	pattern     string
	parts       []string
	matcher     func(path string) bool
}

type Gitignore struct {
	patterns                   []GitPattern
	index_of_last_negated_rule int
	line_number_offset         int
}

func (g Gitignore) Len() int { return len(g.patterns) }

func (g Gitignore) IsIgnored(relpath string, ftype os.FileMode) (is_ignored bool, linenum_of_matching_rule int, pattern string) {
	if os.PathSeparator != '/' {
		relpath = strings.ReplaceAll(relpath, string(os.PathSeparator), "/")
	}
	linenum_of_matching_rule = -1
	for i, pat := range g.patterns {
		if is_ignored {
			if i > g.index_of_last_negated_rule {
				break
			}
			if pat.negated && pat.Match(relpath, ftype) {
				is_ignored = false
				linenum_of_matching_rule = pat.line_number
				pattern = pat.pattern
			}
		} else {
			if !pat.negated && pat.Match(relpath, ftype) {
				is_ignored = true
				linenum_of_matching_rule = pat.line_number
				pattern = pat.pattern
			}
		}
	}
	return
}

func (g *Gitignore) load_line(line string, line_number int) {
	if p, skipped_line := CompileGitIgnoreLine(line); !skipped_line {
		p.line_number = g.line_number_offset + line_number
		g.patterns = append(g.patterns, p)
		if p.negated {
			g.index_of_last_negated_rule = len(g.patterns) - 1
		}
	}
}

func (g *Gitignore) LoadLines(lines ...string) error {
	for i, line := range lines {
		g.load_line(line, i)
	}
	g.line_number_offset += len(lines)
	return nil
}

func (g *Gitignore) LoadString(text string) error {
	s := utils.NewLineScanner(text)
	lnum := 0
	for s.Scan() {
		g.load_line(s.Text(), lnum)
		lnum++
	}
	g.line_number_offset += lnum
	return nil
}

func (g *Gitignore) LoadBytes(text []byte) error {
	return g.LoadString(string(text))
}

func (g *Gitignore) LoadPath(path string) error {
	if data, err := os.ReadFile(path); err == nil {
		return g.LoadString(utils.UnsafeBytesToString(data))
	} else {
		return err
	}
}

func (g *Gitignore) LoadFile(f io.Reader) error {
	if data, err := io.ReadAll(f); err == nil {
		return g.LoadString(utils.UnsafeBytesToString(data))
	} else {
		return err
	}
}

func (p GitPattern) Match(path string, ftype fs.FileMode) bool {
	if p.only_dirs && ftype&fs.ModeDir == 0 {
		return false
	}
	return p.matcher(path)
}

func anchored_single_match(path string, pattern string) bool {
	name, _, _ := strings.Cut(path, "/")
	matches, err := filepath.Match(pattern, name)
	return err == nil && matches
}

func unanchored_single_match(path string, pattern string) bool {
	for path != "" {
		var name string
		name, path, _ = strings.Cut(path, "/")
		matches, err := filepath.Match(pattern, name)
		if err != nil {
			return false
		}
		if matches {
			return true
		}
	}
	return false
}

func anchored_simple_match(path string, parts []string) bool {
	for ; path != "" && len(parts) > 0; parts = parts[1:] {
		var name string
		name, path, _ = strings.Cut(path, "/")
		if matches, err := filepath.Match(parts[0], name); err != nil || !matches {
			return false
		}
	}
	return path == "" && len(parts) == 0
}

func anchored_full_match(path string, parts []string) bool {
	pos, last := 0, len(parts)-1
	for pos <= last && path != "" {
		var name string
		name, path, _ = strings.Cut(path, "/")
		switch parts[pos] {
		case "**":
			for pos+1 < len(parts) && parts[pos+1] == "**" {
				pos++
			}
			if pos == last {
				return true
			}
			pos++
			for {
				matches, err := filepath.Match(parts[pos], name)
				if err != nil {
					return false
				}
				if matches {
					return anchored_full_match(path, parts[pos+1:])
				}
				if path == "" {
					return false
				}
				name, path, _ = strings.Cut(path, "/")
			}
		default:
			if matches, err := filepath.Match(parts[pos], name); err != nil || !matches {
				return false
			}
			pos++
		}
	}
	return path == "" && pos > last
}

// Parse a line from a .gitignore file, see man gitignore for the syntax
func CompileGitIgnoreLine(line string) (ans GitPattern, skipped_line bool) {
	// Strip comments
	if strings.HasPrefix(line, `#`) {
		skipped_line = true
		return
	}

	// Trim OS-specific carriage returns.
	line = strings.TrimRight(line, "\r")

	// Trim trailing spaces unless backslash escaped
	for strings.HasSuffix(line, " ") {
		if strings.HasSuffix(line, `\ `) {
			line = line[:len(line)-2] + " "
			break
		}
		line = line[:len(line)-1]
	}

	// Empty lines are ignored
	if line == "" {
		skipped_line = true
		return
	}
	ans.pattern = line

	// Handle negated (accept) patterns
	if line[0] == '!' {
		line = line[1:]
		ans.negated = true
	}

	// Handle leading slash used to escape leading # or !
	if line[0] == '\\' && len(line) > 1 && (line[1] == '#' || line[1] == '!') {
		line = line[1:]
	}
	if strings.HasSuffix(line, "/") {
		ans.only_dirs = true
		line = strings.TrimRight(line, "/")
		if line == "" {
			skipped_line = true
			return
		}
	}
	starts_with_slash := strings.HasPrefix(line, "/")
	if starts_with_slash {
		line = strings.TrimLeft(line, "/")
	}
	ans.parts = strings.Split(line, "/")
	if slices.Contains(ans.parts, "") {
		ans.parts = slices.DeleteFunc(ans.parts, func(x string) bool { return x == "" })
	}
	if len(ans.parts) == 0 {
		skipped_line = true
		return
	}
	if len(ans.parts) == 1 {
		pattern := ans.parts[0]
		if pattern == "**" {
			ans.matcher = func(string) bool { return true }
		} else {
			if starts_with_slash {
				ans.matcher = func(path string) bool { return anchored_single_match(path, pattern) }
			} else {
				ans.matcher = func(path string) bool { return unanchored_single_match(path, pattern) }
			}
		}
	} else {
		if slices.Contains(ans.parts, "**") {
			ans.matcher = func(path string) bool { return anchored_full_match(path, ans.parts) }
		} else {
			ans.matcher = func(path string) bool { return anchored_simple_match(path, ans.parts) }
		}
	}
	return
}

func get_global_gitconfig_excludesfile() (ans string) {
	cfhome := os.Getenv("XDG_CONFIG_HOME")
	if cfhome == "" {
		cfhome = utils.Expanduser("~/.config")
	}
	for _, candidate := range []string{"/etc/gitconfig", filepath.Join(cfhome, "git", "config"), utils.Expanduser("~/.gitconfig")} {
		if data, err := os.ReadFile(candidate); err == nil {
			s := utils.NewLineScanner(utils.UnsafeBytesToString(data))
			in_core := false
			for s.Scan() {
				line := strings.TrimSpace(s.Text())
				if in_core {
					if strings.HasPrefix(line, "[") {
						in_core = line == "[core]"
						continue
					}
					if k, rest, found := strings.Cut(line, "="); found && strings.ToLower(strings.TrimSpace(k)) == `excludesfile` {
						ans = strings.TrimSpace(rest)
						ans = utils.Expanduser(ans)
						if !filepath.IsAbs(ans) {
							if a, err := filepath.Abs(ans); err != nil {
								ans = a
							}
						}
					}
				} else if strings.ToLower(line) == "[core]" {
					in_core = true
				}
			}
		}
	}
	if ans == "" {
		ans = filepath.Join(cfhome, "git", "ignore")
	}
	return
}

func get_global_gitignore() (ans IgnoreFile) {
	excludesfile := get_global_gitconfig_excludesfile()
	if data, err := os.ReadFile(excludesfile); err == nil {
		q := NewGitignore()
		if q.LoadString(utils.UnsafeBytesToString(data)) == nil {
			ans = q
		}
	}
	return
}
