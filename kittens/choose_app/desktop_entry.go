// License: GPLv3 Copyright: 2026, Kovid Goyal, <kovid at kovidgoyal.net>

package choose_app

import (
	"bufio"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"strings"

	"github.com/kovidgoyal/kitty/tools/utils"
)

var _ = fmt.Print

// DesktopEntry represents an application from a .desktop file, see
// https://specifications.freedesktop.org/desktop-entry-spec/latest/
type DesktopEntry struct {
	// The desktop file id, for example org.kde.okular.desktop
	ID   string `json:"id"`
	Path string `json:"path"`

	Name        string   `json:"name"`
	GenericName string   `json:"generic_name,omitempty"`
	Comment     string   `json:"comment,omitempty"`
	Icon        string   `json:"icon,omitempty"`
	Keywords    []string `json:"keywords,omitempty"`
	Categories  []string `json:"categories,omitempty"`
	MimeTypes   []string `json:"mime_types,omitempty"`
	Exec        string   `json:"exec"`
	TryExec     string   `json:"-"`
	WorkingDir  string   `json:"working_dir,omitempty"`
	Terminal    bool     `json:"terminal,omitempty"`
	// Whether the application should be started via D-Bus rather than
	// by running Exec, see the D-Bus Activation section of the spec
	DBusActivatable bool     `json:"dbus_activatable,omitempty"`
	OnlyShowIn      []string `json:"-"`
	NotShowIn       []string `json:"-"`

	entry_type, no_display, hidden bool
	dir_priority                   int
	// Pre-split arguments, used instead of Exec, if not nil
	exec_tokens []exec_token
}

// IDWithoutSuffix returns the desktop file id without the .desktop suffix,
// this is the form used by the XDG desktop portals.
func (d *DesktopEntry) IDWithoutSuffix() string {
	return strings.TrimSuffix(d.ID, ".desktop")
}

// ShouldShow returns true if the application should be shown in lists of all
// applications in the specified desktop environments (the components of
// XDG_CURRENT_DESKTOP). Applications that should not be shown can still be used to
// open files of the MIME types they declare.
func (d *DesktopEntry) ShouldShow(current_desktops []string) bool {
	if d.no_display {
		return false
	}
	matches := func(q []string) bool {
		for _, x := range q {
			for _, c := range current_desktops {
				if strings.EqualFold(x, c) {
					return true
				}
			}
		}
		return false
	}
	if len(d.OnlyShowIn) > 0 && !matches(d.OnlyShowIn) {
		return false
	}
	if len(d.NotShowIn) > 0 && matches(d.NotShowIn) {
		return false
	}
	return true
}

// SupportsURLs returns true if the Exec line of the application accepts URLs
// rather than only local file paths
func (d *DesktopEntry) SupportsURLs() bool {
	return strings.Contains(d.Exec, "%u") || strings.Contains(d.Exec, "%U")
}

// Locale matching as per the spec {{{

// locale_candidates returns the localized key suffixes to try, in order of
// preference, for the specified POSIX locale of the form
// lang_COUNTRY.ENCODING@MODIFIER
func locale_candidates(locale string) (ans []string) {
	if locale == "" || locale == "C" || locale == "POSIX" {
		return nil
	}
	lang, modifier, _ := strings.Cut(locale, "@")
	lang, _, _ = strings.Cut(lang, ".")
	lang, country, _ := strings.Cut(lang, "_")
	if lang == "" {
		return nil
	}
	if country != "" && modifier != "" {
		ans = append(ans, lang+"_"+country+"@"+modifier)
	}
	if country != "" {
		ans = append(ans, lang+"_"+country)
	}
	if modifier != "" {
		ans = append(ans, lang+"@"+modifier)
	}
	return append(ans, lang)
}

// CurrentLocales returns the localized key suffixes to try in order of
// preference based on the LANGUAGE, LC_ALL, LC_MESSAGES and LANG environment
// variables, the same as GLib does.
func CurrentLocales() (ans []string) {
	locale := ""
	for _, x := range []string{"LC_ALL", "LC_MESSAGES", "LANG"} {
		if locale = os.Getenv(x); locale != "" {
			break
		}
	}
	if locale == "" || locale == "C" || locale == "POSIX" {
		// LANGUAGE is ignored when the locale is C as per gettext
		return nil
	}
	seen := utils.NewSet[string]()
	add := func(l string) {
		for _, x := range locale_candidates(l) {
			if !seen.Has(x) {
				seen.Add(x)
				ans = append(ans, x)
			}
		}
	}
	for x := range strings.SplitSeq(os.Getenv("LANGUAGE"), ":") {
		add(x)
	}
	add(locale)
	return
}

// }}}

// Value parsing {{{

