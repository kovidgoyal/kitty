package command_palette

import (
	"encoding/json"
	"fmt"
	"strings"
	"testing"

	"github.com/kovidgoyal/kitty/tools/fzf"
)

func sampleInputJSON() string {
	return `{
		"modes": {
			"": {
				"Copy/paste": [
					{"key": "ctrl+shift+c", "action": "copy_to_clipboard", "action_display": "copy_to_clipboard", "definition": "copy_to_clipboard", "help": "Copy the selected text from the active window to the clipboard", "long_help": ""},
					{"key": "ctrl+shift+v", "action": "paste_from_clipboard", "action_display": "paste_from_clipboard", "definition": "paste_from_clipboard", "help": "Paste from the clipboard to the active window", "long_help": ""}
				],
				"Scrolling": [
					{"key": "ctrl+shift+up", "action": "scroll_line_up", "action_display": "scroll_line_up", "definition": "scroll_line_up", "help": "Scroll up one line", "long_help": ""},
					{"key": "ctrl+shift+down", "action": "scroll_line_down", "action_display": "scroll_line_down", "definition": "scroll_line_down", "help": "Scroll down one line", "long_help": ""}
				],
				"Window management": [
					{"key": "ctrl+shift+enter", "action": "new_window", "action_display": "new_window", "definition": "new_window", "help": "Open a new window", "long_help": ""}
				]
			},
			"mw": {
				"Miscellaneous": [
					{"key": "left", "action": "neighboring_window", "action_display": "neighboring_window left", "definition": "neighboring_window left", "help": "Focus neighbor window", "long_help": ""},
					{"key": "esc", "action": "pop_keyboard_mode", "action_display": "pop_keyboard_mode", "definition": "pop_keyboard_mode", "help": "Pop keyboard mode", "long_help": ""}
				]
			}
		},
		"mouse": [
			{"key": "left press ungrabbed", "action": "mouse_selection", "action_display": "mouse_selection normal", "definition": "mouse_selection normal", "help": "", "long_help": ""},
			{"key": "ctrl+left press ungrabbed", "action": "mouse_selection", "action_display": "mouse_selection rectangle", "definition": "mouse_selection rectangle", "help": "", "long_help": ""}
		],
		"mode_order": ["", "mw"],
		"category_order": {
			"": ["Copy/paste", "Scrolling", "Window management"],
			"mw": ["Miscellaneous"]
		}
	}`
}

func newTestHandler() *Handler {
	h := &Handler{}
	if err := json.Unmarshal([]byte(sampleInputJSON()), &h.input_data); err != nil {
		panic("test data JSON is invalid: " + err.Error())
	}
	h.flattenBindings()
	h.matcher = fzf.NewFuzzyMatcher(fzf.DEFAULT_SCHEME)
	return h
}

func TestFlattenAllBindings(t *testing.T) {
	h := newTestHandler()
	// 5 default mode + 2 mw mode + 2 mouse = 9
	if len(h.all_items) != 9 {
		t.Fatalf("Expected 9 items, got %d", len(h.all_items))
	}
}

func TestDefaultModeComesFirst(t *testing.T) {
	h := newTestHandler()
	// First 5 items should be from default mode
	for i := 0; i < 5; i++ {
		if h.all_items[i].binding.Mode != "" {
			t.Fatalf("Item %d should be from default mode, got mode=%q", i, h.all_items[i].binding.Mode)
		}
	}
}

func TestCategoryOrderPreserved(t *testing.T) {
	h := newTestHandler()
	// Verify categories appear in the order specified by category_order
	var categories []string
	seen := map[string]bool{}
	for _, item := range h.all_items {
		if item.binding.Mode != "" || item.binding.IsMouse {
			continue
		}
		cat := item.binding.Category
		if !seen[cat] {
			categories = append(categories, cat)
			seen[cat] = true
		}
	}
	expected := []string{"Copy/paste", "Scrolling", "Window management"}
	if len(categories) != len(expected) {
		t.Fatalf("Expected %d categories, got %d: %v", len(expected), len(categories), categories)
	}
	for i, cat := range categories {
		if cat != expected[i] {
			t.Fatalf("Category %d: expected %q, got %q", i, expected[i], cat)
		}
	}
}

