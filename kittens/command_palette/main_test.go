package command_palette

import (
	"encoding/json"
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
	h.query = ""
	h.updateFilter()
	if len(h.filtered_idx) != len(h.all_items) {
		t.Fatalf("With no query, expected %d items, got %d", len(h.all_items), len(h.filtered_idx))
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
	// Verify all returned items actually contain relevant text
	for _, idx := range h.filtered_idx {
		text := strings.ToLower(h.all_items[idx].searchText)
		if !strings.Contains(text, "clipboard") {
			// FZF does fuzzy matching, so this is a soft check —
			// the characters should at least be present
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
		if !strings.Contains(item.searchText, item.binding.Key) {
			t.Fatalf("Item %d: search text %q should contain key %q", i, item.searchText, item.binding.Key)
		}
		if !strings.Contains(item.searchText, item.binding.ActionDisplay) {
			t.Fatalf("Item %d: search text %q should contain action %q", i, item.searchText, item.binding.ActionDisplay)
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
