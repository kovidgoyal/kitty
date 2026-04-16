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
	"github.com/kovidgoyal/kitty/tools/config"
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
	Alias         string `json:"alias"`
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

// wordToken represents a single word extracted from column text, with its
// rune-level position in the original string for match highlighting.
type wordToken struct {
	word     string // lowercased word
	startPos int    // rune offset in original column text
	endPos   int    // rune offset past last char
}

// tokenizeWords splits s into words on delimiters (_ space + / -) and returns
// each word with its rune position in the original string.
func tokenizeWords(s string) []wordToken {
	runes := []rune(strings.ToLower(s))
	var tokens []wordToken
	start := -1
	for i, r := range runes {
		if isWordDelimiter(r) {
			if start >= 0 {
				tokens = append(tokens, wordToken{
					word:     string(runes[start:i]),
					startPos: start,
					endPos:   i,
				})
				start = -1
			}
		} else if start < 0 {
			start = i
		}
	}
	if start >= 0 {
		tokens = append(tokens, wordToken{
			word:     string(runes[start:]),
			startPos: start,
			endPos:   len(runes),
		})
	}
	return tokens
}

// tokenizeQuery splits a query string into lowercase tokens on whitespace only.
// Delimiter characters like _ + / - are preserved within tokens so the user can
// search for compound names (e.g. "mouse_selection") as a single unit.
func tokenizeQuery(s string) []string {
	parts := strings.Fields(s)
	for i := range parts {
		parts[i] = strings.ToLower(parts[i])
	}
	return parts
}

// isWordDelimiter returns true for characters used to split column text into words.
func isWordDelimiter(r rune) bool {
	return r == '_' || r == ' ' || r == '+' || r == '/' || r == '-'
}

// matchSingleWord finds the best-matching word for a simple (no-delimiter) query
// token against a column's pre-tokenized words.
//
// Scoring: exact=4, prefix=3, edit-distance-1=2, edit-distance-2=1, none=0.
func matchSingleWord(queryToken string, words []wordToken) (score int, positions []int) {
	for _, w := range words {
		var s int
		var pos []int

		if w.word == queryToken {
			// Exact match
			s = 4
			pos = runeRange(w.startPos, w.endPos)
		} else if strings.HasPrefix(w.word, queryToken) {
			// Prefix match — highlight only the matched prefix
			s = 3
			pos = runeRange(w.startPos, w.startPos+len([]rune(queryToken)))
		} else if len(queryToken) >= 4 && len(w.word) >= 4 {
			// Typo tolerance via edit distance (only for words >= 4 chars)
			dist := utils.LevenshteinDistance(queryToken, w.word, false)
			if dist == 1 {
				s = 2
				pos = runeRange(w.startPos, w.endPos)
			} else if dist == 2 {
				s = 1
				pos = runeRange(w.startPos, w.endPos)
			}
		}

		if s > score {
			score = s
			positions = pos
		}
	}
	return
}

// bestWordMatch finds the best match for queryToken against a column's words.
// For compound tokens (containing _ + / -), it first tries an exact substring
// match against the full column text, then falls back to matching each sub-part
// independently against individual words.
func bestWordMatch(queryToken string, words []wordToken, colText string) (score int, positions []int) {
	if !strings.ContainsAny(queryToken, "_+/-") {
		return matchSingleWord(queryToken, words)
	}

	// Compound token: try exact substring match in the column text
	colLower := strings.ToLower(colText)
	if before, _, ok := strings.Cut(colLower, queryToken); ok {
		runeIdx := len([]rune(before))
		qRuneLen := len([]rune(queryToken))
		subParts := strings.FieldsFunc(queryToken, isWordDelimiter)
		return 4 * len(subParts), runeRange(runeIdx, runeIdx+qRuneLen)
	}

	// Fallback: match each sub-part independently against words
	subParts := strings.FieldsFunc(queryToken, isWordDelimiter)
	var totalScore int
	var allPos []int
	for _, sub := range subParts {
		s, p := matchSingleWord(sub, words)
		totalScore += s
		allPos = append(allPos, p...)
	}
	if totalScore > 0 {
		return totalScore, allPos
	}
	return 0, nil
}

