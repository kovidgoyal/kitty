// License: GPLv3 Copyright: 2026, Kovid Goyal, <kovid at kovidgoyal.net>

package choose_app

import (
	"fmt"
	"path/filepath"
	"slices"
	"strconv"
	"strings"
	"sync"

	"github.com/kovidgoyal/kitty/tools/config"
	"github.com/kovidgoyal/kitty/tools/fzf"
	"github.com/kovidgoyal/kitty/tools/icons"
	"github.com/kovidgoyal/kitty/tools/tui"
	"github.com/kovidgoyal/kitty/tools/tui/graphics"
	"github.com/kovidgoyal/kitty/tools/tui/loop"
	"github.com/kovidgoyal/kitty/tools/tui/readline"
	"github.com/kovidgoyal/kitty/tools/utils"
	"github.com/kovidgoyal/kitty/tools/wcswidth"
)

var _ = fmt.Print

const (
	search_bar_height  = 4
	header_height      = 1
	footer_height      = 2 // the details of the current application and the shortcuts
	accent_style       = "fg=cyan"
	match_style        = "fg=green"
	current_name_style = "fg=intense-white bold"
	section_style      = "fg=blue bold"
	dim_style          = "dim"
)

// Result is the outcome of the chooser
type Result struct {
	Choice   Choice
	Remember bool
}

type color_scheme int

const (
	color_scheme_unknown color_scheme = iota
	color_scheme_dark
	color_scheme_light
)

type Handler struct {
	lp       *loop.Loop
	settings *Settings
	db       *AppDatabase
	store    *ChoiceStore
	dirs     *XDGDirs
	input    *ChooserInput
	targets  []Target

	all_items []*item
	matches   []*item
	rows      []grid_row
	current   int // index into matches
	first_row int // first row of the grid that is displayed
	query     string
	search_rl *readline.Readline
	matcher   *fzf.FuzzyMatcher
	remember  bool

	// typing a command line instead of choosing an application
	in_command_mode bool
	cmd_rl          *readline.Readline
	cmd_terminal    bool
	command_entry   *item
	saved_command   saved_command

	// non-fatal problems to report on exit
	warnings []string

	screen_size      loop.ScreenSize
	shortcut_tracker config.ShortcutTracker
	mouse_state      tui.MouseState

	color_scheme  color_scheme
	base_theme    func() string
	icon_loader   icon_loader
	icon_epoch    int
	icon_display  icon_display
	icon_renderer *IconRenderer
	icon_px       int

	result *Result
}

func NewHandler(lp *loop.Loop, settings *Settings, db *AppDatabase, store *ChoiceStore, input *ChooserInput) *Handler {
	h := &Handler{
		lp: lp, settings: settings, db: db, store: store, dirs: db.dirs, input: input, targets: input.Targets,
		matcher: fzf.NewFuzzyMatcher(fzf.DEFAULT_SCHEME), remember: settings.Remember_choice,
		icon_renderer: NewIconRenderer(IconCacheDir()),
	}
	h.base_theme = sync.OnceValue(func() string {
		if settings.Icon_theme != "" {
			return settings.Icon_theme
		}
		return h.dirs.IconThemeName()
	})
	h.search_rl = readline.New(lp, readline.RlInit{DontMarkPrompts: true})
	h.init_command_rl()
	h.command_entry = new_command_entry_item()
	h.all_items = build_items(db, store, input)
	h.matches = h.all_items
	if input.Preselect != "" {
		ps := ChoiceForDesktopID(input.Preselect)
		if idx := slices.IndexFunc(h.all_items, func(it *item) bool { return it.choice.Equal(ps) }); idx > -1 {
			h.current = idx
		}
	}
	return h
}

// Icons {{{