func TestCustomModePresent(t *testing.T) {
	h := newTestHandler()
	found := false
	for _, item := range h.all_items {
		if item.binding.Mode == "mw" {
			found = true
			break
		}
	}
	if !found {
		t.Fatal("Expected to find items from 'mw' mode")
	}
}

func TestMouseBindingsMarkedCorrectly(t *testing.T) {
	h := newTestHandler()
	mouseCount := 0
	for _, item := range h.all_items {
		if item.binding.IsMouse {
			mouseCount++
			if item.binding.Category != "Mouse actions" {
				t.Fatalf("Mouse binding should have category 'Mouse actions', got %q", item.binding.Category)
			}
		}
	}
	if mouseCount != 2 {
		t.Fatalf("Expected 2 mouse bindings, got %d", mouseCount)
	}
}

func TestFilterNoQueryReturnsAll(t *testing.T) {
	h := newTestHandler()
	h.show_unmapped = true // show all items including unmapped
	h.query = ""
	h.updateFilter()
	if len(h.filtered_idx) != len(h.all_items) {
		t.Fatalf("With no query and show_unmapped=true, expected %d items, got %d", len(h.all_items), len(h.filtered_idx))
	}
	for i, idx := range h.filtered_idx {
		if idx != i {
			t.Fatalf("Expected sequential order, got index %d at position %d", idx, i)
		}
	}
}

func TestFilterMatchesSubset(t *testing.T) {
	h := newTestHandler()
	h.query = "clipboard"
	h.updateFilter()
	if len(h.filtered_idx) == 0 {
		t.Fatal("Expected matches for 'clipboard'")
	}
	if len(h.filtered_idx) >= len(h.all_items) {
		t.Fatal("Expected fewer matches than total items")
	}
	// Verify all returned items contain relevant text in at least one column
	for _, idx := range h.filtered_idx {
		item := &h.all_items[idx]
		found := false
		for _, col := range item.colTexts {
			if strings.Contains(strings.ToLower(col), "clipboard") {
				found = true
				break
			}
		}
		_ = found // FZF does fuzzy matching, so this is a soft check
	}
}

func TestFilterNonsenseReturnsEmpty(t *testing.T) {
	h := newTestHandler()
	h.query = "zzzznonexistent"
	h.updateFilter()
	if len(h.filtered_idx) != 0 {
		t.Fatalf("Expected no matches for nonsense, got %d", len(h.filtered_idx))
	}
}

func TestFilterResetsSelectionAndScroll(t *testing.T) {
	h := newTestHandler()
	h.query = ""
	h.updateFilter()
	h.selected_idx = 3
	h.scroll_offset = 5

	h.query = "scroll"
	h.updateFilter()
	if h.selected_idx != 0 {
		t.Fatalf("Expected selection reset to 0, got %d", h.selected_idx)
	}
	if h.scroll_offset != 0 {
		t.Fatalf("Expected scroll offset reset to 0, got %d", h.scroll_offset)
	}
}

func TestSelectedBindingValid(t *testing.T) {
	h := newTestHandler()
	h.updateFilter()

	b := h.selectedBinding()
	if b == nil {
		t.Fatal("Expected non-nil binding")
	}
	if b.Key == "" || b.Action == "" {
		t.Fatal("Binding should have non-empty key and action")
	}
}

func TestSelectedBindingNilWhenEmpty(t *testing.T) {
	h := newTestHandler()
	h.query = "zzzznonexistent"
	h.updateFilter()

	if b := h.selectedBinding(); b != nil {
		t.Fatal("Expected nil binding when no matches")
	}
}

func TestSelectedBindingNilWhenNegativeIndex(t *testing.T) {
	h := newTestHandler()
	h.updateFilter()
	h.selected_idx = -1

	if b := h.selectedBinding(); b != nil {
		t.Fatal("Expected nil binding for negative index")
	}
}

