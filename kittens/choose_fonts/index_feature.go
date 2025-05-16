package choose_fonts

import (
	"fmt"
	"strconv"
	"strings"

	"github.com/kovidgoyal/kitty/tools/tui"
	"github.com/kovidgoyal/kitty/tools/tui/loop"
	"github.com/kovidgoyal/kitty/tools/tui/readline"
	"github.com/kovidgoyal/kitty/tools/utils"
)

var _ = fmt.Print

type if_panel struct {
	handler *handler
	rl      *readline.Readline

	family, which, feat_tag string
	settings                faces_settings
	feature_data            FeatureData
	current_val             uint
}

func (self *if_panel) render_lines(start_y int, lines ...string) (y int) {
	sz, _ := self.handler.lp.ScreenSize()
	_, y, str := self.handler.render_lines.InRectangle(lines, 0, start_y, int(sz.WidthCells), int(sz.HeightCells)-y, &self.handler.mouse_state, self.on_click)
	self.handler.lp.QueueWriteString(str)
	return
}

func (self *if_panel) draw_screen() (err error) {
	lp := self.handler.lp
	feat_name := utils.IfElse(self.feature_data.Name == "", self.feat_tag, self.feature_data.Name)
	lp.QueueWriteString(self.handler.format_title("Edit "+feat_name, 0))
	lines := []string{
		fmt.Sprintf("Enter a value for the '%s' feature of the %s font. Values are non-negative integers. Leaving it blank will cause the feature value to be not set, i.e. take its default value.", feat_name, self.family),
	}
	if self.feature_data.Tooltip != "" {
		lines = append(lines, "")
		lines = append(lines, self.feature_data.Tooltip)
	}
	if len(self.feature_data.Params) > 0 {
		lines = append(lines, "")
		lines = append(lines, "You can also click on any of the feature names below to choose the corresponding value.")
	} else {
		lines = append(lines, "")
		lines = append(lines, "Consult the documentation for this font to find out what values are valid for this feature.")
	}
	lines = append(lines, "")
	cursor_y := self.render_lines(2, lines...)
	if len(self.feature_data.Params) > 0 {
		lp.MoveCursorTo(1, cursor_y+3)
		num := 1
		strings.Join(utils.Map(func(x string) string {
			ans := tui.InternalHyperlink(x, fmt.Sprintf("fval:%d", num))
			num++
			return ans
		}, self.feature_data.Params), ", ")
	}
	lp.MoveCursorTo(1, cursor_y+1)
	lp.ClearToEndOfLine()
	self.rl.RedrawNonAtomic()
	lp.SetCursorVisible(true)
	return
}

func (self *if_panel) initialize(h *handler) (err error) {
	self.handler = h
	self.rl = readline.New(h.lp, readline.RlInit{DontMarkPrompts: true, Prompt: "Value: "})
	return
}

func (self *if_panel) on_wakeup() error {
	return self.handler.draw_screen()
}

func (self *if_panel) on_click(id string) (err error) {
	scheme, val, _ := strings.Cut(id, ":")
	if scheme != "fval" {
		return
	}
	v, _ := strconv.ParseUint(val, 10, 0)
	if err = self.handler.face_pane.change_feature_value(self.feat_tag, uint(v), false); err != nil {
		return err
	}
	self.handler.current_pane = &self.handler.face_pane
	return self.handler.draw_screen()
}

func (self *if_panel) on_key_event(event *loop.KeyEvent) (err error) {
	if event.MatchesPressOrRepeat("esc") {
		event.Handled = true
		self.handler.current_pane = &self.handler.face_pane
		return self.handler.draw_screen()
	}
	if event.MatchesPressOrRepeat("enter") {
		event.Handled = true
		text := strings.TrimSpace(self.rl.AllText())
		remove := false
		var val uint64
		if text == "" {
			remove = true
		} else {
			val, err = strconv.ParseUint(text, 10, 0)
		}
		if err != nil {
			self.rl.ResetText()
			self.handler.lp.Beep()
		} else {
			if err = self.handler.face_pane.change_feature_value(self.feat_tag, uint(val), remove); err != nil {
				return err
			}
			self.handler.current_pane = &self.handler.face_pane
		}
		return self.handler.draw_screen()
	}
	if err = self.rl.OnKeyEvent(event); err != nil {
		if err == readline.ErrAcceptInput {
			return nil
		}
		return err
	}
	return self.draw_screen()
}

func (self *if_panel) on_text(text string, from_key_event bool, in_bracketed_paste bool) (err error) {
	if err = self.rl.OnText(text, from_key_event, in_bracketed_paste); err != nil {
		return err
	}
	return self.draw_screen()
}

func (self *if_panel) on_enter(family, which string, settings faces_settings, feat_tag string, fd FeatureData, current_val uint) error {
	self.family = family
	self.feat_tag = feat_tag
	self.settings = settings
	self.which = which
	self.handler.current_pane = self
	self.feature_data = fd
	self.current_val = current_val
	self.rl.ResetText()
	if self.current_val > 0 {
		self.rl.SetText(strconv.FormatUint(uint64(self.current_val), 10))
	}
	return self.handler.draw_screen()
}
