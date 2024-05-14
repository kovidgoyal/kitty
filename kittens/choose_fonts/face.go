package choose_fonts

import (
	"fmt"
	"kitty/tools/tui/loop"
	"math"
	"sync"
)

var _ = fmt.Print

type face_panel struct {
	handler *handler

	family, which       string
	settings            faces_settings
	setting             string
	preview_cache       map[faces_preview_key]map[string]RenderedSampleTransmit
	preview_cache_mutex sync.Mutex
}

func (self *face_panel) draw_screen() (err error) {
	lp := self.handler.lp
	lp.SetCursorVisible(false)
	sz, _ := lp.ScreenSize()
	styled := lp.SprintStyled
	wt := "Regular"
	switch self.which {
	case "bold_font":
		wt = "Bold"
	case "italic_font":
		wt = "Italic"
	case "bold_italic_font":
		wt = "Bold-Italic font"
	}

	lines := []string{
		self.handler.format_title(self.family+": "+wt, 0), "",
		fmt.Sprintf("Press %s to select this face or %s to cancel. Click on a style name below to switch to it.", styled("fg=green", "Enter"), styled("fg=red", "Esc")), "",
	}
	_, y, str := self.handler.render_lines.InRectangle(lines, 0, 0, int(sz.WidthCells), int(sz.HeightCells), &self.handler.mouse_state, self.on_click)
	lp.QueueWriteString(str)
	num_lines_per_font := (int(sz.HeightCells) - y - 1) - 2
	num_lines_needed := int(math.Ceil(100. / float64(sz.WidthCells)))
	num_lines := max(1, min(num_lines_per_font, num_lines_needed))
	key := faces_preview_key{settings: self.settings, width: int(sz.WidthCells * sz.CellWidth), height: int(sz.CellHeight) * num_lines}
	self.preview_cache_mutex.Lock()
	defer self.preview_cache_mutex.Unlock()
	previews, found := self.preview_cache[key]
	if !found {
		self.preview_cache[key] = make(map[string]RenderedSampleTransmit)
		go func() {
			var r map[string]RenderedSampleTransmit
			s := key.settings
			self.handler.set_worker_error(kitty_font_backend.query("render_family_samples", map[string]any{
				"text_style": self.handler.text_style, "font_family": s.font_family,
				"bold_font": s.bold_font, "italic_font": s.italic_font, "bold_italic_font": s.bold_italic_font,
				"width": key.width, "height": key.height, "output_dir": self.handler.temp_dir,
			}, &r))
			self.preview_cache_mutex.Lock()
			defer self.preview_cache_mutex.Unlock()
			self.preview_cache[key] = r
			self.handler.lp.WakeupMainThread()
		}()
		return
	}
	if len(previews) < 4 {
		return
	}

	return
}

func (self *face_panel) initialize(h *handler) (err error) {
	self.handler = h
	self.preview_cache = make(map[faces_preview_key]map[string]RenderedSampleTransmit)
	return
}

func (self *face_panel) on_wakeup() error {
	return self.handler.draw_screen()
}

func (self *face_panel) on_click(id string) (err error) {
	return
}

func (self *face_panel) on_key_event(event *loop.KeyEvent) (err error) {
	if event.MatchesPressOrRepeat("esc") {
		event.Handled = true
		self.handler.current_pane = &self.handler.faces
		return self.handler.draw_screen()
	}
	return
}

func (self *face_panel) on_text(text string, from_key_event bool, in_bracketed_paste bool) (err error) {
	return
}

func (self *face_panel) on_enter(family, which string, settings faces_settings) error {
	self.family = family
	self.settings = settings
	self.which = which
	self.handler.current_pane = self
	return self.handler.draw_screen()
}