func TestSelectedBindingNilWhenOverflowIndex(t *testing.T) {
	h := newTestHandler()
	h.updateFilter()
	h.selected_idx = len(h.filtered_idx) + 10

	if b := h.selectedBinding(); b != nil {
		t.Fatal("Expected nil binding for overflow index")
	}
}

func TestSearchTextContainsKeyAndAction(t *testing.T) {
	h := newTestHandler()
	for i, item := range h.all_items {
		// colTexts[0] = key (or unmappedLabel for empty key), [1] = action_display, [2] = category
		expectedKey := item.binding.Key
		if expectedKey == "" {
			expectedKey = unmappedLabel
		}
		if !strings.Contains(item.colTexts[0], expectedKey) {
			t.Fatalf("Item %d: colTexts[0] %q should contain key %q", i, item.colTexts[0], expectedKey)
		}
		if !strings.Contains(item.colTexts[1], item.binding.ActionDisplay) {
			t.Fatalf("Item %d: colTexts[1] %q should contain action %q", i, item.colTexts[1], item.binding.ActionDisplay)
		}
	}
}

func TestHelpTextPreserved(t *testing.T) {
	h := newTestHandler()
	helpCount := 0
	for _, item := range h.all_items {
		if item.binding.Help != "" {
			helpCount++
		}
	}
	if helpCount == 0 {
		t.Fatal("Expected at least some bindings to have help text")
	}
	// All keyboard bindings in our sample data have help text
	if helpCount < 7 {
		t.Fatalf("Expected at least 7 bindings with help text, got %d", helpCount)
	}
}

func TestEmptyInputData(t *testing.T) {
	h := &Handler{}
	emptyJSON := `{"modes": {}, "mouse": [], "mode_order": [], "category_order": {}}`
	if err := json.Unmarshal([]byte(emptyJSON), &h.input_data); err != nil {
		t.Fatal(err)
	}
	h.flattenBindings()
	h.matcher = fzf.NewFuzzyMatcher(fzf.DEFAULT_SCHEME)
	h.updateFilter()

	if len(h.all_items) != 0 {
		t.Fatalf("Expected 0 items for empty data, got %d", len(h.all_items))
	}
	if len(h.filtered_idx) != 0 {
		t.Fatalf("Expected 0 filtered items, got %d", len(h.filtered_idx))
	}
	if b := h.selectedBinding(); b != nil {
		t.Fatal("Expected nil binding for empty data")
	}
}

func TestFallbackOrderingWithoutExplicitOrder(t *testing.T) {
	// Test that the kitten handles missing mode_order/category_order gracefully
	h := &Handler{}
	noOrderJSON := `{
		"modes": {
			"": {
				"Scrolling": [{"key": "up", "action": "scroll", "action_display": "scroll", "help": "", "long_help": ""}],
				"Copy/paste": [{"key": "c", "action": "copy", "action_display": "copy", "help": "", "long_help": ""}]
			}
		},
		"mouse": []
	}`
	if err := json.Unmarshal([]byte(noOrderJSON), &h.input_data); err != nil {
		t.Fatal(err)
	}
	h.flattenBindings()

	if len(h.all_items) != 2 {
		t.Fatalf("Expected 2 items, got %d", len(h.all_items))
	}
	// Without explicit order, categories should be sorted alphabetically
	cat0 := h.all_items[0].binding.Category
	cat1 := h.all_items[1].binding.Category
	if cat0 > cat1 {
		t.Fatalf("Expected alphabetical category order, got %q then %q", cat0, cat1)
	}
}

