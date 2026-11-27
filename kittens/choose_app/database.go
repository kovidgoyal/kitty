// License: GPLv3 Copyright: 2026, Kovid Goyal, <kovid at kovidgoyal.net>

package choose_app

import (
	"bufio"
	"errors"
	"fmt"
	"io/fs"
	"os"
	"path/filepath"
	"slices"
	"strings"

	"github.com/kovidgoyal/kitty/tools/utils"
)

var _ = fmt.Print

// XDGDirs holds the base directories used to locate applications and
// MIME associations, see
// https://specifications.freedesktop.org/basedir-spec/latest/
type XDGDirs struct {
	DataHome, ConfigHome string
	DataDirs, ConfigDirs []string
	// The components of XDG_CURRENT_DESKTOP
	CurrentDesktops []string
	// The localized key suffixes to use in order of preference
	Locales []string
}

func split_dirs(val, defval string) (ans []string) {
	if val == "" {
		val = defval
	}
	for x := range strings.SplitSeq(val, ":") {
		// relative paths are ignored as per the spec
		if filepath.IsAbs(x) {
			ans = append(ans, filepath.Clean(x))
		}
	}
	return utils.Uniq(ans)
}

func abs_or_default(val, defval string) string {
	if val == "" || !filepath.IsAbs(val) {
		return utils.Expanduser(defval)
	}
	return filepath.Clean(val)
}

func XDGDirsFromEnvironment() *XDGDirs {
	return &XDGDirs{
		DataHome:        abs_or_default(os.Getenv("XDG_DATA_HOME"), "~/.local/share"),
		ConfigHome:      abs_or_default(os.Getenv("XDG_CONFIG_HOME"), "~/.config"),
		DataDirs:        split_dirs(os.Getenv("XDG_DATA_DIRS"), "/usr/local/share:/usr/share"),
		ConfigDirs:      split_dirs(os.Getenv("XDG_CONFIG_DIRS"), "/etc/xdg"),
		CurrentDesktops: utils.Filter(strings.Split(os.Getenv("XDG_CURRENT_DESKTOP"), ":"), func(x string) bool { return x != "" }),
		Locales:         CurrentLocales(),
	}
}

// ApplicationDirs returns the directories containing desktop files, in order of
// decreasing priority
func (x *XDGDirs) ApplicationDirs() (ans []string) {
	ans = append(ans, filepath.Join(x.DataHome, "applications"))
	for _, d := range x.DataDirs {
		ans = append(ans, filepath.Join(d, "applications"))
	}
	return utils.Uniq(ans)
}

// MimeAppsListFiles returns the mimeapps.list files in order of decreasing priority, see
// https://specifications.freedesktop.org/mime-apps-spec/latest/file.html
func (x *XDGDirs) MimeAppsListFiles() (ans []string) {
	add := func(dir string) {
		for _, desktop := range x.CurrentDesktops {
			ans = append(ans, filepath.Join(dir, strings.ToLower(desktop)+"-mimeapps.list"))
		}
		ans = append(ans, filepath.Join(dir, "mimeapps.list"))
	}
	add(x.ConfigHome)
	for _, d := range x.ConfigDirs {
		add(d)
	}
	// The data dir locations are deprecated but still supported
	for _, d := range x.ApplicationDirs() {
		add(d)
	}
	return utils.Uniq(ans)
}

type mimeapps_list struct {
	defaults, added, removed map[string][]string
}

func parse_mimeapps_list(path string) (ans mimeapps_list, err error) {
	f, err := os.Open(path)
	if err != nil {
		return
	}
	defer f.Close()
	ans = mimeapps_list{defaults: map[string][]string{}, added: map[string][]string{}, removed: map[string][]string{}}
	var current map[string][]string
	scanner := bufio.NewScanner(f)
	for scanner.Scan() {
		line := strings.TrimSpace(scanner.Text())
		if line == "" || line[0] == '#' {
			continue
		}
		if line[0] == '[' {
			switch line {
			case "[Default Applications]":
				current = ans.defaults
			case "[Added Associations]":
				current = ans.added
			case "[Removed Associations]":
				current = ans.removed
			default:
				current = nil
			}
			continue
		}
		if current == nil {
			continue
		}
		if mime, val, found := strings.Cut(line, "="); found {
			mime = strings.TrimSpace(mime)
			current[mime] = append(current[mime], parse_list(strings.TrimSpace(val))...)
		}
	}
	err = scanner.Err()
	return
}

