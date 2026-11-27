// License: GPLv3 Copyright: 2026, Kovid Goyal, <kovid at kovidgoyal.net>

package choose_app

import (
	"bufio"
	"context"
	"fmt"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"time"

	"github.com/kovidgoyal/dbus"
	"github.com/kovidgoyal/kitty/tools/utils"
)

var _ = fmt.Print

// Icon lookup as per
// https://specifications.freedesktop.org/icon-theme-spec/latest/

// parse_ini parses the INI style files used by icon themes and GTK/KDE
// settings. Keys with KDE style flags such as Theme[$e] have the flags
// removed.
func parse_ini(path string) (ans map[string]map[string]string, err error) {
	f, err := os.Open(path)
	if err != nil {
		return nil, err
	}
	defer f.Close()
	ans = map[string]map[string]string{}
	var current map[string]string
	scanner := bufio.NewScanner(f)
	scanner.Buffer(make([]byte, 0, 4096), 1024*1024)
	for scanner.Scan() {
		line := strings.TrimSpace(scanner.Text())
		if line == "" || line[0] == '#' || line[0] == ';' {
			continue
		}
		if line[0] == '[' && line[len(line)-1] == ']' {
			name := line[1 : len(line)-1]
			if current = ans[name]; current == nil {
				current = map[string]string{}
				ans[name] = current
			}
			continue
		}
		if current == nil {
			continue
		}
		if k, v, found := strings.Cut(line, "="); found {
			k, _, _ = strings.Cut(k, "[$")
			current[strings.TrimSpace(k)] = strings.Trim(strings.TrimSpace(v), `"'`)
		}
	}
	return ans, scanner.Err()
}

func read_ini_value(path, group, key string) string {
	if data, err := parse_ini(path); err == nil {
		return data[group][key]
	}
	return ""
}

// icon_theme_from_portal reads the icon theme from the desktop settings
// portal, the same setting that GTK and kitty itself use.
func icon_theme_from_portal() string {
	conn, err := dbus.SessionBus()
	if err != nil {
		return ""
	}
	ctx, cancel := context.WithTimeout(context.Background(), 250*time.Millisecond)
	defer cancel()
	obj := conn.Object("org.freedesktop.portal.Desktop", "/org/freedesktop/portal/desktop")
	var v dbus.Variant
	if err = obj.CallWithContext(ctx, "org.freedesktop.portal.Settings.ReadOne", dbus.FlagNoAutoStart, "org.gnome.desktop.interface", "icon-theme").Store(&v); err != nil {
		return ""
	}
	if ans, ok := v.Value().(string); ok {
		return ans
	}
	return ""
}

func (x *XDGDirs) icon_theme_from_config_files() string {
	kde := [3]string{filepath.Join(x.ConfigHome, "kdeglobals"), "Icons", "Theme"}
	candidates := [][3]string{
		{filepath.Join(x.ConfigHome, "gtk-4.0", "settings.ini"), "Settings", "gtk-icon-theme-name"},
		{filepath.Join(x.ConfigHome, "gtk-3.0", "settings.ini"), "Settings", "gtk-icon-theme-name"},
	}
	is_kde := false
	for _, d := range x.CurrentDesktops {
		if strings.EqualFold(d, "KDE") {
			is_kde = true
		}
	}
	if is_kde {
		candidates = append([][3]string{kde}, candidates...)
	} else {
		candidates = append(candidates, kde)
	}
	for _, c := range candidates {
		if ans := read_ini_value(c[0], c[1], c[2]); ans != "" {
			return ans
		}
	}
	return ""
}

// IconThemeName returns the name of the icon theme configured for the desktop,
// or the empty string if none is configured
func (x *XDGDirs) IconThemeName() string {
	if ans := icon_theme_from_portal(); ans != "" {
		return ans
	}
	return x.icon_theme_from_config_files()
}

// split_theme_name splits the name of an icon theme into the name of its
// light variant and whether it is a dark variant, for example: breeze-dark ->
// (breeze, true), Papirus-Dark -> (Papirus, true), Yaru_dark -> (Yaru, true)
func split_theme_name(name string) (base string, is_dark bool) {
	lname := strings.ToLower(name)
	if !strings.HasSuffix(lname, "dark") {
		return name, false
	}
	base = name[:len(name)-len("dark")]
	base = strings.TrimRight(base, "-_ ")
	if base == "" {
		return name, false
	}
	return base, true
}