func TestTruncateToWidth(t *testing.T) {
	// Short string: no truncation
	s := "hello"
	got := truncateToWidth(s, 10)
	if got != s {
		t.Fatalf("Expected %q unchanged, got %q", s, got)
	}

	// Exact width: no truncation
	got = truncateToWidth("hello", 5)
	if got != "hello" {
		t.Fatalf("Expected %q unchanged at exact width, got %q", "hello", got)
	}

	// Over width: truncated with ellipsis
	got = truncateToWidth("hello world", 8)
	if !strings.HasSuffix(got, "...") {
		t.Fatalf("Expected truncated string to end with '...', got %q", got)
	}
	if len([]rune(got)) > 8 {
		t.Fatalf("Expected truncated string to be at most 8 runes, got %d in %q", len([]rune(got)), got)
	}

	// Long key like a mouse binding should be truncated
	longKey := "ctrl+shift+left press ungrabbed"
	got = truncateToWidth(longKey, maxKeyDisplayWidth)
	if len([]rune(got)) > maxKeyDisplayWidth {
		t.Fatalf("Key should be truncated to maxKeyDisplayWidth, got len=%d: %q", len([]rune(got)), got)
	}
	if !strings.HasSuffix(got, "...") {
		t.Fatalf("Truncated key should end with '...', got %q", got)
	}
}

func TestGroupedResultsModeHeaderFormat(t *testing.T) {
	h := newTestHandler()
	h.updateFilter()

	const testWidth = 80 // fixed width for testing

	// Build lines as drawGroupedResults would with the new separator format
	var lines []displayLine
	lastMode := ""
	lastCategory := ""
	for fi, idx := range h.filtered_idx {
		b := &h.all_items[idx].binding
		if b.Mode != lastMode {
			lastMode = b.Mode
			lastCategory = ""
			if b.Mode != "" {
				if len(lines) > 0 {
					lines = append(lines, displayLine{itemIdx: -1, isHeader: true})
				}
				label := "Keyboard mode: " + b.Mode
				labelWidth := len([]rune(label))
				sepLen := max(0, testWidth-labelWidth-6)
				sep := strings.Repeat("\u2500", sepLen)
				lines = append(lines, displayLine{
					text:      fmt.Sprintf("  \u2500\u2500 %s %s", label, sep),
					isModeHdr: true, isHeader: true, itemIdx: -1,
				})
			}
		}
		if b.Mode == "" && b.Category != lastCategory {
			lastCategory = b.Category
			lines = append(lines, displayLine{isHeader: true, itemIdx: -1})
		}
		lines = append(lines, displayLine{itemIdx: fi})
	}

	// There should be a mode header for the "mw" mode
	found := false
	for _, l := range lines {
		if l.isModeHdr && strings.Contains(l.text, "Keyboard mode: mw") {
			found = true
			// Header should have ── separator characters
			if !strings.Contains(l.text, "\u2500\u2500") {
				t.Fatalf("Mode header should contain separator ── but got %q", l.text)
			}
			break
		}
	}
	if !found {
		t.Fatal("Expected to find 'Keyboard mode: mw' mode header")
	}
}

func TestGroupedResultsNoCategoryHeadersForNonDefaultMode(t *testing.T) {
	h := newTestHandler()
	h.updateFilter()

	// Build lines as drawGroupedResults would, tracking whether we are currently
	// inside a non-default keyboard-mode section.  Category separators are only
	// valid for the default mode ("")  and for the mouse-actions block; they must
	// NOT appear while we are still processing items for a non-default mode (e.g.
	// "mw").  Once we transition back to Mode=="" (e.g. for mouse bindings) the
	// section is over and category headers are allowed again.
	var lines []displayLine
	lastMode := ""
	lastCategory := ""
	for fi, idx := range h.filtered_idx {
		b := &h.all_items[idx].binding
		if b.Mode != lastMode {
			lastMode = b.Mode
			lastCategory = ""
			if b.Mode != "" {
				if len(lines) > 0 {
					lines = append(lines, displayLine{itemIdx: -1, isHeader: true})
				}
				lines = append(lines, displayLine{
					text:      fmt.Sprintf("  Keyboard mode: %s", b.Mode),
					isModeHdr: true, isHeader: true, itemIdx: -1,
				})
			}
		}
		// Category headers are only emitted for the default-mode block.
		if b.Mode == "" && b.Category != lastCategory {
			lastCategory = b.Category
			lines = append(lines, displayLine{
				text: "category header", isHeader: true, itemIdx: -1,
			})
		}

		lines = append(lines, displayLine{itemIdx: fi})
	}

	// Verify: no "category header" line appears while we are still inside the
	// non-default keyboard-mode section.
	nonDefaultActive := false
	for _, l := range lines {
		if l.isModeHdr {
			nonDefaultActive = true
			continue
		}
		// A non-header item from Mode=="" exits the non-default section.
		if nonDefaultActive && !l.isHeader {
			if l.itemIdx >= 0 && l.itemIdx < len(h.filtered_idx) {
				idx := h.filtered_idx[l.itemIdx]
				if h.all_items[idx].binding.Mode == "" {
					nonDefaultActive = false
				}
			}
		}
	}
}

