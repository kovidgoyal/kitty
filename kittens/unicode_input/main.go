// License: GPLv3 Copyright: 2023, Kovid Goyal, <kovid at kovidgoyal.net>

package unicode_input

import (
	"bytes"
	"errors"
	"fmt"
	"math"
	"os"
	"os/exec"
	"path/filepath"
	"slices"
	"strconv"
	"strings"
	"unicode"
	"unicode/utf8"

	"github.com/kovidgoyal/kitty/tools/cli"
	"github.com/kovidgoyal/kitty/tools/tty"
	"github.com/kovidgoyal/kitty/tools/tui"
	"github.com/kovidgoyal/kitty/tools/tui/loop"
	"github.com/kovidgoyal/kitty/tools/tui/readline"
	"github.com/kovidgoyal/kitty/tools/unicode_names"
	"github.com/kovidgoyal/kitty/tools/utils"
	"github.com/kovidgoyal/kitty/tools/utils/style"
	"github.com/kovidgoyal/kitty/tools/wcswidth"
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
		EMOTICONS_SET = append(EMOTICONS_SET, rune(i))
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
		code, err := strconv.ParseInt(code_text, 16, 32)
		if err == nil && code <= utf8.MaxRune && codepoint_ok(rune(code)) {
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
		b.WriteString(fmt.Sprintf("%x # %s %s\n", ch, string(ch), unicode_names.NameForCodePoint(ch)))
	}

	return b.String()
}

var loaded_favorites []rune
var favorites_loaded_from_user_config bool

func favorites_path() string {
	return filepath.Join(utils.ConfigDir(), "unicode-input-favorites.conf")
}

func load_favorites(refresh bool) []rune {
	if refresh || loaded_favorites == nil {
		raw, err := os.ReadFile(favorites_path())
		if err == nil {
			loaded_favorites = parse_favorites(utils.UnsafeBytesToString(raw))
			favorites_loaded_from_user_config = true
		} else {
			loaded_favorites = DEFAULT_SET
			favorites_loaded_from_user_config = false
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
	index_word int
}

func (self *checkpoints_key) clear() {
	*self = checkpoints_key{}
}

func (self *checkpoints_key) is_equal(other checkpoints_key) bool {
	return self.mode == other.mode && self.text == other.text && slices.Equal(self.codepoints, other.codepoints) && self.index_word == other.index_word
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
	self.ctx.AllowEscapeCodes = true
	self.checkpoints_key.index_word = -1
	self.table.initialize(self.emoji_variation, self.ctx)
	self.lp.SetWindowTitle("Unicode input")
	self.current_char = InvalidChar
	self.current_tab_formatter = self.ctx.SprintFunc("reverse=false bold=true")
	self.tab_bar_formatter = self.ctx.SprintFunc("reverse=true")
	self.chosen_formatter = self.ctx.SprintFunc("fg=green")
	self.chosen_name_formatter = self.ctx.SprintFunc("italic=true dim=true")
	self.dim_formatter = self.ctx.SprintFunc("dim=true")
	self.rl = readline.New(self.lp, readline.RlInit{Prompt: "> ", DontMarkPrompts: true})
	self.rl.Start()
	self.refresh()
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
	if !strings.HasPrefix(word, INDEX_CHAR) {
		return false
	}
	word = strings.TrimLeft(word, INDEX_CHAR)
	_, err := strconv.ParseUint(word, INDEX_BASE, 32)
	return err == nil
}

func (self *handler) update_codepoints() {
	var q checkpoints_key
	q.mode = self.mode
	q.index_word = -1
	switch self.mode {
	case HEX:
		q.codepoints = self.recent
		if len(q.codepoints) == 0 {
			q.codepoints = DEFAULT_SET
		}
	case EMOTICONS:
		q.codepoints = EMOTICONS_SET
	case FAVORITES:
		q.codepoints = load_favorites(false)
	case NAME:
		q.text = self.rl.AllText()
		if !q.is_equal(self.checkpoints_key) {
			words := strings.Split(q.text, " ")
			words = utils.RemoveAll(words, INDEX_CHAR)
			if len(words) > 1 {
				for i, w := range words {
					if i > 0 && is_index(w) {
						iw := words[i]
						words = words[:i]
						if index_word, perr := strconv.ParseInt(strings.TrimLeft(iw, INDEX_CHAR), INDEX_BASE, 0); perr == nil {
							q.index_word = int(index_word)
						}
						break
					}
				}
			}
			query := strings.Join(words, " ")
			if len(query) > 1 {
				words = words[1:]
				q.codepoints = unicode_names.CodePointsForQuery(query)
			}
		}
	}
	if !q.is_equal(self.checkpoints_key) {
		self.checkpoints_key = q
		self.table.set_codepoints(q.codepoints, self.mode, q.index_word)
	}
}

var debugprintln = tty.DebugPrintln

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
			self.chosen_name_formatter(title(unicode_names.NameForCodePoint(self.current_char))))
	}
	prompt := fmt.Sprintf("%s> ", self.ctx.SprintFunc("fg="+color)(ch))
	self.rl.SetPrompt(prompt)
}

