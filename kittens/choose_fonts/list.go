package choose_fonts

import (
	"fmt"
	"strings"
	"sync"

	"github.com/kovidgoyal/kitty/tools/tui/loop"
	"github.com/kovidgoyal/kitty/tools/tui/readline"
	"github.com/kovidgoyal/kitty/tools/utils"
	"github.com/kovidgoyal/kitty/tools/utils/style"
	"github.com/kovidgoyal/kitty/tools/wcswidth"
)

var _ = fmt.Print

type preview_cache_key struct {
	family        string
	width, height int
}

type preview_cache_value struct {
	path          string
	width, height int
}

type FontList struct {
	rl                             *readline.Readline
	family_list                    FamilyList
	fonts                          map[string][]ListedFont
	family_list_updated            bool
	resolved_faces_from_kitty_conf ResolvedFaces
	handler                        *handler
	variable_data_requested_for    *utils.Set[string]
	preview_cache                  map[preview_cache_key]preview_cache_value
	preview_cache_mutex            sync.Mutex
}

func (self *FontList) initialize(h *handler) error {
	self.handler = h
	self.preview_cache = make(map[preview_cache_key]preview_cache_value)
	self.rl = readline.New(h.lp, readline.RlInit{DontMarkPrompts: true, Prompt: "Family: "})
	self.variable_data_requested_for = utils.NewSet[string](256)
	return nil
}

func (self *FontList) draw_search_bar() {
	lp := self.handler.lp
	lp.SetCursorVisible(true)
	lp.SetCursorShape(loop.BAR_CURSOR, true)
	sz, err := lp.ScreenSize()
	if err != nil {
		return
	}
	lp.MoveCursorTo(1, int(sz.HeightCells))
	lp.ClearToEndOfLine()
	self.rl.RedrawNonAtomic()
}

const SEPARATOR = "║"

func center_string(x string, width int, filler ...string) string {
	space := " "
	if len(filler) > 0 {
		space = filler[0]
	}
	l := wcswidth.Stringwidth(x)
	spaces := int(float64(width-l) / 2)
	space = strings.Repeat(space, utils.Max(0, spaces))
	return space + x + space
}

func (self *handler) format_title(title string, start_x int) string {
	sz, _ := self.lp.ScreenSize()
	return self.lp.SprintStyled("fg=green bold", center_string(title, int(sz.WidthCells)-start_x))
}

func (self *FontList) draw_family_summary(start_x int, sz loop.ScreenSize) (err error) {
	lp := self.handler.lp
	family := self.family_list.CurrentFamily()
	if family == "" || int(sz.WidthCells) < start_x+2 {
		return nil
	}
	lines := []string{self.handler.format_title(family, start_x), ""}
	width := int(sz.WidthCells) - start_x - 1
	add_line := func(x string) {
		lines = append(lines, style.WrapTextAsLines(x, width, style.WrapOptions{})...)
	}
	fonts := self.fonts[family]
	if len(fonts) == 0 {
		return fmt.Errorf("The family: %s has no fonts", family)
	}
	if has_variable_data_for_font(fonts[0]) {
		s := styles_in_family(family, fonts)
		for _, sg := range s.style_groups {
			styles := lp.SprintStyled(control_name_style, sg.name) + ": " + strings.Join(sg.styles, ", ")
			add_line(styles)
			add_line("")
		}
		if s.has_variable_faces {
			add_line(fmt.Sprintf("This font is %s allowing for finer style control", lp.SprintStyled("fg=magenta", "variable")))
		}
		add_line(fmt.Sprintf("Press the %s key to choose this family", lp.SprintStyled("fg=yellow", "Enter")))
	} else {
		lines = append(lines, "Reading font data, please wait…")
		key := fonts[0].cache_key()
		if !self.variable_data_requested_for.Has(key) {
			self.variable_data_requested_for.Add(key)
			go func() {
				self.handler.set_worker_error(ensure_variable_data_for_fonts(fonts...))
				lp.WakeupMainThread()
			}()
		}
	}

	y := 0
	for _, line := range lines {
		if y >= int(sz.HeightCells)-1 {
			break
		}
		lp.MoveCursorTo(start_x+1, y+1)
		lp.QueueWriteString(line)
		y++
	}
	if self.handler.text_style.Background != "" {
		return self.draw_preview(start_x, y, sz)
	}
	return
}

func (self *FontList) draw_preview(x, y int, sz loop.ScreenSize) (err error) {
	width_cells, height_cells := int(sz.WidthCells)-x, int(sz.HeightCells)-y
	if height_cells < 3 {
		return
	}
	y++
	self.handler.lp.MoveCursorTo(x+1, y+1)
	self.handler.draw_preview_header(x)
	y++
	height_cells -= 2
	self.handler.lp.MoveCursorTo(x+1, y+1)
	key := preview_cache_key{
		family: self.family_list.CurrentFamily(), width: int(sz.CellWidth) * width_cells, height: int(sz.CellHeight) * height_cells,
	}
	if key.family == "" {
		return
	}
	self.preview_cache_mutex.Lock()
	defer self.preview_cache_mutex.Unlock()
	cc := self.preview_cache[key]
	switch cc.path {
	case "":
		self.preview_cache[key] = preview_cache_value{path: "requested"}
		go func() {
			var r map[string]RenderedSampleTransmit
			self.handler.set_worker_error(kitty_font_backend.query("render_family_samples", map[string]any{
				"text_style": self.handler.text_style, "font_family": key.family, "width": key.width, "height": key.height,
				"output_dir": self.handler.temp_dir,
			}, &r))
			self.preview_cache_mutex.Lock()
			defer self.preview_cache_mutex.Unlock()
			self.preview_cache[key] = preview_cache_value{path: r["font_family"].Path, width: r["font_family"].Canvas_width, height: r["font_family"].Canvas_height}
			self.handler.lp.WakeupMainThread()
		}()
		return
	case "requested":
		return
	}
	self.handler.graphics_manager.display_image(0, cc.path, cc.width, cc.height)
	return
}

