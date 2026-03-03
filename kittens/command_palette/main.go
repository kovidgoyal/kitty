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
	"github.com/kovidgoyal/kitty/tools/tty"
	"github.com/kovidgoyal/kitty/tools/tui"
	"github.com/kovidgoyal/kitty/tools/tui/loop"
	"github.com/kovidgoyal/kitty/tools/utils"
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

// DisplayItem wraps a binding with its per-column search texts for FZF scoring
type DisplayItem struct {
	binding  Binding
	colTexts [3]string // [0]=key, [1]=action_display, [2]=category
}

// matchInfo stores which column matched and the matched character positions
type matchInfo struct {
	colIdx    int   // which column matched: 0=key, 1=action_display, 2=category
	positions []int // rune positions in the matched column text
}

type displayLine struct {
	text      string
	isHeader  bool
	isModeHdr bool
	itemIdx   int // index into filtered_idx, -1 for headers
}

const maxKeyDisplayWidth = 30

// unmappedLabel is shown in the key column for actions with no keyboard shortcut.
const unmappedLabel = "(unmapped)"

// truncateToWidth truncates s to fit within maxWidth cells, appending "..." if
// truncated and maxWidth > 3. When maxWidth <= 3, the string is simply trimmed
// to fit without appending ellipsis (no room for it).
func truncateToWidth(s string, maxWidth int) string {
	if wcswidth.Stringwidth(s) <= maxWidth {
		return s
	}
	runes := []rune(s)
	if maxWidth <= 3 {
		// Not enough room for ellipsis; just trim to fit
		for len(runes) > 0 && wcswidth.Stringwidth(string(runes)) > maxWidth {
			runes = runes[:len(runes)-1]
		}
		return string(runes)
	}
	for len(runes) > 0 && wcswidth.Stringwidth(string(runes))+3 > maxWidth {
		runes = runes[:len(runes)-1]
	}
	return string(runes) + "..."
}

// CachedSettings holds persistent UI settings stored in command-palette.json.
type CachedSettings struct {
	ShowUnmapped bool `json:"show_unmapped"`
}

type Handler struct {
	lp              *loop.Loop
	screen_size     loop.ScreenSize
	all_items       []DisplayItem
	matcher         *fzf.FuzzyMatcher
	filtered_idx    []int       // indices into all_items for current results
	match_infos     []matchInfo // parallel to filtered_idx, valid when query != ""
	query           string
	selected_idx    int
	scroll_offset   int
	input_data      InputData
	result          string // action definition to execute after exit
	display_lines   []displayLine
	results_start_y int
	results_height  int
	show_unmapped   bool
	cv              *utils.CachedValues[*CachedSettings]
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

	// Initialize with ShowUnmapped: true as the default; Load() returns this
	// default when no cache file exists yet.
	h.cv = utils.NewCachedValues("command-palette", &CachedSettings{ShowUnmapped: true})
	settings := h.cv.Load()
	h.show_unmapped = settings.ShowUnmapped

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
				keyText := b.Key
				if keyText == "" {
					keyText = unmappedLabel
				}
				h.all_items = append(h.all_items, DisplayItem{
					binding:  b,
					colTexts: [3]string{keyText, b.ActionDisplay, catName},
				})
			}
		}
	}

	// Mouse bindings
	for _, b := range h.input_data.Mouse {
		b.Category = "Mouse actions"
		b.Mode = ""
		b.IsMouse = true
		h.all_items = append(h.all_items, DisplayItem{
			binding:  b,
			colTexts: [3]string{b.Key, b.ActionDisplay, "Mouse actions"},
		})
	}
}

