// License: GPLv3 Copyright: 2023, Kovid Goyal, <kovid at kovidgoyal.net>

package diff

import (
	"fmt"
	"regexp"
	"slices"
	"sort"
	"strconv"
	"strings"

	"github.com/kovidgoyal/kitty/tools/config"
	"github.com/kovidgoyal/kitty/tools/tui"
	"github.com/kovidgoyal/kitty/tools/tui/graphics"
	"github.com/kovidgoyal/kitty/tools/tui/loop"
	"github.com/kovidgoyal/kitty/tools/tui/readline"
	"github.com/kovidgoyal/kitty/tools/tui/scrolling"
	"github.com/kovidgoyal/kitty/tools/utils"
	"github.com/kovidgoyal/kitty/tools/wcswidth"
)

var _ = fmt.Print

type ResultType int

const (
	COLLECTION ResultType = iota
	DIFF
	HIGHLIGHT
	IMAGE_LOAD
	IMAGE_RESIZE
)

type ScrollPos struct {
	logical_line, screen_line int
}

func (self ScrollPos) Less(other ScrollPos) bool {
	return self.logical_line < other.logical_line || (self.logical_line == other.logical_line && self.screen_line < other.screen_line)
}

func (self ScrollPos) Add(other ScrollPos) ScrollPos {
	return ScrollPos{self.logical_line + other.logical_line, self.screen_line + other.screen_line}
}

type AsyncResult struct {
	err        error
	rtype      ResultType
	collection *Collection
	diff_map   map[string]*Patch
	page_size  graphics.Size
}

var image_collection *graphics.ImageCollection

type screen_size struct{ rows, columns, num_lines, cell_width, cell_height int }

// The id of the smooth scroll region in which the diff is displayed
const diff_region_id = 1

// The number of screen lines the terminal keeps on each side of the smooth
// scroll region, so that they are restored when changing the direction of scrolling
const diff_region_capacity = 4

// The number of rows used by the sticky header: the title of the file and the separator below it
const sticky_header_rows = 2

type Handler struct {
	async_results                                 chan AsyncResult
	mouse_selection                               tui.MouseSelection
	image_count                                   int
	shortcut_tracker                              config.ShortcutTracker
	left, right                                   string
	collection                                    *Collection
	diff_map                                      map[string]*Patch
	logical_lines                                 *LogicalLines
	terminal_capabilities_received                bool
	lp                                            *loop.Loop
	current_context_count, original_context_count int
	added_count, removed_count                    int
	screen_size                                   screen_size
	// Scrolls the screen lines of the diff, see paint_row(). Its lines are
	// the screen lines of the diff after the ones displayed in the sticky
	// header, indexed from zero.
	scroller scrolling.Scroller
	// line_starts[i] is the index of the first screen line of logical line i
	line_starts      []int
	num_screen_lines int
	// The number of rows at the top of the screen used for the sticky
	// header. The screen lines displayed in it when at the start of the
	// diff, the title of the first file and the separator below it, are not
	// displayed in the scroll region.
	sticky_rows                                         int
	restore_position                                    *ScrollPos
	inputting_command                                   bool
	statusline_message                                  string
	rl                                                  *readline.Readline
	current_search                                      *Search
	current_search_is_regex, current_search_is_backward bool
	largest_line_number                                 int
	images_resized_to                                   graphics.Size
}

func (self *Handler) calculate_statistics() {
	self.added_count, self.removed_count = self.collection.added_count, self.collection.removed_count
	self.largest_line_number = 0
	for _, patch := range self.diff_map {
		self.added_count += patch.added_count
		self.removed_count += patch.removed_count
		self.largest_line_number = utils.Max(patch.largest_line_number, self.largest_line_number)
	}
}

func (self *Handler) update_screen_size(sz loop.ScreenSize) {
	self.screen_size.rows = int(sz.HeightCells)
	self.screen_size.columns = int(sz.WidthCells)
	self.screen_size.num_lines = self.screen_size.rows - 1
	self.screen_size.cell_height = int(sz.CellHeight)
	self.screen_size.cell_width = int(sz.CellWidth)
}