func (h *Handler) load_icons() {
	px := tile_icon_rows * int(h.screen_size.CellHeight)
	if px < 1 {
		return
	}
	h.icon_px = px
	names := make([]string, 0, len(h.all_items))
	for _, it := range h.all_items {
		names = append(names, it.entry.Icon)
	}
	theme_for := func() string {
		theme := h.base_theme()
		switch h.color_scheme {
		case color_scheme_dark:
			theme = h.dirs.IconThemeForBackground(theme, true)
		case color_scheme_light:
			theme = h.dirs.IconThemeForBackground(theme, false)
		}
		return theme
	}
	h.icon_loader.load(h.dirs, h.icon_renderer, theme_for, px, names, func() { h.lp.WakeupMainThread() })
}

func (h *Handler) on_color_scheme_change(p loop.ColorPreference) error {
	cs := color_scheme_unknown
	switch p {
	case loop.DARK_COLOR_PREFERENCE:
		cs = color_scheme_dark
	case loop.LIGHT_COLOR_PREFERENCE:
		cs = color_scheme_light
	}
	if cs != h.color_scheme {
		h.color_scheme = cs
		h.load_icons()
	}
	return nil
}

func (h *Handler) on_escape_code(etype loop.EscapeCodeType, payload []byte) error {
	if etype == loop.APC {
		if gc := graphics.GraphicsCommandFromAPC(payload); gc != nil && h.icon_display.HandleGraphicsCommand(gc) {
			return h.draw_screen()
		}
	}
	return nil
}

// }}}

// Matching and navigation {{{

func (h *Handler) set_query(q string) error {
	if q == h.query {
		return nil
	}
	h.query = q
	matches, err := filter_items(h.all_items, q, h.matcher)
	if err != nil {
		return err
	}
	if q != "" {
		// offer to use the query as a command, after all matches
		matches = append(matches, h.command_entry)
	}
	h.matches = matches
	h.current, h.first_row = 0, 0
	return nil
}

func (h *Handler) grid_width() int { return max(1, int(h.screen_size.WidthCells)-2) }

func (h *Handler) layout() {
	h.rows = layout_grid(h.matches, h.query == "", num_grid_columns(h.grid_width()))
}

func (h *Handler) grid_height() int {
	return int(h.screen_size.HeightCells) - header_height - search_bar_height - footer_height
}

// visible_tile_rows returns the number of rows of tiles that fit on screen
func (h *Handler) visible_tile_rows() int {
	return max(1, h.grid_height()/tile_height)
}

func (h *Handler) move(how string) {
	if len(h.matches) == 0 {
		h.lp.Beep()
		return
	}
	h.layout()
	switch how {
	case "first":
		h.current = 0
	case "last":
		h.current = len(h.matches) - 1
	case "up":
		h.current = move_vertically(h.rows, h.current, -1)
	case "down":
		h.current = move_vertically(h.rows, h.current, 1)
	case "page_up":
		h.current = move_vertically(h.rows, h.current, -h.visible_tile_rows())
	case "page_down":
		h.current = move_vertically(h.rows, h.current, h.visible_tile_rows())
	default:
		if n, err := strconv.Atoi(how); err == nil {
			h.current = max(0, min(len(h.matches)-1, h.current+n))
		} else {
			h.lp.Beep()
		}
	}
}

// ensure_current_visible scrolls the grid so that the current item is visible
func (h *Handler) ensure_current_visible() {
	r, _ := position_of(h.rows, h.current)
	if r < 0 {
		h.first_row = 0
		return
	}
	if r > 0 && h.rows[r-1].is_header() {
		// keep the section header visible with its first row
		r--
	}
	if r < h.first_row {
		h.first_row = r
		return
	}
	for h.first_row < r {
		height := 0
		cr, _ := position_of(h.rows, h.current)
		for _, row := range h.rows[h.first_row : cr+1] {
			height += row.height()
		}
		if height <= h.grid_height() {
			break
		}
		h.first_row++
	}
}

// }}}

// Accepting {{{

func (h *Handler) accept(c Choice) error {
	h.result = &Result{Choice: c, Remember: h.remember}
	h.lp.Quit(0)
	return nil
}

func (h *Handler) accept_current() error {
	if h.current < 0 || h.current >= len(h.matches) {
		h.lp.Beep()
		return nil
	}
	if it := h.matches[h.current]; it.opens_command_entry {
		return h.enter_command_mode(h.query, false)
	}
	return h.accept(h.matches[h.current].choice)
}

