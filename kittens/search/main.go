package search

import (
	"fmt"
	"io"
	"math"
	"os"
	"strconv"
	"strings"
	"sync"

	"github.com/kovidgoyal/kitty"
	"github.com/kovidgoyal/kitty/tools/cli"
	"github.com/kovidgoyal/kitty/tools/config"
	"github.com/kovidgoyal/kitty/tools/tty"
	"github.com/kovidgoyal/kitty/tools/tui/loop"
	"github.com/kovidgoyal/kitty/tools/utils"
	"github.com/kovidgoyal/kitty/tools/wcswidth"
)

var debugPrintln = tty.DebugPrintln
var _ = debugPrintln
var _ = fmt.Print

type DisplayLine struct {
	raw    string
	matchs []*Match
}

type Search struct {
	text         string
	currentMatch *Match
}

type Match struct {
	line int

	start   int
	end     int
	current bool

	prev *Match
	next *Match
}

type Handler struct {
	lp               *loop.Loop
	lines            []DisplayLine
	search           Search
	screenSize       loop.ScreenSize
	viewsStartY      int
	viewsHeight      int
	scrollStart      int
	matchCount       int
	currentMatchIdx  int
	shortcutTracker  config.ShortcutTracker
	keyboardShortcut []*config.KeyAction
}

func (h *Handler) initialize() (string, error) {
	sz, err := h.lp.ScreenSize()
	if err != nil {
		return "", err
	}
	h.screenSize = sz
	h.lp.SetCursorVisible(true)
	h.lp.SetCursorShape(loop.BAR_CURSOR, true)
	h.lp.AllowLineWrapping(true)
	h.lp.SetWindowTitle("Search")

	h.keyboardShortcut = config.ResolveShortcuts(NewConfig().KeyboardShortcuts)

	h.reSearch()
	h.drawScreen()
	h.lp.SendOverlayReady()
	return "", nil
}

func (h *Handler) onKeyEvent(ev *loop.KeyEvent) error {
	if ev.MatchesPressOrRepeat("escape") {
		ev.Handled = true
		if h.search.text != "" {
			h.search.text = ""
			h.reSearch()
			h.drawScreen()
		} else {
			h.lp.Quit(0)
		}
		return nil
	}
	if ev.MatchesPressOrRepeat("up") {
		ev.Handled = true
		h.moveScrollStart(-1)
		return nil
	}
	if ev.MatchesPressOrRepeat("down") {
		ev.Handled = true
		h.moveScrollStart(1)
		return nil
	}
	if ev.MatchesPressOrRepeat("enter") {
		ev.Handled = true

		h.search.currentMatch.current = false
		h.search.currentMatch = h.search.currentMatch.prev
		h.search.currentMatch.current = true

		if h.currentMatchIdx > 0 {
			h.currentMatchIdx--
		}
		if h.currentMatchIdx <= 0 {
			h.currentMatchIdx = h.matchCount
		}
		h.scrollStart = h.search.currentMatch.line
		h.drawScreen()
		return nil
	}
	if ev.MatchesPressOrRepeat("shift+enter") {
		ev.Handled = true

		h.search.currentMatch.current = false
		h.search.currentMatch = h.search.currentMatch.next
		h.search.currentMatch.current = true

		if h.currentMatchIdx <= h.matchCount {
			h.currentMatchIdx++
		}
		if h.currentMatchIdx > h.matchCount {
			h.currentMatchIdx = 1
		}
		h.scrollStart = h.search.currentMatch.line
		h.drawScreen()
		return nil
	}
	if ac := h.shortcutTracker.Match(ev, h.keyboardShortcut); ac != nil {
		ev.Handled = true
		switch ac.Name {
		case "selection_up":
			h.moveScrollStart(-1)
		case "selection_down":
			h.moveScrollStart(1)
		}
		return nil
	}

	if ev.MatchesPressOrRepeat("page_up") {
		ev.Handled = true
		delta := max(1, int(h.screenSize.HeightCells)-4)
		h.moveScrollStart(-delta)
		return nil
	}
	if ev.MatchesPressOrRepeat("page_down") {
		ev.Handled = true
		delta := max(1, int(h.screenSize.HeightCells)-4)
		h.moveScrollStart(delta)
		return nil
	}
	if ev.MatchesPressOrRepeat("home") || ev.MatchesPressOrRepeat("ctrl+home") {
		ev.Handled = true
		h.moveScrollStart(-h.scrollStart)
		return nil
	}
	if ev.MatchesPressOrRepeat("end") || ev.MatchesPressOrRepeat("ctrl+end") {
		ev.Handled = true
		h.moveScrollStart(len(h.lines) - h.scrollStart)
		return nil
	}
	if ev.MatchesPressOrRepeat("backspace") {
		ev.Handled = true
		if h.search.text != "" {
			g := wcswidth.SplitIntoGraphemes(h.search.text)
			h.search.text = strings.Join(g[:len(g)-1], "")
			h.reSearch()
			h.drawScreen()
		} else {
			h.lp.Beep()
		}
		return nil
	}
	return nil
}

