// License: GPLv3 Copyright: 2023, Kovid Goyal, <kovid at kovidgoyal.net>

package themes

import (
	"fmt"
	"github.com/kovidgoyal/kitty"
	"io"
	"maps"
	"regexp"
	"slices"
	"strings"
	"time"

	"github.com/kovidgoyal/kitty/tools/config"
	"github.com/kovidgoyal/kitty/tools/themes"
	"github.com/kovidgoyal/kitty/tools/tui/loop"
	"github.com/kovidgoyal/kitty/tools/tui/readline"
	"github.com/kovidgoyal/kitty/tools/utils"
	"github.com/kovidgoyal/kitty/tools/wcswidth"
)

var _ = fmt.Print

type State int

const (
	FETCHING State = iota
	BROWSING
	SEARCHING
	ACCEPTING
)
const SEPARATOR = "║"

type CachedData struct {
	Recent   []string `json:"recent"`
	Category string   `json:"category"`
}

type fetch_data struct {
	themes *themes.Themes
	err    error
	closer io.Closer
}

var category_filters = map[string]func(*themes.Theme) bool{
	"all":   func(*themes.Theme) bool { return true },
	"dark":  func(t *themes.Theme) bool { return t.IsDark() },
	"light": func(t *themes.Theme) bool { return !t.IsDark() },
	"user":  func(t *themes.Theme) bool { return t.IsUserDefined() },
}

func recent_filter(items []string) func(*themes.Theme) bool {
	allowed := utils.NewSetWithItems(items...)
	return func(t *themes.Theme) bool {
		return allowed.Has(t.Name())
	}
}

type handler struct {
	lp          *loop.Loop
	opts        *Options
	cached_data *CachedData

	state            State
	fetch_result     chan fetch_data
	all_themes       *themes.Themes
	themes_closer    io.Closer
	themes_list      *ThemesList
	category_filters map[string]func(*themes.Theme) bool
	colors_set_once  bool
	tabs             []string
	rl               *readline.Readline
}

// fetching {{{
func (self *handler) fetch_themes() {
	r := fetch_data{}
	r.themes, r.closer, r.err = themes.LoadThemes(time.Duration(self.opts.CacheAge * float64(time.Hour*24)))
	self.lp.WakeupMainThread()
	self.fetch_result <- r
}

func (self *handler) on_fetching_key_event(ev *loop.KeyEvent) error {
	if ev.MatchesPressOrRepeat("esc") {
		self.lp.Quit(0)
		ev.Handled = true
	}
	return nil
}

func (self *handler) on_wakeup() error {
	r := <-self.fetch_result
	if r.err != nil {
		return r.err
	}
	self.state = BROWSING
	self.all_themes = r.themes
	self.themes_closer = r.closer
	self.redraw_after_category_change()
	return nil
}

func (self *handler) draw_fetching_screen() {
	self.lp.Println("Downloading themes from repository, please wait...")
}

// }}}

func (self *handler) finalize() {
	t := self.themes_closer
	if t != nil {
		t.Close()
		self.themes_closer = nil
	}
}

func (self *handler) initialize() {
	self.tabs = strings.Split("all dark light recent user", " ")
	self.rl = readline.New(self.lp, readline.RlInit{DontMarkPrompts: true, Prompt: "/"})
	self.themes_list = &ThemesList{}
	self.fetch_result = make(chan fetch_data)
	self.category_filters = make(map[string]func(*themes.Theme) bool, len(category_filters)+1)
	maps.Copy(self.category_filters, category_filters)
	self.category_filters["recent"] = recent_filter(self.cached_data.Recent)
	go self.fetch_themes()
	self.draw_screen()
}

func (self *handler) enforce_cursor_state() {
	self.lp.SetCursorVisible(self.state == FETCHING)
}

func (self *handler) draw_screen() {
	self.lp.StartAtomicUpdate()
	defer self.lp.EndAtomicUpdate()
	self.lp.ClearScreen()
	self.enforce_cursor_state()
	switch self.state {
	case FETCHING:
		self.draw_fetching_screen()
	case BROWSING, SEARCHING:
		self.draw_browsing_screen()
	case ACCEPTING:
		self.draw_accepting_screen()
	}
}

