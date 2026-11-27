// License: GPLv3 Copyright: 2026, Kovid Goyal, <kovid at kovidgoyal.net>

package choose_app

import (
	"fmt"
	"path"
	"path/filepath"
	"slices"
	"strings"

	"github.com/bmatcuk/doublestar/v4"
	"github.com/kovidgoyal/kitty/tools/config"
	"github.com/kovidgoyal/kitty/tools/utils"
	"github.com/kovidgoyal/kitty/tools/utils/shlex"
)

var _ = fmt.Print

const desktop_choice_prefix = "desktop:"

// Choice is the application chosen to open a file or URL, either an
// installed application or a custom command line
type Choice struct {
	DesktopID string `json:"desktop_id,omitempty"`
	// A command line using the same field codes as the Exec key of desktop files
	Cmdline []string `json:"cmdline,omitempty"`
}

func (c Choice) IsEmpty() bool { return c.DesktopID == "" && len(c.Cmdline) == 0 }

func (c Choice) Equal(o Choice) bool {
	return c.DesktopID == o.DesktopID && slices.Equal(c.Cmdline, o.Cmdline)
}

func join_cmdline(cmd []string) string {
	q := make([]string, len(cmd))
	for i, x := range cmd {
		q[i] = shlex.Quote(x)
	}
	return strings.Join(q, " ")
}

func (c Choice) String() string {
	if c.DesktopID != "" {
		return desktop_choice_prefix + c.DesktopID
	}
	return join_cmdline(c.Cmdline)
}

func ChoiceForDesktopID(id string) Choice {
	if !strings.HasSuffix(id, ".desktop") {
		id += ".desktop"
	}
	return Choice{DesktopID: id}
}

// Entry returns the application for this choice, creating one for custom
// command lines. Returns an error if the chosen application is no longer
// installed.
func (c Choice) Entry(db *AppDatabase) (*DesktopEntry, error) {
	if c.DesktopID != "" {
		if e := db.AppByID(c.DesktopID); e != nil {
			return e, nil
		}
		return nil, fmt.Errorf("the application %s is not installed", c.DesktopID)
	}
	if len(c.Cmdline) == 0 {
		return nil, fmt.Errorf("no application chosen")
	}
	toks := make([]exec_token, len(c.Cmdline))
	for i, x := range c.Cmdline {
		toks[i] = exec_token{text: x}
	}
	cmd := join_cmdline(c.Cmdline)
	return &DesktopEntry{ID: cmd, Name: cmd, Exec: cmd, exec_tokens: toks, entry_type: true}, nil
}

type criterion_type int

const (
	mime_criterion criterion_type = iota
	ext_criterion
	glob_criterion
	scheme_criterion
)

// OpenWithRule is a parsed open_with setting
type OpenWithRule struct {
	Spec     string
	kind     criterion_type
	patterns []string
	Choice   Choice
}