// runeRange returns a slice of consecutive ints from start to end-1.
func runeRange(start, end int) []int {
	pos := make([]int, end-start)
	for i := range pos {
		pos[i] = start + i
	}
	return pos
}

// DisplayItem wraps a binding with its per-column search texts and pre-tokenized
// words for word-level matching.
type DisplayItem struct {
	binding       Binding
	keyText       string
	actionText    string
	categoryText  string
	keyWords      []wordToken
	actionWords   []wordToken
	categoryWords []wordToken
}

// matchInfo stores matched character positions per column for multi-token highlighting
type matchInfo struct {
	keyPositions      []int // matched rune positions in key column
	actionPositions   []int // matched rune positions in action column
	categoryPositions []int // matched rune positions in category column
}

// scoredItem holds ranking data for a single item matching the current query.
type scoredItem struct {
	idx           int
	nMatched      int
	actionScore   int
	keyScore      int
	categoryScore int
	mi            matchInfo
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

// sectionHeader returns a separator line like "  ── label ─────────".
func sectionHeader(label string, width int) string {
	labelWidth := wcswidth.Stringwidth(label)
	sepLen := max(0, width-labelWidth-6)
	sep := strings.Repeat("\u2500", sepLen)
	return fmt.Sprintf("  \u2500\u2500 %s %s", label, sep)
}

// keyDisplayText returns the display string for a binding's key column,
// substituting unmappedLabel for empty keys and truncating to maxKeyDisplayWidth.
func keyDisplayText(b *Binding) string {
	key := b.Key
	if key == "" {
		key = unmappedLabel
	}
	return truncateToWidth(key, maxKeyDisplayWidth)
}

type CachedSettings struct {
	ShowUnmapped bool `json:"show_unmapped"`
}

type Handler struct {
	lp                 *loop.Loop
	screen_size        loop.ScreenSize
	all_items          []DisplayItem
	filtered_idx       []int       // indices into all_items for current results
	match_infos        []matchInfo // parallel to filtered_idx, valid when query != ""
	query              string
	selected_idx       int
	scroll_offset      int
	input_data         InputData
	result             string // action definition to execute after exit
	display_lines      []displayLine
	results_start_y    int
	results_height     int
	show_unmapped      bool
	cv                 *utils.CachedValues[*CachedSettings]
	shortcut_tracker   config.ShortcutTracker
	keyboard_shortcuts []*config.KeyAction
}

// initialize sets up the TUI: screen size, cursor, cached settings, and initial data load.
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

	h.keyboard_shortcuts = config.ResolveShortcuts(NewConfig().KeyboardShortcuts)

	if err := h.loadData(); err != nil {
		return "", err
	}

	h.updateFilter()
	h.draw_screen()
	h.lp.SendOverlayReady()
	return "", nil
}

// loadData reads JSON input data from stdin and flattens it into display items.
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

// bindingToDisplayItem converts a Binding into a DisplayItem with pre-tokenized
// words for word-level matching.
func bindingToDisplayItem(b Binding) DisplayItem {
	keyText := b.Key
	if keyText == "" {
		keyText = unmappedLabel
	}
	actionText := b.ActionDisplay
	if b.Alias != "" {
		actionText = b.Alias + " " + actionText
	}
	return DisplayItem{
		binding:       b,
		keyText:       keyText,
		actionText:    actionText,
		categoryText:  b.Category,
		keyWords:      tokenizeWords(keyText),
		actionWords:   tokenizeWords(actionText),
		categoryWords: tokenizeWords(b.Category),
	}
}

// flattenCategoryBindings appends all bindings from a single category to items.
func flattenCategoryBindings(bindings []Binding, catName, modeName string, items *[]DisplayItem) {
	for _, b := range bindings {
		b.Category = catName
		b.Mode = modeName
		b.IsMouse = false
		*items = append(*items, bindingToDisplayItem(b))
	}
}