func unescape_string(val string) string {
	if !strings.Contains(val, `\`) {
		return val
	}
	var b strings.Builder
	b.Grow(len(val))
	for i := 0; i < len(val); i++ {
		ch := val[i]
		if ch == '\\' && i+1 < len(val) {
			i++
			switch val[i] {
			case 's':
				b.WriteByte(' ')
			case 'n':
				b.WriteByte('\n')
			case 't':
				b.WriteByte('\t')
			case 'r':
				b.WriteByte('\r')
			case '\\':
				b.WriteByte('\\')
			default:
				// Unknown escapes, such as \; in lists, are preserved for later processing
				b.WriteByte('\\')
				b.WriteByte(val[i])
			}
		} else {
			b.WriteByte(ch)
		}
	}
	return b.String()
}

// parse_list parses a list of strings separated by semi-colons, with \; used
// to escape a semi-colon.
func parse_list(val string) (ans []string) {
	var cur strings.Builder
	flush := func() {
		if x := unescape_string(cur.String()); x != "" {
			ans = append(ans, x)
		}
		cur.Reset()
	}
	for i := 0; i < len(val); i++ {
		switch ch := val[i]; {
		case ch == '\\' && i+1 < len(val) && val[i+1] == ';':
			cur.WriteByte(';')
			i++
		case ch == '\\' && i+1 < len(val):
			cur.WriteByte(ch)
			cur.WriteByte(val[i+1])
			i++
		case ch == ';':
			flush()
		default:
			cur.WriteByte(ch)
		}
	}
	flush()
	return
}

func parse_bool(val string) bool { return val == "true" }

// }}}

type localized_value struct {
	value    string
	priority int // index into the locales list, len(locales) for the unlocalized value
	found    bool
}

func (v *localized_value) set(value string, priority int) {
	if !v.found || priority < v.priority {
		v.value, v.priority, v.found = value, priority, true
	}
}

// ParseDesktopEntry parses the [Desktop Entry] group of a desktop file.
// locales is the list of localized key suffixes to use, in order of preference.
func ParseDesktopEntry(r io.Reader, locales []string) (ans *DesktopEntry, err error) {
	ans = &DesktopEntry{}
	locale_priority := make(map[string]int, len(locales))
	for i, l := range locales {
		locale_priority[l] = i
	}
	unlocalized := len(locales)
	var name, generic_name, comment, keywords localized_value
	scanner := bufio.NewScanner(r)
	scanner.Buffer(make([]byte, 0, 4096), 1024*1024)
	in_main_group, seen_main_group := false, false
	for scanner.Scan() {
		line := strings.TrimSpace(scanner.Text())
		if line == "" || line[0] == '#' {
			continue
		}
		if line[0] == '[' {
			if in_main_group {
				// [Desktop Entry] is followed by other groups such as actions
				break
			}
			in_main_group = line == "[Desktop Entry]"
			seen_main_group = seen_main_group || in_main_group
			continue
		}
		if !in_main_group {
			continue
		}
		key, val, found := strings.Cut(line, "=")
		if !found {
			continue
		}
		key, val = strings.TrimSpace(key), strings.TrimSpace(val)
		priority := unlocalized
		if base, locale, is_localized := strings.Cut(key, "["); is_localized {
			locale = strings.TrimSuffix(locale, "]")
			p, ok := locale_priority[locale]
			if !ok {
				continue
			}
			key, priority = base, p
		}
		switch key {
		case "Type":
			ans.entry_type = val == "Application"
		case "Name":
			name.set(unescape_string(val), priority)
		case "GenericName":
			generic_name.set(unescape_string(val), priority)
		case "Comment":
			comment.set(unescape_string(val), priority)
		case "Keywords":
			keywords.set(val, priority)
		case "Icon":
			ans.Icon = unescape_string(val)
		case "Exec":
			ans.Exec = unescape_string(val)
		case "TryExec":
			ans.TryExec = unescape_string(val)
		case "Path":
			ans.WorkingDir = unescape_string(val)
		case "Terminal":
			ans.Terminal = parse_bool(val)
		case "DBusActivatable":
			ans.DBusActivatable = parse_bool(val)
		case "NoDisplay":
			ans.no_display = parse_bool(val)
		case "Hidden":
			ans.hidden = parse_bool(val)
		case "OnlyShowIn":
			ans.OnlyShowIn = parse_list(val)
		case "NotShowIn":
			ans.NotShowIn = parse_list(val)
		case "MimeType":
			ans.MimeTypes = parse_list(val)
		case "Categories":
			ans.Categories = parse_list(val)
		}
	}
	if err = scanner.Err(); err != nil {
		return nil, err
	}
	if !seen_main_group {
		return nil, fmt.Errorf("no [Desktop Entry] group found")
	}
	ans.Name, ans.GenericName, ans.Comment = name.value, generic_name.value, comment.value
	ans.Keywords = parse_list(keywords.value)
	return ans, nil
}

func ParseDesktopFile(path string, locales []string) (ans *DesktopEntry, err error) {
	f, err := os.Open(path)
	if err != nil {
		return nil, err
	}
	defer f.Close()
	if ans, err = ParseDesktopEntry(f, locales); err != nil {
		return nil, fmt.Errorf("failed to parse the desktop file %s with error: %w", path, err)
	}
	ans.Path = path
	return
}

// is_launchable returns true if the entry is an application that can be run
func (d *DesktopEntry) is_launchable() bool {
	if !d.entry_type || d.hidden || d.Name == "" {
		return false
	}
	if d.Exec == "" {
		// The spec allows applications started via D-Bus to have no Exec line
		if _, ok := d.dbus_name(); !d.DBusActivatable || !ok {
			return false
		}
	}
	if d.TryExec != "" {
		if filepath.IsAbs(d.TryExec) {
			if s, err := os.Stat(d.TryExec); err != nil || s.IsDir() || s.Mode().Perm()&0o111 == 0 {
				return false
			}
		} else if utils.Which(d.TryExec) == "" {
			return false
		}
	}
	return true
}