func (self *handler) current_category() string {
	ans := self.cached_data.Category
	if self.category_filters[ans] == nil {
		ans = "all"
	}
	return ans
}

func (self *handler) set_current_category(category string) {
	if self.category_filters[category] == nil {
		category = "all"
	}
	self.cached_data.Category = category
}

func ReadKittyColorSettings() map[string]string {
	settings := make(map[string]string, 512)
	handle_line := func(key, val string) error {
		if themes.AllColorSettingNames[key] {
			settings[key] = val
		}
		return nil
	}
	config.ReadKittyConfig(handle_line)
	return settings
}

func (self *handler) set_colors_to_current_theme() bool {
	if self.themes_list == nil && self.colors_set_once {
		return false
	}
	self.colors_set_once = true
	if self.themes_list != nil {
		t := self.themes_list.CurrentTheme()
		if t != nil {
			raw, err := t.AsEscapeCodes()
			if err == nil {
				self.lp.QueueWriteString(raw)
				return true
			}
		}
	}
	self.lp.QueueWriteString(themes.ColorSettingsAsEscapeCodes(ReadKittyColorSettings()))
	return true
}

func (self *handler) redraw_after_category_change() {
	self.themes_list.UpdateThemes(self.all_themes.Filtered(self.category_filters[self.current_category()]))
	self.set_colors_to_current_theme()
	self.draw_screen()
}

func (self *handler) on_key_event(ev *loop.KeyEvent) error {
	switch self.state {
	case FETCHING:
		return self.on_fetching_key_event(ev)
	case BROWSING:
		return self.on_browsing_key_event(ev)
	case SEARCHING:
		return self.on_searching_key_event(ev)
	case ACCEPTING:
		return self.on_accepting_key_event(ev)
	}
	return nil
}

// browsing ... {{{

func (self *handler) next_category(delta int) {
	idx := slices.Index(self.tabs, self.current_category()) + delta + len(self.tabs)
	self.set_current_category(self.tabs[idx%len(self.tabs)])
	self.redraw_after_category_change()
}

func (self *handler) next(delta int, allow_wrapping bool) {
	if self.themes_list.Next(delta, allow_wrapping) {
		self.set_colors_to_current_theme()
		self.draw_screen()
	} else {
		self.lp.Beep()
	}
}

func (self *handler) on_browsing_key_event(ev *loop.KeyEvent) error {
	if ev.MatchesPressOrRepeat("esc") || ev.MatchesCaseInsensitiveTextOrKey("q") {
		self.lp.Quit(0)
		ev.Handled = true
		return nil
	}
	for _, cat := range self.tabs {
		if ev.MatchesPressOrRepeat(cat[0:1]) || ev.MatchesPressOrRepeat("alt+"+cat[0:1]) || ev.MatchesCaseInsensitiveTextOrKey(cat[0:1]) {
			ev.Handled = true
			if cat != self.current_category() {
				self.set_current_category(cat)
				self.redraw_after_category_change()
				return nil
			}
		}
	}
	if ev.MatchesPressOrRepeat("left") || ev.MatchesPressOrRepeat("shift+tab") {
		self.next_category(-1)
		ev.Handled = true
		return nil
	}
	if ev.MatchesPressOrRepeat("right") || ev.MatchesPressOrRepeat("tab") {
		self.next_category(1)
		ev.Handled = true
		return nil
	}
	if ev.MatchesCaseInsensitiveTextOrKey("j") || ev.MatchesPressOrRepeat("down") {
		self.next(1, true)
		ev.Handled = true
		return nil
	}
	if ev.MatchesCaseInsensitiveTextOrKey("k") || ev.MatchesPressOrRepeat("up") {
		self.next(-1, true)
		ev.Handled = true
		return nil
	}
	if ev.MatchesPressOrRepeat("page_down") {
		ev.Handled = true
		sz, err := self.lp.ScreenSize()
		if err == nil {
			self.next(int(sz.HeightCells)-3, false)
		}
		return nil
	}
	if ev.MatchesPressOrRepeat("page_up") {
		ev.Handled = true
		sz, err := self.lp.ScreenSize()
		if err == nil {
			self.next(3-int(sz.HeightCells), false)
		}
		return nil
	}
	if ev.MatchesCaseInsensitiveTextOrKey("s") || ev.MatchesCaseInsensitiveTextOrKey("/") {
		ev.Handled = true
		self.start_search()
		return nil
	}
	if ev.MatchesCaseInsensitiveTextOrKey("c") || ev.MatchesPressOrRepeat("enter") {
		ev.Handled = true
		if self.themes_list == nil || self.themes_list.Len() == 0 {
			self.lp.Beep()
		} else {
			self.state = ACCEPTING
			self.draw_screen()
		}
	}
	return nil
}