// AppDatabase is the set of installed applications along with the user's
// preferences for which applications open which MIME types.
type AppDatabase struct {
	dirs *XDGDirs
	// All launchable applications, sorted by name
	apps []*DesktopEntry
	// Map of desktop file id to application
	by_id map[string]*DesktopEntry
	// Map of MIME type to default application ids in order of priority
	defaults map[string][]string
	// Map of MIME type to associated application ids in order of priority
	associations map[string][]string
	// Errors encountered while loading, these are not fatal
	Errors []error

	mime_ancestors func(string) []string
}

// desktop_file_id returns the desktop file id for a desktop file at relpath
// in an applications directory as per the spec
func desktop_file_id(relpath string) string {
	return strings.ReplaceAll(filepath.ToSlash(relpath), "/", "-")
}

func (db *AppDatabase) scan_applications() {
	seen := utils.NewSet[string](512)
	for dir_priority, base := range db.dirs.ApplicationDirs() {
		err := filepath.WalkDir(base, func(path string, d fs.DirEntry, err error) error {
			if err != nil {
				if path == base && errors.Is(err, fs.ErrNotExist) {
					return fs.SkipDir
				}
				db.Errors = append(db.Errors, err)
				if d != nil && d.IsDir() {
					return fs.SkipDir
				}
				return nil
			}
			if d.IsDir() || !strings.HasSuffix(d.Name(), ".desktop") {
				return nil
			}
			rel, rerr := filepath.Rel(base, path)
			if rerr != nil {
				db.Errors = append(db.Errors, rerr)
				return nil
			}
			id := desktop_file_id(rel)
			if seen.Has(id) {
				// a higher priority desktop file with this id already exists,
				// including ones that are Hidden, which mask lower priority ones
				return nil
			}
			seen.Add(id)
			entry, perr := ParseDesktopFile(path, db.dirs.Locales)
			if perr != nil {
				db.Errors = append(db.Errors, perr)
				return nil
			}
			entry.ID, entry.dir_priority = id, dir_priority
			if entry.is_launchable() {
				db.by_id[id] = entry
				db.apps = append(db.apps, entry)
			}
			return nil
		})
		if err != nil {
			db.Errors = append(db.Errors, err)
		}
	}
	slices.SortStableFunc(db.apps, func(a, b *DesktopEntry) int {
		if c := strings.Compare(strings.ToLower(a.Name), strings.ToLower(b.Name)); c != 0 {
			return c
		}
		return strings.Compare(a.ID, b.ID)
	})
}

func (db *AppDatabase) load_associations() {
	removed := map[string]*utils.Set[string]{}
	is_removed := func(mime, id string) bool {
		s := removed[mime]
		return s != nil && s.Has(id)
	}
	add_association := func(mime, id string) {
		if _, found := db.by_id[id]; found && !is_removed(mime, id) && !slices.Contains(db.associations[mime], id) {
			db.associations[mime] = append(db.associations[mime], id)
		}
	}
	for _, path := range db.dirs.MimeAppsListFiles() {
		ml, err := parse_mimeapps_list(path)
		if err != nil {
			if !errors.Is(err, fs.ErrNotExist) && !errors.Is(err, fs.ErrPermission) {
				db.Errors = append(db.Errors, fmt.Errorf("failed to read %s with error: %w", path, err))
			}
			continue
		}
		for mime, ids := range ml.defaults {
			for _, id := range ids {
				if !slices.Contains(db.defaults[mime], id) {
					db.defaults[mime] = append(db.defaults[mime], id)
				}
			}
		}
		for mime, ids := range ml.added {
			for _, id := range ids {
				add_association(mime, id)
			}
		}
		// Removals apply to all files and desktop files of lower priority
		for mime, ids := range ml.removed {
			if removed[mime] == nil {
				removed[mime] = utils.NewSet[string]()
			}
			removed[mime].AddItems(ids...)
		}
	}
	// Finally, the MIME types declared by the applications themselves, the
	// apps list is sorted by name, so iterate in priority order of directories
	by_priority := slices.Clone(db.apps)
	slices.SortStableFunc(by_priority, func(a, b *DesktopEntry) int { return a.dir_priority - b.dir_priority })
	for _, e := range by_priority {
		for _, mime := range e.MimeTypes {
			add_association(mime, e.ID)
		}
	}
}

