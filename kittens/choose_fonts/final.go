package choose_fonts

import (
	"fmt"
	"path/filepath"
	"strings"

	"github.com/kovidgoyal/kitty/tools/config"
	"github.com/kovidgoyal/kitty/tools/tui/loop"
	"github.com/kovidgoyal/kitty/tools/utils"
)

var _ = fmt.Print

type final_pane struct {
	handler  *handler
	settings faces_settings
	family   string
	lp       *loop.Loop
}

func (self *final_pane) render_lines(start_y int, lines ...string) (y int) {
	sz, _ := self.handler.lp.ScreenSize()
	_, y, str := self.handler.render_lines.InRectangle(lines, 0, start_y, int(sz.WidthCells), int(sz.HeightCells)-y, &self.handler.mouse_state, self.on_click)
	self.handler.lp.QueueWriteString(str)
	return
}

func (self *final_pane) draw_screen() (err error) {
	s := self.lp.SprintStyled
	h := func(x string) string { return s(highlight_key_style, x) }

	self.render_lines(0,
		fmt.Sprintf("You have chosen the %s family", s(current_val_style, self.family)),
		"",
		"What would you like to do?",
		"",
		fmt.Sprintf("%s to modify %s and use the new fonts", h("Enter"), s("italic", self.handler.opts.Config_file_name)),
		"",
		fmt.Sprintf("%s to abort and return to font selection", h("Esc")),
		"",
		fmt.Sprintf("%s to write the new font settings to %s", h("s"), s("italic", `STDOUT`)),
		"",
		fmt.Sprintf("%s to quit", h("Ctrl+c")),
	)
	return
}

func (self *final_pane) initialize(h *handler) (err error) {
	self.handler = h
	self.lp = h.lp
	return
}

func (self *final_pane) on_wakeup() error {
	return self.handler.draw_screen()
}

func (self *final_pane) on_click(id string) (err error) {
	return
}

func (self faces_settings) serialized() string {
	return strings.Join([]string{
		"font_family      " + self.font_family,
		"bold_font        " + self.bold_font,
		"italic_font      " + self.italic_font,
		"bold_italic_font " + self.bold_italic_font,
	}, "\n")
}

func (self *final_pane) on_key_event(event *loop.KeyEvent) (err error) {
	if event.MatchesPressOrRepeat("esc") {
		event.Handled = true
		self.handler.current_pane = &self.handler.faces
		return self.handler.draw_screen()
	}
	if event.MatchesPressOrRepeat("enter") {
		event.Handled = true
		patcher := config.Patcher{Write_backup: true}
		path := ""
		if filepath.IsAbs(self.handler.opts.Config_file_name) {
			path = self.handler.opts.Config_file_name
		} else {
			path = filepath.Join(utils.ConfigDir(), self.handler.opts.Config_file_name)
		}
		updated, err := patcher.Patch(path, "KITTY_FONTS", self.settings.serialized(), "font_family", "bold_font", "italic_font", "bold_italic_font")
		if err != nil {
			return err
		}
		if updated {
			switch self.handler.opts.Reload_in {
			case "parent":
				config.ReloadConfigInKitty(true)
			case "all":
				config.ReloadConfigInKitty(false)
			}
		}
		self.lp.Quit(0)
		return nil

	}
	return
}

func (self *final_pane) on_text(text string, from_key_event bool, in_bracketed_paste bool) (err error) {
	if from_key_event {
		switch text {
		case "s", "S":
			output_on_exit = self.settings.serialized() + "\n"
			self.lp.Quit(0)
			return
		}
	}
	return
}

func (self *final_pane) on_enter(family string, settings faces_settings) error {
	self.settings = settings
	self.family = family
	self.handler.current_pane = self
	return self.handler.draw_screen()
}
