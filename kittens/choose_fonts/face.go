package choose_fonts

import (
	"fmt"
	"maps"
	"math"
	"slices"
	"strconv"
	"strings"
	"sync"

	"github.com/kovidgoyal/kitty/tools/tui"
	"github.com/kovidgoyal/kitty/tools/tui/loop"
	"github.com/kovidgoyal/kitty/tools/utils"
	"github.com/kovidgoyal/kitty/tools/wcswidth"
)

var _ = fmt.Print

type face_panel struct {
	handler *handler

	family, which       string
	settings            faces_settings
	current_preview     *RenderedSampleTransmit
	current_preview_key faces_preview_key
	preview_cache       map[faces_preview_key]map[string]RenderedSampleTransmit
	preview_cache_mutex sync.Mutex
}

// Create a new FontSpec that keeps features and axis values and named styles
// same as the current setting. Names are all reset apart from style name.
func (self *face_panel) new_font_spec() (*FontSpec, error) {
	fs, err := NewFontSpec(self.get(), self.current_preview.Features)
	if err != nil {
		return nil, err
	}
	if fs.system.val == "auto" {
		if fs, err = NewFontSpec(self.current_preview.Spec, self.current_preview.Features); err != nil {
			return nil, err
		}
	}
	// reset these selectors as we will be using some style/axis based selector instead
	fs.family = settable_string{self.family, true}
	fs.postscript_name = settable_string{}
	fs.full_name = settable_string{}
	if len(self.current_preview.Variable_data.Axes) > 0 {
		fs.variable_name = settable_string{self.current_preview.Variable_data.Variations_postscript_name_prefix, true}
	} else {
		fs.variable_name = settable_string{}
	}
	return &fs, nil
}

func (self *face_panel) set_variable_spec(named_style string, axis_overrides map[string]float64) error {
	fs, err := self.new_font_spec()
	if err != nil {
		return err
	}

	if axis_overrides != nil {
		axis_values := self.current_preview.current_axis_values()
		maps.Copy(axis_values, axis_overrides)
		fs.axes = axis_values
		fs.style = settable_string{"", false}
	} else if named_style != "" {
		fs.style = settable_string{named_style, true}
		fs.axes = nil
	}
	self.set(fs.String())
	return nil
}

func (self *face_panel) set_style(named_style string) error {
	fs, err := self.new_font_spec()
	if err != nil {
		return err
	}
	fs.style = settable_string{named_style, true}
	self.set(fs.String())
	return nil
}

func (self *face_panel) render_lines(start_y int, lines ...string) (y int) {
	sz, _ := self.handler.lp.ScreenSize()
	_, y, str := self.handler.render_lines.InRectangle(lines, 0, start_y, int(sz.WidthCells), int(sz.HeightCells)-y, &self.handler.mouse_state, self.on_click)
	self.handler.lp.QueueWriteString(str)
	return
}

const current_val_style = "fg=cyan bold"
const control_name_style = "fg=yellow bright bold"

func (self *face_panel) draw_axis(sz loop.ScreenSize, y int, ax VariableAxis, axis_value float64) int {
	lp := self.handler.lp
	buf := strings.Builder{}
	buf.WriteString(fmt.Sprintf("%s: ", lp.SprintStyled(control_name_style, utils.IfElse(ax.Strid != "", ax.Strid, ax.Tag))))
	num_of_cells := int(sz.WidthCells) - wcswidth.Stringwidth(buf.String())
	if num_of_cells < 5 {
		return y
	}
	frac := (min(axis_value, ax.Maximum) - ax.Minimum) / (ax.Maximum - ax.Minimum)
	current_cell := int(math.Floor(frac * float64(num_of_cells-1)))
	for i := 0; i < num_of_cells; i++ {
		buf.WriteString(utils.IfElse(i == current_cell, lp.SprintStyled(current_val_style, `⬤`),
			tui.InternalHyperlink("•", fmt.Sprintf("axis:%d/%d:%s", i, num_of_cells-1, ax.Tag))))
	}
	return self.render_lines(y, buf.String())
}

func is_current_named_style(style_group_name, style_name string, vd VariableData, ns NamedStyle) bool {
	for _, dax := range vd.Design_axes {
		if dax.Name == style_group_name {
			if val, found := ns.Axis_values[dax.Tag]; found {
				for _, v := range dax.Values {
					if v.Value == val {
						return v.Name == style_name
					}
				}
			}
			break
		}
	}
	return false
}

