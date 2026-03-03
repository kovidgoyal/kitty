// License: GPLv3 Copyright: 2024, Kovid Goyal <kovid at kovidgoyal.net>

package command_palette

import (
	"encoding/json"
	"fmt"
	"io"
	"os"
	"sort"
	"strings"

	"github.com/kovidgoyal/kitty/tools/cli"
	"github.com/kovidgoyal/kitty/tools/fzf"
	"github.com/kovidgoyal/kitty/tools/tui"
	"github.com/kovidgoyal/kitty/tools/tui/loop"
	"github.com/kovidgoyal/kitty/tools/wcswidth"
)

// JSON data structures matching Python collect_keys_data output
type Binding struct {
	Key           string `json:"key"`
	Action        string `json:"action"`
	ActionDisplay string `json:"action_display"`
	Definition    string `json:"definition"`
	Help          string `json:"help"`
	LongHelp      string `json:"long_help"`
	Category      string
	Mode          string
	IsMouse       bool
}

type InputData struct {
	Modes         map[string]map[string][]Binding `json:"modes"`
	Mouse         []Binding                       `json:"mouse"`
	ModeOrder     []string                        `json:"mode_order"`
	CategoryOrder map[string][]string             `json:"category_order"`
}

// DisplayItem wraps a binding with its search text for FZF scoring
type DisplayItem struct {
	binding    Binding
	searchText string // key + action_display + category for FZF
}

type displayLine struct {
	text      string
	isHeader  bool
	isModeHdr bool
	itemIdx   int // index into filtered_idx, -1 for headers
}

const maxKeyDisplayWidth = 30

// truncateToWidth truncates s to fit within maxWidth cells, appending "..." if truncated.
func truncateToWidth(s string, maxWidth int) string {
	if wcswidth.Stringwidth(s) <= maxWidth {
		return s
	}
	if maxWidth <= 3 {
		runes := []rune(s)
		for len(runes) > 0 && wcswidth.Stringwidth(string(runes)) > maxWidth {
			runes = runes[:len(runes)-1]
		}
		return string(runes)
	}
	runes := []rune(s)
	for len(runes) > 0 && wcswidth.Stringwidth(string(runes))+3 > maxWidth {
		runes = runes[:len(runes)-1]
	}
	return string(runes) + "..."
}

type Handler struct {
	lp              *loop.Loop
	screen_size     loop.ScreenSize
	all_items       []DisplayItem
	search_texts    []string // parallel to all_items, for FZF scoring
	matcher         *fzf.FuzzyMatcher
	filtered_idx    []int // indices into all_items for current results
	query           string
	selected_idx    int
	scroll_offset   int
	input_data      InputData
	result          string // action definition to execute after exit
	display_lines   []displayLine
	results_start_y int
	results_height  int
}

func (h *Handler) initialize() (string, error) {
	sz, err := h.lp.ScreenSize()
	if err != nil {
		return "", err
	}
	h.screen_size = sz
	h.lp.SetCursorVisible(true)
	h.lp.SetCursorShape(loop.BAR_CURSOR, true)
	h.lp.AllowLineWrapping(false)
	h.lp.SetWindowTitle("Command Palette")
	h.lp.MouseTrackingMode(loop.BUTTONS_AND_DRAG_MOUSE_TRACKING)

	if err := h.loadData(); err != nil {
		return "", err
	}

	h.matcher = fzf.NewFuzzyMatcher(fzf.DEFAULT_SCHEME)
	h.updateFilter()
	h.draw_screen()
	h.lp.SendOverlayReady()
	return "", nil
}

func (h *Handler) loadData() error {
	data, err := io.ReadAll(os.Stdin)
	if err != nil {
		return fmt.Errorf("failed to read stdin: %w", err)
	}
	if len(data) == 0 {
		return fmt.Errorf("no input data received on stdin; this kitten must be launched from kitty")
	}
	if err := json.Unmarshal(data, &h.input_data); err != nil {
		return fmt.Errorf("failed to parse input data: %w", err)
	}

	h.flattenBindings()
	return nil
}

