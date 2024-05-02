package list_fonts

import (
	"fmt"
	"strings"

	"kitty/tools/tui/loop"
	"kitty/tools/tui/readline"
	"kitty/tools/utils"

	"golang.org/x/exp/maps"
)

var _ = fmt.Print

type State int

const (
	LISTING_FAMILIES State = iota
	CHOOSING_FACES
)

type handler struct {
	lp                *loop.Loop
	fonts             map[string][]ListedFont
	all_font_families []string
	state             State

	// Listing
	current_font_families []string
	rl                    *readline.Readline
}

// Listing families {{{
func (h *handler) draw_search_bar() {
	h.lp.SetCursorVisible(true)
	sz, err := h.lp.ScreenSize()
	if err != nil {
		return
	}
	h.lp.MoveCursorTo(1, int(sz.HeightCells))
	h.lp.ClearToEndOfLine()
	h.rl.RedrawNonAtomic()
}

func (h *handler) draw_listing_screen() (err error) {
	sz, err := h.lp.ScreenSize()
	if err != nil {
		return err
	}
	_ = sz
	h.draw_search_bar()
	return
}

func (h *handler) update_family_search() {
	text := h.rl.AllText()
	_ = text
}

func (h *handler) handle_listing_key_event(event *loop.KeyEvent) (err error) {
	if event.MatchesPressOrRepeat("ctrl+c") || event.MatchesPressOrRepeat("esc") {
		h.lp.Quit(1)
		event.Handled = true
		return
	}
	if err = h.rl.OnKeyEvent(event); err != nil {
		if err == readline.ErrAcceptInput {
			return nil
		}
		return err
	}
	if event.Handled {
		h.update_family_search()
	}
	h.draw_search_bar()
	return
}

func (h *handler) handle_listing_text(text string, from_key_event bool, in_bracketed_paste bool) (err error) {
	if err = h.rl.OnText(text, from_key_event, in_bracketed_paste); err != nil {
		return err
	}
	h.draw_screen()
	return
}

// }}}

// Events {{{
func (h *handler) initialize() {
	h.lp.SetCursorVisible(false)
	h.all_font_families = utils.StableSortWithKey(maps.Keys(h.fonts), strings.ToLower)
	h.current_font_families = h.all_font_families
	h.rl = readline.New(h.lp, readline.RlInit{DontMarkPrompts: true, Prompt: "Family: "})
	h.draw_screen()
}

func (h *handler) finalize() {
	h.lp.SetCursorVisible(true)
}

func (h *handler) draw_screen() (err error) {
	h.lp.StartAtomicUpdate()
	defer h.lp.EndAtomicUpdate()
	h.lp.ClearScreen()
	h.lp.AllowLineWrapping(false)
	switch h.state {
	case LISTING_FAMILIES:
		return h.draw_listing_screen()
	}
	return
}

func (h *handler) on_wakeup() (err error) {
	return
}

func (h *handler) on_key_event(event *loop.KeyEvent) (err error) {
	switch h.state {
	case LISTING_FAMILIES:
		return h.handle_listing_key_event(event)
	}
	return
}

func (h *handler) on_text(text string, from_key_event bool, in_bracketed_paste bool) (err error) {
	switch h.state {
	case LISTING_FAMILIES:
		return h.handle_listing_text(text, from_key_event, in_bracketed_paste)
	}
	return
}

// }}}
