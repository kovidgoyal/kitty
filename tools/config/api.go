// License: GPLv3 Copyright: 2023, Kovid Goyal, <kovid at kovidgoyal.net>

package config

import (
	"bufio"
	"bytes"
	"errors"
	"fmt"
	"io"
	"io/fs"
	"kitty/tools/utils"
	"os"
	"path/filepath"
	"strings"
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

	lnum := 0
	make_absolute := func(path string) (string, error) {
		if path == "" {
			return "", fmt.Errorf("Empty include paths not allowed")
		}
		if !filepath.IsAbs(path) {
			path = filepath.Join(base_path_for_includes, path)
		}
		return path, nil
	}
	for scanner.Scan() {
		line := strings.TrimLeft(scanner.Text(), " ")
		lnum++
		if line == "" {
			continue
		}
		if line[0] == '#' {
			if self.CommentsHandler != nil {
				err := self.CommentsHandler(line)
				if err != nil {
					self.bad_lines = append(self.bad_lines, ConfigLine{Src_file: name, Line: line, Line_number: lnum, Err: err})
				}
			}
			continue
		}
		key, val, _ := strings.Cut(line, " ")
		switch key {
		default:
			err := self.LineHandler(key, val)
			if err != nil {
				self.bad_lines = append(self.bad_lines, ConfigLine{Src_file: name, Line: line, Line_number: lnum, Err: err})
			}
		case "include", "globinclude", "envinclude":
			var includes []string
			switch key {
			case "include":
				aval, err := make_absolute(val)
				if err == nil {
					includes = []string{aval}
				}
			case "globinclude":
				aval, err := make_absolute(val)
				if err == nil {
					matches, err := filepath.Glob(aval)
					if err == nil {
						includes = matches
					}
				}
			case "envinclude":
				env := self.override_env
				if env == nil {
					env = os.Environ()
				}
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
					raw, err := os.ReadFile(incpath)
					if err == nil {
						err := recurse(bytes.NewReader(raw), incpath, filepath.Dir(incpath))
						if err != nil {
							return err
						}
					} else if !errors.Is(err, fs.ErrNotExist) {
						return fmt.Errorf("Failed to process include %#v with error: %w", incpath, err)
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
		scanner := bufio.NewScanner(bytes.NewReader(raw))
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
	s := LinesScanner{lines: overrides}
	self.seen_includes = make(map[string]bool)
	return self.parse(&s, "<overrides>", utils.ConfigDir(), 0)
}