// flattenBindings converts the hierarchical mode/category/binding data into
// a flat list suitable for display and word-level scoring. Uses the explicit
// ordering arrays from Python since Go maps do not preserve insertion order.
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
			flattenCategoryBindings(bindings, catName, modeName, &h.all_items)
		}
	}

	// Mouse bindings
	for _, b := range h.input_data.Mouse {
		b.Category = "Mouse actions"
		b.Mode = ""
		b.IsMouse = true
		h.all_items = append(h.all_items, bindingToDisplayItem(b))
	}
}

// updateFilter rebuilds the filtered item list based on the current query.
func (h *Handler) updateFilter() {
	tokens := tokenizeQuery(h.query)

	if len(tokens) == 0 {
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

	var matches []scoredItem
	for i := range h.all_items {
		if !h.show_unmapped && h.all_items[i].binding.Key == "" {
			continue
		}
		item := &h.all_items[i]
		var s scoredItem
		s.idx = i

		for _, qt := range tokens {
			ks, kp := bestWordMatch(qt, item.keyWords, item.keyText)
			as, ap := bestWordMatch(qt, item.actionWords, item.actionText)
			cs, cp := bestWordMatch(qt, item.categoryWords, item.categoryText)

			best := max(ks, max(as, cs))
			if best > 0 {
				s.nMatched++
			}
			s.keyScore += ks
			s.actionScore += as
			s.categoryScore += cs
			s.mi.keyPositions = append(s.mi.keyPositions, kp...)
			s.mi.actionPositions = append(s.mi.actionPositions, ap...)
			s.mi.categoryPositions = append(s.mi.categoryPositions, cp...)
		}

		if s.nMatched > 0 {
			matches = append(matches, s)
		}
	}

	// Sort: most tokens matched > actionScore > keyScore > categoryScore > shorter ActionDisplay
	sort.Slice(matches, func(i, j int) bool {
		if matches[i].nMatched != matches[j].nMatched {
			return matches[i].nMatched > matches[j].nMatched
		}
		if matches[i].actionScore != matches[j].actionScore {
			return matches[i].actionScore > matches[j].actionScore
		}
		if matches[i].keyScore != matches[j].keyScore {
			return matches[i].keyScore > matches[j].keyScore
		}
		if matches[i].categoryScore != matches[j].categoryScore {
			return matches[i].categoryScore > matches[j].categoryScore
		}
		return len(h.all_items[matches[i].idx].binding.ActionDisplay) < len(h.all_items[matches[j].idx].binding.ActionDisplay)
	})

	// Build filtered_idx and match_infos
	h.filtered_idx = make([]int, len(matches))
	h.match_infos = make([]matchInfo, len(matches))
	for i, m := range matches {
		h.filtered_idx[i] = m.idx
		h.match_infos[i] = m.mi
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

// selectedBinding returns the currently selected binding, or nil if none.
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

// draw_screen renders the full palette UI: query input, help bar, and results.
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
	resultsHeight := max(helpY-resultsStartY, 1)

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
		helpStr := truncateToWidth(b.Help, max(width-2, 3))
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
	matchCount := ""
	if h.query != "" {
		matchCount = fmt.Sprintf("  %d/%d", len(h.filtered_idx), len(h.all_items))
	}
	h.lp.QueueWriteString(" " + footer + h.lp.SprintStyled("dim", matchCount))

	// Position cursor at end of search text for typing
	h.lp.MoveCursorTo(3+wcswidth.Stringwidth(h.query), searchBarY)
}

// drawGroupedResults renders results organized by mode and category headers.
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
				if len(lines) > 0 {
					lines = append(lines, displayLine{itemIdx: -1, isHeader: true})
				}
				lines = append(lines, displayLine{
					text:      sectionHeader("Keyboard mode: "+b.Mode, width),
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
			lines = append(lines, displayLine{
				text:     sectionHeader(b.Category, width),
				isHeader: true, itemIdx: -1,
			})
		}

		// Binding line
		keyDisplay := keyDisplayText(b)
		lines = append(lines, displayLine{
			text:    fmt.Sprintf("    %-*s %s", maxKeyDisplayWidth, keyDisplay, item.actionText),
			itemIdx: fi,
		})
	}

	h.display_lines = lines
	h.drawLines(lines, startY, maxRows, width)
}

// drawFlatResults renders a flat list of scored results without category headers.
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
		keyDisplay := keyDisplayText(b)
		catSuffix := ""
		if b.Mode != "" {
			catSuffix = fmt.Sprintf(" [%s/%s]", b.Mode, b.Category)
		} else {
			catSuffix = fmt.Sprintf(" [%s]", b.Category)
		}
		lines = append(lines, displayLine{
			text:    fmt.Sprintf("    %-*s %-30s%s", maxKeyDisplayWidth, keyDisplay, item.actionText, catSuffix),
			itemIdx: fi,
		})
	}

	h.display_lines = lines
	h.drawLines(lines, startY, maxRows, width)
}

