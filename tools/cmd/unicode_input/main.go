// License: GPLv3 Copyright: 2023, Kovid Goyal, <kovid at kovidgoyal.net>

package unicode_input

import (
	"fmt"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"unicode"

	"kitty/tools/cli"
	"kitty/tools/tui"
	"kitty/tools/tui/loop"
	"kitty/tools/tui/readline"
	"kitty/tools/unicode_names"
	"kitty/tools/utils"
	"kitty/tools/utils/style"
	"kitty/tools/wcswidth"

	"golang.org/x/exp/slices"
)

var _ = fmt.Print

const INDEX_CHAR string = "."
const INDEX_BASE = 36
const InvalidChar rune = unicode.MaxRune + 1
const default_set_of_symbols string = `
‘’“”‹›«»‚„ 😀😛😇😈😉😍😎😮👍👎 —–§¶†‡©®™ →⇒•·°±−×÷¼½½¾
…µ¢£€¿¡¨´¸ˆ˜ ÀÁÂÃÄÅÆÇÈÉÊË ÌÍÎÏÐÑÒÓÔÕÖØ ŒŠÙÚÛÜÝŸÞßàá âãäåæçèéêëìí
îïðñòóôõöøœš ùúûüýÿþªºαΩ∞
`

var DEFAULT_SET []rune
var EMOTICONS_SET []rune

const DEFAULT_MODE string = "HEX"

func build_sets() {
	DEFAULT_SET = make([]rune, 0, len(default_set_of_symbols))
	for _, ch := range default_set_of_symbols {
		if !unicode.IsSpace(ch) {
			DEFAULT_SET = append(DEFAULT_SET, ch)
		}
	}
	EMOTICONS_SET = make([]rune, 0, 0x1f64f-0x1f600+1)
	for i := 0x1f600; i <= 0x1f64f; i++ {
		DEFAULT_SET = append(DEFAULT_SET, rune(i))
	}
}

func codepoint_ok(code rune) bool {
	return !(code <= 32 || code == 127 || (128 <= code && code <= 159) || (0xd800 <= code && code <= 0xdbff) || (0xDC00 <= code && code <= 0xDFFF) || code > unicode.MaxRune)
}

func parse_favorites(raw string) (ans []rune) {
	ans = make([]rune, 0, 128)
	for _, line := range utils.Splitlines(raw) {
		line = strings.TrimSpace(line)
		if len(line) == 0 || strings.HasPrefix(line, "#") {
			continue
		}
		idx := strings.Index(line, "#")
		if idx > -1 {
			line = line[:idx]
		}
		code_text, _, _ := strings.Cut(line, " ")
		code, err := strconv.ParseUint(code_text, 16, 32)
		if err == nil && codepoint_ok(rune(code)) {
			ans = append(ans, rune(code))
		}
	}
	return
}

func serialize_favorites(favs []rune) string {
	b := strings.Builder{}
	b.Grow(8192)
	b.WriteString(`# Favorite characters for unicode input
# Enter the hex code for each favorite character on a new line. Blank lines are
# ignored and anything after a # is considered a comment.

`)
	for _, ch := range favs {
		b.WriteString(fmt.Sprintf("%x # %s %s", ch, string(ch), unicode_names.NameForCodePoint(ch)))
	}

	return b.String()
}

var loaded_favorites []rune

func favorites_path() string {
	return filepath.Join(utils.ConfigDir(), "unicode-input-favorites.conf")
}

func load_favorites(refresh bool) []rune {
	if refresh || loaded_favorites == nil {
		raw, err := os.ReadFile(favorites_path())
		if err == nil {
			loaded_favorites = parse_favorites(utils.UnsafeBytesToString(raw))
		} else {
			loaded_favorites = parse_favorites("")
		}
	}
	return loaded_favorites
}

type CachedData struct {
	Recent []rune `json:"recent,omitempty"`
	Mode   string `json:"mode,omitempty"`
}

var cached_data *CachedData

type Mode int

const (
	HEX Mode = iota
	NAME
	EMOTICONS
	FAVORITES
)

type ModeData struct {
	mode  Mode
	key   string
	title string
}

var all_modes [4]ModeData

type checkpoints_key struct {
	mode       Mode
	text       string
	codepoints []rune
}

func (self *checkpoints_key) clear() {
	*self = checkpoints_key{}
}

func (self *checkpoints_key) is_equal(other checkpoints_key) bool {
	return self.mode == other.mode && self.text == other.text && slices.Equal(self.codepoints, other.codepoints)
}

type handler struct {
	mode            Mode
	recent          []rune
	current_char    rune
	err             error
	lp              *loop.Loop
	ctx             style.Context
	rl              *readline.Readline
	choice_line     string
	emoji_variation string
	checkpoints_key checkpoints_key
	table           table

	current_tab_formatter, tab_bar_formatter, chosen_formatter, chosen_name_formatter, dim_formatter func(...any) string
}