func (h *Handler) onText(text string, fromKeyEvent bool, inBracketedPaste bool) error {
	h.search.text += text
	h.reSearch()
	h.drawScreen()
	return nil
}

func (h *Handler) onMouseEvent(ev *loop.MouseEvent) error {
	switch ev.Event_type {
	case loop.MOUSE_PRESS:
		if ev.Buttons&(loop.MOUSE_WHEEL_UP|loop.MOUSE_WHEEL_DOWN) != 0 {
			h.handleWheelEvent(ev.Buttons&(loop.MOUSE_WHEEL_UP) != 0)
		}
	}
	return nil
}

func (h *Handler) reSearch() {
	query := h.search.text
	queryLen := len(query)
	if queryLen == 0 {
		return
	}

	h.matchCount = 0
	h.search.currentMatch = nil

	var firstMatch *Match
	var lastMatch *Match
	for i := range h.lines {
		line := &h.lines[i]
		line.matchs = nil
		offset := 0
		for {
			idx := strings.Index(line.raw[offset:], query)
			if idx == -1 {
				break
			}

			realIdx := offset + idx

			match := &Match{
				line:    i,
				start:   realIdx,
				end:     realIdx + queryLen,
				current: false,
			}

			if firstMatch == nil {
				firstMatch = match
			} else {
				lastMatch.next = match
				match.prev = lastMatch
			}
			lastMatch = match
			line.matchs = append(line.matchs, match)

			h.matchCount++
			offset = match.end
		}
	}

	h.currentMatchIdx = h.matchCount
	if firstMatch != nil && lastMatch != nil {
		lastMatch.next = firstMatch
		firstMatch.prev = lastMatch

		lastMatch.current = true
		h.search.currentMatch = lastMatch
	}
}

func (h *Handler) drawScreen() {
	h.lp.StartAtomicUpdate()
	defer h.lp.EndAtomicUpdate()
	h.lp.ClearScreen()

	height := int(h.screenSize.HeightCells)

	// Layout: line 1 = search bar, lines 2..height-2 = views,
	// line height-1 = help text, line height = key hints
	searchBarY := 1
	viewsStartY := 2
	hintsY := height
	viewsHeight := max(hintsY-viewsStartY, 1)

	h.viewsStartY = viewsStartY
	h.viewsHeight = viewsHeight

	// Draw search bar
	h.lp.MoveCursorTo(1, searchBarY)
	h.lp.QueueWriteString(h.lp.SprintStyled("fg=bright-yellow", "> "))
	h.lp.QueueWriteString(h.search.text)

	// Draw views
	h.drawViews(viewsStartY, viewsHeight)

	// Draw key hints footer
	h.lp.MoveCursorTo(1, hintsY)
	footer := h.lp.SprintStyled("fg=bright-yellow", "[Esc]") + " Quit  "
	if len(h.search.text) != 0 {
		footer += h.lp.SprintStyled("fg=bright-yellow", "Enter/Shift+Enter") + " Navigate"
	}

	matchCount := ""
	if h.search.text != "" {
		matchCount = fmt.Sprintf("  %d/%d", h.currentMatchIdx, h.matchCount)
	}
	h.lp.QueueWriteString(" " + footer + h.lp.SprintStyled("dim", matchCount))

	// Position cursor at end of search text for typing
	h.lp.MoveCursorTo(3+wcswidth.Stringwidth(h.search.text), searchBarY)
}