// use_command switches to typing a command, starting with the search text.
// Previously used commands are available from the history of the command line.
func (h *Handler) use_command() error {
	return h.enter_command_mode(h.query, false)
}

func (h *Handler) toggle_remember() {
	h.remember = !h.remember
}

func (h *Handler) dispatch_action(name, args string) error {
	switch name {
	case "quit":
		h.lp.Quit(1)
		return nil
	case "accept":
		return h.accept_current()
	case "use_command":
		return h.use_command()
	case "toggle":
		if args == "remember" {
			h.toggle_remember()
		} else {
			h.lp.Beep()
		}
	case "next":
		h.move(args)
	default:
		h.lp.Beep()
		return nil
	}
	return h.draw_screen()
}

// }}}

// Event handlers {{{

func (h *Handler) OnInitialize() (string, error) {
	sz, err := h.lp.ScreenSize()
	if err != nil {
		return "", err
	}
	h.screen_size = sz
	h.lp.AllowLineWrapping(false)
	h.lp.SetCursorShape(loop.BAR_CURSOR, true)
	h.lp.StartBracketedPaste()
	h.lp.RequestCurrentColorScheme()
	h.icon_display.Initialize(h.lp)
	h.load_icons()
	if err = h.draw_screen(); err != nil {
		return "", err
	}
	h.lp.SendOverlayReady()
	return "", nil
}

func (h *Handler) OnResize(old, new_size loop.ScreenSize) error {
	h.screen_size = new_size
	h.search_rl.ClearCachedScreenSize()
	if tile_icon_rows*int(new_size.CellHeight) != h.icon_px {
		h.load_icons()
	}
	return h.draw_screen()
}

func (h *Handler) OnKeyEvent(ev *loop.KeyEvent) error {
	if h.in_command_mode {
		return h.command_mode_key_event(ev)
	}
	if ac := h.shortcut_tracker.Match(ev, h.settings.KeyboardShortcuts); ac != nil {
		ev.Handled = true
		return h.dispatch_action(ac.Name, ac.Args)
	}
	if err := h.search_rl.OnKeyEvent(ev); err != nil {
		return err
	}
	if err := h.set_query(h.search_rl.AllText()); err != nil {
		return err
	}
	return h.draw_screen()
}

func (h *Handler) OnText(text string, from_key_event, in_bracketed_paste bool) error {
	if h.in_command_mode {
		if err := h.cmd_rl.OnText(text, from_key_event, in_bracketed_paste); err != nil {
			return err
		}
		return h.draw_screen()
	}
	if err := h.search_rl.OnText(text, from_key_event, in_bracketed_paste); err != nil {
		return err
	}
	if err := h.set_query(h.search_rl.AllText()); err != nil {
		return err
	}
	return h.draw_screen()
}

func (h *Handler) OnMouseEvent(ev *loop.MouseEvent) error {
	redraw := h.mouse_state.UpdateState(ev)
	if err := h.mouse_state.DispatchEventToHoveredRegions(ev); err != nil {
		return err
	}
	if redraw && h.result == nil {
		return h.draw_screen()
	}
	return nil
}

func (h *Handler) OnWakeup() error {
	return h.draw_screen()
}

func (h *Handler) OnFinalize() string {
	h.icon_display.Finalize(h.lp)
	return ""
}

// }}}

// Drawing {{{

func (h *Handler) styled(style, text string) string { return h.lp.SprintStyled(style, text) }