func (h *Handler) updateFilter() {
	if h.query == "" {
		// Show all items in original order, respecting the show_unmapped toggle
		h.filtered_idx = make([]int, 0, len(h.all_items))
		for i, item := range h.all_items {
			if !h.show_unmapped && item.binding.Key == "" {
				continue
			}
			h.filtered_idx = append(h.filtered_idx, i)
		}
		h.match_infos = nil
		h.selected_idx = 0
		h.scroll_offset = 0
		return
	}

	nItems := len(h.all_items)

	// Build per-column text slices for batch FZF scoring
	colSlices := [3][]string{
		make([]string, nItems),
		make([]string, nItems),
		make([]string, nItems),
	}
	for i, item := range h.all_items {
		colSlices[0][i] = item.colTexts[0]
		colSlices[1][i] = item.colTexts[1]
		colSlices[2][i] = item.colTexts[2]
	}

	// Score each column independently
	colResults := [3][]fzf.Result{}
	for c := 0; c < 3; c++ {
		results, err := h.matcher.Score(colSlices[c], h.query)
		if err == nil {
			colResults[c] = results
		}
	}

	type scored struct {
		idx       int
		score     uint
		colIdx    int
		positions []int
	}
	var matches []scored
	for i := range h.all_items {
		if !h.show_unmapped && h.all_items[i].binding.Key == "" {
			continue
		}
		bestScore := uint(0)
		bestCol := 0
		var bestPositions []int
		for c := 0; c < 3; c++ {
			if colResults[c] != nil && i < len(colResults[c]) && colResults[c][i].Score > bestScore {
				bestScore = colResults[c][i].Score
				bestCol = c
				bestPositions = colResults[c][i].Positions
			}
		}
		if bestScore > 0 {
			matches = append(matches, scored{idx: i, score: bestScore, colIdx: bestCol, positions: bestPositions})
		}
	}
	sort.Slice(matches, func(i, j int) bool {
		return matches[i].score > matches[j].score
	})
	h.filtered_idx = make([]int, len(matches))
	h.match_infos = make([]matchInfo, len(matches))
	for i, m := range matches {
		h.filtered_idx[i] = m.idx
		h.match_infos[i] = matchInfo{colIdx: m.colIdx, positions: m.positions}
	}
	h.selected_idx = 0
	h.scroll_offset = 0
}