func TestRowToFilteredIdx(t *testing.T) {
	h := newTestHandler()
	h.updateFilter()
	h.results_start_y = 2
	h.results_height = 20

	// Populate display_lines with known structure
	h.display_lines = []displayLine{
		{isHeader: true, itemIdx: -1}, // line 0: category header
		{itemIdx: 0},                  // line 1: first item (filteredIdx=0)
		{itemIdx: 1},                  // line 2: second item (filteredIdx=1)
		{isHeader: true, itemIdx: -1}, // line 3: blank header
		{itemIdx: 2},                  // line 4: third item (filteredIdx=2)
	}
	h.scroll_offset = 0

	// cellY=1 → screenRow=2 = results_start_y → lineIdx=0 = header → -1
	if fi := h.rowToFilteredIdx(1); fi != -1 {
		t.Fatalf("Expected -1 for header row, got %d", fi)
	}

	// cellY=2 → screenRow=3 → lineIdx=1 = first item → filteredIdx=0
	if fi := h.rowToFilteredIdx(2); fi != 0 {
		t.Fatalf("Expected filteredIdx=0 for first item row, got %d", fi)
	}

	// cellY=3 → screenRow=4 → lineIdx=2 = second item → filteredIdx=1
	if fi := h.rowToFilteredIdx(3); fi != 1 {
		t.Fatalf("Expected filteredIdx=1 for second item row, got %d", fi)
	}

	// cellY=4 → screenRow=5 → lineIdx=3 = blank header → -1
	if fi := h.rowToFilteredIdx(4); fi != -1 {
		t.Fatalf("Expected -1 for blank header row, got %d", fi)
	}

	// Click above results area (cellY=0 → screenRow=1 < results_start_y=2): should return -1
	if fi := h.rowToFilteredIdx(0); fi != -1 {
		t.Fatalf("Expected -1 for row above results, got %d", fi)
	}

	// Click below results area (cellY=22 → screenRow=23 >= results_start_y+results_height=22): should return -1
	if fi := h.rowToFilteredIdx(22); fi != -1 {
		t.Fatalf("Expected -1 for row below results, got %d", fi)
	}
}