func (self *handler) start_search() {
	self.state = SEARCHING
	self.rl.SetText(self.themes_list.current_search)
	self.draw_screen()
}

func (self *handler) draw_browsing_screen() {
	self.draw_tab_bar()
	sz, err := self.lp.ScreenSize()
	if err != nil {
		return
	}
	num_rows := int(sz.HeightCells) - 2
	mw := self.themes_list.max_width + 1
	green_fg, _, _ := strings.Cut(self.lp.SprintStyled("fg=green", "|"), "|")
	for _, l := range self.themes_list.Lines(num_rows) {
		line := l.text
		if l.is_current {
			line = strings.ReplaceAll(line, themes.MARK_AFTER, green_fg)
			self.lp.PrintStyled("fg=green", ">")
			self.lp.PrintStyled("fg=green bold", line)
		} else {
			self.lp.PrintStyled("fg=green", " ")
			self.lp.QueueWriteString(line)
		}
		self.lp.MoveCursorHorizontally(mw - l.width)
		self.lp.Println(SEPARATOR)
		num_rows--
	}
	for ; num_rows > 0; num_rows-- {
		self.lp.MoveCursorHorizontally(mw + 1)
		self.lp.Println(SEPARATOR)
	}
	if self.themes_list != nil && self.themes_list.Len() > 0 {
		self.draw_theme_demo()
	}
	if self.state == BROWSING {
		self.draw_bottom_bar()
	} else {
		self.draw_search_bar()
	}
}

func (self *handler) draw_bottom_bar() {
	sz, err := self.lp.ScreenSize()
	if err != nil {
		return
	}
	self.lp.MoveCursorTo(1, int(sz.HeightCells))
	self.lp.PrintStyled("reverse", strings.Repeat(" ", int(sz.WidthCells)))
	self.lp.QueueWriteString("\r")

	draw_tab := func(t, sc string) {
		text := self.mark_shortcut(utils.Capitalize(t), sc)
		self.lp.PrintStyled("reverse", " "+text+" ")
	}
	draw_tab("search (/)", "s")
	draw_tab("accept (⏎)", "c")
	self.lp.QueueWriteString("\x1b[m")
}

func (self *handler) draw_search_bar() {
	sz, err := self.lp.ScreenSize()
	if err != nil {
		return
	}
	self.lp.MoveCursorTo(1, int(sz.HeightCells))
	self.lp.ClearToEndOfLine()
	self.rl.RedrawNonAtomic()
}

func (self *handler) mark_shortcut(text, acc string) string {
	acc_idx := strings.Index(strings.ToLower(text), strings.ToLower(acc))
	return text[:acc_idx] + self.lp.SprintStyled("underline bold", text[acc_idx:acc_idx+1]) + text[acc_idx+1:]
}

func (self *handler) draw_tab_bar() {
	sz, err := self.lp.ScreenSize()
	if err != nil {
		return
	}
	self.lp.PrintStyled("reverse", strings.Repeat(` `, int(sz.WidthCells)))
	self.lp.QueueWriteString("\r")
	cc := self.current_category()
	draw_tab := func(text, name, acc string) {
		is_active := name == cc
		if is_active {
			text := self.lp.SprintStyled("italic", fmt.Sprintf("%s #%d", text, self.themes_list.Len()))
			self.lp.Printf(" %s ", text)
		} else {
			text = self.mark_shortcut(text, acc)
			self.lp.PrintStyled("reverse", " "+text+" ")
		}
	}
	for _, title := range self.tabs {
		draw_tab(utils.Capitalize(title), title, string([]rune(title)[0]))
	}
	self.lp.Println("\x1b[m")
}

