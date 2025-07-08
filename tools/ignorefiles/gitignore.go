package ignorefiles

import (
	"fmt"
	"io/fs"
	"os"
	"path/filepath"
	"slices"
	"strings"
)

var _ = fmt.Print

type GitPattern struct {
	only_dirs bool
	negated   bool
	parts     []string
	matcher   func(path string) bool
}

func (p GitPattern) Match(path string, ftype fs.FileMode) bool {
	if p.only_dirs && ftype&fs.ModeDir == 0 {
		return false
	}
	if os.PathSeparator != '/' {
		path = strings.ReplaceAll(path, string(os.PathSeparator), "/")
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
