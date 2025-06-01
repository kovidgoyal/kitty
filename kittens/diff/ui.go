// License: GPLv3 Copyright: 2023, Kovid Goyal, <kovid at kovidgoyal.net>

package diff

import (
	"fmt"
	"regexp"
	"strconv"
	"strings"

	"github.com/kovidgoyal/kitty/tools/config"
	"github.com/kovidgoyal/kitty/tools/tui"
	"github.com/kovidgoyal/kitty/tools/tui/graphics"
	"github.com/kovidgoyal/kitty/tools/tui/loop"
	"github.com/kovidgoyal/kitty/tools/tui/readline"
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
type Handler struct {
	async_results                                       chan AsyncResult
	mouse_selection                                     tui.MouseSelection
	image_count                                         int
	shortcut_tracker                                    config.ShortcutTracker
	left, right                                         string
	collection                                          *Collection
	diff_map                                            map[string]*Patch
	logical_lines                                       *LogicalLines
	terminal_capabilities_received                      bool
	lp                                                  *loop.Loop
	current_context_count, original_context_count       int
	added_count, removed_count                          int
	screen_size                                         screen_size
	scroll_pos, max_scroll_pos                          ScrollPos
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
	if self.diff_map != nil && self.collection != nil {
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
		self.diff_map = r.diff_map
		self.calculate_statistics()
		self.clear_mouse_selection()
		err := self.render_diff()
		if err != nil {
			return err
		}
		self.scroll_pos = ScrollPos{}
		if self.restore_position != nil {
			self.scroll_pos = *self.restore_position
			if self.max_scroll_pos.Less(self.scroll_pos) {
				self.scroll_pos = self.max_scroll_pos
			}
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
	if self.diff_map != nil && self.collection != nil {
		err := self.render_diff()
		if err != nil {
			return err
		}
		if self.max_scroll_pos.Less(self.scroll_pos) {
			self.scroll_pos = self.max_scroll_pos
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
	self.logical_lines, err = render(self.collection, self.diff_map, self.screen_size, self.largest_line_number, self.images_resized_to)
	if err != nil {
		return err
	}
	last := self.logical_lines.Len() - 1
	self.max_scroll_pos.logical_line = last
	if last > -1 {
		self.max_scroll_pos.screen_line = len(self.logical_lines.At(last).screen_lines) - 1
	} else {
		self.max_scroll_pos.screen_line = 0
	}
	self.logical_lines.IncrementScrollPosBy(&self.max_scroll_pos, -self.screen_size.num_lines+1)
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

func (self *Handler) draw_screen() {
	self.lp.StartAtomicUpdate()
	defer self.lp.EndAtomicUpdate()
	if self.image_count > 0 {
		self.resize_all_images_if_needed()
		image_collection.DeleteAllVisiblePlacements(self.lp)
	}
	lp.MoveCursorTo(1, 1)
	lp.ClearToEndOfScreen()
	if self.logical_lines == nil || self.diff_map == nil || self.collection == nil || !self.terminal_capabilities_received {
		lp.Println(`Calculating diff, please wait...`)
		return
	}
	pos := self.scroll_pos
	seen_images := utils.NewSet[int]()
	for num_written := 0; num_written < self.screen_size.num_lines; num_written++ {
		ll := self.logical_lines.At(pos.logical_line)
		if ll == nil || self.logical_lines.ScreenLineAt(pos) == nil {
			num_written--
		} else {
			is_image := ll.line_type == IMAGE_LINE
			ll.render_screen_line(pos.screen_line, lp, self.logical_lines.margin_size, self.logical_lines.columns)
			if is_image && !seen_images.Has(pos.logical_line) && pos.screen_line >= ll.image_lines_offset {
				seen_images.Add(pos.logical_line)
				self.draw_image_pair(ll, pos.screen_line-ll.image_lines_offset)
			}
			if self.current_search != nil {
				if mkp := self.current_search.markup_line(pos, num_written); mkp != "" {
					lp.QueueWriteString(mkp)
				}
			}
			if mkp := self.add_mouse_selection_to_line(pos, num_written); mkp != "" {
				lp.QueueWriteString(mkp)
			}
			lp.MoveCursorVertically(1)
			lp.QueueWriteString("\x1b[m\r")
		}
		if self.logical_lines.IncrementScrollPosBy(&pos, 1) == 0 {
			break
		}
	}
	self.draw_status_line()
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
		num := self.logical_lines.NumScreenLinesTo(self.scroll_pos)
		den := self.logical_lines.NumScreenLinesTo(self.max_scroll_pos)
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
		if self.scroll_to_next_match(false, true) {
			self.draw_screen()
		} else {
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

func (self *Handler) scroll_lines(amt int) (delta int) {
	before := self.scroll_pos
	delta = self.logical_lines.IncrementScrollPosBy(&self.scroll_pos, amt)
	if delta > 0 && self.max_scroll_pos.Less(self.scroll_pos) {
		self.scroll_pos = self.max_scroll_pos
		delta = self.logical_lines.Minus(self.scroll_pos, before)
	}
	return
}

func (self *Handler) scroll_to_next_change(backwards bool) bool {
	if backwards {
		for i := self.scroll_pos.logical_line - 1; i >= 0; i-- {
			line := self.logical_lines.At(i)
			if line.is_change_start {
				self.scroll_pos = ScrollPos{i, 0}
				return true
			}
		}
	} else {
		for i := self.scroll_pos.logical_line + 1; i < self.logical_lines.Len(); i++ {
			line := self.logical_lines.At(i)
			if line.is_change_start {
				self.scroll_pos = ScrollPos{i, 0}
				return true
			}
		}
	}
	return false
}

func (self *Handler) scroll_to_next_file(backwards bool) bool {
	if backwards {
		for i := self.scroll_pos.logical_line - 1; i >= 0; i-- {
			line := self.logical_lines.At(i)
			if line.line_type == TITLE_LINE {
				self.scroll_pos = ScrollPos{i, 0}
				return true
			}
		}
	} else {
		for i := self.scroll_pos.logical_line + 1; i < self.logical_lines.Len(); i++ {
			line := self.logical_lines.At(i)
			if line.line_type == TITLE_LINE {
				self.scroll_pos = ScrollPos{i, 0}
				return true
			}
		}
	}
	return false
}

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
	pos := self.scroll_pos
	if offset != 0 && self.logical_lines.IncrementScrollPosBy(&pos, offset) == 0 {
		return false
	}
	for {
		if self.current_search.Has(pos) {
			self.scroll_pos = pos
			self.draw_screen()
			return true
		}
		if self.logical_lines.IncrementScrollPosBy(&pos, delta) == 0 || self.max_scroll_pos.Less(pos) {
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
	p := self.scroll_pos
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
		if err == nil {
			if self.scroll_lines(amt) == 0 {
				self.lp.Beep()
			} else {
				self.draw_screen()
			}
		} else {
			self.lp.Beep()
		}
	case `scroll_to`:
		done := false
		switch {
		case strings.Contains(args, "file"):
			done = self.scroll_to_next_file(strings.Contains(args, `prev`))
		case strings.Contains(args, `change`):
			done = self.scroll_to_next_change(strings.Contains(args, `prev`))
		case strings.Contains(args, `match`):
			done = self.scroll_to_next_match(strings.Contains(args, `prev`), false)
		case strings.Contains(args, `page`):
			amt := self.screen_size.num_lines
			if strings.Contains(args, `half`) {
				amt = amt / 2
			}
			if strings.Contains(args, `prev`) {
				amt *= -1
			}
			done = self.scroll_lines(amt) != 0
		default:
			npos := ScrollPos{}
			if strings.Contains(args, `end`) {
				npos = self.max_scroll_pos
			}
			done = npos != self.scroll_pos
			self.scroll_pos = npos
		}
		if done {
			self.draw_screen()
		} else {
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
	if ev.Event_type == loop.MOUSE_PRESS && ev.Buttons&(loop.MOUSE_WHEEL_UP|loop.MOUSE_WHEEL_DOWN) != 0 {
		self.handle_wheel_event(ev.Buttons&(loop.MOUSE_WHEEL_UP) != 0)
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