func (h *Handler) draw_screen() (err error) {
	lp := h.lp
	lp.StartAtomicUpdate()
	defer lp.EndAtomicUpdate()
	lp.ClearScreenButNotGraphics()
	h.mouse_state.ClearCellRegions()
	if epoch := h.icon_loader.Epoch(); epoch != h.icon_epoch {
		// the icons were reloaded, for example, due to a change of theme
		h.icon_epoch = epoch
		h.icon_display.Forget(lp)
	}
	h.icon_display.StartRender()
	if h.in_command_mode {
		h.icon_display.FinishRender(lp) // removes all icons
		h.draw_command_screen()
		h.mouse_state.UpdateHoveredIds()
		h.mouse_state.ApplyHoverStyles(lp)
		return nil
	}
	h.draw_header()
	h.layout()
	h.ensure_current_visible()
	if err = h.draw_grid(header_height + search_bar_height); err != nil {
		return err
	}
	h.icon_display.FinishRender(lp)
	h.draw_footer()
	h.mouse_state.UpdateHoveredIds()
	h.mouse_state.ApplyHoverStyles(lp)
	// draw the search bar last so the cursor ends up in it
	h.draw_search_bar(header_height)
	return nil
}

func (h *Handler) draw_header() {
	text := "Choose an application"
	icon := "󰀻"
	types := h.styled(dim_style, " · "+strings.Join(h.input.MimeTypes, ", "))
	switch {
	case h.input.DisplayName != "":
		text = "Open " + sanitize(h.input.DisplayName) + types
		icon = icons.IconForPath(h.input.DisplayName)
	case len(h.targets) == 1:
		t := h.targets[0]
		if t.URL != "" {
			text, icon = t.URL, "󰖟"
		} else {
			text, icon = filepath.Base(t.Path), icons.IconForPath(t.Path)
		}
		text = "Open " + sanitize(text) + types
	case len(h.targets) > 1:
		text = fmt.Sprintf("Open %d items", len(h.targets)) + types
	case len(h.input.MimeTypes) > 0:
		text = "Choose an application for" + types
	}
	h.lp.MoveCursorTo(2, 1)
	line := h.styled(accent_style, icon) + " " + text
	h.lp.QueueWriteString(wcswidth.TruncateToVisualLength(line, int(h.screen_size.WidthCells)-2))
}

// sanitize removes control characters from text that comes from file names, URLs or desktop files
func sanitize(text string) string {
	return strings.Map(func(r rune) rune {
		if r < 32 || r == 127 || (r >= 0x80 && r < 0xa0) {
			return '?'
		}
		return r
	}, text)
}

func (h *Handler) draw_frame(x, y, width, height int, style string) {
	lp := h.lp
	pre, post, _ := strings.Cut(h.styled(style, " "), " ")
	lp.QueueWriteString(pre)
	for i := range height {
		lp.MoveCursorTo(x+1, y+i+1)
		switch i {
		case 0:
			lp.QueueWriteString("╭" + strings.Repeat("─", width-2) + "╮")
		case height - 1:
			lp.QueueWriteString("╰" + strings.Repeat("─", width-2) + "╯")
		default:
			lp.QueueWriteString("│")
			lp.MoveCursorHorizontally(width - 2)
			lp.QueueWriteString("│")
		}
	}
	lp.QueueWriteString(post)
}

func (h *Handler) draw_controls(y int) (width int) {
	remember := utils.IfElse(h.remember, "󰄲 ", "󰄱 ") + "remember"
	command := "\uf489 command"
	width = max(wcswidth.Stringwidth(remember), wcswidth.Stringwidth(command)) + 1
	x := int(h.screen_size.WidthCells) - width
	h.lp.MoveCursorTo(x+1, y+2)
	h.lp.QueueWriteString(utils.IfElse(h.remember, h.styled(accent_style, remember), remember))
	h.mouse_state.AddCellRegion("toggle-remember", x, y+1, x+width-1, y+1, func(string) error {
		h.toggle_remember()
		return h.draw_screen()
	})
	h.lp.MoveCursorTo(x+1, y+3)
	h.lp.QueueWriteString(command)
	h.mouse_state.AddCellRegion("type-command", x, y+2, x+width-1, y+2, func(string) error {
		return h.use_command()
	})
	return width + 1
}