func (self *face_panel) draw_variable_fine_tune(sz loop.ScreenSize, start_y int, preview RenderedSampleTransmit) (y int, err error) {
	s := styles_for_variable_data(preview.Variable_data)
	lines := []string{}
	lp := self.handler.lp
	for _, sg := range s.style_groups {
		if len(sg.styles) < 2 {
			continue
		}
		formatted := make([]string, len(sg.styles))
		for i, style_name := range sg.styles {
			if is_current_named_style(sg.name, style_name, preview.Variable_data, preview.Variable_named_style) {
				formatted[i] = self.handler.lp.SprintStyled(current_val_style, style_name)
			} else {
				formatted[i] = tui.InternalHyperlink(style_name, "variable_style:"+style_name)
			}
		}
		line := lp.SprintStyled(control_name_style, sg.name) + ": " + strings.Join(formatted, ", ")
		lines = append(lines, line)
	}
	y = self.render_lines(start_y, lines...)
	sub_title := "Fine tune the appearance by clicking in the variable axes below:"
	axis_values := self.current_preview.current_axis_values()
	for _, ax := range self.current_preview.Variable_data.Axes {
		if ax.Hidden {
			continue
		}
		if sub_title != "" {
			y = self.render_lines(y+1, sub_title, "")
			sub_title = ``
		}
		y = self.draw_axis(sz, y, ax, axis_values[ax.Tag])
	}
	return y, nil
}

func (self *face_panel) draw_family_style_select(_ loop.ScreenSize, start_y int, preview RenderedSampleTransmit) (y int, err error) {
	lp := self.handler.lp
	s := styles_in_family(self.family, self.handler.listing.fonts[self.family])
	lines := []string{}
	for _, sg := range s.style_groups {
		formatted := make([]string, len(sg.styles))
		for i, style_name := range sg.styles {
			if style_name == preview.Style {
				formatted[i] = lp.SprintStyled(current_val_style, style_name)
			} else {
				formatted[i] = tui.InternalHyperlink(style_name, "style:"+style_name)
			}
		}
		line := lp.SprintStyled(control_name_style, sg.name) + ": " + strings.Join(formatted, ", ")
		lines = append(lines, line)
	}
	y = self.render_lines(start_y, lines...)
	return y, nil
}

func (self *face_panel) draw_font_features(_ loop.ScreenSize, start_y int, preview RenderedSampleTransmit) (y int, err error) {
	lp := self.handler.lp
	y = start_y
	if len(preview.Features) == 0 {
		return
	}
	formatted := make([]string, 0, len(preview.Features))
	sort_keys := make(map[string]string)
	for feat_tag, data := range preview.Features {
		var text, sort_key string

		if preview.Applied_features[feat_tag] != "" {
			text = preview.Applied_features[feat_tag]
			sort_key = text
			if sort_key[0] == '-' || sort_key[1] == '+' {
				sort_key = sort_key[1:]
			}
			text = strings.Replace(text, "+", lp.SprintStyled("fg=green", "+"), 1)
			text = strings.Replace(text, "-", lp.SprintStyled("fg=red", "-"), 1)
			text = strings.Replace(text, "=", lp.SprintStyled("fg=cyan", "="), 1)
			if data.Name != "" {
				text = data.Name + ": " + text
				sort_key = data.Name
			}
		} else {
			if data.Name != "" {
				text = data.Name
				sort_key = data.Name + ": " + text
			} else {
				text = feat_tag
				sort_key = text
			}
			text = lp.SprintStyled("dim", text)
		}
		f := tui.InternalHyperlink(text, "feature:"+feat_tag)
		sort_keys[f] = strings.ToLower(sort_key)
		formatted = append(formatted, f)
	}
	utils.StableSortWithKey(formatted, func(a string) string { return sort_keys[a] })
	line := lp.SprintStyled(control_name_style, `Features`) + ": " + strings.Join(formatted, ", ")
	y = self.render_lines(start_y, ``, line)
	return
}

func (self *handler) draw_preview_header(x int) {
	sz, _ := self.lp.ScreenSize()
	width := int(sz.WidthCells) - x
	p := center_string(self.lp.SprintStyled("italic", " preview "), width, "─")
	self.lp.QueueWriteString(self.lp.SprintStyled("dim", p))
}

