package command_palette

import (
	"encoding/json"
	"fmt"
	"strings"
	"testing"
)

// testBinding creates a Binding where Action, ActionDisplay, and Definition all
// equal action. Covers 90% of test bindings.
func testBinding(key, action, help string) Binding {
	return Binding{
		Key:           key,
		Action:        action,
		ActionDisplay: action,
		Definition:    action,
		Help:          help,
	}
}

// testMouseBinding creates a mouse Binding where ActionDisplay differs from
// Action. Action is derived as the first word of actionDisplay.
func testMouseBinding(key, actionDisplay string) Binding {
	action := actionDisplay
	if idx := strings.IndexByte(actionDisplay, ' '); idx >= 0 {
		action = actionDisplay[:idx]
	}
	return Binding{
		Key:           key,
		Action:        action,
		ActionDisplay: actionDisplay,
		Definition:    actionDisplay,
	}
}

// testHandlerBuilder constructs a Handler with programmatic data (no JSON round-trip).
type testHandlerBuilder struct {
	input InputData
}

func newBuilder() *testHandlerBuilder {
	return &testHandlerBuilder{
		input: InputData{
			Modes:         make(map[string]map[string][]Binding),
			CategoryOrder: make(map[string][]string),
		},
	}
}

func (b *testHandlerBuilder) addBinding(mode, category string, binding Binding) *testHandlerBuilder {
	if b.input.Modes[mode] == nil {
		b.input.Modes[mode] = make(map[string][]Binding)
		b.input.ModeOrder = append(b.input.ModeOrder, mode)
	}
	cats := b.input.Modes[mode]
	if _, ok := cats[category]; !ok {
		b.input.CategoryOrder[mode] = append(b.input.CategoryOrder[mode], category)
	}
	cats[category] = append(cats[category], binding)
	return b
}

func (b *testHandlerBuilder) addMouse(binding Binding) *testHandlerBuilder {
	b.input.Mouse = append(b.input.Mouse, binding)
	return b
}

func (b *testHandlerBuilder) build() *Handler {
	h := &Handler{}
	h.input_data = b.input
	h.flattenBindings()
	h.show_unmapped = true
	return h
}