func (self *Handler) on_escape_code(etype loop.EscapeCodeType, payload []byte) error {
	switch etype {
	case loop.OSC:
		if loop.IsSmoothScrollQueryResponse(payload) && !self.scroller.Supported() {
			self.scroller.SetSupported()
			self.draw_screen()
		}
	case loop.APC:
		gc := graphics.GraphicsCommandFromAPC(payload)
		if gc != nil {
			if !image_collection.HandleGraphicsCommand(gc) {
				self.draw_screen()
			}
		}
	}
	return nil
}

func (self *Handler) finalize() {
	self.scroller.Remove(self.lp)
	image_collection.Finalize(self.lp)
}

func set_terminal_colors(lp *loop.Loop) {
	create_formatters()
	lp.SetDefaultColor(loop.FOREGROUND, resolved_colors.Foreground)
	lp.SetDefaultColor(loop.CURSOR, resolved_colors.Foreground)
	lp.SetDefaultColor(loop.BACKGROUND, resolved_colors.Background)
	lp.SetDefaultColor(loop.SELECTION_BG, resolved_colors.Select_bg)
	if resolved_colors.Select_fg.IsSet {
		lp.SetDefaultColor(loop.SELECTION_FG, resolved_colors.Select_fg.Color)
	}
}

func (self *Handler) on_capabilities_received(tc loop.TerminalCapabilities) {
	var use_dark_colors bool
	prev := use_light_colors
	switch conf.Color_scheme {
	case Color_scheme_auto:
		use_dark_colors = tc.ColorPreference != loop.LIGHT_COLOR_PREFERENCE
	case Color_scheme_light:
		use_dark_colors = false
	case Color_scheme_dark:
		use_dark_colors = true
	}
	use_light_colors = !use_dark_colors
	if use_light_colors != prev && (light_highlight_started || dark_highlight_started) {
		self.highlight_all()
	}
	set_terminal_colors(self.lp)
	self.terminal_capabilities_received = true
	self.draw_screen()
}

func (self *Handler) on_color_scheme_change(cp loop.ColorPreference) error {
	if conf.Color_scheme != Color_scheme_auto {
		return nil
	}
	light := cp == loop.LIGHT_COLOR_PREFERENCE
	if use_light_colors != light {
		use_light_colors = light
		set_terminal_colors(self.lp)
		self.highlight_all()
		self.draw_screen()
	}
	return nil
}

func (self *Handler) initialize() {
	self.rl = readline.New(self.lp, readline.RlInit{DontMarkPrompts: true, Prompt: "/"})
	self.scroller = scrolling.Scroller{Id: diff_region_id, Capacity: diff_region_capacity, Paint: self.paint_row}
	self.lp.OnEscapeCode = self.on_escape_code
	self.lp.OnColorSchemeChange = self.on_color_scheme_change
	image_collection = graphics.NewImageCollection()
	self.current_context_count = opts.Context
	if self.current_context_count < 0 {
		self.current_context_count = int(conf.Num_context_lines)
	}
	sz, _ := self.lp.ScreenSize()
	self.update_screen_size(sz)
	self.original_context_count = self.current_context_count
	self.async_results = make(chan AsyncResult, 32)
	go func() {
		self.lp.RecoverFromPanicInGoRoutine()
		r := AsyncResult{}
		r.collection, r.err = create_collection(self.left, self.right)
		self.async_results <- r
		self.lp.WakeupMainThread()
	}()
	self.draw_screen()
}

func (self *Handler) generate_diff() {
	self.diff_map = nil
	jobs := make([]diff_job, 0, 32)
	_ = self.collection.Apply(func(path, typ, changed_path string) error {
		if typ == "diff" {
			if is_path_text(path) && is_path_text(changed_path) {
				jobs = append(jobs, diff_job{path, changed_path})
			}
		}
		return nil
	})
	go func() {
		self.lp.RecoverFromPanicInGoRoutine()
		r := AsyncResult{rtype: DIFF}
		r.diff_map, r.err = diff(jobs, self.current_context_count)
		self.async_results <- r
		self.lp.WakeupMainThread()
	}()
}

