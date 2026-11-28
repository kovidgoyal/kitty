// License: GPLv3 Copyright: 2026, Kovid Goyal, <kovid at kovidgoyal.net>

package choose_app

import (
	"fmt"
	"os"
	"path/filepath"
	"slices"
	"strconv"
	"strings"
	"sync"
	"time"

	"github.com/kovidgoyal/kitty/tools/config"
	"github.com/kovidgoyal/kitty/tools/fzf"
	"github.com/kovidgoyal/kitty/tools/icons"
	"github.com/kovidgoyal/kitty/tools/tui"
	"github.com/kovidgoyal/kitty/tools/tui/graphics"
	"github.com/kovidgoyal/kitty/tools/tui/loop"
	"github.com/kovidgoyal/kitty/tools/tui/readline"
	"github.com/kovidgoyal/kitty/tools/tui/scrolling"
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
	// An XDG activation token for launching the chosen application, if the terminal provided one
	ActivationToken string
}

// How long to wait for the terminal to provide an activation token
const activation_token_timeout = time.Second

// activation_token_id returns a unique identifier for activation token
// requests, see docs/misc-protocol.rst, so that a late reply to a request from
// another run of this kitten in the same terminal is not mistaken for a reply
// to this one
func activation_token_id(kind string) string {
	return fmt.Sprintf("choose-app-%s-%d-%s", kind, os.Getpid(), utils.RandomFilename())
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
	// Whether the terminal can provide XDG activation tokens
	activation_tokens_supported bool
	// Whether an activation token is needed for the chosen application
	want_activation_token bool
	// the label for the accept action, describing what happens to the chosen application
	accept_label string
	// Identifiers for the activation token query and request
	activation_token_query_id, activation_token_request_id string

	screen_size loop.ScreenSize
	// The grid as lines of cells, scrolled by the scroller, and its left edge
	grid      grid_scroll
	grid_left int
	scroller  scrolling.Scroller
	indicator scrolling.Indicator
	// Whether to scroll the current item into view after drawing the grid
	want_current_visible bool
	// The first error placing an icon while drawing the grid
	paint_err error
	// Placeholders for applications without icons, rendered as images
	placeholders     map[string]icon_info
	tiles            tile_geometry
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
		matcher: fzf.NewFuzzyMatcher(fzf.DEFAULT_SCHEME), remember: settings.Remember_choice, tiles: settings.tiles,
		icon_renderer: NewIconRenderer(IconCacheDir()), accept_label: "choose",
	}
	h.base_theme = sync.OnceValue(func() string {
		if settings.Icon_theme != "" {
			return settings.Icon_theme
		}
		return icon_theme_name(h.dirs)
	})
	h.scroller = scrolling.Scroller{Id: grid_region_id, Capacity: grid_region_capacity, Paint: h.paint_grid_line}
	h.indicator = scrolling.Indicator{TrackStyle: "\x1b[2m"}
	h.placeholders = map[string]icon_info{}
	h.search_rl = readline.New(lp, readline.RlInit{DontMarkPrompts: true})
	h.init_command_rl()
	h.command_entry = new_command_entry_item()
	h.all_items = build_items(db, store, input)
	h.matches = h.all_items
	if input.Preselect != "" {
		ps := ChoiceForDesktopID(input.Preselect)
		if idx := slices.IndexFunc(h.all_items, func(it *item) bool { return it.choice.Equal(ps) }); idx > -1 {
			h.current = idx
			h.want_current_visible = true
		}
	}
	return h
}

// Icons {{{