func (h *Handler) drawViews(startY, maxRows int) {
	h.scrollStart = min(h.scrollStart, max(0, len(h.lines)-maxRows))

	end := min(h.scrollStart+maxRows, len(h.lines))
	for row, line := range h.lines[h.scrollStart:end] {
		h.lp.MoveCursorTo(1, startY+row)
		if len(line.matchs) == 0 {
			h.lp.QueueWriteString(line.raw)
		} else {
			for _, m := range line.matchs {
				h.lp.QueueWriteString(line.raw[:m.start])
				styled := "fg=black bright bg=yellow bright"
				if m.current {
					styled = "fg=black bright bg=orange bright"
				}
				h.lp.QueueWriteString(h.lp.SprintStyled(styled, line.raw[m.start:m.end]))
				h.lp.QueueWriteString(line.raw[m.end:])
			}
		}
	}
}

func (h *Handler) moveScrollStart(delta int) {
	h.scrollStart = min(max(0, h.scrollStart+delta), len(h.lines))
	if h.scrollStart == 0 || h.scrollStart == len(h.lines) {
		h.lp.Beep()
	}
	h.drawScreen()
}

type KittyOpts struct {
	WheelScrollMultiplier float64
	CopyOnSelect          bool
}

func readRelevantKittyOpts() KittyOpts {
	ans := KittyOpts{WheelScrollMultiplier: kitty.KittyConfigDefaults.Wheel_scroll_multiplier}
	handleLine := func(key, val string) error {
		switch key {
		case "wheel_scroll_multiplier":
			v, err := strconv.ParseFloat(val, 64)
			if err == nil {
				ans.WheelScrollMultiplier = v
			}
		case "copy_on_select":
			ans.CopyOnSelect = strings.ToLower(val) == "clipboard"
		}
		return nil
	}
	config.ReadKittyConfig(handleLine)
	return ans
}

var RelevantKittyOpts = sync.OnceValue(func() KittyOpts {
	return readRelevantKittyOpts()
})

func (h *Handler) handleWheelEvent(up bool) {
	amt := int(math.Round(RelevantKittyOpts().WheelScrollMultiplier))
	if amt == 0 {
		amt = 1
	}
	if up {
		amt *= -1
	}

	h.moveScrollStart(amt)
}

func parseDisplayLine(inputData string) []DisplayLine {
	lines := strings.Split(inputData, "\n")
	result := make([]DisplayLine, 0, len(lines))
	for _, line := range lines {
		result = append(result, DisplayLine{raw: line})
	}
	return result
}

func main(_ *cli.Command, opts *Options, _ []string) (rc int, err error) {
	if tty.IsTerminal(os.Stdin.Fd()) {
		return 1, fmt.Errorf("This kitten must only be run via the search action mapped to a shortcut in kitty.conf")
	}

	var (
		inputData string
		selection = opts.Selection
	)
	stdin, err := io.ReadAll(os.Stdin)
	if err != nil {
		inputData = ""
	} else {
		inputData = utils.UnsafeBytesToString(stdin)
	}
	lines := parseDisplayLine(inputData)

	lp, err := loop.New()
	if err != nil {
		return 1, err
	}
	handler := &Handler{
		lp:    lp,
		lines: lines,
		search: Search{
			text: selection,
		},
		scrollStart: len(lines),
	}
	lp.MouseTrackingMode(loop.FULL_MOUSE_TRACKING)
	lp.OnInitialize = func() (string, error) {
		return handler.initialize()
	}
	lp.OnFinalize = func() string { return "" }
	lp.OnKeyEvent = handler.onKeyEvent
	lp.OnText = handler.onText
	lp.OnMouseEvent = handler.onMouseEvent

	err = lp.Run()
	if err != nil {
		return 1, err
	}
	ds := lp.DeathSignalName()
	if ds != "" {
		fmt.Println("Killed by signal:", ds)
		lp.KillIfSignalled()
		return
	}
	rc = lp.ExitCode()
	return
}

func EntryPoint(parent *cli.Command) {
	create_cmd(parent, main)
}