// IconThemeForBackground returns the variant of the specified icon theme
// suitable for the terminal background. The monochrome icons of light
// themes are drawn for light backgrounds and are almost invisible on dark
// ones, and vice versa. So on a dark background, an installed dark variant
// of the theme, such as breeze-dark for breeze or Papirus-Dark for Papirus,
// is used and on a light background the light variant of a dark theme is
// used. When no such variant is installed, the theme is returned unchanged.
func (x *XDGDirs) IconThemeForBackground(theme string, dark_background bool) string {
	if theme == "" {
		return theme
	}
	base, is_dark := split_theme_name(theme)
	if is_dark == dark_background {
		return theme
	}
	lbase := strings.ToLower(base)
	best := ""
	for _, ibase := range x.IconBaseDirs() {
		list_dir(ibase, func(name string) {
			cbase, cdark := split_theme_name(name)
			if cdark != dark_background || strings.ToLower(cbase) != lbase {
				return
			}
			if _, err := os.Stat(filepath.Join(ibase, name, "index.theme")); err != nil {
				return
			}
			// prefer the exact case of the original theme name, then the
			// first in sorted order, for determinism
			exact, best_exact := strings.HasPrefix(name, base), strings.HasPrefix(best, base)
			if best == "" || (exact && !best_exact) || (exact == best_exact && name < best) {
				best = name
			}
		})
		if best != "" {
			return best
		}
	}
	return theme
}

// IconBaseDirs returns the directories in which icon themes are looked for, in
// order of decreasing priority
func (x *XDGDirs) IconBaseDirs() (ans []string) {
	ans = append(ans, filepath.Join(x.DataHome, "icons"))
	if x.Home != "" {
		ans = append(ans, filepath.Join(x.Home, ".icons"))
	}
	for _, d := range x.DataDirs {
		ans = append(ans, filepath.Join(d, "icons"))
	}
	return utils.Uniq(ans)
}

// PixmapDirs returns the directories used for icons not found in any theme
func (x *XDGDirs) PixmapDirs() (ans []string) {
	for _, d := range x.DataDirs {
		ans = append(ans, filepath.Join(d, "pixmaps"))
	}
	return utils.Uniq(ans)
}

type icon_dir_type int

const (
	icon_dir_threshold icon_dir_type = iota
	icon_dir_fixed
	icon_dir_scalable
)

type icon_dir struct {
	name                             string
	size, scale, min, max, threshold int
	kind                             icon_dir_type
}

func new_icon_dir(name string, group map[string]string) (ans icon_dir, ok bool) {
	atoi := func(key string, defval int) int {
		if v, err := strconv.Atoi(group[key]); err == nil && v > 0 {
			return v
		}
		return defval
	}
	if ans.size = atoi("Size", 0); ans.size == 0 {
		return ans, false
	}
	ans.name = name
	ans.scale = atoi("Scale", 1)
	ans.min, ans.max = atoi("MinSize", ans.size), atoi("MaxSize", ans.size)
	ans.threshold = atoi("Threshold", 2)
	switch group["Type"] {
	case "Fixed":
		ans.kind = icon_dir_fixed
	case "Scalable":
		ans.kind = icon_dir_scalable
	default:
		ans.kind = icon_dir_threshold
	}
	return ans, true
}

// distance returns the distance in pixels between the size of the icons in
// this directory and the requested size, zero means the icons match the size.
func (d icon_dir) distance(px int) int {
	lo, hi := d.size*d.scale, d.size*d.scale
	switch d.kind {
	case icon_dir_scalable:
		lo, hi = d.min*d.scale, d.max*d.scale
	case icon_dir_threshold:
		lo, hi = (d.size-d.threshold)*d.scale, (d.size+d.threshold)*d.scale
	}
	switch {
	case px < lo:
		return lo - px
	case px > hi:
		return px - hi
	}
	return 0
}

// largest returns the largest size in pixels that icons in this directory can
// be rendered at without upscaling
func (d icon_dir) largest() int {
	if d.kind == icon_dir_scalable {
		return d.max * d.scale
	}
	return d.size * d.scale
}

type icon_theme struct {
	name     string
	dirs     []icon_dir
	inherits []string
}

func (x *XDGDirs) load_icon_theme(name string) (ans icon_theme, found bool) {
	ans.name = name
	for _, base := range x.IconBaseDirs() {
		data, err := parse_ini(filepath.Join(base, name, "index.theme"))
		if err != nil {
			continue
		}
		main := data["Icon Theme"]
		for x := range strings.SplitSeq(main["Inherits"], ",") {
			if x = strings.TrimSpace(x); x != "" {
				ans.inherits = append(ans.inherits, x)
			}
		}
		if !found {
			// The directories come from the highest priority index.theme
			found = true
			dirs := main["Directories"] + "," + main["ScaledDirectories"]
			seen := utils.NewSet[string]()
			for d := range strings.SplitSeq(dirs, ",") {
				if d = strings.TrimSpace(d); d != "" && !seen.Has(d) {
					seen.Add(d)
					if idir, ok := new_icon_dir(d, data[d]); ok {
						ans.dirs = append(ans.dirs, idir)
					}
				}
			}
		}
	}
	return
}

