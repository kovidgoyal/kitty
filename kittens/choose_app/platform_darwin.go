// License: GPLv3 Copyright: 2026, Kovid Goyal, <kovid at kovidgoyal.net>

package choose_app

import (
	"fmt"
	"os"
	"path/filepath"
	"slices"
	"strings"
	"sync"

	"github.com/kovidgoyal/kitty/tools/utils"
	"howett.net/plist"
)

var _ = fmt.Print

// Applications are identified by their bundle ids, such as com.apple.Preview
var app_id_suffix = ""

// On macOS almost every type of file has a default application, so using
// it without asking would make this kitten equivalent to the open command
func set_platform_defaults(cfg *Config) {
	cfg.Use_system_defaults = false
}

// The MIME type used for types of files that have no MIME type
const uti_mime_prefix = "x-apple-uti/"

// The uniform type identifiers of the MIME types of files seen so far, used
// to look up applications for the exact type of file rather than for the
// type corresponding to the MIME type
var uti_for_mime = struct {
	sync.Mutex
	m map[string]string
}{m: map[string]string{}}

func is_generic_mime_type(mime string) bool {
	switch mime {
	case "application/octet-stream", "inode/directory", "inode/executable":
		return true
	}
	return false
}

// platform_mime_type_for_path returns the MIME type for the type of file
// LaunchServices thinks the file is, so that the applications for it are
// the ones shown by Finder. Types of files with no MIME type, such as
// application bundles, use a MIME type of the form x-apple-uti/<identifier>.
func platform_mime_type_for_path(path string) string {
	guess := mime_type_for_path(path)
	if real_path, err := filepath.EvalSymlinks(path); err == nil {
		// the type of a symlink is public.symlink
		path = real_path
	}
	uti, mime, dynamic, ok := macos_content_type(path)
	if !ok || dynamic || uti == "public.data" || uti == "public.item" {
		return guess
	}
	if mime == "" {
		switch {
		case uti == "public.folder":
			mime = "inode/directory"
		case !is_generic_mime_type(guess):
			mime = guess
		default:
			mime = uti_mime_prefix + uti
		}
	}
	uti_for_mime.Lock()
	if _, found := uti_for_mime.m[mime]; !found {
		uti_for_mime.m[mime] = uti
	}
	uti_for_mime.Unlock()
	return mime
}

// The directories containing applications, in order of decreasing priority
func application_dirs() []string {
	return []string{utils.Expanduser("~/Applications"), "/Applications", "/System/Applications", "/System/Library/CoreServices/Applications"}
}

const finder_bundle = "/System/Library/CoreServices/Finder.app"

// Applications outside the application directories that are shown
var extra_bundles = []string{finder_bundle}

// How deep in the application directories to look for applications
const max_application_dir_depth = 3

type bundle_info struct {
	Identifier     string `plist:"CFBundleIdentifier"`
	Name           string `plist:"CFBundleName"`
	DisplayName    string `plist:"CFBundleDisplayName"`
	Executable     string `plist:"CFBundleExecutable"`
	PackageType    string `plist:"CFBundlePackageType"`
	Category       string `plist:"LSApplicationCategoryType"`
	UIElement      any    `plist:"LSUIElement"`
	BackgroundOnly any    `plist:"LSBackgroundOnly"`
}

// plist_bool interprets values that are sometimes stored as strings or numbers
func plist_bool(v any) bool {
	switch x := v.(type) {
	case bool:
		return x
	case string:
		switch strings.ToLower(x) {
		case "1", "yes", "true":
			return true
		}
	case int64:
		return x != 0
	case uint64:
		return x != 0
	}
	return false
}

// category_name returns a human readable name for an application category
// such as public.app-category.developer-tools
func category_name(category string) string {
	name, found := strings.CutPrefix(category, "public.app-category.")
	if !found || name == "" {
		return ""
	}
	words := strings.Split(name, "-")
	for i, w := range words {
		if w != "" {
			words[i] = strings.ToUpper(w[:1]) + w[1:]
		}
	}
	return strings.Join(words, " ")
}