func new_app_database(dirs *XDGDirs, mime_ancestors func(string) []string) *AppDatabase {
	db := &AppDatabase{
		dirs: dirs, by_id: map[string]*DesktopEntry{}, defaults: map[string][]string{},
		associations: map[string][]string{}, mime_ancestors: mime_ancestors,
	}
	db.scan_applications()
	db.load_associations()
	return db
}

// LoadAppDatabase scans the system for installed applications and MIME associations
func LoadAppDatabase() *AppDatabase {
	return new_app_database(XDGDirsFromEnvironment(), utils.MimeTypeAncestors)
}

// AllApps returns all applications that should be shown to the user, sorted by name
func (db *AppDatabase) AllApps() []*DesktopEntry {
	return utils.Filter(db.apps, func(e *DesktopEntry) bool { return e.ShouldShow(db.dirs.CurrentDesktops) })
}

// AppByID returns the application with the specified desktop file id, which
// may or may not have the .desktop suffix
func (db *AppDatabase) AppByID(id string) *DesktopEntry {
	if !strings.HasSuffix(id, ".desktop") {
		id += ".desktop"
	}
	return db.by_id[id]
}

// mime_types_for returns the MIME type, its aliases and ancestors in order
func (db *AppDatabase) mime_types_for(mime string) (ans []string) {
	seen := utils.NewSet[string]()
	add := func(x string) {
		if !seen.Has(x) {
			seen.Add(x)
			ans = append(ans, x)
		}
	}
	add(mime)
	for _, m := range db.mime_ancestors(mime) {
		add(m)
		for _, a := range utils.MimeTypeAliases(m) {
			add(a)
		}
	}
	return
}

// DefaultAppFor returns the default application for the specified MIME type
// from mimeapps.list, falling back to the defaults for its parent types.
// Returns nil if no default is configured.
func (db *AppDatabase) DefaultAppFor(mime string) *DesktopEntry {
	for _, m := range db.mime_types_for(mime) {
		for _, id := range db.defaults[m] {
			if e := db.by_id[id]; e != nil {
				return e
			}
		}
	}
	return nil
}

// AppsFor returns the applications that can open the specified MIME type, in
// order of preference: the default application first, then applications
// associated with the type, then with its parent types.
func (db *AppDatabase) AppsFor(mime string) (ans []*DesktopEntry) {
	seen := utils.NewSet[string]()
	add := func(e *DesktopEntry) {
		if e != nil && !seen.Has(e.ID) {
			seen.Add(e.ID)
			ans = append(ans, e)
		}
	}
	add(db.DefaultAppFor(mime))
	for _, m := range db.mime_types_for(mime) {
		for _, id := range db.associations[m] {
			add(db.by_id[id])
		}
	}
	return
}

// MimeTypeForTarget returns the MIME type used to find applications for the
// specified target. URLs use the x-scheme-handler/scheme type.
func MimeTypeForTarget(t Target) string {
	if t.URL != "" {
		scheme, _, _ := strings.Cut(t.URL, ":")
		return "x-scheme-handler/" + strings.ToLower(scheme)
	}
	if ans := utils.GuessMimeTypeWithFileSystemAccess(t.Path); ans != "" {
		return ans
	}
	return "application/octet-stream"
}