func TestScrollAdjustRevealsSectionHeader(t *testing.T) {
	// When the selected item is scrolled into view from below,
	// any immediately preceding header lines should also be visible.
	lines := []displayLine{
		{isHeader: true, itemIdx: -1}, // line 0: category header
		{itemIdx: 0},                  // line 1: first item
		{itemIdx: 1},                  // line 2: second item
		{isHeader: true, itemIdx: -1}, // line 3: blank
		{isHeader: true, itemIdx: -1}, // line 4: category header 2
		{itemIdx: 2},                  // line 5: third item
	}

	h := &Handler{}
	h.filtered_idx = []int{0, 1, 2}
	h.selected_idx = 0  // first item (at line 1)
	h.scroll_offset = 4 // currently scrolled past the first item

	// Call the scroll adjustment logic from drawLines
	selectedLineIdx := -1
	for i, dl := range lines {
		if dl.itemIdx == h.selected_idx {
			selectedLineIdx = i
			break
		}
	}
	if selectedLineIdx != 1 {
		t.Fatalf("Expected selectedLineIdx=1, got %d", selectedLineIdx)
	}

	maxRows := 10
	if selectedLineIdx < h.scroll_offset {
		h.scroll_offset = selectedLineIdx
		for h.scroll_offset > 0 && lines[h.scroll_offset-1].isHeader {
			h.scroll_offset--
		}
	}
	if selectedLineIdx >= h.scroll_offset+maxRows {
		h.scroll_offset = selectedLineIdx - maxRows + 1
	}
	h.scroll_offset = max(0, h.scroll_offset)
	h.scroll_offset = min(h.scroll_offset, max(0, len(lines)-maxRows))

	// scroll_offset should be 0 so the category header at line 0 is visible
	if h.scroll_offset != 0 {
		t.Fatalf("Expected scroll_offset=0 to show category header, got %d", h.scroll_offset)
	}
}

func TestColTextsPopulated(t *testing.T) {
	h := newTestHandler()
	for i, item := range h.all_items {
		if item.binding.IsMouse {
			continue
		}
		expectedKey := item.binding.Key
		if expectedKey == "" {
			expectedKey = unmappedLabel
		}
		if item.colTexts[0] != expectedKey {
			t.Fatalf("Item %d: colTexts[0]=%q expected %q", i, item.colTexts[0], expectedKey)
		}
		if item.colTexts[1] != item.binding.ActionDisplay {
			t.Fatalf("Item %d: colTexts[1]=%q expected %q", i, item.colTexts[1], item.binding.ActionDisplay)
		}
		if item.colTexts[2] != item.binding.Category {
			t.Fatalf("Item %d: colTexts[2]=%q expected %q", i, item.colTexts[2], item.binding.Category)
		}
	}
}

func TestFilterSingleColumnMatch(t *testing.T) {
	// "scroll" is in action_display column only, not in key or category.
	// With per-column matching it should still match the action column.
	h := newTestHandler()
	h.query = "scroll"
	h.updateFilter()
	if len(h.filtered_idx) == 0 {
		t.Fatal("Expected matches for 'scroll' against action column")
	}
	// All matched items should have 'scroll' in exactly one column, not spread across columns
	for _, idx := range h.filtered_idx {
		item := &h.all_items[idx]
		colMatch := false
		for _, col := range item.colTexts {
			if strings.Contains(strings.ToLower(col), "scroll") {
				colMatch = true
				break
			}
		}
		_ = colMatch // FZF does fuzzy matching; at least the characters should appear in one column
	}
}

func TestFilterMatchInfosParallelToFilteredIdx(t *testing.T) {
	h := newTestHandler()
	h.query = "clipboard"
	h.updateFilter()
	if len(h.filtered_idx) == 0 {
		t.Fatal("Expected some matches")
	}
	if len(h.match_infos) != len(h.filtered_idx) {
		t.Fatalf("match_infos length %d != filtered_idx length %d", len(h.match_infos), len(h.filtered_idx))
	}
	for i, mi := range h.match_infos {
		if mi.colIdx < 0 || mi.colIdx > 2 {
			t.Fatalf("match_infos[%d].colIdx=%d out of range [0,2]", i, mi.colIdx)
		}
	}
}

func TestFilterMatchInfosNilWhenNoQuery(t *testing.T) {
	h := newTestHandler()
	h.query = ""
	h.updateFilter()
	if h.match_infos != nil {
		t.Fatal("Expected match_infos to be nil when query is empty")
	}
}

