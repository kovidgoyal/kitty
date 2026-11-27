// License: GPLv3 Copyright: 2026, Kovid Goyal, <kovid at kovidgoyal.net>

package choose_app

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"strings"

	"github.com/kovidgoyal/kitty/tools/utils"
	"github.com/zeebo/xxh3"
)

var _ = fmt.Print

const command_desktop_file_prefix = "kitty-choose-app-"

// Characters that require an argument to be quoted in an Exec line, as per
// the desktop entry spec
const exec_reserved_chars = " \t\n\"'\\><~|&;$*?#()`"

var exec_quote_escaper = strings.NewReplacer(`"`, `\"`, "`", "\\`", `$`, `\$`, `\`, `\\`)

// The escapes for string values, applied after the quoting of Exec arguments
var string_value_escaper = strings.NewReplacer(`\`, `\\`, "\n", `\n`, "\t", `\t`, "\r", `\r`)

// exec_line returns the Exec value for the command line, with the arguments
// quoted and escaped as per the desktop entry spec
func exec_line(argv []string) string {
	quoted := make([]string, len(argv))
	for i, arg := range argv {
		if arg == "" || strings.ContainsAny(arg, exec_reserved_chars) {
			arg = `"` + exec_quote_escaper.Replace(arg) + `"`
		}
		quoted[i] = arg
	}
	return string_value_escaper.Replace(strings.Join(quoted, " "))
}

// WriteCommandDesktopFile creates a hidden desktop file that runs the
// command line of the choice, returning its desktop file id. The same
// command always gives the same desktop file.
func WriteCommandDesktopFile(dirs *XDGDirs, c Choice) (id string, err error) {
	if len(c.Cmdline) == 0 {
		return "", fmt.Errorf("no command to create a desktop file for")
	}
	key, err := json.Marshal(c)
	if err != nil {
		return "", err
	}
	id = fmt.Sprintf("%s%016x.desktop", command_desktop_file_prefix, xxh3.Hash(key))
	argv := c.Cmdline
	if !has_field_code(utils.Map(func(x string) exec_token { return exec_token{text: x} }, argv), "fFuU") {
		// the same as when launching the command directly
		argv = append(argv[:len(argv):len(argv)], "%f")
	}
	name := string_value_escaper.Replace(join_cmdline(c.Cmdline))
	text := strings.Join([]string{
		"[Desktop Entry]",
		"Type=Application",
		"Name=" + name,
		"Comment=Command chosen with kitten choose-app",
		"Exec=" + exec_line(argv),
		"Terminal=" + utils.IfElse(c.Terminal, "true", "false"),
		"NoDisplay=true",
		"",
	}, "\n")
	dir := filepath.Join(dirs.DataHome, "applications")
	if err = os.MkdirAll(dir, 0o755); err != nil {
		return "", fmt.Errorf("failed to create the directory for the desktop file with error: %w", err)
	}
	path := filepath.Join(dir, id)
	if existing, rerr := os.ReadFile(path); rerr == nil && string(existing) == text {
		return id, nil
	}
	if err = utils.AtomicWriteFile(path, strings.NewReader(text), 0o644); err != nil {
		return "", fmt.Errorf("failed to write the desktop file %s with error: %w", path, err)
	}
	return id, nil
}