// read_bundle creates an entry for the application bundle at path, which
// must be the real path, not a symlink, returning nil if it is not an application
func read_bundle(path string) (*DesktopEntry, error) {
	f, err := os.Open(filepath.Join(path, "Contents", "Info.plist"))
	if err != nil {
		return nil, err
	}
	defer f.Close()
	var info bundle_info
	if err = plist.NewDecoder(f).Decode(&info); err != nil {
		return nil, fmt.Errorf("failed to read the Info.plist of %s with error: %w", path, err)
	}
	// Finder has the package type FNDR
	if info.PackageType != "" && info.PackageType != "APPL" && info.PackageType != "FNDR" {
		return nil, nil
	}
	stem := strings.TrimSuffix(filepath.Base(path), ".app")
	e := &DesktopEntry{
		ID: utils.IfElse(info.Identifier != "", info.Identifier, path), Path: path, bundle_path: path, Icon: path,
		Name:    utils.IfElse(info.DisplayName != "", info.DisplayName, utils.IfElse(info.Name != "", info.Name, stem)),
		Comment: category_name(info.Category), entry_type: true,
		no_display: plist_bool(info.UIElement) || plist_bool(info.BackgroundOnly),
	}
	// allow matching on the various names of the application
	for _, x := range []string{info.Name, info.Executable, stem} {
		if x != "" && x != e.Name && !slices.Contains(e.Keywords, x) {
			e.Keywords = append(e.Keywords, x)
		}
	}
	return e, nil
}

// darwin_apps finds and tracks application bundles
type darwin_apps struct {
	db *AppDatabase
	// map of bundle path, both as found and resolved, to application
	by_path map[string]*DesktopEntry
}

// add adds the bundle at path, if it is an application not seen before,
// returning its entry, which is that of the earlier application with the same
// id, if any.
func (d *darwin_apps) add(path string, show bool) *DesktopEntry {
	if e := d.by_path[path]; e != nil {
		return e
	}
	real_path, err := filepath.EvalSymlinks(path)
	if err != nil {
		return nil
	}
	if e := d.by_path[real_path]; e != nil {
		d.by_path[path] = e
		return e
	}
	e, err := read_bundle(real_path)
	if err != nil {
		d.db.Errors = append(d.db.Errors, err)
	}
	if e == nil {
		return nil
	}
	// use the path as found, as that is what the user knows, for example
	// /Applications/Safari.app rather than the cryptex it links to
	e.Path, e.bundle_path, e.Icon = path, path, path
	if existing := d.db.by_id[e.ID]; existing != nil {
		e = existing
	} else {
		d.db.by_id[e.ID] = e
		if !show {
			e.no_display = true
		}
		d.db.apps = append(d.db.apps, e)
	}
	d.by_path[path], d.by_path[real_path] = e, e
	return e
}

func (d *darwin_apps) scan(dir string, depth int) {
	entries, err := os.ReadDir(dir)
	if err != nil {
		if !os.IsNotExist(err) {
			d.db.Errors = append(d.db.Errors, err)
		}
		return
	}
	var subdirs []string
	for _, x := range entries {
		name := x.Name()
		if strings.HasPrefix(name, ".") {
			continue
		}
		path := filepath.Join(dir, name)
		if strings.HasSuffix(name, ".app") {
			// applications can be symlinks, such as /Applications/Safari.app
			if s, err := os.Stat(path); err == nil && s.IsDir() {
				d.add(path, true)
			}
		} else if x.IsDir() && depth < max_application_dir_depth {
			// symlinks to directories are not followed, to avoid loops
			subdirs = append(subdirs, path)
		}
	}
	// applications in sub-directories are often old copies or bundled
	// helpers, so applications with the same id higher up take precedence
	for _, path := range subdirs {
		d.scan(path, depth+1)
	}
}