func (self *Handler) on_wakeup() error {
	var r AsyncResult
	for {
		select {
		case r = <-self.async_results:
			if r.err != nil {
				return r.err
			}
			r.err = self.handle_async_result(r)
			if r.err != nil {
				return r.err
			}
		default:
			return nil
		}
	}
}

var dark_highlight_started bool
var light_highlight_started bool

func (self *Handler) highlight_all() {
	if (use_light_colors && light_highlight_started) || (!use_light_colors && dark_highlight_started) {
		return
	}
	if use_light_colors {
		light_highlight_started = true
	} else {
		dark_highlight_started = true
	}
	text_files := utils.Filter(self.collection.paths_to_highlight.AsSlice(), is_path_text)
	go func() {
		self.lp.RecoverFromPanicInGoRoutine()
		r := AsyncResult{rtype: HIGHLIGHT}
		highlight_all(text_files, use_light_colors)
		self.async_results <- r
		self.lp.WakeupMainThread()
	}()
}

func (self *Handler) load_all_images() {
	_ = self.collection.Apply(func(path, item_type, changed_path string) error {
		if path != "" && is_image(path) {
			image_collection.AddPaths(path)
			self.image_count++
		}
		if changed_path != "" && is_image(changed_path) {
			image_collection.AddPaths(changed_path)
			self.image_count++
		}
		return nil
	})
	if self.image_count > 0 {
		image_collection.Initialize(self.lp)
		go func() {
			self.lp.RecoverFromPanicInGoRoutine()
			r := AsyncResult{rtype: IMAGE_LOAD}
			image_collection.LoadAll()
			self.async_results <- r
			self.lp.WakeupMainThread()
		}()
	}
}

func (self *Handler) resize_all_images_if_needed() {
	if self.logical_lines == nil {
		return
	}
	margin_size := self.logical_lines.margin_size
	columns := self.logical_lines.columns
	available_cols := columns/2 - margin_size
	sz := graphics.Size{
		Width:  available_cols * self.screen_size.cell_width,
		Height: self.screen_size.num_lines * 2 * self.screen_size.cell_height,
	}
	if sz != self.images_resized_to && self.image_count > 0 {
		go func() {
			self.lp.RecoverFromPanicInGoRoutine()
			image_collection.ResizeForPageSize(sz.Width, sz.Height)
			r := AsyncResult{rtype: IMAGE_RESIZE, page_size: sz}
			self.async_results <- r
			self.lp.WakeupMainThread()
		}()
	}
}

func (self *Handler) rerender_diff() error {
	if self.diff_map != nil && self.collection != nil && self.terminal_capabilities_received {
		err := self.render_diff()
		if err != nil {
			return err
		}
		self.draw_screen()
	}
	return nil
}

func (self *Handler) handle_async_result(r AsyncResult) error {
	switch r.rtype {
	case COLLECTION:
		self.collection = r.collection
		self.generate_diff()
		self.highlight_all()
		self.load_all_images()
	case DIFF:
		if !self.terminal_capabilities_received {
			go func() {
				self.async_results <- r
				self.lp.WakeupMainThread()
			}()
			return nil
		}
		self.diff_map = r.diff_map
		self.calculate_statistics()
		self.clear_mouse_selection()
		err := self.render_diff()
		if err != nil {
			return err
		}
		self.set_scroll_pos(ScrollPos{})
		if self.restore_position != nil {
			self.set_scroll_pos(*self.restore_position)
			self.restore_position = nil
		}
		self.draw_screen()
	case IMAGE_RESIZE:
		self.images_resized_to = r.page_size
		return self.rerender_diff()
	case IMAGE_LOAD, HIGHLIGHT:
		return self.rerender_diff()
	}
	return nil
}