func center_string(x string, width int) string {
	l := wcswidth.Stringwidth(x)
	spaces := int(float64(width-l) / 2)
	return strings.Repeat(" ", utils.Max(0, spaces)) + x + strings.Repeat(" ", utils.Max(0, width-(spaces+l)))
}

func (self *handler) draw_theme_demo() {
	ssz, err := self.lp.ScreenSize()
	if err != nil {
		return
	}
	theme := self.themes_list.CurrentTheme()
	if theme == nil {
		return
	}
	xstart := self.themes_list.max_width + 3
	sz := int(ssz.WidthCells) - xstart
	if sz < 20 {
		return
	}
	sz--
	y := 0
	colors := strings.Split(`black red green yellow blue magenta cyan white`, ` `)
	trunc := sz/8 - 1
	pat := regexp.MustCompile(`\s+`)

	next_line := func() {
		self.lp.QueueWriteString("\r")
		y++
		self.lp.MoveCursorTo(xstart, y+1)
		self.lp.QueueWriteString(SEPARATOR + " ")
	}

	write_para := func(text string) {
		text = pat.ReplaceAllLiteralString(text, " ")
		for text != "" {
			t, sp := wcswidth.TruncateToVisualLengthWithWidth(text, sz)
			self.lp.QueueWriteString(t)
			next_line()
			text = text[sp:]
		}
	}

	write_colors := func(bg string) {
		for _, intense := range []bool{false, true} {
			buf := strings.Builder{}
			buf.Grow(1024)
			for _, c := range colors {
				s := c
				if intense {
					s = "bright-" + s
				}
				sTrunc := s
				if len(sTrunc) > trunc {
					sTrunc = sTrunc[:trunc]
				}
				buf.WriteString(self.lp.SprintStyled("fg="+s, sTrunc))
				buf.WriteString(" ")
			}
			text := strings.TrimSpace(buf.String())
			if bg == "" {
				self.lp.QueueWriteString(text)
			} else {
				s := bg
				if intense {
					s = "bright-" + s
				}
				self.lp.PrintStyled("bg="+s, text)
			}
			next_line()
		}
		next_line()
	}
	self.lp.MoveCursorTo(1, 1)
	next_line()
	self.lp.PrintStyled("fg=green bold", center_string(theme.Name(), sz))
	next_line()
	if theme.Author() != "" {
		self.lp.PrintStyled("italic", center_string(theme.Author(), sz))
		next_line()
	}
	if theme.Blurb() != "" {
		next_line()
		write_para(theme.Blurb())
		next_line()
	}
	write_colors("")
	for _, bg := range colors {
		write_colors(bg)
	}
}

// }}}

// accepting {{{

func (self *handler) on_accepting_key_event(ev *loop.KeyEvent) error {
	if ev.MatchesCaseInsensitiveTextOrKey("q") || ev.MatchesPressOrRepeat("esc") || ev.MatchesPressOrRepeat("shift+q") {
		ev.Handled = true
		self.lp.Quit(0)
		return nil
	}
	if ev.MatchesCaseInsensitiveTextOrKey("a") || ev.MatchesPressOrRepeat("shift+a") {
		ev.Handled = true
		self.state = BROWSING
		self.draw_screen()
		return nil
	}
	if ev.MatchesCaseInsensitiveTextOrKey("p") || ev.MatchesPressOrRepeat("shift+p") {
		ev.Handled = true
		self.themes_list.CurrentTheme().SaveInDir(utils.ConfigDir())
		self.update_recent()
		self.lp.Quit(0)
		return nil
	}
	if ev.MatchesCaseInsensitiveTextOrKey("m") || ev.MatchesPressOrRepeat("shift+m") {
		ev.Handled = true
		self.themes_list.CurrentTheme().SaveInConf(utils.ConfigDir(), self.opts.ReloadIn, self.opts.ConfigFileName)
		self.update_recent()
		self.lp.Quit(0)
		return nil
	}

	scheme := func(name string) error {
		ev.Handled = true
		self.themes_list.CurrentTheme().SaveInFile(utils.ConfigDir(), name)
		self.update_recent()
		self.lp.Quit(0)
		return nil

	}
	if ev.MatchesCaseInsensitiveTextOrKey("d") || ev.MatchesPressOrRepeat("shift+d") {
		return scheme(kitty.DarkThemeFileName)
	}
	if ev.MatchesCaseInsensitiveTextOrKey("l") || ev.MatchesPressOrRepeat("shift+l") {
		return scheme(kitty.LightThemeFileName)
	}
	if ev.MatchesCaseInsensitiveTextOrKey("n") || ev.MatchesPressOrRepeat("shift+n") {
		return scheme(kitty.NoPreferenceThemeFileName)
	}
	return nil
}