// flattenBindings converts the hierarchical mode/category/binding data into
// a flat list suitable for display and FZF scoring. Uses the explicit ordering
// arrays from Python since Go maps do not preserve insertion order.
func (h *Handler) flattenBindings() {
	// Use explicit mode ordering from Python, falling back to sorted keys
	modeNames := h.input_data.ModeOrder
	if len(modeNames) == 0 {
		modeNames = make([]string, 0, len(h.input_data.Modes))
		for name := range h.input_data.Modes {
			modeNames = append(modeNames, name)
		}
		sort.Slice(modeNames, func(i, j int) bool {
			if modeNames[i] == "" {
				return true
			}
			if modeNames[j] == "" {
				return false
			}
			return modeNames[i] < modeNames[j]
		})
	}

	for _, modeName := range modeNames {
		categories, ok := h.input_data.Modes[modeName]
		if !ok {
			continue
		}

		// Use explicit category ordering from Python, falling back to sorted keys
		catNames := h.input_data.CategoryOrder[modeName]
		if len(catNames) == 0 {
			catNames = make([]string, 0, len(categories))
			for name := range categories {
				catNames = append(catNames, name)
			}
			sort.Strings(catNames)
		}

		for _, catName := range catNames {
			bindings, ok := categories[catName]
			if !ok {
				continue
			}
			for _, b := range bindings {
				b.Category = catName
				b.Mode = modeName
				b.IsMouse = false
				searchText := b.Key + " " + b.ActionDisplay + " " + catName
				if modeName != "" {
					searchText += " " + modeName
				}
				h.all_items = append(h.all_items, DisplayItem{
					binding:    b,
					searchText: searchText,
				})
			}
		}
	}

	// Mouse bindings
	for _, b := range h.input_data.Mouse {
		b.Category = "Mouse actions"
		b.Mode = ""
		b.IsMouse = true
		searchText := b.Key + " " + b.ActionDisplay + " Mouse"
		h.all_items = append(h.all_items, DisplayItem{
			binding:    b,
			searchText: searchText,
		})
	}

	// Build parallel search texts array for FZF
	h.search_texts = make([]string, len(h.all_items))
	for i, item := range h.all_items {
		h.search_texts[i] = item.searchText
	}
}

func (h *Handler) updateFilter() {
	if h.query == "" {
		// Show all items in original order
		h.filtered_idx = make([]int, len(h.all_items))
		for i := range h.all_items {
			h.filtered_idx[i] = i
		}
	} else {
		results, err := h.matcher.Score(h.search_texts, h.query)
		if err != nil {
			h.filtered_idx = nil
			return
		}
		type scored struct {
			idx   int
			score uint
		}
		var matches []scored
		for i, r := range results {
			if r.Score > 0 {
				matches = append(matches, scored{idx: i, score: r.Score})
			}
		}
		sort.Slice(matches, func(i, j int) bool {
			return matches[i].score > matches[j].score
		})
		h.filtered_idx = make([]int, len(matches))
		for i, m := range matches {
			h.filtered_idx[i] = m.idx
		}
	}
	h.selected_idx = 0
	h.scroll_offset = 0
}

func (h *Handler) selectedBinding() *Binding {
	if h.selected_idx < 0 || h.selected_idx >= len(h.filtered_idx) {
		return nil
	}
	idx := h.filtered_idx[h.selected_idx]
	if idx < 0 || idx >= len(h.all_items) {
		return nil
	}
	return &h.all_items[idx].binding
}