func (self *Handler) on_resize(old_size, new_size loop.ScreenSize) error {
	self.clear_mouse_selection()
	self.update_screen_size(new_size)
	// The terminal removes smooth scroll regions when it is resized
	self.scroller.Invalidate()
	if self.diff_map != nil && self.collection != nil && self.terminal_capabilities_received {
		err := self.render_diff()
		if err != nil {
			return err
		}
	}
	self.draw_screen()
	return nil
}

func (self *Handler) render_diff() (err error) {
	if self.screen_size.columns < 8 {
		return fmt.Errorf("Screen too narrow, need at least 8 columns")
	}
	if self.screen_size.rows < 2 {
		return fmt.Errorf("Screen too short, need at least 2 rows")
	}
	var prev_pos ScrollPos
	had_lines := self.logical_lines != nil
	if had_lines {
		prev_pos = self.scroll_pos()
	}
	prev_line_starts := self.line_starts
	self.logical_lines, err = render(self.collection, self.diff_map, self.screen_size, self.largest_line_number, self.images_resized_to)
	if err != nil {
		return err
	}
	self.line_starts = make([]int, self.logical_lines.Len())
	self.num_screen_lines = 0
	for i := range self.line_starts {
		self.line_starts[i] = self.num_screen_lines
		self.num_screen_lines += len(self.logical_lines.At(i).screen_lines)
	}
	self.update_scroller_geometry()
	if had_lines && !slices.Equal(prev_line_starts, self.line_starts) {
		// Keep the same line at the top of the screen
		self.set_scroll_pos(prev_pos)
	}
	if self.current_search != nil {
		self.current_search.search(self.logical_lines)
	}
	return nil
}

func (self *Handler) draw_image(key string, _, starting_row int) {
	image_collection.PlaceImageSubRect(self.lp, key, self.images_resized_to, 0, self.screen_size.cell_height*starting_row, -1, -1)
}

func (self *Handler) draw_image_pair(ll *LogicalLine, starting_row int) {
	if ll.left_image.key == "" && ll.right_image.key == "" {
		return
	}
	defer self.lp.QueueWriteString("\r")
	if ll.left_image.key != "" {
		self.lp.QueueWriteString("\r")
		self.lp.MoveCursorHorizontally(self.logical_lines.margin_size)
		self.draw_image(ll.left_image.key, ll.left_image.count, starting_row)
	}
	if ll.right_image.key != "" {
		self.lp.QueueWriteString("\r")
		self.lp.MoveCursorHorizontally(self.logical_lines.margin_size + self.logical_lines.columns/2)
		self.draw_image(ll.right_image.key, ll.right_image.count, starting_row)
	}
}

// update_scroller_geometry sets the geometry of the scroll region, below the
// sticky header, if any, and above the status line
func (self *Handler) update_scroller_geometry() {
	self.sticky_rows = 0
	ll := self.logical_lines
	if conf != nil && conf.Sticky_header && ll != nil && len(ll.title_line_indices) > 0 && ll.title_line_indices[0] == 0 && self.screen_size.num_lines > 2*sticky_header_rows {
		self.sticky_rows = sticky_header_rows
	}
	self.scroller.SetNumLines(max(0, self.num_screen_lines-self.sticky_rows))
	self.scroller.SetGeometry(0, self.sticky_rows, self.screen_size.columns, self.screen_size.num_lines-self.sticky_rows, self.screen_size.cell_height)
}

// pos_for_line returns the position of the screen line with the specified index
func (self *Handler) pos_for_line(idx int) ScrollPos {
	if len(self.line_starts) == 0 {
		return ScrollPos{}
	}
	idx = max(0, min(idx, self.num_screen_lines-1))
	i := sort.Search(len(self.line_starts), func(i int) bool { return self.line_starts[i] > idx }) - 1
	return ScrollPos{i, idx - self.line_starts[i]}
}