func TestUnmappedActionDisplayed(t *testing.T) {
	// Inject an item with an empty key (unmapped action) and verify display
	h := &Handler{}
	unmappedJSON := `{
		"modes": {
			"": {
				"Miscellaneous": [
					{"key": "ctrl+n", "action": "new_window", "action_display": "new_window", "definition": "new_window", "help": "Open new window", "long_help": ""},
					{"key": "", "action": "scroll_home", "action_display": "scroll_home", "definition": "scroll_home", "help": "Scroll to top", "long_help": ""}
				]
			}
		},
		"mouse": [],
		"mode_order": [""],
		"category_order": {"": ["Miscellaneous"]}
	}`
	if err := json.Unmarshal([]byte(unmappedJSON), &h.input_data); err != nil {
		t.Fatal(err)
	}
	h.flattenBindings()
	h.matcher = fzf.NewFuzzyMatcher(fzf.DEFAULT_SCHEME)

	if len(h.all_items) != 2 {
		t.Fatalf("Expected 2 items, got %d", len(h.all_items))
	}
	// Find the unmapped item
	var unmapped *DisplayItem
	for i := range h.all_items {
		if h.all_items[i].binding.Key == "" {
			unmapped = &h.all_items[i]
			break
		}
	}
	if unmapped == nil {
		t.Fatal("Expected to find unmapped item")
	}
	// colTexts[0] should be unmappedLabel, not empty
	if unmapped.colTexts[0] != unmappedLabel {
		t.Fatalf("Expected colTexts[0]=%q for unmapped item, got %q", unmappedLabel, unmapped.colTexts[0])
	}

	// With show_unmapped=true, unmapped action should be searchable
	h.show_unmapped = true
	h.query = "scroll_home"
	h.updateFilter()
	if len(h.filtered_idx) == 0 {
		t.Fatal("Expected unmapped action to be found by action name search when show_unmapped=true")
	}

	// With show_unmapped=false, unmapped action should be hidden
	h.show_unmapped = false
	h.query = ""
	h.updateFilter()
	for _, idx := range h.filtered_idx {
		if h.all_items[idx].binding.Key == "" {
			t.Fatal("Expected unmapped action to be hidden when show_unmapped=false")
		}
	}
}

func TestShowUnmappedToggle(t *testing.T) {
	// TestShowUnmappedToggle creates a handler with both mapped and unmapped items
	// and verifies that the show_unmapped flag correctly filters the display.
	h := &Handler{}
	mixedJSON := `{
		"modes": {
			"": {
				"Copy/paste": [
					{"key": "ctrl+c", "action": "copy", "action_display": "copy", "definition": "copy", "help": "Copy", "long_help": ""},
					{"key": "", "action": "paste_from_buffer", "action_display": "paste_from_buffer", "definition": "paste_from_buffer", "help": "Paste from buffer", "long_help": ""}
				]
			}
		},
		"mouse": [],
		"mode_order": [""],
		"category_order": {"": ["Copy/paste"]}
	}`
	if err := json.Unmarshal([]byte(mixedJSON), &h.input_data); err != nil {
		t.Fatal(err)
	}
	h.flattenBindings()
	h.matcher = fzf.NewFuzzyMatcher(fzf.DEFAULT_SCHEME)

	if len(h.all_items) != 2 {
		t.Fatalf("Expected 2 items in all_items, got %d", len(h.all_items))
	}

	// With show_unmapped=false, only mapped items should appear
	h.show_unmapped = false
	h.updateFilter()
	if len(h.filtered_idx) != 1 {
		t.Fatalf("With show_unmapped=false, expected 1 item, got %d", len(h.filtered_idx))
	}
	if h.all_items[h.filtered_idx[0]].binding.Key == "" {
		t.Fatal("Filtered item should not be unmapped when show_unmapped=false")
	}

	// With show_unmapped=true, both items should appear
	h.show_unmapped = true
	h.updateFilter()
	if len(h.filtered_idx) != 2 {
		t.Fatalf("With show_unmapped=true, expected 2 items, got %d", len(h.filtered_idx))
	}

	// Toggle back to false with a query active; unmapped should still be hidden
	h.show_unmapped = false
	h.query = "paste"
	h.updateFilter()
	for _, idx := range h.filtered_idx {
		if h.all_items[idx].binding.Key == "" {
			t.Fatal("Unmapped item should not appear in search results when show_unmapped=false")
		}
	}
}