func ParseOpenWith(spec string) (ans OpenWithRule, err error) {
	ans.Spec = spec
	parts, err := shlex.Split(spec)
	if err != nil {
		return ans, fmt.Errorf("invalid open_with %#v with error: %w", spec, err)
	}
	if len(parts) < 2 {
		return ans, fmt.Errorf("invalid open_with %#v: no program specified", spec)
	}
	prefix, patterns, found := strings.Cut(parts[0], ":")
	if !found {
		return ans, fmt.Errorf("invalid open_with %#v: the criterion %#v does not start with one of mime:, ext:, glob: or scheme:", spec, parts[0])
	}
	switch prefix {
	case "mime":
		ans.kind = mime_criterion
	case "ext":
		ans.kind = ext_criterion
	case "glob":
		ans.kind = glob_criterion
	case "scheme":
		ans.kind = scheme_criterion
	default:
		return ans, fmt.Errorf("invalid open_with %#v: unknown criterion type %#v, must be one of mime, ext, glob or scheme", spec, prefix)
	}
	if ans.kind == glob_criterion {
		// glob patterns can legitimately contain commas
		ans.patterns = []string{patterns}
	} else {
		for p := range strings.SplitSeq(patterns, ",") {
			if p = strings.TrimSpace(p); p != "" {
				ans.patterns = append(ans.patterns, strings.ToLower(strings.TrimPrefix(p, ".")))
			}
		}
	}
	if len(ans.patterns) == 0 || ans.patterns[0] == "" {
		return ans, fmt.Errorf("invalid open_with %#v: no patterns specified", spec)
	}
	for _, p := range ans.patterns {
		if ans.kind == glob_criterion && strings.Contains(p, "/") {
			if !doublestar.ValidatePattern(utils.Expanduser(p)) {
				return ans, fmt.Errorf("invalid open_with %#v: %#v is not a valid pattern", spec, p)
			}
		} else if _, err := path.Match(p, ""); err != nil {
			return ans, fmt.Errorf("invalid open_with %#v: %#v is not a valid pattern", spec, p)
		}
	}
	if id, is_desktop := strings.CutPrefix(parts[1], desktop_choice_prefix); is_desktop {
		if len(parts) > 2 || id == "" {
			return ans, fmt.Errorf("invalid open_with %#v: %s must be followed by only the application id", spec, desktop_choice_prefix)
		}
		ans.Choice = ChoiceForDesktopID(id)
	} else {
		ans.Choice = Choice{Cmdline: parts[1:]}
	}
	return
}

// extensions_of returns all the possible extensions of a file name, for
// example: a.tar.gz -> gz, tar.gz
func extensions_of(name string) (ans []string) {
	name = strings.ToLower(name)
	// ignore the leading dot of hidden files
	trimmed := strings.TrimLeft(name, ".")
	for i := len(trimmed) - 1; i > 0; i-- {
		if trimmed[i] == '.' && i+1 < len(trimmed) {
			ans = append(ans, trimmed[i+1:])
		}
	}
	return
}

func (r OpenWithRule) match_any(candidates ...string) bool {
	for _, p := range r.patterns {
		for _, c := range candidates {
			if m, err := path.Match(p, c); m && err == nil {
				return true
			}
		}
	}
	return false
}

// Matches returns true if this rule matches the target. mime_types is the MIME
// type of the target, its aliases and the types it is a sub-class of.
func (r OpenWithRule) Matches(t Target, mime_types []string) bool {
	switch r.kind {
	case mime_criterion:
		lowered := make([]string, len(mime_types))
		for i, m := range mime_types {
			lowered[i] = strings.ToLower(m)
		}
		return r.match_any(lowered...)
	case scheme_criterion:
		scheme := "file"
		if t.URL != "" {
			scheme, _, _ = strings.Cut(t.URL, ":")
		}
		return r.match_any(strings.ToLower(scheme))
	case ext_criterion:
		return t.Path != "" && r.match_any(extensions_of(filepath.Base(t.Path))...)
	case glob_criterion:
		if t.Path == "" {
			return false
		}
		p := r.patterns[0]
		if strings.Contains(p, "/") {
			m, err := doublestar.PathMatch(utils.Expanduser(p), t.Path)
			return m && err == nil
		}
		m, err := path.Match(p, filepath.Base(t.Path))
		return m && err == nil
	}
	return false
}

// Settings is the parsed configuration of this kitten
type Settings struct {
	*Config
	Rules []OpenWithRule
}

func LoadSettings(config_paths, overrides []string) (ans *Settings, err error) {
	cfg := NewConfig()
	p := config.ConfigParser{LineHandler: cfg.Parse}
	if err = p.LoadConfig("choose-app.conf", config_paths, overrides); err != nil {
		return nil, err
	}
	return settings_from_config(cfg)
}

func settings_from_config(cfg *Config) (ans *Settings, err error) {
	ans = &Settings{Config: cfg}
	for _, spec := range cfg.Open_with {
		rule, err := ParseOpenWith(spec)
		if err != nil {
			return nil, err
		}
		ans.Rules = append(ans.Rules, rule)
	}
	return ans, nil
}