func (h *Handler) draw_screen() {
	h.lp.StartAtomicUpdate()
	defer h.lp.EndAtomicUpdate()
	h.lp.ClearScreen()

	width := int(h.screen_size.WidthCells)
	height := int(h.screen_size.HeightCells)
	if width < 10 || height < 5 {
		return
	}

	// Layout: line 1 = search bar, lines 2..height-2 = results,
	// line height-1 = help text, line height = key hints
	searchBarY := 1
	resultsStartY := 2
	helpY := height - 1
	hintsY := height
	resultsHeight := helpY - resultsStartY
	if resultsHeight < 1 {
		resultsHeight = 1
	}

	h.results_start_y = resultsStartY
	h.results_height = resultsHeight

	// Draw search bar
	h.lp.MoveCursorTo(1, searchBarY)
	h.lp.QueueWriteString(h.lp.SprintStyled("fg=bright-yellow", "> "))
	h.lp.QueueWriteString(h.query)

	// Draw results
	if h.query == "" {
		h.drawGroupedResults(resultsStartY, resultsHeight, width)
	} else {
		h.drawFlatResults(resultsStartY, resultsHeight, width)
	}

	// Draw help text for selected binding
	h.lp.MoveCursorTo(1, helpY)
	if b := h.selectedBinding(); b != nil && b.Help != "" {
		helpStr := b.Help
		maxLen := width - 2
		if maxLen < 3 {
			maxLen = 3
		}
		if wcswidth.Stringwidth(helpStr) > maxLen {
			// Truncate by runes to avoid breaking multi-byte characters
			runes := []rune(helpStr)
			for len(runes) > 0 && wcswidth.Stringwidth(string(runes))+3 > maxLen {
				runes = runes[:len(runes)-1]
			}
			helpStr = string(runes) + "..."
		}
		h.lp.QueueWriteString(h.lp.SprintStyled("dim italic", " "+helpStr))
	}

	// Draw key hints footer
	h.lp.MoveCursorTo(1, hintsY)
	footer := h.lp.SprintStyled("fg=bright-yellow", "[Enter]") + " Run  " +
		h.lp.SprintStyled("fg=bright-yellow", "[Esc]") + " Quit  " +
		h.lp.SprintStyled("fg=bright-yellow", "\u2191\u2193") + " Navigate"
	matchInfo := ""
	if h.query != "" {
		matchInfo = fmt.Sprintf("  %d/%d", len(h.filtered_idx), len(h.all_items))
	}
	h.lp.QueueWriteString(" " + footer + h.lp.SprintStyled("dim", matchInfo))

	// Position cursor at end of search text for typing
	h.lp.MoveCursorTo(3+wcswidth.Stringwidth(h.query), searchBarY)
}

func (h *Handler) drawGroupedResults(startY, maxRows, width int) {
	var lines []displayLine
	lastMode := ""
	lastCategory := ""

	for fi, idx := range h.filtered_idx {
		item := &h.all_items[idx]
		b := &item.binding

		// Mode header when mode changes
		if b.Mode != lastMode {
			lastMode = b.Mode
			lastCategory = ""
			if b.Mode != "" {
				// Non-default mode: show "Keyboard mode: name" header (purple), no category separators
				if len(lines) > 0 {
					lines = append(lines, displayLine{itemIdx: -1, isHeader: true})
				}
				lines = append(lines, displayLine{
					text:      fmt.Sprintf("  Keyboard mode: %s", b.Mode),
					isModeHdr: true, isHeader: true, itemIdx: -1,
				})
			}
		}

		// Category header when category changes - only for the default mode ("")
		if b.Mode == "" && b.Category != lastCategory {
			lastCategory = b.Category
			if len(lines) > 0 && !lines[len(lines)-1].isHeader {
				lines = append(lines, displayLine{itemIdx: -1, isHeader: true})
			}
			catWidth := wcswidth.Stringwidth(b.Category)
			sepLen := max(0, width-catWidth-6)
			sep := strings.Repeat("\u2500", sepLen)
			lines = append(lines, displayLine{
				text:     fmt.Sprintf("  \u2500\u2500 %s %s", b.Category, sep),
				isHeader: true, itemIdx: -1,
			})
		}

		// Binding line
		keyDisplay := truncateToWidth(b.Key, maxKeyDisplayWidth)
		lines = append(lines, displayLine{
			text:    fmt.Sprintf("    %-*s %s", maxKeyDisplayWidth, keyDisplay, b.ActionDisplay),
			itemIdx: fi,
		})
	}

	h.display_lines = lines
	h.drawLines(lines, startY, maxRows, width)
}

func (h *Handler) drawFlatResults(startY, maxRows, width int) {
	var lines []displayLine
	for fi, idx := range h.filtered_idx {
		item := &h.all_items[idx]
		b := &item.binding
		keyDisplay := truncateToWidth(b.Key, maxKeyDisplayWidth)
		catSuffix := ""
		if b.Mode != "" {
			catSuffix = fmt.Sprintf(" [%s/%s]", b.Mode, b.Category)
		} else {
			catSuffix = fmt.Sprintf(" [%s]", b.Category)
		}
		lines = append(lines, displayLine{
			text:    fmt.Sprintf("    %-*s %-30s%s", maxKeyDisplayWidth, keyDisplay, b.ActionDisplay, catSuffix),
			itemIdx: fi,
		})
	}

	h.display_lines = lines
	h.drawLines(lines, startY, maxRows, width)
}

