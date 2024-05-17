package choose_fonts

import (
	"fmt"
	"math"
	"strings"
	"sync"

	"kitty/tools/tui"
	"kitty/tools/tui/loop"
)

var _ = fmt.Print

type face_panel struct {
	handler *handler

	family, which       string
	settings            faces_settings
	preview_cache       map[faces_preview_key]map[string]RenderedSampleTransmit
	preview_cache_mutex sync.Mutex
}

func (self *face_panel) draw_variable_fine_tune(sz loop.ScreenSize, start_y int, preview RenderedSampleTransmit) (y int, err error) {
	y = start_y
	return
}

func (self *face_panel) draw_family_style_select(sz loop.ScreenSize, start_y int) (y int, err error) {
	s := styles_in_family(self.family, self.handler.listing.fonts[self.family])
	lines := []string{}
	for _, sg := range s.style_groups {
		formatted := make([]string, len(sg.styles))
		for i, style_name := range sg.styles {
			formatted[i] = tui.InternalHyperlink(style_name, "style:"+style_name)
		}
		line := sg.name + ": " + strings.Join(formatted, ", ")
		lines = append(lines, line)
	}
	_, y, str := self.handler.render_lines.InRectangle(lines, 0, start_y, int(sz.WidthCells), int(sz.HeightCells)-start_y, &self.handler.mouse_state, self.on_click)
	self.handler.lp.QueueWriteString(str)
	return y, nil
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

	lp.QueueWriteString(self.handler.format_title(fmt.Sprintf("%s: %s face", self.family, wt), 0))

	lines := []string{
		fmt.Sprintf("Press %s to accept any changes or %s to cancel. Click on a style name below to switch to it.", styled("fg=green", "Enter"), styled("fg=red", "Esc")), "",
		fmt.Sprintf("Current setting: %s", self.get()), "",
	}
	_, y, str := self.handler.render_lines.InRectangle(lines, 0, 2, int(sz.WidthCells), int(sz.HeightCells)-2, &self.handler.mouse_state, self.on_click)
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
	preview := previews[self.which]
	if len(preview.Variable_data.Axes) > 0 {
		y, err = self.draw_variable_fine_tune(sz, y, preview)
	} else {
		y, err = self.draw_family_style_select(sz, y)
	}
	if err != nil {
		return err
	}

	lp.MoveCursorTo(1, y+2)
	self.handler.graphics_manager.display_image(0, preview.Path, key.width, key.height)
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

func (self *face_panel) get() string {
	switch self.which {
	case "font_family":
		return self.settings.font_family
	case "bold_font":
		return self.settings.bold_font
	case "italic_font":
		return self.settings.italic_font
	case "bold_italic_font":
		return self.settings.bold_italic_font
	}
	panic(fmt.Sprintf("Unknown self.which value: %s", self.which))
}

func (self *face_panel) set(setting string) {
	switch self.which {
	case "font_family":
		self.settings.font_family = setting
	case "bold_font":
		self.settings.bold_font = setting
	case "italic_font":
		self.settings.italic_font = setting
	case "bold_italic_font":
		self.settings.bold_italic_font = setting
	}
}

func (self *face_panel) on_click(id string) (err error) {
	scheme, val, _ := strings.Cut(id, ":")
	switch scheme {
	case "style":
		self.set(fmt.Sprintf(`family="%s" style="%s"`, self.family, val))
	}
	return self.handler.draw_screen()
}

func (self *face_panel) on_key_event(event *loop.KeyEvent) (err error) {
	if event.MatchesPressOrRepeat("esc") {
		event.Handled = true
		self.handler.current_pane = &self.handler.faces
		return self.handler.draw_screen()
	} else if event.MatchesPressOrRepeat("enter") {
		event.Handled = true
		self.handler.current_pane = &self.handler.faces
		self.handler.faces.settings = self.settings
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