// use_display_names uses the localized names shown by Finder for the applications
func (d *darwin_apps) use_display_names(apps []*DesktopEntry) {
	names, err := macos_display_names(utils.Map(func(e *DesktopEntry) string { return e.bundle_path }, apps))
	if err != nil {
		d.db.Errors = append(d.db.Errors, err)
		return
	}
	for i, e := range apps {
		if n := strings.TrimSuffix(names[i], ".app"); n != "" && n != e.Name {
			if !slices.Contains(e.Keywords, e.Name) {
				e.Keywords = append(e.Keywords, e.Name)
			}
			e.Name = n
		}
	}
}

func (d *darwin_apps) sort() {
	slices.SortStableFunc(d.db.apps, func(a, b *DesktopEntry) int {
		if c := strings.Compare(strings.ToLower(a.Name), strings.ToLower(b.Name)); c != 0 {
			return c
		}
		return strings.Compare(a.ID, b.ID)
	})
}

// lookup fills in the default and associated applications for the MIME
// type from LaunchServices
func (d *darwin_apps) lookup(db *AppDatabase, mime string) {
	kind, val := query_mime, mime
	if scheme, found := strings.CutPrefix(mime, "x-scheme-handler/"); found {
		kind, val = query_scheme, scheme
	} else if uti, found := strings.CutPrefix(mime, uti_mime_prefix); found {
		kind, val = query_uti, uti
	} else {
		uti_for_mime.Lock()
		uti, found := uti_for_mime.m[mime]
		uti_for_mime.Unlock()
		if found {
			kind, val = query_uti, uti
		}
	}
	default_app, apps, err := macos_apps_for(kind, val)
	if err != nil {
		db.Errors = append(db.Errors, err)
		return
	}
	num_apps := len(db.apps)
	for _, p := range apps {
		if e := d.add(p, false); e != nil && !slices.Contains(db.associations[mime], e.ID) {
			db.associations[mime] = append(db.associations[mime], e.ID)
		}
	}
	if default_app == "" && mime == "inode/directory" {
		// LaunchServices does not consider Finder an application for folders
		default_app = finder_bundle
	}
	if default_app != "" {
		if e := d.add(default_app, false); e != nil {
			db.defaults[mime] = []string{e.ID}
		}
	}
	if added := db.apps[num_apps:]; len(added) > 0 {
		d.use_display_names(added)
		d.sort()
	}
}

// LoadAppDatabase finds the installed applications. The applications for
// types of files are looked up from LaunchServices when needed.
func LoadAppDatabase() *AppDatabase {
	db := &AppDatabase{
		dirs: XDGDirsFromEnvironment(), by_id: map[string]*DesktopEntry{}, defaults: map[string][]string{},
		associations: map[string][]string{}, mime_ancestors: utils.MimeTypeAncestors,
	}
	d := &darwin_apps{db: db, by_path: map[string]*DesktopEntry{}}
	for _, dir := range application_dirs() {
		d.scan(dir, 1)
	}
	for _, p := range extra_bundles {
		d.add(p, true)
	}
	d.use_display_names(db.apps)
	d.sort()
	db.lookup_associations = d.lookup
	return db
}

// Application icons are rendered by macOS, there are no icon themes
func icon_theme_name(*XDGDirs) string { return "" }

func is_app_bundle(path string) bool { return strings.HasSuffix(path, ".app") }

// find_icon_paths returns the paths to the icons, which for applications are
// the paths to their bundles
func find_icon_paths(dirs *XDGDirs, theme string, px int, names []string) map[string]string {
	var others []string
	ans := make(map[string]string, len(names))
	for _, n := range names {
		if is_app_bundle(n) {
			ans[n] = n
		} else {
			others = append(others, n)
		}
	}
	if len(others) > 0 {
		for k, v := range dirs.FindIcons(theme, px, others...) {
			ans[k] = v
		}
	}
	return ans
}

// render_app_bundle_icon writes the icon of the application bundle, as shown
// by Finder, as a PNG file, using the image closest to the specified size
func render_app_bundle_icon(src, output_path string, px int) error {
	if real_path, err := filepath.EvalSymlinks(src); err == nil {
		// the icons of symlinks have an alias arrow badge
		src = real_path
	}
	return macos_write_icon(src, output_path, px)
}