func (h *Handler) drawLines(lines []displayLine, startY, maxRows, width int) {
	if maxRows <= 0 || len(lines) == 0 {
		return
	}

	// Adjust scroll to keep selected item visible
	selectedLineIdx := -1
	for i, dl := range lines {
		if dl.itemIdx == h.selected_idx {
			selectedLineIdx = i
			break
		}
	}
	if selectedLineIdx >= 0 {
		if selectedLineIdx < h.scroll_offset {
			// Scroll up to show selected item; also reveal any header lines above it
			h.scroll_offset = selectedLineIdx
			for h.scroll_offset > 0 && lines[h.scroll_offset-1].isHeader {
				h.scroll_offset--
			}
		}
		if selectedLineIdx >= h.scroll_offset+maxRows {
			h.scroll_offset = selectedLineIdx - maxRows + 1
		}
	}
	h.scroll_offset = max(0, h.scroll_offset)
	h.scroll_offset = min(h.scroll_offset, max(0, len(lines)-maxRows))

	end := min(h.scroll_offset+maxRows, len(lines))
	for row, li := range lines[h.scroll_offset:end] {
		h.lp.MoveCursorTo(1, startY+row)
		text := li.text
		// Truncate at rune boundary to avoid breaking multi-byte characters
		if wcswidth.Stringwidth(text) > width {
			runes := []rune(text)
			for len(runes) > 0 && wcswidth.Stringwidth(string(runes)) > width {
				runes = runes[:len(runes)-1]
			}
			text = string(runes)
		}

		if li.isModeHdr {
			h.lp.QueueWriteString(h.lp.SprintStyled("bold fg=magenta", text))
		} else if li.isHeader {
			h.lp.QueueWriteString(h.lp.SprintStyled("fg=bright-blue", text))
		} else if li.itemIdx == h.selected_idx {
			// Selected item: highlight with reverse video
			padded := text
			textWidth := wcswidth.Stringwidth(text)
			if textWidth < width {
				padded += strings.Repeat(" ", width-textWidth)
			}
			h.lp.QueueWriteString(h.lp.SprintStyled("fg=black bg=white", padded))
		} else {
			h.drawBindingLine(text, li.itemIdx, width)
		}
	}
}

func (h *Handler) drawBindingLine(text string, filteredIdx, width int) {
	if filteredIdx < 0 || filteredIdx >= len(h.filtered_idx) {
		h.lp.QueueWriteString(text)
		return
	}
	idx := h.filtered_idx[filteredIdx]
	if idx < 0 || idx >= len(h.all_items) {
		h.lp.QueueWriteString(text)
		return
	}
	b := &h.all_items[idx].binding

	// Style the key portion green, leave action unstyled
	keyDisplay := truncateToWidth(b.Key, maxKeyDisplayWidth)
	keyPrefix := fmt.Sprintf("    %-*s", maxKeyDisplayWidth, keyDisplay)
	rest := ""
	if len(text) > len(keyPrefix) {
		rest = text[len(keyPrefix):]
	}
	h.lp.QueueWriteString(h.lp.SprintStyled("fg=green", keyPrefix))
	h.lp.QueueWriteString(rest)
}

// rowToFilteredIdx converts a 0-indexed cell row to a filtered item index,
// or -1 if the row is not over a clickable item.
func (h *Handler) rowToFilteredIdx(cellY int) int {
	screenRow := cellY + 1 // convert to 1-indexed
	if screenRow < h.results_start_y || screenRow >= h.results_start_y+h.results_height {
		return -1
	}
	lineIdx := h.scroll_offset + (screenRow - h.results_start_y)
	if lineIdx < 0 || lineIdx >= len(h.display_lines) {
		return -1
	}
	return h.display_lines[lineIdx].itemIdx
}