// highlightMatchedChars returns a string with characters at the given rune
// positions rendered using matchStyle, and the rest rendered using baseStyle
// (or unstyled if baseStyle is empty).
func (h *Handler) highlightMatchedChars(text string, positions []int, baseStyle, matchStyle string) string {
	if len(positions) == 0 {
		if baseStyle != "" {
			return h.lp.SprintStyled(baseStyle, text)
		}
		return text
	}
	posSet := make(map[int]bool, len(positions))
	for _, p := range positions {
		posSet[p] = true
	}
	runes := []rune(text)
	var sb strings.Builder
	for i, r := range runes {
		ch := string(r)
		if posSet[i] {
			sb.WriteString(h.lp.SprintStyled(matchStyle, ch))
		} else if baseStyle != "" {
			sb.WriteString(h.lp.SprintStyled(baseStyle, ch))
		} else {
			sb.WriteString(ch)
		}
	}
	return sb.String()
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
	unmappedToggleLabel := "Show"
	if h.show_unmapped {
		unmappedToggleLabel = "Hide"
	}
	footer := h.lp.SprintStyled("fg=bright-yellow", "[Enter]") + " Run  " +
		h.lp.SprintStyled("fg=bright-yellow", "[Esc]") + " Quit  " +
		h.lp.SprintStyled("fg=bright-yellow", "\u2191\u2193") + " Navigate  " +
		h.lp.SprintStyled("fg=bright-yellow", "[F12]") + " " + unmappedToggleLabel + " unmapped"
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
				// Non-default mode: show "── Keyboard mode: name ──" header (purple), no category separators
				if len(lines) > 0 {
					lines = append(lines, displayLine{itemIdx: -1, isHeader: true})
				}
				label := "Keyboard mode: " + b.Mode
				labelWidth := wcswidth.Stringwidth(label)
				sepLen := max(0, width-labelWidth-6)
				sep := strings.Repeat("\u2500", sepLen)
				lines = append(lines, displayLine{
					text:      fmt.Sprintf("  \u2500\u2500 %s %s", label, sep),
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

		// Binding line — key column shows "(unmapped)" for actions with no shortcut
		keyDisplay := b.Key
		if keyDisplay == "" {
			keyDisplay = unmappedLabel
		}
		keyDisplay = truncateToWidth(keyDisplay, maxKeyDisplayWidth)
		lines = append(lines, displayLine{
			text:    fmt.Sprintf("    %-*s %s", maxKeyDisplayWidth, keyDisplay, b.ActionDisplay),
			itemIdx: fi,
		})
	}

	h.display_lines = lines
	h.drawLines(lines, startY, maxRows, width)
}

func (h *Handler) drawFlatResults(startY, maxRows, width int) {
	if len(h.filtered_idx) == 0 {
		h.lp.MoveCursorTo(1, startY)
		h.lp.QueueWriteString(h.lp.SprintStyled("italic dim", "  No matches found"))
		h.display_lines = []displayLine{}
		return
	}

	var lines []displayLine
	for fi, idx := range h.filtered_idx {
		item := &h.all_items[idx]
		b := &item.binding
		keyDisplay := b.Key
		if keyDisplay == "" {
			keyDisplay = unmappedLabel
		}
		keyDisplay = truncateToWidth(keyDisplay, maxKeyDisplayWidth)
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

	// Build the key display (using unmappedLabel for items with no shortcut)
	rawKey := b.Key
	if rawKey == "" {
		rawKey = unmappedLabel
	}
	keyDisplay := truncateToWidth(rawKey, maxKeyDisplayWidth)

	// Determine match info for highlighting (only set when a query is active)
	var mi *matchInfo
	if h.query != "" && filteredIdx < len(h.match_infos) {
		mi = &h.match_infos[filteredIdx]
	}

	const matchStyle = "fg=bright-yellow"
	const keyStyle = "fg=green"
	const unmappedStyle = "dim fg=green"

	// Render key column (4-space indent + key padded to maxKeyDisplayWidth + space)
	paddingLen := max(0, maxKeyDisplayWidth-wcswidth.Stringwidth(keyDisplay))
	if mi != nil && mi.colIdx == 0 {
		ks := keyStyle
		if b.Key == "" {
			ks = unmappedStyle
		}
		h.lp.QueueWriteString("    ")
		h.lp.QueueWriteString(h.highlightMatchedChars(keyDisplay, mi.positions, ks, matchStyle))
		h.lp.QueueWriteString(strings.Repeat(" ", paddingLen) + " ")
	} else if b.Key == "" {
		h.lp.QueueWriteString(h.lp.SprintStyled(unmappedStyle, "    "+keyDisplay+strings.Repeat(" ", paddingLen)+" "))
	} else {
		h.lp.QueueWriteString(h.lp.SprintStyled(keyStyle, "    "+keyDisplay+strings.Repeat(" ", paddingLen)+" "))
	}

	// Render action display column
	if mi != nil && mi.colIdx == 1 {
		h.lp.QueueWriteString(h.highlightMatchedChars(b.ActionDisplay, mi.positions, "", matchStyle))
	} else {
		h.lp.QueueWriteString(b.ActionDisplay)
	}

	// Render category suffix (only present in flat / search-results mode)
	if h.query != "" {
		if mi != nil && mi.colIdx == 2 {
			if b.Mode != "" {
				h.lp.QueueWriteString(fmt.Sprintf(" [%s/", b.Mode))
			} else {
				h.lp.QueueWriteString(" [")
			}
			h.lp.QueueWriteString(h.highlightMatchedChars(b.Category, mi.positions, "", matchStyle))
			h.lp.QueueWriteString("]")
		} else {
			if b.Mode != "" {
				h.lp.QueueWriteString(fmt.Sprintf(" [%s/%s]", b.Mode, b.Category))
			} else {
				h.lp.QueueWriteString(fmt.Sprintf(" [%s]", b.Category))
			}
		}
	}
}

// rowToFilteredIdx converts a 0-indexed cell Y coordinate to a filtered item
// index, or -1 if the cell is not over a clickable item. Internally converts
// to 1-indexed screen rows (matching the MoveCursorTo convention) to compare
// against results_start_y.
func (h *Handler) rowToFilteredIdx(cellY int) int {
	screenRow := cellY + 1 // convert 0-indexed cell to 1-indexed screen row
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
		h.lp.ClearPointerShapes()
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
	if ev.MatchesPressOrRepeat("f12") {
		ev.Handled = true
		h.show_unmapped = !h.show_unmapped
		if h.cv != nil {
			h.cv.Opts.ShowUnmapped = h.show_unmapped
			h.cv.Save()
		}
		h.updateFilter()
		h.draw_screen()
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
	if tty.IsTerminal(os.Stdin.Fd()) {
		return 1, fmt.Errorf("This kitten must only be run via a mapping in kitty.conf")
	}
	output := tui.KittenOutputSerializer()
	lp, err := loop.New()
	if err != nil {
		return 1, err
	}

	handler := &Handler{lp: lp}
	lp.MouseTrackingMode(loop.FULL_MOUSE_TRACKING)

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