func (self *face_panel) render_preview(key faces_preview_key) {
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
	y := self.render_lines(2, lines...)

	num_lines_per_font := (int(sz.HeightCells) - y - 1) - 2
	num_lines := max(1, num_lines_per_font)
	key := faces_preview_key{settings: self.settings, width: int(sz.WidthCells * sz.CellWidth), height: int(sz.CellHeight) * num_lines}
	self.current_preview_key = key
	self.preview_cache_mutex.Lock()
	defer self.preview_cache_mutex.Unlock()
	previews, found := self.preview_cache[key]
	if !found {
		self.preview_cache[key] = make(map[string]RenderedSampleTransmit)
		go func() {
			self.render_preview(key)
			self.handler.lp.WakeupMainThread()
		}()
		return
	}
	if len(previews) < 4 {
		return
	}
	preview := previews[self.which]
	self.current_preview = &preview
	if len(preview.Variable_data.Axes) > 0 {
		y, err = self.draw_variable_fine_tune(sz, y, preview)
	} else {
		y, err = self.draw_family_style_select(sz, y, preview)
	}
	if err != nil {
		return err
	}
	if y, err = self.draw_font_features(sz, y, preview); err != nil {
		return err
	}

	num_lines = int(math.Ceil(float64(preview.Canvas_height) / float64(sz.CellHeight)))
	if int(sz.HeightCells)-y >= num_lines+2 {
		y++
		lp.MoveCursorTo(1, y+1)
		self.handler.draw_preview_header(0)
		y++
		lp.MoveCursorTo(1, y+1)
		self.handler.graphics_manager.display_image(0, preview.Path, preview.Canvas_width, preview.Canvas_height)
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

func (self *face_panel) update_feature_in_setting(pff ParsedFontFeature) error {
	fs, err := self.new_font_spec()
	if err != nil {
		return err
	}
	found := false
	for _, f := range fs.features {
		if f.tag == pff.tag {
			f.val = pff.val
			found = true
			break
		}
	}
	if !found {
		fs.features = append(fs.features, &pff)
	}
	self.set(fs.String())
	return nil
}

func (self *face_panel) remove_feature_in_setting(tag string) error {
	fs, err := self.new_font_spec()
	if err != nil {
		return err
	}
	if len(fs.features) > 0 {
		fs.features = slices.DeleteFunc(fs.features, func(x *ParsedFontFeature) bool {
			return x.tag == tag
		})
	}
	self.set(fs.String())
	return nil
}

func (self *face_panel) change_feature_value(tag string, val uint, remove bool) error {
	if remove {
		return self.remove_feature_in_setting(tag)
	}
	pff := ParsedFontFeature{tag: tag, val: val}
	return self.update_feature_in_setting(pff)
}

func (self *face_panel) handle_click_on_feature(feat_tag string) error {
	d := self.current_preview.Features[feat_tag]
	if d.Is_index {
		var current_val uint
		for q, serialized := range self.current_preview.Applied_features {
			if q == feat_tag && serialized != "" {
				if _, num, found := strings.Cut(serialized, "="); found {
					if v, err := strconv.ParseUint(num, 10, 0); err == nil {
						current_val = uint(v)
					}
				} else {
					current_val = utils.IfElse(serialized[0] == '-', uint(0), uint(1))
				}
				return self.handler.if_pane.on_enter(self.family, self.which, self.settings, feat_tag, d, current_val)
			}
		}
		return self.handler.if_pane.on_enter(self.family, self.which, self.settings, feat_tag, d, current_val)
	} else {
		for q, serialized := range self.current_preview.Applied_features {
			if q == feat_tag && serialized != "" {
				if serialized[0] == '-' {
					return self.remove_feature_in_setting(feat_tag)
				}
				return self.update_feature_in_setting(ParsedFontFeature{tag: feat_tag, is_bool: true, val: 0})
			}
		}
		return self.update_feature_in_setting(ParsedFontFeature{tag: feat_tag, is_bool: true, val: 1})
	}
}

func (self *face_panel) on_click(id string) (err error) {
	scheme, val, _ := strings.Cut(id, ":")
	switch scheme {
	case "style":
		if err = self.set_style(val); err != nil {
			return err
		}
	case "variable_style":
		if err = self.set_variable_spec(val, nil); err != nil {
			return err
		}
	case "feature":
		if err = self.handle_click_on_feature(val); err != nil {
			return err
		}
	case "axis":
		p, tag, _ := strings.Cut(val, ":")
		num, den, _ := strings.Cut(p, "/")
		n, _ := strconv.Atoi(num)
		d, _ := strconv.Atoi(den)
		frac := float64(n) / float64(d)
		for _, ax := range self.current_preview.Variable_data.Axes {
			if ax.Tag == tag {
				axval := ax.Minimum + (ax.Maximum-ax.Minimum)*frac
				if err = self.set_variable_spec("", map[string]float64{tag: axval}); err != nil {
					return err
				}
				break
			}
		}
	}
	// Render preview synchronously to void flashing
	key := self.current_preview_key
	key.settings = self.settings
	self.preview_cache_mutex.Lock()
	previews := self.preview_cache[key]
	self.preview_cache_mutex.Unlock()
	if len(previews) < 4 {
		self.render_preview(key)
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