// line_for_pos returns the index of the screen line at the specified position
func (self *Handler) line_for_pos(pos ScrollPos) int {
	if len(self.line_starts) == 0 {
		return 0
	}
	l := max(0, min(pos.logical_line, len(self.line_starts)-1))
	return self.line_starts[l] + max(0, pos.screen_line)
}

// scroll_pos returns the position of the screen line in the first row of the scroll region
func (self *Handler) scroll_pos() ScrollPos {
	return self.pos_for_line(self.sticky_rows + self.scroller.FirstLine())
}

// max_scroll_pos returns the position of the screen line in the first row
// of the scroll region when scrolled to the end
func (self *Handler) max_scroll_pos() ScrollPos {
	return self.pos_for_line(self.sticky_rows + self.scroller.MaxFirstLine())
}

// set_scroll_pos sets the position without scrolling, for use before drawing the screen
func (self *Handler) set_scroll_pos(pos ScrollPos) {
	self.scroller.SetPosition((self.line_for_pos(pos) - self.sticky_rows) * self.screen_size.cell_height)
}

// scroll_to_pos scrolls the screen line at the specified position to the
// first row of the scroll region, or as close to it as possible. Must be
// called inside an atomic update.
func (self *Handler) scroll_to_pos(pos ScrollPos) bool {
	return self.scroller.ScrollToLine(self.lp, self.line_for_pos(pos)-self.sticky_rows)
}

// scroll_lines scrolls by the specified number of whole lines, keeping any
// fractional offset of the scroll region. Must be called inside an atomic update.
func (self *Handler) scroll_lines(amt int) bool {
	return self.scroller.ScrollPixels(self.lp, amt*self.screen_size.cell_height)
}

// do_scroll calls scroll inside an atomic update and if it scrolled, updates
// the sticky header and status line, returning whether it scrolled
func (self *Handler) do_scroll(scroll func() bool) bool {
	if self.logical_lines == nil {
		return false
	}
	if !self.lp.IsAtomicUpdateActive() {
		self.lp.StartAtomicUpdate()
		defer self.lp.EndAtomicUpdate()
	}
	if scroll() {
		self.draw_sticky_header()
		self.draw_status_line()
		return true
	}
	return false
}

func (self *Handler) draw_screen() {
	if !self.lp.IsAtomicUpdateActive() {
		self.lp.StartAtomicUpdate()
		defer self.lp.EndAtomicUpdate()
	}
	if self.image_count > 0 {
		self.resize_all_images_if_needed()
		image_collection.DeleteAllVisiblePlacements(self.lp)
	}
	lp.MoveCursorTo(1, 1)
	lp.ClearToEndOfScreen()
	if self.logical_lines == nil || self.diff_map == nil || self.collection == nil || !self.terminal_capabilities_received {
		// The region would draw this message shifted
		self.scroller.Remove(lp)
		lp.Println(`Calculating diff, please wait...`)
		return
	}
	self.scroller.Draw(lp)
	self.draw_sticky_header()
	self.draw_status_line()
}

// paint_row draws the screen line with the specified index, relative to the
// first line of the scroll region, in the specified row of the scroll
// region, called by the scroller for the rows that move into the scroll region
func (self *Handler) paint_row(row, line int) {
	lp := self.lp
	y := self.sticky_rows + row
	lp.MoveCursorTo(1, y+1)
	lp.QueueWriteString("\x1b[m")
	lp.ClearToEndOfLine()
	idx := self.sticky_rows + line
	if idx < 0 || idx >= self.num_screen_lines {
		return
	}
	pos := self.pos_for_line(idx)
	ll := self.logical_lines.At(pos.logical_line)
	ll.render_screen_line(pos.screen_line, lp, self.logical_lines.margin_size, self.logical_lines.columns)
	lp.QueueWriteString("\x1b[m\r")
	// Images are placed from their first line, the terminal clips them to
	// the scroll region and reveals the rest as it is scrolled. When the
	// first line is above the scroll region, the part of the image below
	// it is placed from the first row. Placing an image again replaces it,
	// as the same placement id is used.
	if ll.line_type == IMAGE_LINE && pos.screen_line >= ll.image_lines_offset && (row == 0 || pos.screen_line == ll.image_lines_offset) {
		self.draw_image_pair(ll, pos.screen_line-ll.image_lines_offset)
	}
	if self.current_search != nil {
		if mkp := self.current_search.markup_line(pos, y); mkp != "" {
			lp.QueueWriteString(mkp)
		}
	}
	if mkp := self.add_mouse_selection_to_line(pos, y); mkp != "" {
		lp.QueueWriteString(mkp)
	}
}