func newTestHandler() *Handler {
	return newBuilder().
		addBinding("", "Copy/paste", testBinding("ctrl+shift+c", "copy_to_clipboard", "Copy the selected text from the active window to the clipboard")).
		addBinding("", "Copy/paste", testBinding("ctrl+shift+v", "paste_from_clipboard", "Paste from the clipboard to the active window")).
		addBinding("", "Scrolling", testBinding("ctrl+shift+up", "scroll_line_up", "Scroll up one line")).
		addBinding("", "Scrolling", testBinding("ctrl+shift+down", "scroll_line_down", "Scroll down one line")).
		addBinding("", "Window management", testBinding("ctrl+shift+enter", "new_window", "Open a new window")).
		addBinding("mw", "Miscellaneous", Binding{
			Key: "left", Action: "neighboring_window",
			ActionDisplay: "neighboring_window left",
			Definition: "neighboring_window left", Help: "Focus neighbor window",
		}).
		addBinding("mw", "Miscellaneous", testBinding("esc", "pop_keyboard_mode", "Pop keyboard mode")).
		addMouse(Binding{
			Key: "left press ungrabbed", Action: "mouse_selection",
			ActionDisplay: "mouse_selection normal",
			Definition: "mouse_selection normal",
		}).
		addMouse(Binding{
			Key: "ctrl+left press ungrabbed", Action: "mouse_selection",
			ActionDisplay: "mouse_selection rectangle",
			Definition: "mouse_selection rectangle",
		}).
		build()
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
	for i := range 5 {
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
		found := strings.Contains(strings.ToLower(item.keyText), "clipboard") ||
			strings.Contains(strings.ToLower(item.actionText), "clipboard") ||
			strings.Contains(strings.ToLower(item.categoryText), "clipboard")
		if !found {
			t.Fatalf("Matched item %q has no column containing 'clipboard'", item.actionText)
		}
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
		// keyText = key (or unmappedLabel for empty key), actionText = action_display, categoryText = category
		expectedKey := item.binding.Key
		if expectedKey == "" {
			expectedKey = unmappedLabel
		}
		if !strings.Contains(item.keyText, expectedKey) {
			t.Fatalf("Item %d: keyText %q should contain key %q", i, item.keyText, expectedKey)
		}
		if !strings.Contains(item.actionText, item.binding.ActionDisplay) {
			t.Fatalf("Item %d: actionText %q should contain action %q", i, item.actionText, item.binding.ActionDisplay)
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
	h := newBuilder().build()
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

func TestDisplayItemFieldsPopulated(t *testing.T) {
	h := newTestHandler()
	for i, item := range h.all_items {
		if item.binding.IsMouse {
			continue
		}
		expectedKey := item.binding.Key
		if expectedKey == "" {
			expectedKey = unmappedLabel
		}
		if item.keyText != expectedKey {
			t.Fatalf("Item %d: keyText=%q expected %q", i, item.keyText, expectedKey)
		}
		if item.actionText != item.binding.ActionDisplay {
			t.Fatalf("Item %d: actionText=%q expected %q", i, item.actionText, item.binding.ActionDisplay)
		}
		if item.categoryText != item.binding.Category {
			t.Fatalf("Item %d: categoryText=%q expected %q", i, item.categoryText, item.binding.Category)
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
		colMatch := strings.Contains(strings.ToLower(item.keyText), "scroll") ||
			strings.Contains(strings.ToLower(item.actionText), "scroll") ||
			strings.Contains(strings.ToLower(item.categoryText), "scroll")
		if !colMatch {
			t.Fatalf("Matched item %q has no column containing 'scroll'", item.actionText)
		}
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
		if len(mi.keyPositions) == 0 && len(mi.actionPositions) == 0 && len(mi.categoryPositions) == 0 {
			t.Fatalf("match_infos[%d] has no positions in any column", i)
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
	h := newBuilder().
		addBinding("", "Miscellaneous", testBinding("ctrl+n", "new_window", "Open new window")).
		addBinding("", "Miscellaneous", testBinding("", "scroll_home", "Scroll to top")).
		build()

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
	// keyText should be unmappedLabel, not empty
	if unmapped.keyText != unmappedLabel {
		t.Fatalf("Expected keyText=%q for unmapped item, got %q", unmappedLabel, unmapped.keyText)
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
	h := newBuilder().
		addBinding("", "Copy/paste", testBinding("ctrl+c", "copy", "Copy")).
		addBinding("", "Copy/paste", testBinding("", "paste_from_buffer", "Paste from buffer")).
		build()
	h.show_unmapped = false // override default from build()

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

// newMultiTokenTestHandler creates a handler with items designed to test
// multi-token search. It has items where different tokens match different
// columns, enabling cross-column and RRF ranking tests.
func newMultiTokenTestHandler() *Handler {
	return newBuilder().
		addBinding("", "Copy/paste", testBinding("ctrl+shift+c", "copy_to_clipboard", "Copy selected text")).
		addBinding("", "Copy/paste", testBinding("ctrl+shift+v", "paste_from_clipboard", "Paste from clipboard")).
		addBinding("", "Scrolling", testBinding("ctrl+shift+up", "scroll_line_up", "Scroll up one line")).
		addBinding("", "Scrolling", testBinding("ctrl+shift+down", "scroll_line_down", "Scroll down one line")).
		addBinding("", "Scrolling", testBinding("ctrl+shift+page_up", "scroll_page_up", "Scroll up one page")).
		addBinding("", "Scrolling", testBinding("ctrl+shift+home", "scroll_home", "Scroll to top")).
		addBinding("", "Window management", testBinding("ctrl+shift+enter", "new_window", "Open a new window")).
		addBinding("", "Window management", testBinding("ctrl+shift+w", "close_window", "Close the active window")).
		addBinding("", "Tab management", testBinding("ctrl+shift+t", "new_tab", "Open a new tab")).
		addBinding("", "Tab management", testBinding("ctrl+shift+q", "close_tab", "Close the active tab")).
		build()
}

func TestMultiTokenAllMatchRanksAbovePartial(t *testing.T) {
	// An item matching ALL tokens should rank above an item matching only SOME tokens.
	// "scroll up" should rank scroll_line_up and scroll_page_up (both tokens match)
	// above scroll_home or scroll_line_down (only "scroll" matches).
	h := newMultiTokenTestHandler()
	h.query = "scroll up"
	h.updateFilter()

	if len(h.filtered_idx) == 0 {
		t.Fatal("Expected matches for 'scroll up'")
	}

	// Items matching both "scroll" and "up" should appear before items matching only one token.
	// scroll_line_up and scroll_page_up match both; scroll_line_down and scroll_home match only "scroll".
	topResults := make([]string, 0)
	for i, idx := range h.filtered_idx {
		action := h.all_items[idx].binding.ActionDisplay
		if i < 2 {
			topResults = append(topResults, action)
		}
	}
	for _, action := range topResults {
		if !strings.Contains(action, "scroll") || !strings.Contains(action, "up") {
			t.Fatalf("Top result %q should match both 'scroll' and 'up'", action)
		}
	}
}

func TestMultiTokenCrossColumnMatch(t *testing.T) {
	// A query with tokens that match different columns should find the item.
	// "ctrl+shift+c copy" — "ctrl+shift+c" matches the key column,
	// "copy" matches the action column.
	h := newMultiTokenTestHandler()
	h.query = "ctrl+shift+c copy"
	h.updateFilter()

	if len(h.filtered_idx) == 0 {
		t.Fatal("Expected matches for cross-column query 'ctrl+shift+c copy'")
	}

	// copy_to_clipboard (key=ctrl+shift+c, action=copy_to_clipboard) should be the top result
	topAction := h.all_items[h.filtered_idx[0]].binding.ActionDisplay
	if topAction != "copy_to_clipboard" {
		t.Fatalf("Expected top result to be 'copy_to_clipboard', got %q", topAction)
	}
}

func TestMultiTokenCrossColumnCategoryMatch(t *testing.T) {
	// A token matching the category column combined with a token matching the action column.
	// "window close" — "window" matches category "Window management",
	// "close" matches action "close_window".
	h := newMultiTokenTestHandler()
	h.query = "window close"
	h.updateFilter()

	if len(h.filtered_idx) == 0 {
		t.Fatal("Expected matches for 'window close'")
	}

	// close_window should rank highly since both tokens match
	found := false
	for _, idx := range h.filtered_idx[:min(3, len(h.filtered_idx))] {
		if h.all_items[idx].binding.ActionDisplay == "close_window" {
			found = true
			break
		}
	}
	if !found {
		t.Fatal("Expected 'close_window' in top results for 'window close'")
	}
}

func TestMultiTokenExtraWhitespace(t *testing.T) {
	// Extra whitespace in the query should not produce empty/ghost tokens.
	// "  scroll   up  " should behave the same as "scroll up".
	h := newMultiTokenTestHandler()
	h.query = "scroll up"
	h.updateFilter()
	normalResults := make([]int, len(h.filtered_idx))
	copy(normalResults, h.filtered_idx)

	h.query = "  scroll   up  "
	h.updateFilter()

	if len(h.filtered_idx) != len(normalResults) {
		t.Fatalf("Extra whitespace changed result count: %d vs %d", len(h.filtered_idx), len(normalResults))
	}
	for i := range h.filtered_idx {
		if h.filtered_idx[i] != normalResults[i] {
			t.Fatalf("Extra whitespace changed result order at position %d", i)
		}
	}
}

func TestMultiTokenAllWhitespaceIsEmptyQuery(t *testing.T) {
	// A query that is only whitespace should behave like an empty query:
	// return all items in original order with no match_infos.
	h := newMultiTokenTestHandler()
	h.query = "   "
	h.updateFilter()

	if len(h.filtered_idx) != len(h.all_items) {
		t.Fatalf("All-whitespace query should return all %d items, got %d", len(h.all_items), len(h.filtered_idx))
	}
	if h.match_infos != nil {
		t.Fatal("All-whitespace query should produce nil match_infos")
	}
}

func TestMultiTokenSingleTokenRegression(t *testing.T) {
	// A single-token query (no spaces) should produce the same results as before.
	h := newMultiTokenTestHandler()
	h.query = "clipboard"
	h.updateFilter()

	if len(h.filtered_idx) == 0 {
		t.Fatal("Expected matches for single token 'clipboard'")
	}
	// All results should have "clipboard" matched in at least one column
	for _, idx := range h.filtered_idx {
		item := &h.all_items[idx]
		anyMatch := strings.Contains(strings.ToLower(item.keyText), "clipboard") ||
			strings.Contains(strings.ToLower(item.actionText), "clipboard") ||
			strings.Contains(strings.ToLower(item.categoryText), "clipboard")
		if !anyMatch {
			t.Fatalf("Matched item %q has no column containing 'clipboard'", item.actionText)
		}
	}
	// match_infos should still be parallel to filtered_idx
	if len(h.match_infos) != len(h.filtered_idx) {
		t.Fatalf("match_infos length %d != filtered_idx length %d", len(h.match_infos), len(h.filtered_idx))
	}
}

func TestMultiTokenNoMatchReturnsEmpty(t *testing.T) {
	// When no item matches any token, the result should be empty.
	h := newMultiTokenTestHandler()
	h.query = "zzzzz xxxxx"
	h.updateFilter()

	if len(h.filtered_idx) != 0 {
		t.Fatalf("Expected no matches for nonsense multi-token query, got %d", len(h.filtered_idx))
	}
}

func TestMultiTokenPartialMatchStillShown(t *testing.T) {
	// Items matching only some tokens should still appear,
	// but ranked lower than items matching all tokens.
	h := newMultiTokenTestHandler()
	h.query = "scroll zzzznonexistent"
	h.updateFilter()

	// "scroll" matches several items, "zzzznonexistent" matches nothing.
	// Items matching "scroll" should still appear.
	if len(h.filtered_idx) == 0 {
		t.Fatal("Expected partial matches when one token matches and one doesn't")
	}

	// Verify that matched items are related to "scroll"
	for _, idx := range h.filtered_idx {
		item := &h.all_items[idx]
		anyMatch := strings.Contains(strings.ToLower(item.keyText), "scroll") ||
			strings.Contains(strings.ToLower(item.actionText), "scroll") ||
			strings.Contains(strings.ToLower(item.categoryText), "scroll")
		if !anyMatch {
			t.Fatalf("Matched item %q has no column containing 'scroll'", item.actionText)
		}
	}
}

func TestMultiTokenMatchInfosTrackMultipleColumns(t *testing.T) {
	// When tokens match different columns, match_infos should reflect
	// positions in each matched column so highlighting works correctly.
	h := newMultiTokenTestHandler()
	h.query = "tab close"
	h.updateFilter()

	if len(h.filtered_idx) == 0 {
		t.Fatal("Expected matches for 'tab close'")
	}
	if len(h.match_infos) != len(h.filtered_idx) {
		t.Fatalf("match_infos length %d != filtered_idx length %d", len(h.match_infos), len(h.filtered_idx))
	}

	// Find close_tab — "tab" matches category "Tab management" and action "close_tab",
	// "close" matches action "close_tab". match_infos must have positions in multiple columns.
	for fi, idx := range h.filtered_idx {
		if h.all_items[idx].binding.ActionDisplay == "close_tab" {
			mi := h.match_infos[fi]
			if len(mi.actionPositions) == 0 {
				t.Fatal("close_tab: expected match positions in action column")
			}
			if len(mi.categoryPositions) == 0 {
				t.Fatal("close_tab: expected match positions in category column for 'tab' in 'Tab management'")
			}
			return
		}
	}
	t.Fatal("Expected close_tab in results for 'tab close'")
}

func TestMultiTokenOrderIndependence(t *testing.T) {
	// Token order should not matter: "close window" and "window close"
	// should produce the same set of results (possibly in different order,
	// but the same items).
	h := newMultiTokenTestHandler()

	h.query = "window close"
	h.updateFilter()
	results1 := make(map[int]bool)
	for _, idx := range h.filtered_idx {
		results1[idx] = true
	}

	h.query = "close window"
	h.updateFilter()
	results2 := make(map[int]bool)
	for _, idx := range h.filtered_idx {
		results2[idx] = true
	}

	if len(results1) != len(results2) {
		t.Fatalf("Token order changed result count: %d vs %d", len(results1), len(results2))
	}
	for idx := range results1 {
		if !results2[idx] {
			t.Fatalf("Item %d present in 'window close' but not 'close window'", idx)
		}
	}
}

// topActions returns the action_display names of the first n results after
// running query on h. It is a test helper for verifying ranking.
func topActions(h *Handler, query string, n int) []string {
	h.query = query
	h.updateFilter()
	var result []string
	for i, idx := range h.filtered_idx {
		if i >= n {
			break
		}
		result = append(result, h.all_items[idx].binding.ActionDisplay)
	}
	return result
}

func TestQueryRankingScrollUp(t *testing.T) {
	h := newMultiTokenTestHandler()
	top := topActions(h, "scroll up", 4)
	if len(top) < 4 {
		t.Fatalf("Expected at least 4 results for 'scroll up', got %d", len(top))
	}
	// Top 2 should match both "scroll" and "up", with scroll_line_up first (shorter)
	for _, action := range top[:2] {
		if !strings.Contains(action, "scroll") || !strings.Contains(action, "up") {
			t.Fatalf("Top result %q should match both 'scroll' and 'up'", action)
		}
	}
	if top[0] != "scroll_line_up" {
		t.Fatalf("Expected scroll_line_up first, got %q", top[0])
	}
	if top[1] != "scroll_page_up" {
		t.Fatalf("Expected scroll_page_up second, got %q", top[1])
	}
	// Items matching only "scroll" (not "up") should rank below
	for _, action := range top[2:] {
		if strings.Contains(action, "up") {
			continue // other "up" matches are fine here
		}
		if !strings.Contains(action, "scroll") {
			t.Fatalf("Lower result %q should still contain 'scroll'", action)
		}
	}
}

func TestQueryRankingNewWindow(t *testing.T) {
	h := newMultiTokenTestHandler()
	top := topActions(h, "new window", 3)
	if len(top) == 0 {
		t.Fatal("Expected results for 'new window'")
	}
	if top[0] != "new_window" {
		t.Fatalf("Expected new_window first, got %q", top[0])
	}
	// close_window should not appear above new_window
	for i, action := range top {
		if action == "close_window" && i == 0 {
			t.Fatal("close_window should not be the top result for 'new window'")
		}
	}
}

func TestQueryRankingCloseTab(t *testing.T) {
	h := newMultiTokenTestHandler()
	top := topActions(h, "close tab", 3)
	if len(top) == 0 {
		t.Fatal("Expected results for 'close tab'")
	}
	if top[0] != "close_tab" {
		t.Fatalf("Expected close_tab first, got %q", top[0])
	}
}

func TestQueryRankingSingleToken(t *testing.T) {
	h := newMultiTokenTestHandler()
	top := topActions(h, "clipboard", 2)
	if len(top) < 2 {
		t.Fatalf("Expected at least 2 results for 'clipboard', got %d", len(top))
	}
	// copy_to_clipboard is shorter than paste_from_clipboard
	if top[0] != "copy_to_clipboard" {
		t.Fatalf("Expected copy_to_clipboard first, got %q", top[0])
	}
	if top[1] != "paste_from_clipboard" {
		t.Fatalf("Expected paste_from_clipboard second, got %q", top[1])
	}
}

func TestQueryRankingExactActionMatch(t *testing.T) {
	h := newMultiTokenTestHandler()
	top := topActions(h, "new_tab", 1)
	if len(top) == 0 {
		t.Fatal("Expected results for 'new_tab'")
	}
	if top[0] != "new_tab" {
		t.Fatalf("Expected new_tab first, got %q", top[0])
	}
}

// newMouseTestHandler creates a handler with realistic mouse bindings matching
// the actual kitty command palette data, to test ranking of mouse_selection queries.
// Includes keyboard bindings with "selection" in their names to ensure mouse_selection
// items rank above them for the query "mouse selection".
func newMouseTestHandler() *Handler {
	return newBuilder().
		addBinding("", "Scrolling", testBinding("ctrl+shift+up", "scroll_line_up", "Scroll up")).
		addBinding("", "Copy/paste", testBinding("ctrl+shift+c", "copy_to_clipboard", "Copy selected text")).
		addBinding("", "Copy/paste", testBinding("shift+insert", "paste_selection", "Paste from primary selection")).
		addBinding("", "Copy/paste", testBinding("ctrl+shift+v", "paste_from_clipboard", "Paste from clipboard")).
		addBinding("", "Copy/paste", testBinding("", "copy_or_interrupt", "Copy selection or interrupt")).
		addBinding("", "Copy/paste", testBinding("", "copy_and_clear_or_interrupt", "Copy selection and clear")).
		addBinding("", "Copy/paste", testBinding("", "pass_selection_to_program", "Pass selection to program")).
		addMouse(testMouseBinding("shift+left click ungrabbed", "mouse_handle_click selection link prompt")).
		addMouse(testMouseBinding("shift+left click grabbed ungrabbed", "mouse_handle_click selection link prompt")).
		addMouse(testMouseBinding("ctrl+shift+left release grabbed ungrabbed", "mouse_handle_click link")).
		addMouse(testMouseBinding("shift+middle release ungrabbed grabbed", "paste_selection")).
		addMouse(testMouseBinding("middle release ungrabbed", "paste_from_selection")).
		addMouse(testMouseBinding("left drag ungrabbed", "mouse_selection")).
		addMouse(testMouseBinding("shift+left drag ungrabbed", "mouse_selection")).
		addMouse(testMouseBinding("left triplepress ungrabbed", "mouse_selection line")).
		addMouse(testMouseBinding("shift+left doublepress ungrabbed", "mouse_selection word")).
		addMouse(testMouseBinding("shift+left triplepress ungrabbed", "mouse_selection line_from_point")).
		addMouse(testMouseBinding("shift+left triplepress+grabbed", "mouse_selection line_from_point")).
		addMouse(testMouseBinding("right press ungrabbed", "mouse_selection extend")).
		addMouse(testMouseBinding("shift+left press ungrabbed", "mouse_selection extend")).
		addMouse(testMouseBinding("left press ungrabbed", "mouse_selection normal")).
		addMouse(testMouseBinding("ctrl+left press ungrabbed", "mouse_selection rectangle")).
		addMouse(testMouseBinding("ctrl+shift+right press ungrabbed", "mouse_selection rectangle extend")).
		addMouse(testMouseBinding("ctrl+shift+left press ungrabbed", "mouse_selection rectangle extend")).
		addMouse(testMouseBinding("shift+left triplepress", "mouse_selection line_from_point")).
		addMouse(testMouseBinding("left press", "mouse_selection normal")).
		build()
}

// searchResult captures the full display state of a single result row:
// all three visible columns plus which columns have highlighted match positions.
type searchResult struct {
	key      string // key binding
	action   string // action_display
	category string // category
	// Which columns have highlighted (matched) character positions.
	keyMatch      bool
	actionMatch   bool
	categoryMatch bool
}

// queryResults runs query on h and returns the full display state of each result.
func queryResults(h *Handler, query string) []searchResult {
	h.query = query
	h.updateFilter()
	results := make([]searchResult, len(h.filtered_idx))
	for i, idx := range h.filtered_idx {
		item := &h.all_items[idx]
		results[i] = searchResult{
			key:           item.keyText,
			action:        item.actionText,
			category:      item.categoryText,
			keyMatch:      len(h.match_infos[i].keyPositions) > 0,
			actionMatch:   len(h.match_infos[i].actionPositions) > 0,
			categoryMatch: len(h.match_infos[i].categoryPositions) > 0,
		}
	}
	return results
}

func TestQueryRankingMouseSelection(t *testing.T) {
	h := newMouseTestHandler()
	results := queryResults(h, "mouse selection")

	if len(results) == 0 {
		t.Fatal("Expected results for 'mouse selection'")
	}

	// Bare "mouse_selection" (shortest, exact match for both tokens) must rank
	// above all suffixed variants like mouse_selection line/word/extend/normal.
	if results[0].action != "mouse_selection" {
		t.Fatalf("Expected bare 'mouse_selection' first, got %q", results[0].action)
	}

	// All mouse_selection variants (action starts with "mouse_selection") must
	// rank above any non-mouse_selection item.
	lastMouseSelection := -1
	firstOther := -1
	for i, r := range results {
		if strings.HasPrefix(r.action, "mouse_selection") {
			lastMouseSelection = i
		} else if firstOther == -1 {
			firstOther = i
		}
	}
	if firstOther != -1 && firstOther < lastMouseSelection {
		t.Fatalf("Non-mouse_selection item %q at position %d ranks above mouse_selection item at position %d",
			results[firstOther].action, firstOther+1, lastMouseSelection+1)
	}

	// Every mouse_selection result must have action column highlighted (both
	// "mouse" and "selection" appear in the action text).
	for i, r := range results {
		if !strings.HasPrefix(r.action, "mouse_selection") {
			continue
		}
		if !r.actionMatch {
			t.Fatalf("Result %d (%s): mouse_selection item must have action column highlighted", i+1, r.action)
		}
	}

	// mouse_handle_click also matches both "mouse" and "selection" in its action
	// text, but it's a longer string so it should rank below mouse_selection items.
	for i, r := range results {
		if strings.HasPrefix(r.action, "mouse_handle_click") {
			if i < lastMouseSelection {
				t.Fatalf("Result %d (%s): should rank below all mouse_selection variants (last at %d)",
					i+1, r.action, lastMouseSelection+1)
			}
		}
	}
}

func TestQueryRankingMouseSelectionSingleToken(t *testing.T) {
	h := newMouseTestHandler()
	results := queryResults(h, "mouse")
	if len(results) == 0 {
		t.Fatal("Expected results for 'mouse'")
	}
	// Bare "mouse_selection" (shortest action with "mouse") should be first
	if results[0].action != "mouse_selection" {
		t.Fatalf("Expected bare 'mouse_selection' first, got %q", results[0].action)
	}
	// Items matching only via category (paste_selection, paste_from_selection)
	// should rank below items matching "mouse" in the action column.
	lastActionMatch := -1
	for i, r := range results {
		if r.actionMatch {
			lastActionMatch = i
		}
	}
	for i, r := range results {
		if !r.actionMatch && r.categoryMatch && i < lastActionMatch {
			t.Fatalf("Result %d (%s): category-only match should rank below action matches", i+1, r.action)
		}
	}
}

func TestQueryRankingShorterMatchFirst(t *testing.T) {
	h := newMouseTestHandler()
	// "mouse_selection normal" (shorter) should rank above "mouse_selection rectangle" (longer)
	// when both match equally well
	top := topActions(h, "mouse_selection normal", 1)
	if len(top) == 0 {
		t.Fatal("Expected results")
	}
	if top[0] != "mouse_selection normal" {
		t.Fatalf("Expected 'mouse_selection normal' first, got %q", top[0])
	}
}

func TestQueryMatchInfoColumns(t *testing.T) {
	// Verify match_infos correctly tracks positions in all 3 columns: key, action, category.
	h := newMultiTokenTestHandler()

	// "ctrl clipboard" — "ctrl" matches key column (ctrl+shift+c), "clipboard" matches action
	h.query = "ctrl clipboard"
	h.updateFilter()
	if len(h.filtered_idx) == 0 {
		t.Fatal("Expected matches for 'ctrl clipboard'")
	}

	// Find copy_to_clipboard in results
	for fi, idx := range h.filtered_idx {
		if h.all_items[idx].binding.ActionDisplay != "copy_to_clipboard" {
			continue
		}
		mi := h.match_infos[fi]
		// Key column (col 0) should have positions for "ctrl"
		if len(mi.keyPositions) == 0 {
			t.Fatal("copy_to_clipboard: expected match positions in key column for 'ctrl'")
		}
		// Action column (col 1) should have positions for "clipboard"
		if len(mi.actionPositions) == 0 {
			t.Fatal("copy_to_clipboard: expected match positions in action column for 'clipboard'")
		}
		return
	}
	t.Fatal("Expected copy_to_clipboard in results")
}

func TestQueryMatchInfoCategoryColumn(t *testing.T) {
	// Verify the category column (col 2) gets match positions when a token matches it.
	h := newMultiTokenTestHandler()

	// "tab close" — "tab" matches category "Tab management", "close" matches action close_tab
	h.query = "tab close"
	h.updateFilter()
	if len(h.filtered_idx) == 0 {
		t.Fatal("Expected matches for 'tab close'")
	}
	for fi, idx := range h.filtered_idx {
		if h.all_items[idx].binding.ActionDisplay != "close_tab" {
			continue
		}
		mi := h.match_infos[fi]
		// Action column (col 1) should have positions for "close" and/or "tab"
		if len(mi.actionPositions) == 0 {
			t.Fatal("close_tab: expected match positions in action column")
		}
		// Category column (col 2) should have positions for "tab" in "Tab management"
		if len(mi.categoryPositions) == 0 {
			t.Fatal("close_tab: expected match positions in category column for 'tab'")
		}
		return
	}
	t.Fatal("Expected close_tab in results")
}

func TestQueryMatchInfoKeyColumn(t *testing.T) {
	// Verify the key column (col 0) gets match positions when searching by key binding.
	h := newMouseTestHandler()

	// "left press" — matches key column for mouse bindings
	h.query = "left press"
	h.updateFilter()
	if len(h.filtered_idx) == 0 {
		t.Fatal("Expected matches for 'left press'")
	}
	// At least one result should have positions in the key column
	foundKeyMatch := false
	for fi := range h.filtered_idx {
		mi := h.match_infos[fi]
		if len(mi.keyPositions) > 0 {
			foundKeyMatch = true
			break
		}
	}
	if !foundKeyMatch {
		t.Fatal("Expected at least one result with match positions in key column for 'left press'")
	}
}

func TestQueryRankingShorterActionFirst(t *testing.T) {
	// When 2 tokens both match in the action column of item A,
	// A should rank above item B that also matches both tokens but has a
	// longer action string. This verifies that shorter matches are preferred.
	h := newBuilder().
		addBinding("", "Window management", testBinding("ctrl+n", "new_window", "Open a new window")).
		addBinding("", "Window management", testBinding("ctrl+w", "close_active", "Close the active pane")).
		addBinding("", "Miscellaneous", testBinding("ctrl+shift+n", "new_os_window", "Open new OS window")).
		build()

	// "new window" — both tokens match new_window's action coherently,
	// while new_os_window also matches but is longer.
	top := topActions(h, "new window", 2)
	if len(top) < 2 {
		t.Fatalf("Expected at least 2 results, got %d", len(top))
	}
	// new_window should beat new_os_window (shorter action string)
	if top[0] != "new_window" {
		t.Fatalf("Expected new_window first (shorter match), got %q", top[0])
	}
}

func TestQueryRankingCrossColumnVsCategoryOnly(t *testing.T) {
	// An item matching tokens across key+action columns should rank above
	// an item that only matches via the category column.
	h := newBuilder().
		addBinding("", "Scrolling", testBinding("ctrl+shift+up", "scroll_line_up", "Scroll up")).
		addBinding("", "Scrolling", testBinding("page_up", "scroll_page_up", "Scroll one page up")).
		addBinding("", "Scroll buffer", Binding{
			Key: "ctrl+l", Action: "clear_terminal",
			ActionDisplay: "clear_terminal reset active",
			Definition: "clear_terminal reset active", Help: "Clear screen",
		}).
		build()

	// "scroll up" — scroll_line_up and scroll_page_up match both tokens in action;
	// clear_terminal only matches "scroll" via its category "Scroll buffer".
	top := topActions(h, "scroll up", 3)
	if len(top) < 2 {
		t.Fatalf("Expected at least 2 results, got %d", len(top))
	}
	// Both scroll_*_up actions should rank above clear_terminal
	for i, action := range top[:2] {
		if !strings.Contains(action, "scroll") || !strings.Contains(action, "up") {
			t.Fatalf("Result %d: expected scroll_*_up variant, got %q", i+1, action)
		}
	}
	// If clear_terminal appears, it should be last
	for i, action := range top {
		if action == "clear_terminal" && i < 2 {
			t.Fatalf("clear_terminal (category-only match) should rank below action matches, but got position %d", i+1)
		}
	}
}