func (h *Handler) draw_search_bar(y int) {
	width := int(h.screen_size.WidthCells) - h.draw_controls(y)
	if width < 8 {
		return
	}
	h.draw_frame(0, y, width, search_bar_height, "")
	h.lp.MoveCursorTo(3, y+2)
	// The text is drawn at double size, so only half the width is available,
	// and one cell is reserved for the cursor at the end of the text
	available := (width-4)/2 - 1
	before, after := h.search_rl.TextBeforeCursor(), h.search_rl.TextAfterCursor()
	for wcswidth.Stringwidth(before) > available {
		g := wcswidth.SplitIntoGraphemes(before)
		before = strings.Join(g[1:], "")
	}
	after = wcswidth.TruncateToVisualLength(after, max(0, available-wcswidth.Stringwidth(before)))
	h.lp.DrawSizedText(before+after+" ", loop.SizedText{Scale: 2})
	h.lp.MoveCursorHorizontally(-2 * (wcswidth.Stringwidth(after) + 1))
}

// wrapped_line is a line of a wrapped name as a range of runes
type wrapped_line struct {
	start, end int
	ellipsis   bool
}

// wrap_name wraps text at spaces into at most max_lines lines of at most
// width cells, truncating the last line with an ellipsis if needed
func wrap_name(text string, width, max_lines int) (ans []wrapped_line) {
	runes := []rune(text)
	start := 0
	for start < len(runes) && len(ans) < max_lines {
		for start < len(runes) && runes[start] == ' ' {
			start++
		}
		if start >= len(runes) {
			break
		}
		end, w, last_space := start, 0, -1
		for end < len(runes) {
			cw := wcswidth.Runewidth(runes[end])
			if w+cw > width {
				break
			}
			if runes[end] == ' ' {
				last_space = end
			}
			w += cw
			end++
		}
		if end < len(runes) && len(ans) < max_lines-1 && last_space > start && runes[end] != ' ' {
			end = last_space
		}
		line := wrapped_line{start: start, end: end}
		if end < len(runes) && len(ans) == max_lines-1 {
			// no more lines available, truncate with an ellipsis
			for line.end > line.start && wcswidth.Stringwidth(string(runes[line.start:line.end]))+1 > width {
				line.end--
			}
			line.ellipsis = true
		}
		ans = append(ans, line)
		start = end
	}
	return
}

func (h *Handler) render_name_line(runes []rune, line wrapped_line, positions []int, is_current bool) string {
	var b strings.Builder
	base := utils.IfElse(is_current, current_name_style, "")
	pos := utils.NewSetWithItems(positions...)
	for i := line.start; i < line.end; i++ {
		ch := sanitize(string(runes[i]))
		switch {
		case pos.Has(i):
			b.WriteString(h.styled(match_style+utils.IfElse(is_current, " bold", ""), ch))
		case base != "":
			b.WriteString(h.styled(base, ch))
		default:
			b.WriteString(ch)
		}
	}
	if line.ellipsis {
		b.WriteString("…")
	}
	return b.String()
}

func (h *Handler) draw_tile(it *item, idx, x, y int) error {
	lp := h.lp
	is_current := idx == h.current
	if is_current {
		h.draw_frame(x, y, tile_width, tile_height, accent_style)
	}
	for row := y; row < y+tile_height; row++ {
		h.mouse_state.AddCellRegion("tile-"+strconv.Itoa(idx), x, row, x+tile_width-1, row, func(string) error {
			h.current = idx
			return h.accept_current()
		}).HoverStyle = "none"
	}
	// The icon
	icon_drawn := false
	if h.icon_display.CanDisplay() && it.entry.Icon != "" {
		if ii, found := h.icon_loader.get(it.entry.Icon); found {
			if err := h.icon_display.Place(lp, ii, uint32(idx+1), x+1, y+1, tile_content_width, tile_icon_rows, h.screen_size); err != nil {
				return err
			}
			icon_drawn = true
		}
	}
	if !icon_drawn {
		// A placeholder, the first letter of the name at triple size
		glyph := ""
		if !it.is_custom_command() {
			for _, r := range it.entry.Name {
				if wcswidth.Runewidth(r) == 1 {
					glyph = strings.ToUpper(string(r))
				}
				break
			}
		}
		if glyph == "" {
			glyph = "\uf489" // the Nerd Fonts terminal icon
		}
		lp.MoveCursorTo(x+2+(tile_content_width-tile_icon_rows)/2, y+2)
		pre, post, _ := strings.Cut(h.styled(dim_style, " "), " ")
		lp.QueueWriteString(pre)
		lp.DrawSizedText(glyph, loop.SizedText{Scale: tile_icon_rows})
		lp.QueueWriteString(post)
	}
	// The name
	runes := []rune(it.entry.Name)
	for i, line := range wrap_name(it.entry.Name, tile_content_width, tile_name_lines) {
		text := h.render_name_line(runes, line, it.name_positions, is_current)
		w := wcswidth.Stringwidth(string(runes[line.start:line.end])) + utils.IfElse(line.ellipsis, 1, 0)
		lp.MoveCursorTo(x+2+(tile_content_width-w)/2, y+tile_icon_rows+2+i)
		lp.QueueWriteString(text)
	}
	return nil
}