// draw_sticky_header draws the title of the file and the separator below
// it, for the file the screen line above the scroll region would be in, if
// the sticky header was not there, so that the header of the next file
// scrolls into the scroll region below it and replaces it, once it scrolls
// past its top
func (self *Handler) draw_sticky_header() {
	if self.sticky_rows == 0 {
		return
	}
	lp := self.lp
	for y := range self.sticky_rows {
		lp.MoveCursorTo(1, y+1)
		lp.QueueWriteString("\x1b[m")
		lp.ClearToEndOfLine()
	}
	pos := self.pos_for_line(self.scroller.FirstLine())
	title_idx := self.logical_lines.TitleLineIdxFor(pos.logical_line)
	if title_idx < 0 {
		return
	}
	for y := range sticky_header_rows {
		lp.MoveCursorTo(1, y+1)
		self.logical_lines.At(title_idx+y).render_screen_line(0, lp, self.logical_lines.margin_size, self.logical_lines.columns)
		lp.QueueWriteString("\x1b[m")
	}
}

func (self *Handler) draw_status_line() {
	if self.logical_lines == nil || self.diff_map == nil {
		return
	}
	self.lp.MoveCursorTo(1, self.screen_size.rows)
	self.lp.ClearToEndOfLine()
	self.lp.SetCursorVisible(self.inputting_command)
	if self.inputting_command {
		self.rl.RedrawNonAtomic()
	} else if self.statusline_message != "" {
		self.lp.QueueWriteString(message_format(wcswidth.TruncateToVisualLength(sanitize(self.statusline_message), self.screen_size.columns)))
	} else {
		num := self.scroller.FirstLine()
		den := self.scroller.MaxFirstLine()
		var frac int
		if den > 0 {
			frac = int((float64(num) * 100.0) / float64(den))
		}
		sp := statusline_format(fmt.Sprintf("%d%%", frac))
		var counts string
		if self.current_search == nil {
			counts = added_count_format(strconv.Itoa(self.added_count)) + statusline_format(`,`) + removed_count_format(strconv.Itoa(self.removed_count))
		} else {
			counts = statusline_format(fmt.Sprintf("%d matches", self.current_search.Len()))
		}
		suffix := counts + "  " + sp
		prefix := statusline_format(":")
		filler := strings.Repeat(" ", utils.Max(0, self.screen_size.columns-wcswidth.Stringwidth(prefix)-wcswidth.Stringwidth(suffix)))
		self.lp.QueueWriteString(prefix + filler + suffix)
	}
}

func (self *Handler) on_text(text string, a, b bool) error {
	if self.inputting_command {
		defer self.draw_status_line()
		return self.rl.OnText(text, a, b)
	}
	if self.statusline_message != "" {
		self.statusline_message = ""
		self.draw_status_line()
		return nil
	}
	return nil
}

func (self *Handler) do_search(query string) {
	self.current_search = nil
	if len(query) < 2 {
		return
	}
	if !self.current_search_is_regex {
		query = regexp.QuoteMeta(query)
	}
	pat, err := regexp.Compile(`(?i)` + query)
	if err != nil {
		self.statusline_message = fmt.Sprintf("Bad regex: %s", err)
		self.lp.Beep()
		return
	}
	self.current_search = do_search(pat, self.logical_lines)
	if self.current_search.Len() == 0 {
		self.current_search = nil
		self.statusline_message = fmt.Sprintf("No matches for: %#v", query)
		self.lp.Beep()
	} else {
		if !self.do_scroll_to(func() bool { return self.scroll_to_next_match(false, true) }) {
			self.lp.Beep()
		}
	}
}