func (self *FontList) on_wakeup() error {
	if !self.family_list_updated {
		self.family_list_updated = true
		self.family_list.UpdateFamilies(utils.StableSortWithKey(utils.Keys(self.fonts), strings.ToLower))
		self.family_list.SelectFamily(self.resolved_faces_from_kitty_conf.Font_family.Family)
	}
	return self.handler.draw_screen()
}

func (self *FontList) draw_screen() (err error) {
	lp := self.handler.lp
	sz, err := lp.ScreenSize()
	if err != nil {
		return err
	}
	num_rows := max(0, int(sz.HeightCells)-1)
	mw := self.family_list.max_width + 1
	green_fg, _, _ := strings.Cut(lp.SprintStyled("fg=green", "|"), "|")
	lines := make([]string, 0, num_rows)
	for _, l := range self.family_list.Lines(num_rows) {
		line := l.text
		if l.is_current {
			line = strings.ReplaceAll(line, MARK_AFTER, green_fg)
			line = lp.SprintStyled("fg=green", ">") + lp.SprintStyled("fg=green bold", line)
		} else {
			line = " " + line
		}
		lines = append(lines, line)
	}
	_, _, str := self.handler.render_lines.InRectangle(lines, 0, 0, 0, num_rows, &self.handler.mouse_state, self.on_click)
	lp.QueueWriteString(str)
	seps := strings.Repeat(SEPARATOR, num_rows)
	seps = strings.TrimSpace(seps)
	_, _, str = self.handler.render_lines.InRectangle(strings.Split(seps, ""), mw+1, 0, 0, num_rows, &self.handler.mouse_state)
	lp.QueueWriteString(str)

	if self.family_list.Len() > 0 {
		if err = self.draw_family_summary(mw+3, sz); err != nil {
			return err
		}
	}
	self.draw_search_bar()
	return
}

func (self *FontList) on_click(id string) error {
	which, data, found := strings.Cut(id, ":")
	if !found {
		return fmt.Errorf("Not a valid click id: %s", id)
	}
	switch which {
	case "family-chosen":
		if self.handler.state == LISTING_FAMILIES {
			if self.family_list.Select(data) {
				self.handler.draw_screen()
			} else {
				self.handler.lp.Beep()
			}

		}
	}
	return nil
}

func (self *FontList) update_family_search() {
	text := self.rl.AllText()
	if self.family_list.UpdateSearch(text) {
		self.handler.draw_screen()
	} else {
		self.draw_search_bar()
	}
}

func (self *FontList) next(delta int, allow_wrapping bool) error {
	if self.family_list.Next(delta, allow_wrapping) {
		return self.handler.draw_screen()
	}
	self.handler.lp.Beep()
	return nil
}

func (self *FontList) on_key_event(event *loop.KeyEvent) (err error) {
	if event.MatchesPressOrRepeat("enter") {
		event.Handled = true
		if family := self.family_list.CurrentFamily(); family != "" {
			return self.handler.faces.on_enter(family)
		}
		self.handler.lp.Beep()
		return
	}
	if event.MatchesPressOrRepeat("esc") {
		event.Handled = true
		if self.rl.AllText() != "" {
			self.rl.ResetText()
			self.update_family_search()
			self.handler.draw_screen()
		} else {
			return fmt.Errorf("canceled by user")
		}
		return
	}
	ev := event
	if ev.MatchesPressOrRepeat("down") {
		ev.Handled = true
		return self.next(1, true)
	}
	if ev.MatchesPressOrRepeat("up") {
		ev.Handled = true
		return self.next(-1, true)
	}
	if ev.MatchesPressOrRepeat("page_down") {
		ev.Handled = true
		sz, err := self.handler.lp.ScreenSize()
		if err == nil {
			err = self.next(int(sz.HeightCells)-3, false)
		}
		return err
	}
	if ev.MatchesPressOrRepeat("page_up") {
		ev.Handled = true
		sz, err := self.handler.lp.ScreenSize()
		if err == nil {
			err = self.next(3-int(sz.HeightCells), false)
		}
		return err
	}

	if err = self.rl.OnKeyEvent(event); err != nil {
		if err == readline.ErrAcceptInput {
			return nil
		}
		return err
	}
	if event.Handled {
		self.update_family_search()
	}
	self.draw_search_bar()
	return
}

func (self *FontList) on_text(text string, from_key_event bool, in_bracketed_paste bool) (err error) {
	if err = self.rl.OnText(text, from_key_event, in_bracketed_paste); err != nil {
		return err
	}
	self.update_family_search()
	return
}