func (h *Handler) load_icons() {
	px := h.tiles.icon_rows * int(h.screen_size.CellHeight)
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
	if etype == loop.OSC && loop.IsSmoothScrollQueryResponse(payload) {
		if !h.scroller.Supported() {
			h.scroller.SetSupported()
			return h.draw_screen()
		}
		return nil
	}
	if etype == loop.OSC {
		if resp, ok := loop.ParseActivationTokenResponse(payload); ok {
			switch {
			case resp.IsQueryReply && resp.Id == h.activation_token_query_id:
				h.activation_tokens_supported = true
			case !resp.IsQueryReply && resp.Id == h.activation_token_request_id && h.result != nil:
				h.result.ActivationToken = resp.Token
				h.lp.Quit(0)
			}
			return nil
		}
	}
	if etype == loop.APC {
		if t := h.indicator.Thumb; t != nil && !t.Supported && t.IsSupportResponse(payload) {
			// Indexed color data is supported, used for the thumb and placeholders
			t.Supported = true
			return h.draw_screen()
		}
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
	h.current = 0
	h.scroller.SetPosition(0)
	return nil
}

// grid_width is the width of the grid, which starts in the second column and
// ends with an empty column before the scroll indicator
func (h *Handler) grid_width() int {
	return max(1, scroll_indicator_column(int(h.screen_size.WidthCells))-2)
}

func (h *Handler) layout() {
	ncols := num_grid_columns(h.grid_width(), h.tiles)
	h.rows = layout_grid(h.matches, h.query == "", ncols, h.tiles)
	h.grid = new_grid_scroll(h.rows)
	h.grid_left = 1 + (h.grid_width()-ncols*h.tiles.width())/2
	top, height, x := header_height+search_bar_height, max(0, h.grid_height()), scroll_indicator_column(int(h.screen_size.WidthCells))
	h.scroller.SetNumLines(h.grid.total)
	// The scroll region is the grid, up to the scroll indicator
	h.scroller.SetGeometry(0, top, x, height, int(h.screen_size.CellHeight))
	h.indicator.SetGeometry(x, top, height, int(h.screen_size.CellWidth), int(h.screen_size.CellHeight))
}

func (h *Handler) grid_height() int {
	return int(h.screen_size.HeightCells) - header_height - search_bar_height - footer_height
}

// visible_tile_rows returns the number of rows of tiles that fit on screen
func (h *Handler) visible_tile_rows() int {
	return max(1, h.grid_height()/h.tiles.height())
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
	h.want_current_visible = true
}

// }}}

// Accepting {{{

func (h *Handler) accept(c Choice) error {
	if h.result != nil {
		// already accepted, waiting for an activation token
		return nil
	}
	h.result = &Result{Choice: c, Remember: h.remember}
	if !h.want_activation_token || !h.activation_tokens_supported {
		h.lp.Quit(0)
		return nil
	}
	// Get an activation token so that the chosen application can get focus,
	// the user has just interacted with this window, so the terminal will
	// provide one. Quit without one if it takes too long.
	h.activation_token_request_id = activation_token_id("token")
	if err := h.lp.RequestActivationToken(h.activation_token_request_id); err != nil {
		h.lp.Quit(0)
		return nil
	}
	if _, err := h.lp.AddTimer(activation_token_timeout, false, func(loop.IdType) error {
		h.lp.Quit(0)
		return nil
	}); err != nil {
		h.lp.Quit(0)
	}
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
	if h.want_activation_token {
		h.activation_token_query_id = activation_token_id("query")
		if err := h.lp.QueryActivationTokenSupport(h.activation_token_query_id); err != nil {
			return "", err
		}
	}
	h.lp.QuerySmoothScrolling()
	h.icon_display.Initialize(h.lp)
	h.indicator.Thumb = graphics.NewScrollThumb(h.icon_display.next_id)
	h.icon_display.next_id++
	h.indicator.Thumb.Query(h.lp)
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
	// The terminal removes smooth scroll regions when it is resized
	h.scroller.Invalidate()
	if h.tiles.icon_rows*int(new_size.CellHeight) != h.icon_px {
		h.load_icons()
	}
	return h.draw_screen()
}

func (h *Handler) OnKeyEvent(ev *loop.KeyEvent) error {
	if h.result != nil {
		// a choice has been made, waiting for an activation token
		ev.Handled = true
		return nil
	}
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
	if h.result != nil {
		return nil
	}
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
	if h.result != nil {
		return nil
	}
	// Scrolling and drawing the lines that move into the grid must be done
	// in a single atomic update
	h.lp.StartAtomicUpdate()
	defer h.lp.EndAtomicUpdate()
	h.paint_err = nil
	// Scrolling draws the lines that move into the grid and the scroll
	// indicator, keep the cursor in the search bar
	h.lp.SaveCursorPosition()
	consumed := h.handle_grid_mouse(ev)
	h.lp.RestoreCursorPosition()
	if h.paint_err != nil {
		return h.paint_err
	}
	if consumed {
		h.update_pointer_shape(ev.Cell.X, ev.Cell.Y)
		return nil
	}
	redraw := h.mouse_state.UpdateState(ev)
	if ev.Event_type == loop.MOUSE_CLICK && ev.Buttons&loop.LEFT_MOUSE_BUTTON != 0 {
		if idx := h.tile_at(ev.Cell.X, ev.Cell.Y); idx > -1 {
			h.current = idx
			return h.accept_current()
		}
	}
	if err := h.mouse_state.DispatchEventToHoveredRegions(ev); err != nil {
		return err
	}
	if h.result != nil {
		return nil
	}
	if redraw {
		return h.draw_screen()
	}
	h.update_pointer_shape(ev.Cell.X, ev.Cell.Y)
	return nil
}

func (h *Handler) OnWakeup() error {
	return h.draw_screen()
}

func (h *Handler) OnFinalize() string {
	h.scroller.Remove(h.lp)
	h.icon_display.Finalize(h.lp)
	h.indicator.Free(h.lp)
	return ""
}

// }}}

// Drawing {{{

func (h *Handler) styled(style, text string) string { return h.lp.SprintStyled(style, text) }

// update_pointer_shape sets the shape of the mouse pointer, which is at the
// specified zero based cell, for the grid and the scroll indicator. Elsewhere
// it is set by the mouse state for the cell regions.
func (h *Handler) update_pointer_shape(x, y int) {
	ps := loop.DEFAULT_POINTER
	switch {
	case h.indicator.Dragging:
		ps = loop.GRABBING_POINTER
	case h.indicator.Hovering:
		ps = loop.GRAB_POINTER
	case h.tile_at(x, y) > -1:
		ps = loop.POINTER_POINTER
	default:
		if !h.in_grid(x, y) {
			// Over the cell regions, if any
			return
		}
	}
	if ps == loop.DEFAULT_POINTER {
		h.lp.ClearPointerShapes()
	} else if cur, has := h.lp.CurrentPointerShape(); !has || cur != ps {
		h.lp.PopPointerShape()
		h.lp.PushPointerShape(ps)
	}
}

func (h *Handler) draw_screen() (err error) {
	lp := h.lp
	if !lp.IsAtomicUpdateActive() {
		lp.StartAtomicUpdate()
		defer lp.EndAtomicUpdate()
	}
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
		// The command screen is drawn over the grid
		h.scroller.Remove(lp)
		h.indicator.Dragging, h.indicator.Hovering = false, false
		if h.indicator.Thumb != nil {
			h.indicator.Thumb.Hide(lp)
		}
		h.draw_command_screen()
		h.mouse_state.UpdateHoveredIds()
		h.mouse_state.ApplyHoverStyles(lp)
		return nil
	}
	h.draw_header()
	h.layout()
	if err = h.draw_grid(); err != nil {
		return err
	}
	h.icon_display.FinishRender(lp)
	h.draw_scroll_indicator()
	h.draw_footer()
	h.mouse_state.UpdateHoveredIds()
	h.mouse_state.ApplyHoverStyles(lp)
	h.update_pointer_shape(h.mouse_state.Cell.X, h.mouse_state.Cell.Y)
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
	for i := range height {
		h.draw_frame_line(x, y+i, width, height, i, style)
	}
}

