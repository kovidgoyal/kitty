package choose_fonts

import (
	"fmt"
	"kitty/tools/tui/loop"
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
