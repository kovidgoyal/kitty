// License: GPLv3 Copyright: 2026, Kovid Goyal, <kovid at kovidgoyal.net>

package choose_app

import (
	"strings"

	"github.com/kovidgoyal/kitty/tools/wcswidth"
)

// Applications without an icon are shown with a placeholder: the first
// letter of their name, or a terminal icon for custom commands, drawn scaled
// with the text sizing protocol, see draw_placeholder_line().

// The text used for custom commands and names whose first letter is not a
// single cell wide
const command_placeholder = ">_"

// placeholder_text returns the text to display for an item without an icon
func placeholder_text(it *item) string {
	if it.is_custom_command() {
		return command_placeholder
	}
	for _, r := range it.entry.Name {
		if wcswidth.Runewidth(r) == 1 {
			return strings.ToUpper(string(r))
		}
		break
	}
	return command_placeholder
}