func (self *Handler) on_key_event(ev *loop.KeyEvent) error {
	if self.inputting_command {
		defer self.draw_status_line()
		if ev.MatchesPressOrRepeat("esc") {
			self.inputting_command = false
			ev.Handled = true
			return nil
		}
		if ev.MatchesPressOrRepeat("enter") {
			self.inputting_command = false
			ev.Handled = true
			self.do_search(self.rl.AllText())
			self.draw_screen()
			return nil
		}
		return self.rl.OnKeyEvent(ev)
	}
	if self.statusline_message != "" {
		if ev.Type != loop.RELEASE {
			ev.Handled = true
			self.statusline_message = ""
			self.draw_status_line()
		}
		return nil
	}
	if self.current_search != nil && ev.MatchesPressOrRepeat("esc") {
		self.current_search = nil
		self.draw_screen()
		return nil
	}
	ac := self.shortcut_tracker.Match(ev, conf.KeyboardShortcuts)
	if ac != nil {
		ev.Handled = true
		return self.dispatch_action(ac.Name, ac.Args)
	}
	return nil
}

// do_scroll_to calls scroll_to inside an atomic update, updating the sticky
// header and status line, returning the result of scroll_to
func (self *Handler) do_scroll_to(scroll_to func() bool) (found bool) {
	self.do_scroll(func() bool {
		before := self.scroller.Position()
		found = scroll_to()
		return self.scroller.Position() != before
	})
	return
}

// scroll_to_next_change scrolls to the next (or previous) change, returning
// whether there is one. Must be called inside an atomic update.
func (self *Handler) scroll_to_next_change(backwards bool) bool {
	cur := self.scroll_pos()
	if backwards {
		for i := cur.logical_line - 1; i >= 0; i-- {
			line := self.logical_lines.At(i)
			if line.is_change_start {
				return self.scroll_to_pos(ScrollPos{i, 0})
			}
		}
	} else {
		for i := cur.logical_line + 1; i < self.logical_lines.Len(); i++ {
			line := self.logical_lines.At(i)
			if line.is_change_start {
				return self.scroll_to_pos(ScrollPos{i, 0})
			}
		}
	}
	return false
}

// scroll_to_next_file scrolls to the next (or previous) file, returning
// whether there is one. Must be called inside an atomic update.
func (self *Handler) scroll_to_next_file(backwards bool) bool {
	cur := self.scroll_pos()
	if backwards {
		for i := cur.logical_line - 1; i >= 0; i-- {
			line := self.logical_lines.At(i)
			if line.line_type == TITLE_LINE {
				return self.scroll_to_pos(ScrollPos{i, 0})
			}
		}
	} else {
		for i := cur.logical_line + 1; i < self.logical_lines.Len(); i++ {
			line := self.logical_lines.At(i)
			if line.line_type == TITLE_LINE {
				return self.scroll_to_pos(ScrollPos{i, 0})
			}
		}
	}
	return false
}

// scroll_to_next_match scrolls to the next (or previous) match, returning
// whether there is one. Must be called inside an atomic update.
func (self *Handler) scroll_to_next_match(backwards, include_current_match bool) bool {
	if self.current_search == nil {
		return false
	}
	if self.current_search_is_backward {
		backwards = !backwards
	}
	offset, delta := 1, 1
	if include_current_match {
		offset = 0
	}
	if backwards {
		offset *= -1
		delta *= -1
	}
	pos := self.scroll_pos()
	if offset != 0 && self.logical_lines.IncrementScrollPosBy(&pos, offset) == 0 {
		return false
	}
	max_pos := self.max_scroll_pos()
	for {
		if self.current_search.Has(pos) {
			self.scroll_to_pos(pos)
			return true
		}
		if self.logical_lines.IncrementScrollPosBy(&pos, delta) == 0 || max_pos.Less(pos) {
			break
		}
	}
	return false
}