func (self *handler) initialize() {
	self.lp.AllowLineWrapping(false)
	self.table.initialize(self.emoji_variation, self.ctx)
	self.lp.SetWindowTitle("Unicode input")
	self.ctx.AllowEscapeCodes = true
	self.current_char = InvalidChar
	self.current_tab_formatter = self.ctx.SprintFunc("reverse=false bold=true")
	self.tab_bar_formatter = self.ctx.SprintFunc("reverse=true")
	self.chosen_formatter = self.ctx.SprintFunc("fg=green")
	self.chosen_name_formatter = self.ctx.SprintFunc("italic=true dim=true")
	self.dim_formatter = self.ctx.SprintFunc("dim=true")
	self.rl = readline.New(self.lp, readline.RlInit{Prompt: "> "})
	self.rl.Start()
	self.draw_screen()
}

func (self *handler) finalize() string {
	self.rl.End()
	self.rl.Shutdown()
	return ""
}

func (self *handler) resolved_char() string {
	if self.current_char == InvalidChar {
		return ""
	}
	return resolved_char(self.current_char, self.emoji_variation)
}

func is_index(word string) bool {
	if !strings.HasSuffix(word, INDEX_CHAR) {
		return false
	}
	word = strings.TrimLeft(word, INDEX_CHAR)
	_, err := strconv.ParseUint(word, 36, 32)
	return err == nil
}

func (self *handler) update_codepoints() {
	var codepoints []rune
	var index_word int
	var q checkpoints_key
	q.mode = self.mode
	switch self.mode {
	case HEX:
		codepoints = self.recent
	case EMOTICONS:
		codepoints = EMOTICONS_SET
	case FAVORITES:
		codepoints = load_favorites(false)
		q.codepoints = codepoints
	case NAME:
		q.text = self.rl.AllText()
		if !q.is_equal(self.checkpoints_key) {
			words := strings.Split(q.text, " ")
			words = utils.RemoveAll(words, INDEX_CHAR)
			words = utils.Filter(words, is_index)
			if len(words) > 0 {
				iw := strings.TrimLeft(words[0], INDEX_CHAR)
				words = words[1:]
				n, err := strconv.ParseUint(iw, INDEX_BASE, 32)
				if err == nil {
					index_word = int(n)
				}
			}
			codepoints = unicode_names.CodePointsForQuery(strings.Join(words, " "))
		}
	}
	if !q.is_equal(self.checkpoints_key) {
		self.checkpoints_key = q
		self.table.set_codepoints(codepoints, self.mode, index_word)
	}
}

func (self *handler) update_current_char() {
	self.update_codepoints()
	self.current_char = InvalidChar
	text := self.rl.AllText()
	switch self.mode {
	case HEX:
		if strings.HasPrefix(text, INDEX_CHAR) {
			if len(text) > 1 {
				self.current_char = self.table.codepoint_at_hint(text[1:])
			}
		} else if len(text) > 0 {
			code, err := strconv.ParseUint(text, 16, 32)
			if err == nil && code <= unicode.MaxRune {
				self.current_char = rune(code)
			}
		}
	case NAME:
		cc := self.table.current_codepoint()
		if cc > 0 && cc <= unicode.MaxRune {
			self.current_char = rune(cc)
		}
	default:
		if len(text) > 0 {
			self.current_char = self.table.codepoint_at_hint(strings.TrimLeft(text, INDEX_CHAR))
		}
	}
	if !codepoint_ok(self.current_char) {
		self.current_char = InvalidChar
	}
}

func (self *handler) update_prompt() {
	self.update_current_char()
	ch := "??"
	color := "red"
	self.choice_line = ""
	if self.current_char != InvalidChar {
		ch, color = self.resolved_char(), "green"
		self.choice_line = fmt.Sprintf(
			"Chosen: %s U+%x %s", self.chosen_formatter(ch), self.current_char,
			self.chosen_name_formatter(unicode_names.NameForCodePoint(self.current_char)))
	}
	prompt := fmt.Sprintf("%s> ", self.ctx.SprintFunc("fg="+color)(ch))
	self.rl.SetPrompt(prompt)
}

func (self *handler) draw_title_bar() {
	entries := make([]string, 0, len(all_modes))
	for _, md := range all_modes {
		entry := fmt.Sprintf(" %s (%s) ", md.title, md.key)
		if md.mode == self.mode {
			entry = self.current_tab_formatter(entry)
		}
		entries = append(entries, entry)
	}
	sz, _ := self.lp.ScreenSize()
	text := fmt.Sprintf("Search by:%s", strings.Join(entries, ""))
	extra := int(sz.WidthCells) - wcswidth.Stringwidth(text)
	if extra > 0 {
		text += strings.Repeat(" ", extra)
	}
	self.lp.Println(self.tab_bar_formatter(text))
}