// drawLines renders display lines within the visible scroll window.
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
			// Selected item: highlight with reverse video, preserving match highlights
			h.drawBindingLine(li.itemIdx, width, true)
		} else {
			h.drawBindingLine(li.itemIdx, width, false)
		}
	}
}

// drawCategorySuffix renders the " [category]" or " [mode/category]" suffix
// with optional match highlighting.
func (h *Handler) drawCategorySuffix(b *Binding, mi *matchInfo, baseStyle, matchStyle string) {
	styled := func(s string) string {
		if baseStyle != "" {
			return h.lp.SprintStyled(baseStyle, s)
		}
		return s
	}
	prefix := " ["
	if b.Mode != "" {
		prefix = fmt.Sprintf(" [%s/", b.Mode)
	}
	if mi != nil && len(mi.categoryPositions) > 0 {
		h.lp.QueueWriteString(styled(prefix))
		h.lp.QueueWriteString(h.highlightMatchedChars(b.Category, mi.categoryPositions, baseStyle, matchStyle))
		h.lp.QueueWriteString(styled("]"))
	} else {
		h.lp.QueueWriteString(styled(prefix + b.Category + "]"))
	}
}

// categorySuffixWidth returns the display width of the category suffix.
func categorySuffixWidth(b *Binding) int {
	w := 2 + wcswidth.Stringwidth(b.Category) + 1 // " [" + category + "]"
	if b.Mode != "" {
		w += wcswidth.Stringwidth(b.Mode) + 1 // mode + "/"
	}
	return w
}