func (h *Handler) onMouseEvent(ev *loop.MouseEvent) error {
	switch ev.Event_type {
	case loop.MOUSE_CLICK:
		if ev.Buttons&loop.LEFT_MOUSE_BUTTON != 0 {
			fi := h.rowToFilteredIdx(ev.Cell.Y)
			if fi >= 0 {
				h.selected_idx = fi
				h.triggerSelected()
			}
		}
	case loop.MOUSE_MOVE:
		fi := h.rowToFilteredIdx(ev.Cell.Y)
		h.lp.PopPointerShape()
		if fi >= 0 {
			h.lp.PushPointerShape(loop.POINTER_POINTER)
		}
	}
	return nil
}

func (h *Handler) onKeyEvent(ev *loop.KeyEvent) error {
	if ev.MatchesPressOrRepeat("escape") {
		ev.Handled = true
		if h.query != "" {
			h.query = ""
			h.updateFilter()
			h.draw_screen()
		} else {
			h.lp.Quit(0)
		}
		return nil
	}
	if ev.MatchesPressOrRepeat("enter") {
		ev.Handled = true
		h.triggerSelected()
		return nil
	}
	if ev.MatchesPressOrRepeat("up") || ev.MatchesPressOrRepeat("ctrl+k") || ev.MatchesPressOrRepeat("ctrl+p") {
		ev.Handled = true
		h.moveSelection(-1)
		return nil
	}
	if ev.MatchesPressOrRepeat("down") || ev.MatchesPressOrRepeat("ctrl+j") || ev.MatchesPressOrRepeat("ctrl+n") {
		ev.Handled = true
		h.moveSelection(1)
		return nil
	}
	if ev.MatchesPressOrRepeat("page_up") {
		ev.Handled = true
		delta := max(1, int(h.screen_size.HeightCells)-4)
		h.moveSelection(-delta)
		return nil
	}
	if ev.MatchesPressOrRepeat("page_down") {
		ev.Handled = true
		delta := max(1, int(h.screen_size.HeightCells)-4)
		h.moveSelection(delta)
		return nil
	}
	if ev.MatchesPressOrRepeat("home") || ev.MatchesPressOrRepeat("ctrl+home") {
		ev.Handled = true
		h.selected_idx = 0
		h.draw_screen()
		return nil
	}
	if ev.MatchesPressOrRepeat("end") || ev.MatchesPressOrRepeat("ctrl+end") {
		ev.Handled = true
		if len(h.filtered_idx) > 0 {
			h.selected_idx = len(h.filtered_idx) - 1
		}
		h.draw_screen()
		return nil
	}
	if ev.MatchesPressOrRepeat("backspace") {
		ev.Handled = true
		if h.query != "" {
			g := wcswidth.SplitIntoGraphemes(h.query)
			h.query = strings.Join(g[:len(g)-1], "")
			h.updateFilter()
			h.draw_screen()
		} else {
			h.lp.Beep()
		}
		return nil
	}
	return nil
}

func (h *Handler) onText(text string, from_key_event bool, in_bracketed_paste bool) error {
	h.query += text
	h.updateFilter()
	h.draw_screen()
	return nil
}

func (h *Handler) onResize(old, new_size loop.ScreenSize) error {
	h.screen_size = new_size
	h.draw_screen()
	return nil
}

func (h *Handler) moveSelection(delta int) {
	if len(h.filtered_idx) == 0 {
		return
	}
	h.selected_idx += delta
	h.selected_idx = max(0, h.selected_idx)
	h.selected_idx = min(h.selected_idx, len(h.filtered_idx)-1)
	h.draw_screen()
}

func (h *Handler) triggerSelected() {
	b := h.selectedBinding()
	if b == nil || b.IsMouse {
		h.lp.Beep()
		return
	}
	h.result = b.Definition
	h.lp.Quit(0)
}

func main(cmd *cli.Command, opts *Options, args []string) (rc int, err error) {
	output := tui.KittenOutputSerializer()
	lp, err := loop.New()
	if err != nil {
		return 1, err
	}

	handler := &Handler{lp: lp}

	lp.OnInitialize = func() (string, error) {
		return handler.initialize()
	}
	lp.OnFinalize = func() string { return "" }
	lp.OnKeyEvent = handler.onKeyEvent
	lp.OnText = handler.onText
	lp.OnResize = handler.onResize
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
	if handler.result != "" {
		s, serr := output(map[string]string{"action": handler.result})
		if serr == nil {
			fmt.Println(s)
		}
	}
	return
}

func EntryPoint(parent *cli.Command) {
	create_cmd(parent, main)
}
