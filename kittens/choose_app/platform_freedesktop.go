// License: GPLv3 Copyright: 2026, Kovid Goyal, <kovid at kovidgoyal.net>

//go:build !darwin

package choose_app

import (
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
