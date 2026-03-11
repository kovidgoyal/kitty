# Kitty Native Search - Design Spec

## Overview

A floating search bar rendered natively via OpenGL that searches terminal scrollback content. Activated with Cmd+F, dismissed with Escape. Case-sensitive literal string matching, no regex.

## Requirements

1. **Floating window** - rendered as an OpenGL overlay, not a terminal row or kitten
2. **Browser-like UX** - Cmd+F opens, Escape closes (keeps current scroll position)
3. **Case-sensitive string search** - no regex, "foo" and "Foo" are different
4. **Full scrollback** - searches HistoryBuf + LineBuf (entire scrollback + visible screen)
5. **Firefox-style navigation** - Enter = next match, Shift+Enter = previous match
6. **Top-right positioning** - 8px padding from window edges
7. **Expandable input** - grows with text, wraps at ~60% of window width
8. **Match highlighting** - current match: yellow bg, other matches: muted/dim yellow bg

## Architecture: Native OpenGL Overlay

### Approach

Render the search bar directly in kitty's OpenGL pipeline as a new layer painted after terminal content. All logic in C, integrated into the existing rendering and input systems. No kitten subprocess.

### Components

#### 1. SearchState (new struct, lives on Screen)

```c
typedef struct {
    // Line addressing: history lines are 0..historybuf_count-1 (oldest first),
    // screen lines are historybuf_count..historybuf_count+screen_lines-1.
    // This gives a single absolute coordinate space.
    size_t line;        // absolute line index in the unified space
    size_t column;      // start column (cell index, accounting for wide chars)
    size_t length;      // match length in cells
} SearchMatch;

typedef struct {
    // Query stored as UCS-4 codepoints (matching kitty's internal representation)
    char query_utf8[4096];      // UTF-8 for display in search bar
    size_t query_utf8_len;      // byte length of UTF-8 query
    uint32_t query_ucs4[1024];  // UCS-4 for searching (converted from UTF-8)
    size_t query_ucs4_len;      // codepoint count
    size_t cursor_pos;          // cursor position in UTF-8 bytes (for display)

    // Matches
    SearchMatch *matches;       // dynamic array, sorted by line then column
    size_t match_count;
    size_t match_capacity;
    size_t current_match;       // 0-based index of active match

    // State
    bool is_active;
    bool is_dirty;              // query changed, needs re-scan
    bool render_dirty;          // bar needs re-render
} SearchState;
```

**Memory lifecycle**: `matches` array uses a realloc growth pattern (double capacity when full). Freed on `screen_search_deactivate()` and on Screen destroy. Never freed between re-scans, just reset `match_count = 0` and reuse the buffer.

#### 2. Search Engine (C, UCS-4 codepoint search)

**Text representation**: Kitty stores text internally as UCS-4 (32-bit codepoints) in `CPUCell` arrays. The query is converted from UTF-8 to UCS-4 once per keystroke. Search operates on the UCS-4 codepoint buffer directly, avoiding any Python object overhead.

**Scanning procedure**:
1. Convert query from UTF-8 to UCS-4 (`query_ucs4[]`)
2. Iterate HistoryBuf lines 0..count-1 (oldest to newest)
3. Then iterate LineBuf lines 0..screen_lines-1 (top to bottom)
4. For each line: access the CPUCell array, extract codepoints via `unicode_in_range()` into a scratch buffer
5. Scan the codepoint buffer for `query_ucs4` using a simple linear scan (equivalent to memmem but on uint32_t arrays)
6. For each hit: map the codepoint offset back to a cell column (accounting for wide/CJK characters) and store as SearchMatch
7. Cap at 10,000 matches

**Performance**: Runs synchronously on the main thread. For large scrollbacks (100k+ lines), debounce keystroke-triggered scans with a ~50ms delay to avoid blocking the render loop. Typical scrollback (<10k lines) scans in <5ms with no debounce needed.

**Known limitation**: Cross-line matching is not supported. If a search string spans a soft-wrapped line boundary, it won't be found. This matches the behavior of most terminal search implementations. Explicitly out of scope for v1.

**Alternate screen**: Search works in alternate screen mode (vim, less, etc.) but only searches the alt LineBuf (no history buffer in alt screen).