func (self *Handler) change_context_count(val int) bool {
	val = utils.Max(0, val)
	if val == self.current_context_count {
		return false
	}
	self.current_context_count = val
	p := self.scroll_pos()
	self.restore_position = &p
	self.clear_mouse_selection()
	self.generate_diff()
	self.draw_screen()
	return true
}

func (self *Handler) start_search(is_regex, is_backward bool) {
	if self.inputting_command {
		self.lp.Beep()
		return
	}
	self.inputting_command = true
	self.current_search_is_regex = is_regex
	self.current_search_is_backward = is_backward
	self.rl.SetText(``)
	self.draw_status_line()
}

func (self *Handler) dispatch_action(name, args string) error {
	switch name {
	case `quit`:
		self.lp.Quit(0)
	case `copy_to_clipboard`:
		text := self.text_for_current_mouse_selection()
		if text == "" {
			self.lp.Beep()
		} else {
			self.lp.CopyTextToClipboard(text)
		}
	case `copy_to_clipboard_or_exit`:
		text := self.text_for_current_mouse_selection()
		if text == "" {
			self.lp.Quit(0)
		} else {
			self.lp.CopyTextToClipboard(text)
		}
	case `scroll_by`:
		if args == "" {
			args = "1"
		}
		amt, err := strconv.Atoi(args)
		if err != nil || !self.do_scroll(func() bool { return self.scroll_lines(amt) }) {
			self.lp.Beep()
		}
	case `scroll_to`:
		if self.logical_lines == nil {
			self.lp.Beep()
			break
		}
		prev := strings.Contains(args, `prev`)
		var done bool
		switch {
		case strings.Contains(args, "file"):
			done = self.do_scroll_to(func() bool { return self.scroll_to_next_file(prev) })
		case strings.Contains(args, `change`):
			done = self.do_scroll_to(func() bool { return self.scroll_to_next_change(prev) })
		case strings.Contains(args, `match`):
			done = self.do_scroll_to(func() bool { return self.scroll_to_next_match(prev, false) })
		case strings.Contains(args, `page`):
			amt := self.scroller.Height()
			if strings.Contains(args, `half`) {
				amt = amt / 2
			}
			if prev {
				amt *= -1
			}
			done = self.do_scroll(func() bool { return self.scroll_lines(amt) })
		default:
			done = self.do_scroll(func() bool {
				if strings.Contains(args, `end`) {
					return self.scroller.ScrollTo(self.lp, self.scroller.MaxPosition())
				}
				return self.scroller.ScrollTo(self.lp, 0)
			})
		}
		if !done {
			self.lp.Beep()
		}
	case `change_context`:
		new_ctx := self.current_context_count
		switch args {
		case `all`:
			new_ctx = 100000
		case `default`:
			new_ctx = self.original_context_count
		default:
			delta, _ := strconv.Atoi(args)
			new_ctx += delta
		}
		if !self.change_context_count(new_ctx) {
			self.lp.Beep()
		}
	case `start_search`:
		if self.diff_map != nil && self.logical_lines != nil {
			a, b, _ := strings.Cut(args, " ")
			self.start_search(config.StringToBool(a), config.StringToBool(b))
		}
	}
	return nil
}

func (self *Handler) on_mouse_event(ev *loop.MouseEvent) error {
	if self.logical_lines == nil {
		return nil
	}
	if self.handle_wheel_event(ev) {
		return nil
	}
	if ev.Event_type == loop.MOUSE_PRESS && ev.Buttons&loop.LEFT_MOUSE_BUTTON != 0 {
		self.start_mouse_selection(ev)
		return nil
	}
	if ev.Event_type == loop.MOUSE_MOVE {
		self.update_mouse_selection(ev)
		return nil
	}
	if ev.Event_type == loop.MOUSE_RELEASE && ev.Buttons&loop.LEFT_MOUSE_BUTTON != 0 {
		self.finish_mouse_selection(ev)
		return nil
	}
	return nil
}
