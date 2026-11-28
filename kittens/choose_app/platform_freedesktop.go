// License: GPLv3 Copyright: 2026, Kovid Goyal, <kovid at kovidgoyal.net>

//go:build !darwin

package choose_app

import (
	"errors"
	"fmt"

	"github.com/kovidgoyal/kitty/tools/utils"
)

var _ = fmt.Print

// Applications are identified by their desktop file ids
var app_id_suffix = ".desktop"

// LoadAppDatabase scans the system for installed applications and MIME associations
func LoadAppDatabase() *AppDatabase {
	return new_app_database(XDGDirsFromEnvironment(), utils.MimeTypeAncestors)
}

func platform_mime_type_for_path(path string) string { return mime_type_for_path(path) }

func set_platform_defaults(*Config) {}

func icon_theme_name(dirs *XDGDirs) string { return dirs.IconThemeName() }

func find_icon_paths(dirs *XDGDirs, theme string, px int, names []string) map[string]string {
	return dirs.FindIcons(theme, px, names...)
}

func is_app_bundle(string) bool { return false }

func render_app_bundle_icon(src, output_path string, px int) error {
	return errors.New("rendering the icons of application bundles is only supported on macOS")
}
