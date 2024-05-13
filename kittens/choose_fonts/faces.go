package choose_fonts

import (
	"fmt"
	"kitty/tools/tui/loop"
	"kitty/tools/utils"
)

var _ = fmt.Print

type faces struct {
	handler *handler

	family   string
	settings struct {
		font_family, bold_font, italic_font, bold_italic_font string
	}
}

func (self *faces) draw_screen() (err error) {
	self.handler.lp.SetCursorVisible(false)
	sz, _ := self.handler.lp.ScreenSize()
	lines := []string{self.handler.format_title(self.family, 0), ""}
	_, _, str := self.handler.render_lines.InRectangle(lines, 0, 0, int(sz.WidthCells), int(sz.HeightCells), &self.handler.mouse_state, self.on_click)
	self.handler.lp.QueueWriteString(str)
	return
}

func (self *faces) initialize(h *handler) (err error) {
	self.handler = h
	return
}

func (self *faces) on_wakeup() error {
	return self.handler.draw_screen()
}

func (self *faces) on_click(id string) (err error) {
	return
}

func (self *faces) on_key_event(event *loop.KeyEvent) (err error) {
	if event.MatchesPressOrRepeat("esc") {
		event.Handled = true
		self.handler.current_pane = &self.handler.listing
		return self.handler.draw_screen()
	}
	return
}

func (self *faces) on_text(text string, from_key_event bool, in_bracketed_paste bool) (err error) {
	return
}

func (self *faces) on_enter(family string) error {
	if family != "" {
		self.family = family
		r := self.handler.listing.resolved_faces_from_kitty_conf
		d := func(conf ResolvedFace, setting *string, defval string) {
			*setting = utils.IfElse(family == conf.Family, conf.Spec, defval)
		}
		d(r.Font_family, &self.settings.font_family, family)
		d(r.Bold_font, &self.settings.bold_font, "auto")
		d(r.Italic_font, &self.settings.italic_font, "auto")
		d(r.Bold_italic_font, &self.settings.bold_italic_font, "auto")
	}
	self.handler.current_pane = self
	return self.handler.draw_screen()
}