func (self *handler) update_recent() {
	if self.themes_list != nil {
		recent := slices.Clone(self.cached_data.Recent)
		name := self.themes_list.CurrentTheme().Name()
		recent = utils.Remove(recent, name)
		recent = append([]string{name}, recent...)
		if len(recent) > 20 {
			recent = recent[:20]
		}
		self.cached_data.Recent = recent
	}
}

func (self *handler) draw_accepting_screen() {
	name := self.themes_list.CurrentTheme().Name()
	name = self.lp.SprintStyled("fg=green bold", name)
	kc := self.lp.SprintStyled("italic", self.opts.ConfigFileName)

	ac := func(x string) string {
		return self.lp.SprintStyled("fg=red", x)
	}
	self.lp.AllowLineWrapping(true)
	defer self.lp.AllowLineWrapping(false)
	self.lp.Printf(`You have chosen the %s theme`, name)
	self.lp.Println()
	self.lp.Println()
	self.lp.Println(`What would you like to do?`)
	self.lp.Println()
	self.lp.Printf(` %sodify %s to load %s`, ac("M"), kc, name)
	self.lp.Println()
	self.lp.Println()
	self.lp.Printf(` %slace the theme file in %s but do not modify %s`, ac("P"), utils.ConfigDir(), kc)
	self.lp.Println()
	self.lp.Println()
	self.lp.Printf(` Save as colors to use when the OS switches to:`)
	self.lp.Println()
	self.lp.Printf(`   %sark mode`, ac("D"))
	self.lp.Println()
	self.lp.Printf(`   %sight mode`, ac("L"))
	self.lp.Println()
	self.lp.Printf(`   %so preference mode`, ac("N"))
	self.lp.Println()
	self.lp.Println()
	self.lp.Printf(` %sbort and return to list of themes`, ac("A"))
	self.lp.Println()
	self.lp.Println()
	self.lp.Printf(` %suit`, ac("Q"))
	self.lp.Println()
}

// }}}

// searching {{{

func (self *handler) update_search() {
	text := self.rl.AllText()
	if self.themes_list.UpdateSearch(text) {
		self.set_colors_to_current_theme()
		self.draw_screen()
	} else {
		self.draw_search_bar()
	}
}

func (self *handler) on_text(text string, a, b bool) error {
	if self.state == SEARCHING {
		err := self.rl.OnText(text, a, b)
		if err != nil {
			return err
		}
		self.update_search()
	}
	return nil
}

func (self *handler) on_searching_key_event(ev *loop.KeyEvent) error {
	if ev.MatchesPressOrRepeat("enter") {
		ev.Handled = true
		self.state = BROWSING
		self.draw_bottom_bar()
		return nil
	}
	if ev.MatchesPressOrRepeat("esc") {
		ev.Handled = true
		self.state = BROWSING
		self.themes_list.UpdateSearch("")
		self.set_colors_to_current_theme()
		self.draw_screen()
		return nil
	}
	err := self.rl.OnKeyEvent(ev)
	if err != nil {
		return err
	}
	if ev.Handled {
		self.update_search()
	}
	return nil
}

// }}}