// drawBindingLine renders a single binding row with key, action, and optional category.
func (h *Handler) drawBindingLine(filteredIdx, width int, isSelected bool) {
	if filteredIdx < 0 || filteredIdx >= len(h.filtered_idx) {
		return
	}
	idx := h.filtered_idx[filteredIdx]
	if idx < 0 || idx >= len(h.all_items) {
		return
	}
	b := &h.all_items[idx].binding
	actionDisplay := h.all_items[idx].actionText

	// Build the key display
	keyDisplay := keyDisplayText(b)

	// Determine match info for highlighting (only set when a query is active)
	var mi *matchInfo
	if h.query != "" && filteredIdx < len(h.match_infos) {
		mi = &h.match_infos[filteredIdx]
	}

	// Style definitions vary based on whether this row is selected
	var matchStyle, keyStyle, unmappedStyle, baseStyle string
	if isSelected {
		matchStyle = "fg=bright-yellow reverse"
		keyStyle = "fg=green reverse"
		unmappedStyle = "dim fg=green reverse"
		baseStyle = "reverse"
	} else {
		matchStyle = "fg=bright-yellow"
		keyStyle = "fg=green"
		unmappedStyle = "dim fg=green"
	}

	// styled applies baseStyle to s when selected, or returns s unchanged.
	styled := func(s string) string {
		if baseStyle != "" {
			return h.lp.SprintStyled(baseStyle, s)
		}
		return s
	}

	// Render key column (4-space indent + key padded to maxKeyDisplayWidth + space)
	paddingLen := max(0, maxKeyDisplayWidth-wcswidth.Stringwidth(keyDisplay))
	pad := strings.Repeat(" ", paddingLen) + " "
	ks := keyStyle
	if b.Key == "" {
		ks = unmappedStyle
	}
	if mi != nil && len(mi.keyPositions) > 0 {
		h.lp.QueueWriteString(styled("    "))
		h.lp.QueueWriteString(h.highlightMatchedChars(keyDisplay, mi.keyPositions, ks, matchStyle))
		h.lp.QueueWriteString(styled(pad))
	} else {
		h.lp.QueueWriteString(h.lp.SprintStyled(ks, "    "+keyDisplay+pad))
	}

	// Render action display column
	if mi != nil && len(mi.actionPositions) > 0 {
		h.lp.QueueWriteString(h.highlightMatchedChars(actionDisplay, mi.actionPositions, baseStyle, matchStyle))
	} else {
		h.lp.QueueWriteString(styled(actionDisplay))
	}

	// Render category suffix (only present in flat / search-results mode)
	if h.query != "" {
		h.drawCategorySuffix(b, mi, baseStyle, matchStyle)
	}

	// For selected rows, pad the rest of the line with reverse video
	if isSelected {
		rendered := 4 + wcswidth.Stringwidth(keyDisplay) + paddingLen + 1 + wcswidth.Stringwidth(actionDisplay)
		if h.query != "" {
			rendered += categorySuffixWidth(b)
		}
		if pad := width - rendered; pad > 0 {
			h.lp.QueueWriteString(h.lp.SprintStyled(baseStyle, strings.Repeat(" ", pad)))
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

// onMouseEvent handles mouse clicks to select and trigger items.
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

// onKeyEvent handles keyboard input for navigation, selection, and query editing.
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
	if ev.MatchesPressOrRepeat("up") {
		ev.Handled = true
		h.moveSelection(-1)
		return nil
	}
	if ev.MatchesPressOrRepeat("down") {
		ev.Handled = true
		h.moveSelection(1)
		return nil
	}
	if ac := h.shortcut_tracker.Match(ev, h.keyboard_shortcuts); ac != nil {
		ev.Handled = true
		switch ac.Name {
		case "selection_up":
			h.moveSelection(-1)
		case "selection_down":
			h.moveSelection(1)
		}
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

// onText handles typed characters, appending them to the search query.
func (h *Handler) onText(text string, from_key_event bool, in_bracketed_paste bool) error {
	h.query += text
	h.updateFilter()
	h.draw_screen()
	return nil
}

// onResize redraws the screen when the terminal is resized.
func (h *Handler) onResize(old, new_size loop.ScreenSize) error {
	h.screen_size = new_size
	h.draw_screen()
	return nil
}

// moveSelection moves the selected item by delta positions, clamping to bounds.
func (h *Handler) moveSelection(delta int) {
	if len(h.filtered_idx) == 0 {
		return
	}
	h.selected_idx += delta
	h.selected_idx = max(0, h.selected_idx)
	h.selected_idx = min(h.selected_idx, len(h.filtered_idx)-1)
	h.draw_screen()
}

// triggerSelected sets the selected binding's definition as the result and exits.
func (h *Handler) triggerSelected() {
	b := h.selectedBinding()
	if b == nil || b.IsMouse {
		h.lp.Beep()
		return
	}
	h.result = b.Definition
	h.lp.Quit(0)
}

// main runs the command palette TUI as a kitty overlay.
func main(cmd *cli.Command, opts *Options, args []string) (rc int, err error) {
	if tty.IsTerminal(os.Stdin.Fd()) {
		return 1, fmt.Errorf("This kitten must only be run via the command_palette action mapped to a shortcut in kitty.conf")
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

// EntryPoint registers the command palette subcommand on the parent CLI.
func EntryPoint(parent *cli.Command) {
	create_cmd(parent, main)
}
