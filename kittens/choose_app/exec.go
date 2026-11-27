// License: GPLv3 Copyright: 2026, Kovid Goyal, <kovid at kovidgoyal.net>

package choose_app

import (
	"fmt"
	"net/url"
	"os"
	"path/filepath"
	"slices"
	"strings"
)

var _ = fmt.Print

type exec_token struct {
	text   string
	quoted bool
}

// tokenize_exec splits an Exec line into arguments as per the desktop entry
// spec. Quoted arguments are enclosed in double quotes, inside which ", `, $
// and \ are escaped with a backslash. The general string escapes must
// already have been processed.
func tokenize_exec(exec string) (ans []exec_token, err error) {
	var cur strings.Builder
	in_token, in_quotes, was_quoted := false, false, false
	flush := func() {
		if in_token {
			ans = append(ans, exec_token{text: cur.String(), quoted: was_quoted})
		}
		cur.Reset()
		in_token, was_quoted = false, false
	}
	for i := 0; i < len(exec); i++ {
		ch := exec[i]
		switch {
		case in_quotes:
			switch ch {
			case '"':
				in_quotes = false
			case '\\':
				if i+1 < len(exec) && strings.IndexByte("\"`$\\", exec[i+1]) > -1 {
					i++
					cur.WriteByte(exec[i])
				} else {
					cur.WriteByte(ch)
				}
			default:
				cur.WriteByte(ch)
			}
		case ch == ' ' || ch == '\t' || ch == '\n':
			flush()
		case ch == '"':
			in_quotes, in_token, was_quoted = true, true, true
		case ch == '\\' && i+1 < len(exec):
			i++
			cur.WriteByte(exec[i])
			in_token = true
		default:
			cur.WriteByte(ch)
			in_token = true
		}
	}
	if in_quotes {
		return nil, fmt.Errorf("unterminated quote in Exec line: %s", exec)
	}
	flush()
	return
}

// Target is a file or URL to be opened by an application
type Target struct {
	// Either an absolute path or a URL with a scheme other than file
	Path, URL string
}

func NewTarget(path_or_url string) (Target, error) {
	if path_or_url == "" {
		return Target{}, fmt.Errorf("cannot open an empty path")
	}
	if _, serr := os.Lstat(path_or_url); serr == nil {
		// an existing file whose name looks like a URL, such as a:b.txt
		p, err := filepath.Abs(path_or_url)
		return Target{Path: p}, err
	}
	if u, err := url.Parse(path_or_url); err == nil && u.Scheme != "" && len(u.Scheme) > 1 {
		if u.Scheme == "file" {
			if u.Host != "" && u.Host != "localhost" {
				return Target{}, fmt.Errorf("file URLs on remote hosts are not supported: %s", path_or_url)
			}
			return Target{Path: u.Path}, nil
		}
		return Target{URL: path_or_url}, nil
	}
	p, err := filepath.Abs(path_or_url)
	if err != nil {
		return Target{}, err
	}
	return Target{Path: p}, nil
}

func (t Target) as_path() string {
	if t.Path != "" {
		return t.Path
	}
	return t.URL
}

func (t Target) as_url() string {
	if t.URL != "" {
		return t.URL
	}
	u := url.URL{Scheme: "file", Path: t.Path}
	return u.String()
}

func (t Target) String() string { return t.as_url() }

// tokens returns the arguments of the Exec line of this entry
func (d *DesktopEntry) tokens() ([]exec_token, error) {
	if d.exec_tokens != nil {
		return d.exec_tokens, nil
	}
	return tokenize_exec(d.Exec)
}

func has_field_code(toks []exec_token, codes string) bool {
	for _, t := range toks {
		for i := 0; i+1 < len(t.text); i++ {
			if t.text[i] == '%' {
				if strings.IndexByte(codes, t.text[i+1]) > -1 {
					return true
				}
				i++
			}
		}
	}
	return false
}

// expand_token expands the field codes in a single argument. Field codes for
// lists of files are only expanded to multiple arguments when they are the
// whole argument, otherwise they are treated as the single file version.
func (d *DesktopEntry) expand_token(tok exec_token, targets []Target) (ans []string) {
	if !tok.quoted {
		switch tok.text {
		case "%F":
			for _, t := range targets {
				ans = append(ans, t.as_path())
			}
			return
		case "%U":
			for _, t := range targets {
				ans = append(ans, t.as_url())
			}
			return
		case "%i":
			if d.Icon != "" {
				ans = append(ans, "--icon", d.Icon)
			}
			return
		case "%f", "%u":
			if len(targets) == 0 {
				return
			}
		}
	}
	var b strings.Builder
	text := tok.text
	for i := 0; i < len(text); i++ {
		if text[i] != '%' || i+1 >= len(text) {
			b.WriteByte(text[i])
			continue
		}
		i++
		switch text[i] {
		case '%':
			b.WriteByte('%')
		case 'f', 'F':
			if len(targets) > 0 {
				b.WriteString(targets[0].as_path())
			}
		case 'u', 'U':
			if len(targets) > 0 {
				b.WriteString(targets[0].as_url())
			}
		case 'c':
			b.WriteString(d.Name)
		case 'k':
			b.WriteString(d.Path)
		case 'i':
			b.WriteString(d.Icon)
		default:
			// deprecated and unknown field codes are removed
		}
	}
	return append(ans, b.String())
}

// Commands returns the command lines to run to open the specified targets
// with this application. Applications that accept only a single file per
// invocation result in one command line per target. Applications with no
// field codes for files get the file appended, the same as GLib does.
func (d *DesktopEntry) Commands(targets ...Target) (ans [][]string, err error) {
	toks, err := d.tokens()
	if err != nil {
		return nil, err
	}
	if len(toks) == 0 {
		return nil, fmt.Errorf("the Exec line of %s is empty", d.ID)
	}
	takes_list, takes_single := has_field_code(toks, "FU"), has_field_code(toks, "fu")
	if !takes_list && !takes_single && len(targets) > 0 {
		toks = append(slices.Clip(toks), exec_token{text: "%f"})
	}
	expand := func(targets []Target) (cmd []string) {
		for _, tok := range toks {
			cmd = append(cmd, d.expand_token(tok, targets)...)
		}
		return
	}
	if takes_list || len(targets) < 2 {
		ans = append(ans, expand(targets))
	} else {
		for _, t := range targets {
			ans = append(ans, expand([]Target{t}))
		}
	}
	for _, cmd := range ans {
		if len(cmd) == 0 || cmd[0] == "" {
			return nil, fmt.Errorf("the Exec line of %s has no program to run", d.ID)
		}
	}
	return
}