// draw_frame_line draws line i of a frame of the specified height, in the
// zero based row y
func (h *Handler) draw_frame_line(x, y, width, height, i int, style string) {
	lp := h.lp
	pre, post, _ := strings.Cut(h.styled(style, " "), " ")
	lp.QueueWriteString(pre)
	lp.MoveCursorTo(x+1, y+1)
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

// draw_tile_line draws line k of the tile of the specified item, in the zero
// based row y of the screen, which is the specified row of the grid area
func (h *Handler) draw_tile_line(it *item, idx, x, y, k, row int) {
	lp := h.lp
	t := h.tiles
	if idx == h.current {
		h.draw_frame_line(x, y, t.width(), t.height(), k, accent_style)
	}
	if ik := k - 1; ik >= 0 && ik < t.icon_rows {
		// The icon is placed from its first line, the terminal clips it to
		// the grid and reveals the rest as it is scrolled. When its first
		// line is above the grid, the part of it below is placed from the
		// first row. Placing it again replaces it, as the same placement id
		// is used.
		if ik == 0 || row == 0 {
			h.draw_icon(it, idx, x, y-ik, ik)
		}
		return
	}
	if nk := k - 1 - t.icon_rows; nk >= 0 && nk < t.name_lines {
		runes := []rune(it.entry.Name)
		lines := wrap_name(it.entry.Name, t.content_width, t.name_lines)
		if nk < len(lines) {
			line := lines[nk]
			text := h.render_name_line(runes, line, it.name_positions, idx == h.current)
			w := wcswidth.Stringwidth(string(runes[line.start:line.end])) + utils.IfElse(line.ellipsis, 1, 0)
			lp.MoveCursorTo(x+2+(t.content_width-w)/2, y+1)
			lp.QueueWriteString(text)
		}
	}
}

// draw_icon draws the icon of the item, in the box of the icon, whose top
// is in the zero based row box_y, which can be above the grid, the first
// skip_rows rows of the box not being drawn
func (h *Handler) draw_icon(it *item, idx, x, box_y, skip_rows int) {
	lp := h.lp
	t := h.tiles
	if h.icon_display.CanDisplay() {
		ii, found := icon_info{}, false
		if it.entry.Icon != "" {
			ii, found = h.icon_loader.get(it.entry.Icon)
		}
		if !found {
			ii, found = h.placeholder_image(it)
		}
		if found {
			if err := h.icon_display.Place(lp, ii, uint32(idx+1), x+1, box_y, t.content_width, t.icon_rows, skip_rows, h.screen_size); err != nil && h.paint_err == nil {
				h.paint_err = err
			}
			return
		}
	}
	// A placeholder, the first letter of the name, drawn with the text sizing
	// protocol, only when it is entirely in the grid, as it cannot be
	// partially displayed
	top := h.scroller.Top()
	if skip_rows > 0 || box_y < top || box_y+t.icon_rows > top+h.scroller.Height() {
		return
	}
	glyph := placeholder_text(it)
	if glyph == command_placeholder {
		glyph = "\uf489" // the Nerd Fonts terminal icon
	}
	lp.MoveCursorTo(x+2+(t.content_width-t.icon_rows)/2, box_y+1)
	pre, post, _ := strings.Cut(h.styled(dim_style, " "), " ")
	lp.QueueWriteString(pre)
	lp.DrawSizedText(glyph, loop.SizedText{Scale: t.icon_rows})
	lp.QueueWriteString(post)
}

// placeholder_image returns the placeholder for an application without an
// icon as an image, if the terminal supports images with indexed color data
func (h *Handler) placeholder_image(it *item) (icon_info, bool) {
	if h.indicator.Thumb == nil || !h.indicator.Thumb.Supported {
		return icon_info{}, false
	}
	text := placeholder_text(it)
	w, ht := h.tiles.content_width*int(h.screen_size.CellWidth), h.tiles.icon_rows*int(h.screen_size.CellHeight)
	if w < 1 || ht < 1 {
		return icon_info{}, false
	}
	key := fmt.Sprintf("placeholder:%s:%dx%d", text, w, ht)
	if ii, found := h.placeholders[key]; found {
		return ii, ii.indexed_data != nil
	}
	data, err := render_placeholder(text, w, ht, 0.8)
	if err != nil {
		h.warnings = append(h.warnings, err.Error())
	}
	// Failures are cached as well, so that they are reported only once
	ii := icon_info{path: key, width: w, height: ht, indexed_data: data}
	h.placeholders[key] = ii
	return ii, data != nil
}

// paint_grid_line draws the specified line of the grid in the specified row
// of the grid area, called by the scroller for the lines that move into it
func (h *Handler) paint_grid_line(row, line int) {
	lp := h.lp
	y := h.scroller.Top() + row
	lp.MoveCursorTo(1, y+1)
	// Erase the row, except for the scroll indicator, outside the scroll region
	lp.QueueWriteString(fmt.Sprintf("\x1b[m\x1b[%dX", h.scroller.Width()))
	r, k := h.grid.row_at(line)
	if r < 0 || r >= len(h.rows) {
		return
	}
	gr := h.rows[r]
	if gr.is_header() {
		lp.MoveCursorTo(h.grid_left+3, y+1)
		lp.QueueWriteString(h.styled(section_style, gr.header))
		return
	}
	for c, idx := range gr.items {
		h.draw_tile_line(h.matches[idx], idx, h.grid_left+c*h.tiles.width(), y, k, row)
	}
}

func (h *Handler) draw_grid() error {
	if h.grid_height() < 1 {
		return nil
	}
	h.paint_err = nil
	h.scroller.Draw(h.lp)
	if h.want_current_visible {
		h.want_current_visible = false
		h.ensure_current_visible()
	}
	if len(h.matches) == 0 {
		h.lp.MoveCursorTo(3, h.scroller.Top()+2)
		h.lp.QueueWriteString("No applications found")
	}
	return h.paint_err
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
		if detail := utils.IfElse(e.bundle_path != "", e.bundle_path, e.Exec); detail != "" {
			parts = append(parts, h.styled(dim_style, sanitize(detail)))
		}
		lp.MoveCursorTo(2, y)
		lp.QueueWriteString(wcswidth.TruncateToVisualLength(strings.Join(parts, " · "), width))
	}
	hints := []string{}
	for _, x := range [][2]string{{"accept", h.accept_label}, {"use_command", "type a command"}, {"toggle remember", "remember"}, {"quit", "cancel"}} {
		if sc := h.shortcut_for(x[0]); sc != "" {
			hints = append(hints, h.styled(accent_style, sc)+" "+x[1])
		}
	}
	lp.MoveCursorTo(2, y+1)
	lp.QueueWriteString(wcswidth.TruncateToVisualLength(strings.Join(hints, "  "), width))
}

// }}}