func (self *handler) draw_title_bar() {
	self.lp.AllowLineWrapping(false)
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
	self.lp.AllowLineWrapping(false)
	self.lp.SaveCursorPosition()
	defer self.lp.RestoreCursorPosition()
	writeln()
	writeln(self.choice_line)
	sz, _ := self.lp.ScreenSize()

	write_help := func(x string) {
		lines := style.WrapTextAsLines(x, int(sz.WidthCells)-1, style.WrapOptions{})
		for _, line := range lines {
			if line != "" {
				writeln(self.dim_formatter(line))
			}
		}
	}

	switch self.mode {
	case HEX:
		write_help(fmt.Sprintf("Type %s followed by the index for the recent entries below", INDEX_CHAR))
	case NAME:
		write_help(fmt.Sprintf("Use Tab or arrow keys to choose a character. Type space and %s to select by index", INDEX_CHAR))
	case FAVORITES:
		write_help("Press F12 to edit the list of favorites")
	}
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

func (self *handler) switch_mode(mode Mode) {
	if self.mode != mode {
		self.mode = mode
		self.rl.ResetText()
		self.current_char = InvalidChar
		self.choice_line = ""
	}
}

func (self *handler) handle_hex_key_event(event *loop.KeyEvent) {
	text := self.rl.AllText()
	uval, err := strconv.ParseUint(text, 16, 32)
	new_val := -1
	if err != nil || uval > math.MaxInt {
		return
	}
	val := int(uval)
	if event.MatchesPressOrRepeat("tab") {
		new_val = val + 10
	} else if event.MatchesPressOrRepeat("up") {
		new_val = val + 1
	} else if event.MatchesPressOrRepeat("down") {
		new_val = max(32, val-1)
	}
	if new_val > -1 {
		event.Handled = true
		self.rl.SetText(fmt.Sprintf("%x", new_val))
	}
}

func (self *handler) handle_name_key_event(event *loop.KeyEvent) {
	if event.MatchesPressOrRepeat("shift+tab") || event.MatchesPressOrRepeat("left") {
		event.Handled = true
		self.table.move_current(0, -1)
	} else if event.MatchesPressOrRepeat("tab") || event.MatchesPressOrRepeat("right") {
		event.Handled = true
		self.table.move_current(0, 1)
	} else if event.MatchesPressOrRepeat("up") {
		event.Handled = true
		self.table.move_current(-1, 0)
	} else if event.MatchesPressOrRepeat("down") {
		event.Handled = true
		self.table.move_current(1, 0)
	}
}

func (self *handler) handle_emoticons_key_event(event *loop.KeyEvent) {
}

func (self *handler) handle_favorites_key_event(event *loop.KeyEvent) {
	if event.MatchesPressOrRepeat("f12") {
		event.Handled = true
		exe, err := os.Executable()
		if err != nil {
			self.err = err
			self.lp.Quit(1)
			return
		}
		fp := favorites_path()
		if len(load_favorites(false)) == 0 || !favorites_loaded_from_user_config {
			raw := serialize_favorites(load_favorites(false))
			err = os.MkdirAll(filepath.Dir(fp), 0o755)
			if err != nil {
				self.err = fmt.Errorf("Failed to create config directory to store favorites in: %w", err)
				self.lp.Quit(1)
				return
			}
			err = utils.AtomicUpdateFile(fp, bytes.NewReader(utils.UnsafeStringToBytes(raw)), 0o600)
			if err != nil {
				self.err = fmt.Errorf("Failed to write to favorites file %s with error: %w", fp, err)
				self.lp.Quit(1)
				return
			}
		}
		err = self.lp.SuspendAndRun(func() error {
			cmd := exec.Command(exe, "edit-in-kitty", "--type=overlay", fp)
			cmd.Stdin = os.Stdin
			cmd.Stdout = os.Stdout
			cmd.Stderr = os.Stderr
			err = cmd.Run()
			if err == nil {
				load_favorites(true)
			} else {
				fmt.Fprintln(os.Stderr, err)
				fmt.Fprintln(os.Stderr, "Failed to run edit-in-kitty, favorites have not been changed. Press Enter to continue.")
				var ln string
				fmt.Scanln(&ln)
			}
			return nil
		})
		if err != nil {
			self.err = err
			self.lp.Quit(1)
			return
		}
	}
}

func (self *handler) next_mode(delta int) {
	for num, md := range all_modes {
		if md.mode == self.mode {
			idx := (num + delta + len(all_modes)) % len(all_modes)
			md = all_modes[idx]
			self.switch_mode(md.mode)
			break
		}
	}
}

var ErrCanceledByUser = errors.New("Canceled by user")

func (self *handler) on_key_event(event *loop.KeyEvent) (err error) {
	if event.MatchesPressOrRepeat("esc") || event.MatchesPressOrRepeat("ctrl+c") {
		return ErrCanceledByUser
	}
	if event.MatchesPressOrRepeat("f1") || event.MatchesPressOrRepeat("ctrl+1") {
		event.Handled = true
		self.switch_mode(HEX)
	} else if event.MatchesPressOrRepeat("f2") || event.MatchesPressOrRepeat("ctrl+2") {
		event.Handled = true
		self.switch_mode(NAME)
	} else if event.MatchesPressOrRepeat("f3") || event.MatchesPressOrRepeat("ctrl+3") {
		event.Handled = true
		self.switch_mode(EMOTICONS)
	} else if event.MatchesPressOrRepeat("f4") || event.MatchesPressOrRepeat("ctrl+4") {
		event.Handled = true
		self.switch_mode(FAVORITES)
	} else if event.MatchesPressOrRepeat("ctrl+tab") || event.MatchesPressOrRepeat("ctrl+]") {
		event.Handled = true
		self.next_mode(1)
	} else if event.MatchesPressOrRepeat("ctrl+shift+tab") || event.MatchesPressOrRepeat("ctrl+[") {
		event.Handled = true
		self.next_mode(-1)
	}
	if !event.Handled {
		switch self.mode {
		case HEX:
			self.handle_hex_key_event(event)
		case NAME:
			self.handle_name_key_event(event)
		case EMOTICONS:
			self.handle_emoticons_key_event(event)
		case FAVORITES:
			self.handle_favorites_key_event(event)
		}
	}
	if !event.Handled {
		err = self.rl.OnKeyEvent(event)
		if err != nil {
			if err == readline.ErrAcceptInput {
				self.refresh()
				self.lp.Quit(0)
				return nil
			}
			return err
		}
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
	switch opts.Tab {
	case "previous":
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
	case "code":
		h.mode = HEX
	case "name":
		h.mode = NAME
	case "emoticons":
		h.mode = EMOTICONS
	case "favorites":
		h.mode = FAVORITES
	}
	all_modes[0] = ModeData{mode: HEX, title: "Code", key: "F1"}
	all_modes[1] = ModeData{mode: NAME, title: "Name", key: "F2"}
	all_modes[2] = ModeData{mode: EMOTICONS, title: "Emoticons", key: "F3"}
	all_modes[3] = ModeData{mode: FAVORITES, title: "Favorites", key: "F4"}

	lp.OnInitialize = func() (string, error) {
		h.initialize()
		lp.SendOverlayReady()
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
			cached_data.Recent = slices.Insert(cached_data.Recent, 0, h.current_char)
			if len(cached_data.Recent) > len(DEFAULT_SET) {
				cached_data.Recent = cached_data.Recent[:len(DEFAULT_SET)]
			}
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
		if err == ErrCanceledByUser {
			err = nil
		}
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
