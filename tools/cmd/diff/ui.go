// License: GPLv3 Copyright: 2023, Kovid Goyal, <kovid at kovidgoyal.net>

package diff

import (
	"fmt"
	"regexp"
	"strconv"
	"strings"

	"kitty/tools/config"
	"kitty/tools/tui/graphics"
	"kitty/tools/tui/loop"
	"kitty/tools/tui/readline"
	"kitty/tools/utils"
	"kitty/tools/wcswidth"
)

var _ = fmt.Print

type ResultType int

const (
	COLLECTION ResultType = iota
	DIFF
	HIGHLIGHT
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
}

type Handler struct {
	async_results                                       chan AsyncResult
	shortcut_tracker                                    config.ShortcutTracker
	pending_keys                                        []string
	left, right                                         string
	collection                                          *Collection
	diff_map                                            map[string]*Patch
	logical_lines                                       *LogicalLines
	lp                                                  *loop.Loop
	current_context_count, original_context_count       int
	added_count, removed_count                          int
	screen_size                                         struct{ rows, columns, num_lines int }
	scroll_pos, max_scroll_pos                          ScrollPos
	restore_position                                    *ScrollPos
	inputting_command                                   bool
	statusline_message                                  string
	rl                                                  *readline.Readline
	current_search                                      *Search
	current_search_is_regex, current_search_is_backward bool
}

func (self *Handler) calculate_statistics() {
	self.added_count, self.removed_count = self.collection.added_count, self.collection.removed_count
	for _, patch := range self.diff_map {
		self.added_count += patch.added_count
		self.removed_count += patch.removed_count
	}
}

var DebugPrintln func(...any)

func (self *Handler) initialize() {
	DebugPrintln = self.lp.DebugPrintln
	self.pending_keys = make([]string, 0, 4)
	self.rl = readline.New(self.lp, readline.RlInit{DontMarkPrompts: true, Prompt: "/"})
	self.current_context_count = opts.Context
	if self.current_context_count < 0 {
		self.current_context_count = int(conf.Num_context_lines)
	}
	sz, _ := self.lp.ScreenSize()
	self.screen_size.rows = int(sz.HeightCells)
	self.screen_size.columns = int(sz.WidthCells)
	self.screen_size.num_lines = self.screen_size.rows - 1
	self.original_context_count = self.current_context_count
	self.lp.SetDefaultColor(loop.FOREGROUND, conf.Foreground)
	self.lp.SetDefaultColor(loop.CURSOR, conf.Foreground)
	self.lp.SetDefaultColor(loop.BACKGROUND, conf.Background)
	self.lp.SetDefaultColor(loop.SELECTION_BG, conf.Select_bg)
	if conf.Select_fg.IsSet {
		self.lp.SetDefaultColor(loop.SELECTION_FG, conf.Select_fg.Color)
	}
	self.async_results = make(chan AsyncResult, 32)
	go func() {
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
	self.collection.Apply(func(path, typ, changed_path string) error {
		if typ == "diff" {
			if is_path_text(path) && is_path_text(changed_path) {
				jobs = append(jobs, diff_job{path, changed_path})
			}
		}
		return nil
	})
	go func() {
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

func (self *Handler) highlight_all() {
	text_files := utils.Filter(self.collection.paths_to_highlight.AsSlice(), is_path_text)
	go func() {
		r := AsyncResult{rtype: HIGHLIGHT}
		highlight_all(text_files)
		self.async_results <- r
		self.lp.WakeupMainThread()
	}()

}

func (self *Handler) handle_async_result(r AsyncResult) error {
	switch r.rtype {
	case COLLECTION:
		self.collection = r.collection
		self.generate_diff()
		self.highlight_all()
	case DIFF:
		self.diff_map = r.diff_map
		self.calculate_statistics()
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
	case HIGHLIGHT:
		if self.diff_map != nil && self.collection != nil {
			err := self.render_diff()
			if err != nil {
				return err
			}
			self.draw_screen()
		}
	}
	return nil
}

func (self *Handler) on_resize(old_size, new_size loop.ScreenSize) error {
	self.screen_size.rows = int(new_size.HeightCells)
	self.screen_size.num_lines = self.screen_size.rows - 1
	self.screen_size.columns = int(new_size.WidthCells)
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
	self.logical_lines, err = render(self.collection, self.diff_map, self.screen_size.columns)
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

func (self *Handler) draw_screen() {
	self.lp.StartAtomicUpdate()
	defer self.lp.EndAtomicUpdate()
	g := (&graphics.GraphicsCommand{}).SetAction(graphics.GRT_action_delete).SetDelete(graphics.GRT_delete_visible)
	g.WriteWithPayloadToLoop(self.lp, nil)
	lp.MoveCursorTo(1, 1)
	lp.ClearToEndOfScreen()
	if self.logical_lines == nil || self.diff_map == nil || self.collection == nil {
		lp.Println(`Calculating diff, please wait...`)
		return
	}
	num_written := 0
	for i, line := range self.logical_lines.lines[self.scroll_pos.logical_line:] {
		if num_written >= self.screen_size.num_lines {
			break
		}
		screen_lines := line.screen_lines
		if i == 0 {
			screen_lines = screen_lines[self.scroll_pos.screen_line:]
		}
		for snum, sl := range screen_lines {
			if self.current_search != nil {
				sl = self.current_search.markup_line(sl, ScrollPos{i, snum}.Add(self.scroll_pos))
			}
			lp.QueueWriteString(sl)
			lp.MoveCursorVertically(1)
			lp.QueueWriteString("\r")
			num_written++
			if num_written >= self.screen_size.num_lines {
				break
			}
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
	pat, err := regexp.Compile(query)
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
	if self.logical_lines.IncrementScrollPosBy(&pos, offset) == 0 {
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
		case strings.Contains(args, `change`):
			done = self.scroll_to_next_change(strings.Contains(args, `prev`))
		case strings.Contains(args, `match`):
			done = self.scroll_to_next_match(strings.Contains(args, `prev`), false)
		case strings.Contains(args, `page`):
			amt := self.screen_size.num_lines
			if strings.Contains(args, `prev`) {
				amt *= -1
			}
			done = self.scroll_lines(amt) != 0
		default:
			npos := self.scroll_pos
			if strings.Contains(args, `end`) {
				npos = self.max_scroll_pos
			} else {
				npos = ScrollPos{}
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