// themes_to_search returns the theme and all the themes it inherits from, in
// breadth first order, with hicolor last. The inherits of all index.theme files
// for a theme are used, so that a theme with no Inherits in one base dir, such
// as a cursor only default theme in the users home, does not hide the others.
func (x *XDGDirs) themes_to_search(theme string) (ans []icon_theme) {
	if theme == "" {
		theme = "default"
	}
	seen := utils.NewSet[string]()
	queue := []string{theme}
	for len(queue) > 0 {
		t := queue[0]
		queue = queue[1:]
		if seen.Has(t) || t == "hicolor" {
			continue
		}
		seen.Add(t)
		if it, found := x.load_icon_theme(t); found {
			ans = append(ans, it)
			queue = append(queue, it.inherits...)
		}
	}
	if it, found := x.load_icon_theme("hicolor"); found {
		ans = append(ans, it)
	}
	return
}

var icon_extensions = map[string]int{".png": 0, ".svg": 1, ".xpm": 2}

type icon_candidate struct {
	path         string
	distance     int
	largest      int
	ext_priority int
	order        int
}

func (c icon_candidate) better_than(o icon_candidate) bool {
	if c.distance != o.distance {
		return c.distance < o.distance
	}
	if c.distance > 0 && c.largest != o.largest {
		// prefer downscaling to upscaling
		return c.largest > o.largest
	}
	if c.order != o.order {
		return c.order < o.order
	}
	return c.ext_priority < o.ext_priority
}

// normalize_icon_name removes the file extensions that some desktop files
// incorrectly add to icon names
func normalize_icon_name(name string) string {
	ext := filepath.Ext(name)
	if _, found := icon_extensions[strings.ToLower(ext)]; found {
		return name[:len(name)-len(ext)]
	}
	return name
}

func list_dir(path string, callback func(name string)) {
	f, err := os.Open(path)
	if err != nil {
		return
	}
	defer f.Close()
	for {
		names, err := f.Readdirnames(1024)
		for _, n := range names {
			callback(n)
		}
		if err != nil {
			return
		}
	}
}

// FindIcons returns the paths to the icon files for the specified icon names,
// as found in the Icon key of desktop files, best suited for display at the
// specified size in pixels. Names that are absolute paths are used as is, if
// they exist. Names for which no icon is found are not present in the result.
func (x *XDGDirs) FindIcons(theme string, px int, names ...string) (ans map[string]string) {
	ans = make(map[string]string, len(names))
	remaining := map[string][]string{} // normalized name -> original names
	for _, n := range names {
		if n == "" {
			continue
		}
		if filepath.IsAbs(n) {
			if s, err := os.Stat(n); err == nil && !s.IsDir() {
				ans[n] = n
			}
			continue
		}
		nn := normalize_icon_name(n)
		remaining[nn] = append(remaining[nn], n)
	}
	found := func(nn, path string) {
		for _, n := range remaining[nn] {
			ans[n] = path
		}
		delete(remaining, nn)
	}
	match := func(fname string) (nn string, ext_priority int, ok bool) {
		ext := filepath.Ext(fname)
		if ext_priority, ok = icon_extensions[ext]; ok {
			nn = fname[:len(fname)-len(ext)]
			_, ok = remaining[nn]
		}
		return
	}
	for _, t := range x.themes_to_search(theme) {
		if len(remaining) == 0 {
			break
		}
		best := map[string]icon_candidate{}
		order := 0
		for _, d := range t.dirs {
			distance, largest := d.distance(px), d.largest()
			for _, base := range x.IconBaseDirs() {
				dirpath := filepath.Join(base, t.name, d.name)
				list_dir(dirpath, func(fname string) {
					if nn, ext_priority, ok := match(fname); ok {
						c := icon_candidate{path: filepath.Join(dirpath, fname), distance: distance, largest: largest, ext_priority: ext_priority, order: order}
						if prev, exists := best[nn]; !exists || c.better_than(prev) {
							best[nn] = c
						}
					}
				})
				order++
			}
		}
		for nn, c := range best {
			found(nn, c.path)
		}
	}
	for _, dirpath := range x.PixmapDirs() {
		if len(remaining) == 0 {
			break
		}
		best := map[string]icon_candidate{}
		list_dir(dirpath, func(fname string) {
			if nn, ext_priority, ok := match(fname); ok {
				c := icon_candidate{path: filepath.Join(dirpath, fname), ext_priority: ext_priority}
				if prev, exists := best[nn]; !exists || c.better_than(prev) {
					best[nn] = c
				}
			}
		})
		for nn, c := range best {
			found(nn, c.path)
		}
	}
	return
}