func (h *Handler) draw_grid(y int) error {
	lp := h.lp
	height := h.grid_height()
	if height < 1 {
		return nil
	}
	if len(h.matches) == 0 {
		lp.MoveCursorTo(3, y+2)
		if h.query == "" {
			lp.QueueWriteString("No applications found")
		} else {
			lp.QueueWriteString("No applications found")
		}
		return nil
	}
	ncols := num_grid_columns(h.grid_width())
	left := 1 + (h.grid_width()-ncols*tile_width)/2
	bottom := y + height
	for r := h.first_row; r < len(h.rows); r++ {
		row := h.rows[r]
		if y+row.height() > bottom {
			break
		}
		if row.is_header() {
			lp.MoveCursorTo(left+2, y+1)
			lp.QueueWriteString(h.styled(section_style, row.header))
		} else {
			for c, idx := range row.items {
				if err := h.draw_tile(h.matches[idx], idx, left+c*tile_width, y); err != nil {
					return err
				}
			}
		}
		y += row.height()
	}
	return nil
}

// shortcut_for returns the keys bound to the specified action and arguments
func (h *Handler) shortcut_for(action string) string {
	name, args, _ := strings.Cut(action, " ")
	var keys []string
	for _, ac := range h.settings.KeyboardShortcuts {
		if ac.Name == name && ac.Args == args && len(ac.Normalized_keys) > 0 {
			keys = append(keys, strings.Join(ac.Normalized_keys, " "))
		}
	}
	slices.SortStableFunc(keys, func(a, b string) int { return len(a) - len(b) })
	return strings.Join(keys, "/")
}

func (h *Handler) draw_footer() {
	lp := h.lp
	width := int(h.screen_size.WidthCells) - 2
	y := int(h.screen_size.HeightCells) - footer_height + 1
	if h.current >= 0 && h.current < len(h.matches) {
		it := h.matches[h.current]
		e := it.entry
		var parts []string
		if it.opens_command_entry {
			parts = append(parts, h.styled("bold", "Type a command to open with"))
		} else if it.is_custom_command() {
			parts = append(parts, h.styled("bold", utils.IfElse(it.choice.Terminal, "Custom command in a terminal", "Custom command")))
		} else {
			parts = append(parts, h.styled("bold", sanitize(e.Name)))
			if desc := utils.IfElse(e.GenericName != "", e.GenericName, e.Comment); desc != "" {
				parts = append(parts, sanitize(desc))
			}
		}
		if e.Exec != "" {
			parts = append(parts, h.styled(dim_style, sanitize(e.Exec)))
		}
		lp.MoveCursorTo(2, y)
		lp.QueueWriteString(wcswidth.TruncateToVisualLength(strings.Join(parts, " · "), width))
	}
	hints := []string{}
	for _, x := range [][2]string{{"accept", "open"}, {"use_command", "type a command"}, {"toggle remember", "remember"}, {"quit", "cancel"}} {
		if sc := h.shortcut_for(x[0]); sc != "" {
			hints = append(hints, h.styled(accent_style, sc)+" "+x[1])
		}
	}
	lp.MoveCursorTo(2, y+1)
	lp.QueueWriteString(wcswidth.TruncateToVisualLength(strings.Join(hints, "  "), width))
}

// }}}