func (self *handler) draw_screen() {
	self.lp.StartAtomicUpdate()
	defer self.lp.EndAtomicUpdate()
	self.lp.ClearScreen()
	self.draw_title_bar()

	y := 1
	writeln := func(text ...any) {
		self.lp.Println(text...)
		y += 1
	}
	switch self.mode {
	case NAME:
		writeln("Enter words from the name of the character")
	case HEX:
		writeln("Enter the hex code for the character")
	default:
		writeln("Enter the index for the character you want from the list below")
	}
	self.rl.RedrawNonAtomic()
	self.lp.SaveCursorPosition()
	defer self.lp.RestoreCursorPosition()
	writeln()
	writeln(self.choice_line)
	switch self.mode {
	case HEX:
		writeln(self.dim_formatter(fmt.Sprintf("Type %s followed by the index for the recent entries below", INDEX_CHAR)))
	case NAME:
		writeln(self.dim_formatter(fmt.Sprintf("Use Tab or arrow keys to choose a character. Type space and %s to select by index", INDEX_CHAR)))
	case FAVORITES:
		writeln(self.dim_formatter("Press F12 to edit the list of favorites"))
	}
	sz, _ := self.lp.ScreenSize()
	q := self.table.layout(int(sz.HeightCells)-y, int(sz.WidthCells))
	if q != "" {
		self.lp.QueueWriteString(q)
	}
}

func (self *handler) on_text(text string, from_key_event, in_bracketed_paste bool) error {
	err := self.rl.OnText(text, from_key_event, in_bracketed_paste)
	if err != nil {
		return err
	}
	self.refresh()
	return nil
}

func (self *handler) on_key_event(event *loop.KeyEvent) (err error) {
	// TODO: Implement rest of this
	err = self.rl.OnKeyEvent(event)
	if err != nil {
		if err == readline.ErrAcceptInput {
			self.refresh()
			self.lp.Quit(0)
			return nil
		}
		return err
	}
	if event.Handled {
		self.refresh()
	}
	return
}

func (self *handler) refresh() {
	self.update_prompt()
	self.draw_screen()
}

func run_loop(opts *Options) (lp *loop.Loop, err error) {
	output := tui.KittenOutputSerializer()
	lp, err = loop.New()
	if err != nil {
		return
	}
	cv := utils.NewCachedValues("unicode-input", &CachedData{Recent: DEFAULT_SET, Mode: DEFAULT_MODE})
	cached_data = cv.Load()
	defer cv.Save()

	h := handler{recent: cached_data.Recent, lp: lp, emoji_variation: opts.EmojiVariation}
	switch cached_data.Mode {
	case "HEX":
		h.mode = HEX
	case "NAME":
		h.mode = NAME
	case "EMOTICONS":
		h.mode = EMOTICONS
	case "FAVORITES":
		h.mode = FAVORITES
	}
	all_modes[0] = ModeData{mode: HEX, title: "Code", key: "F1"}
	all_modes[1] = ModeData{mode: NAME, title: "Name", key: "F2"}
	all_modes[2] = ModeData{mode: EMOTICONS, title: "Emoticons", key: "F3"}
	all_modes[3] = ModeData{mode: FAVORITES, title: "Favorites", key: "F4"}

	lp.OnInitialize = func() (string, error) {
		h.initialize()
		return "", nil
	}

	lp.OnResize = func(old_size, new_size loop.ScreenSize) error {
		h.refresh()
		return nil
	}

	lp.OnResumeFromStop = func() error {
		h.refresh()
		return nil
	}

	lp.OnText = h.on_text
	lp.OnFinalize = h.finalize
	lp.OnKeyEvent = h.on_key_event

	err = lp.Run()
	if err != nil {
		return
	}
	if h.err == nil {
		switch h.mode {
		case HEX:
			cached_data.Mode = "HEX"
		case NAME:
			cached_data.Mode = "NAME"
		case EMOTICONS:
			cached_data.Mode = "EMOTICONS"
		case FAVORITES:
			cached_data.Mode = "FAVORITES"
		}
		if h.current_char != InvalidChar {
			cached_data.Recent = h.recent
			idx := slices.Index(cached_data.Recent, h.current_char)
			if idx > -1 {
				cached_data.Recent = slices.Delete(cached_data.Recent, idx, idx+1)
			}
			cached_data.Recent = slices.Insert(cached_data.Recent, 0, h.current_char)[:len(DEFAULT_SET)]
			ans := h.resolved_char()
			o, err := output(ans)
			if err != nil {
				return lp, err
			}
			fmt.Println(o)
		}
	}
	err = h.err
	return
}

func main(cmd *cli.Command, o *Options, args []string) (rc int, err error) {
	go unicode_names.Initialize() // start parsing name data in the background
	build_sets()
	lp, err := run_loop(o)
	if err != nil {
		return 1, err
	}
	ds := lp.DeathSignalName()
	if ds != "" {
		fmt.Println("Killed by signal: ", ds)
		lp.KillIfSignalled()
		return 1, nil
	}
	return
}

func EntryPoint(parent *cli.Command) {
	create_cmd(parent, main)
}