#### 3. Search Bar Renderer (OpenGL)

- Rendered AFTER main terminal content (new pass in shaders.c)
- Components: rounded rect background, query text, match count ("2 of 15")
- No close button (X) in v1 since mouse interaction is out of scope, Escape/Cmd+F close it
- Reuse existing `ROUNDED_RECT_PROGRAM` shader for the background (already exists in kitty for borders)
- Uses existing glyph/sprite system for text rendering
- Position: top-right, 8px from edges
- Width: min ~200px, grows with text, max ~60% of window width
- Height: grows if text wraps

#### 4. Match Highlighter (GPU cell color override)

- During cell rendering pass, check if visible cells fall within any match
- Use binary search on the sorted `matches` array to find matches overlapping the visible row range, then linear scan within those rows
- Current match: yellow background
- Other matches: muted/dim yellow background (lower opacity)
- No border or outline on any match
- Cell column mapping must account for wide (CJK) characters that occupy 2 cells. The SearchMatch stores cell-based columns (not codepoint offsets), so the highlighter can directly compare cell positions.

## Input Handling

When search is active, ALL keyboard input is intercepted (not sent to the shell):

| Key | Action |
|-----|--------|
| Cmd+F | Toggle search (open if closed, close if open) |
| Printable chars | Insert at cursor position, re-run search |
| Backspace | Delete char before cursor, re-run search |
| Cmd+Backspace | Delete entire query, re-run search |
| Left/Right arrows | Move cursor within query |
| Cmd+Left/Right | Jump to start/end of query |
| Cmd+V | Paste from clipboard into query |
| Cmd+A | Select all text in query |
| Enter | Jump to next match (wraps around) |
| Shift+Enter | Jump to previous match (wraps around) |
| Escape | Close search, keep current scroll position |

**Keybinding**: Default Cmd+F on macOS, Ctrl+Shift+F on Linux/other (avoids conflict with shell Ctrl+F). Users can remap via kitty's standard keybinding system (`map` in kitty.conf). The keybinding maps to a new `toggle_search` action.

When navigating to a match that's off-screen, the terminal scrolls to show it using `screen_history_scroll_to_absolute()`.

## File Changes

### New Files
- `kitty/search.c` - search engine, state management, text scanning, UCS-4 matching
- `kitty/search.h` - SearchState, SearchMatch struct definitions

### Modified Files
- `kitty/screen.h` - add SearchState to Screen struct
- `kitty/screen.c` - init/cleanup search state on screen create/destroy
- `kitty/shaders.c` - add search bar render pass (reuse ROUNDED_RECT_PROGRAM), match highlight logic
- `kitty/keys.c` - intercept key events when search is active
- `kitty/boss.py` - add `toggle_search` action
- `kitty/options/definition.py` - default Cmd+F / Ctrl+Shift+F keybinding
- `kitty/cell_fragment.glsl` or `cell_vertex.glsl` - pass match highlight info to cell rendering

## Search Algorithm

- **Algorithm**: Linear scan on UCS-4 codepoint arrays (equivalent to memmem on uint32_t)
- **Complexity**: O(n) per line, O(total_text) per full scan
- **Performance**: <5ms for typical scrollback, debounce at 50ms for 100k+ lines
- **Match limit**: 10,000 (show "10000+" in counter if exceeded)

## Edge Cases

### Handled
- Empty query: no matches, no highlights, just the empty search bar
- No matches found: display "0 matches" in the bar
- Very long query: input wraps, bar height increases
- Empty scrollback: only search visible screen lines
- Window resize while searching: reposition bar, re-scan
- 10,000+ matches: cap array, show "10000+" in counter
- Match at screen boundary: highlight visible portion
- Alternate screen mode: search alt buffer only, no history
- Wide/CJK characters: match columns stored as cell positions, not codepoint offsets

### Known Limitations (v1)
- Cross-line matching not supported (string spanning soft-wrapped line boundary won't be found)

### Out of Scope (v1)
- Regex search
- Case-insensitive toggle
- Search across multiple windows/tabs
- Search and replace
- Persistent search across tab switches
- Mouse interaction with the search bar
- Customizable highlight colors via config
