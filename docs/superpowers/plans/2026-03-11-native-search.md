# Native Search Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a floating native search bar to kitty that searches terminal scrollback with case-sensitive string matching, rendered as an OpenGL overlay at the top-right of the window.

**Architecture:** All search logic lives in C within a new `SearchState` struct on `Screen`. The search bar is rendered as a post-processing OpenGL pass: `TINT_PROGRAM` for the filled background, `ROUNDED_RECT_PROGRAM` for the border, and `render_simple_text` + `draw_centered_alpha_mask` for text. Match highlights use `TINT_PROGRAM` viewport-clipped rects. Key input is intercepted at the Python level when search is active.

**Tech Stack:** C (search engine, rendering), Python (action dispatch, key interception), GLSL (reuse existing shaders)

**Spec:** `docs/superpowers/specs/2026-03-11-native-search-design.md`

**Key codebase facts (verified):**
- `historybuf_init_line(buf, lnum, line)`: lnum=0 is the NEWEST line, not oldest. Iterate oldest-first with `historybuf_init_line(buf, count - 1 - i, line)`.
- `draw_rounded_rect` with thickness=0 draws NOTHING (alpha=0). It only draws borders. Use `TINT_PROGRAM` for filled rects.
- `render_simple_text(fonts_data, text)` returns a `StringCanvas` with alpha-channel bitmap. Draw with `draw_centered_alpha_mask`.
- `cmd+f` is already bound to `search_scrollback` on macOS (definition.py:4173). We must REPLACE this binding.
- Clipboard: `from kitty.clipboard import get_clipboard_string`
- Window resize: handled in `Window.set_geometry()` which calls `screen.resize()` and watchers.
- `draw_cells_with_layers` is used when `os_window->needs_layers` (transparency, bg image, etc.). `draw_cells_without_layers` is the fast path for opaque windows. We must add search rendering to BOTH paths for correctness.

---

## Chunk 1: SearchState Foundation & Build Integration

### Task 1: Create search.h with data structures

**Files:**
- Create: `kitty/search.h`

- [ ] **Step 1: Create search.h**

```c
// kitty/search.h
#pragma once
#include "data-types.h"

#define SEARCH_MAX_QUERY_UTF8 4096
#define SEARCH_MAX_QUERY_UCS4 1024
#define SEARCH_MAX_MATCHES 10000

typedef struct {
    // Absolute line index in unified coordinate space:
    // 0..historybuf_count-1 = history (0 = oldest)
    // historybuf_count..historybuf_count+screen_lines-1 = visible screen
    size_t line;
    size_t column;   // start column in cell coordinates
    size_t length;   // match length in cells
} SearchMatch;

typedef struct {
    // Query in UTF-8 (for display and rendering)
    char query_utf8[SEARCH_MAX_QUERY_UTF8];
    size_t query_utf8_len;

    // Query in UCS-4 (for searching, matches kitty's internal char_type)
    char_type query_ucs4[SEARCH_MAX_QUERY_UCS4];
    size_t query_ucs4_len;

    // Cursor position in query (UTF-8 byte offset)
    size_t cursor_pos;

    // Match results (dynamic array, sorted by line then column)
    SearchMatch *matches;
    size_t match_count;
    size_t match_capacity;

    // Index of the currently highlighted match (0-based)
    size_t current_match;

    // State flags
    bool is_active;
    bool is_dirty;       // query changed, needs re-scan
    bool render_dirty;   // bar visual needs update
} SearchState;

// API
void search_init(SearchState *state);
void search_destroy(SearchState *state);
void search_activate(SearchState *state);
void search_deactivate(SearchState *state);
bool search_is_active(const SearchState *state);
bool search_set_query(SearchState *state, const char *utf8, size_t utf8_len);
void search_run_scan(SearchState *state, void *screen_ptr);
void search_scroll_to_match(SearchState *state, void *screen_ptr);
```

- [ ] **Step 2: Verify it compiles**

Run: `cd /Users/tomi/kitty && python3 setup.py build`

- [ ] **Step 3: Commit**

```bash
git add kitty/search.h
git commit -m "Add SearchState data structures for native search"
```

### Task 2: Create search.c with init/cleanup and integrate into Screen

**Files:**
- Create: `kitty/search.c`
- Modify: `kitty/screen.h` - include search.h, add SearchState to Screen
- Modify: `kitty/screen.c` - init/cleanup search state

`search.c` is auto-discovered by `setup.py:find_c_files()`.

- [ ] **Step 1: Create search.c**

```c
// kitty/search.c
#include "search.h"
#include <stdlib.h>
#include <string.h>

void
search_init(SearchState *state) {
    memset(state, 0, sizeof(SearchState));
}

void
search_destroy(SearchState *state) {
    free(state->matches);
    memset(state, 0, sizeof(SearchState));
}

void
search_activate(SearchState *state) {
    state->is_active = true;
    state->is_dirty = true;
    state->render_dirty = true;
    state->query_utf8_len = 0;
    state->query_ucs4_len = 0;
    state->query_utf8[0] = '\0';
    state->cursor_pos = 0;
    state->match_count = 0;
    state->current_match = 0;
}

void
search_deactivate(SearchState *state) {
    state->is_active = false;
    state->match_count = 0;
    state->current_match = 0;
    state->query_utf8_len = 0;
    state->query_ucs4_len = 0;
    state->query_utf8[0] = '\0';
    state->cursor_pos = 0;
}

bool
search_is_active(const SearchState *state) {
    return state->is_active;
}
```

- [ ] **Step 2: Add SearchState to Screen struct**

In `kitty/screen.h`, add `#include "search.h"` near other includes, then add `SearchState search;` to the Screen struct (after the `OverlayLine overlay_line` field).

- [ ] **Step 3: Init/cleanup in screen.c**

In `screen.c`:
- In the Screen init function (`new_screen_object` or equivalent): add `search_init(&self->search);`
- In the Screen dealloc function: add `search_destroy(&self->search);`

- [ ] **Step 4: Build and verify**

Run: `cd /Users/tomi/kitty && python3 setup.py build`

- [ ] **Step 5: Commit**

```bash
git add kitty/search.c kitty/search.h kitty/screen.h kitty/screen.c
git commit -m "Integrate SearchState into Screen lifecycle"
```

---

## Chunk 2: Search Engine

### Task 3: UTF-8 to UCS-4 conversion and match storage

**Files:**
- Modify: `kitty/search.c`

- [ ] **Step 1: Add query update function**

```c
bool
search_set_query(SearchState *state, const char *utf8, size_t utf8_len) {
    if (utf8_len >= SEARCH_MAX_QUERY_UTF8) return false;
    memcpy(state->query_utf8, utf8, utf8_len);
    state->query_utf8[utf8_len] = '\0';
    state->query_utf8_len = utf8_len;
    state->cursor_pos = utf8_len;

    // Convert UTF-8 to UCS-4
    state->query_ucs4_len = 0;
    size_t i = 0;
    while (i < utf8_len && state->query_ucs4_len < SEARCH_MAX_QUERY_UCS4) {
        uint32_t cp = 0;
        unsigned char c = (unsigned char)utf8[i];
        if (c < 0x80) {
            cp = c; i += 1;
        } else if (c < 0xE0) {
            cp = (c & 0x1F) << 6;
            if (i + 1 < utf8_len) cp |= ((unsigned char)utf8[i+1] & 0x3F);
            i += 2;
        } else if (c < 0xF0) {
            cp = (c & 0x0F) << 12;
            if (i + 1 < utf8_len) cp |= (((unsigned char)utf8[i+1] & 0x3F) << 6);
            if (i + 2 < utf8_len) cp |= ((unsigned char)utf8[i+2] & 0x3F);
            i += 3;
        } else {
            cp = (c & 0x07) << 18;
            if (i + 1 < utf8_len) cp |= (((unsigned char)utf8[i+1] & 0x3F) << 12);
            if (i + 2 < utf8_len) cp |= (((unsigned char)utf8[i+2] & 0x3F) << 6);
            if (i + 3 < utf8_len) cp |= ((unsigned char)utf8[i+3] & 0x3F);
            i += 4;
        }
        state->query_ucs4[state->query_ucs4_len++] = (char_type)cp;
    }

    state->is_dirty = true;
    state->render_dirty = true;
    return true;
}
```

- [ ] **Step 2: Add match storage helper**

```c
static bool
search_add_match(SearchState *state, size_t line, size_t column, size_t length) {
    if (state->match_count >= SEARCH_MAX_MATCHES) return false;
    if (state->match_count >= state->match_capacity) {
        size_t new_cap = state->match_capacity ? state->match_capacity * 2 : 256;
        SearchMatch *new_buf = realloc(state->matches, new_cap * sizeof(SearchMatch));
        if (!new_buf) return false;
        state->matches = new_buf;
        state->match_capacity = new_cap;
    }
    SearchMatch *m = &state->matches[state->match_count++];
    m->line = line;
    m->column = column;
    m->length = length;
    return true;
}
```

- [ ] **Step 3: Build and verify**

Run: `cd /Users/tomi/kitty && python3 setup.py build`

- [ ] **Step 4: Commit**

```bash
git add kitty/search.c
git commit -m "Add UTF-8 to UCS-4 conversion and match storage"
```

### Task 4: Implement the search scan engine

**Files:**
- Modify: `kitty/search.c`

**IMPORTANT**: `historybuf_init_line(buf, lnum, line)` uses REVERSE indexing: lnum=0 is the NEWEST line. To iterate oldest-to-newest, call with `count - 1 - i`.

- [ ] **Step 1: Add UCS-4 substring search**

```c
// Case-sensitive UCS-4 codepoint search
static const char_type*
ucs4_find(const char_type *haystack, size_t haystack_len,
          const char_type *needle, size_t needle_len) {
    if (needle_len == 0 || needle_len > haystack_len) return NULL;
    size_t limit = haystack_len - needle_len + 1;
    for (size_t i = 0; i < limit; i++) {
        if (haystack[i] == needle[0]) {
            bool match = true;
            for (size_t j = 1; j < needle_len; j++) {
                if (haystack[i + j] != needle[j]) { match = false; break; }
            }
            if (match) return &haystack[i];
        }
    }
    return NULL;
}
```

- [ ] **Step 2: Add per-line scan function**

```c
#include "lineops.h"
#include "screen.h"

// Map a codepoint offset in the extracted text back to a cell column.
// unicode_in_range with include_cc=false outputs one codepoint per base cell,
// skipping continuation cells of multicell characters.
static size_t
codepoint_offset_to_cell_column(const Line *line, size_t cp_offset) {
    size_t cp_idx = 0;
    for (size_t c = 0; c < line->xnum; c++) {
        // Skip continuation cells of multicell chars (same skip logic as unicode_in_range)
        if (line->cpu_cells[c].is_multicell && line->cpu_cells[c].x) continue;
        if (cp_idx == cp_offset) return c;
        cp_idx++;
    }
    return line->xnum;  // past end
}

// Count cells occupied by `num_codepoints` starting from cell `start_cell`
static size_t
count_cells_for_codepoints(const Line *line, size_t start_cell, size_t num_codepoints) {
    size_t cells = 0;
    size_t cps = 0;
    for (size_t c = start_cell; c < line->xnum && cps < num_codepoints; c++) {
        cells++;
        if (line->cpu_cells[c].is_multicell && line->cpu_cells[c].x) continue;
        cps++;
    }
    return cells;
}

static void
search_scan_line(SearchState *state, Line *line, size_t line_idx, ANSIBuf *buf) {
    if (state->query_ucs4_len == 0) return;
    if (state->match_count >= SEARCH_MAX_MATCHES) return;

    // Extract codepoints from the line (no combining chars, no trailing newline)
    buf->len = 0;
    if (!unicode_in_range(line, 0, line->xnum, false, false, false, false, buf)) return;
    if (buf->len == 0) return;

    const char_type *text = buf->buf;
    size_t text_len = buf->len;
    size_t offset = 0;

    while (offset + state->query_ucs4_len <= text_len) {
        const char_type *found = ucs4_find(text + offset, text_len - offset,
                                           state->query_ucs4, state->query_ucs4_len);
        if (!found) break;

        size_t text_pos = (size_t)(found - text);
        size_t cell_col = codepoint_offset_to_cell_column(line, text_pos);
        size_t cell_len = count_cells_for_codepoints(line, cell_col, state->query_ucs4_len);

        if (!search_add_match(state, line_idx, cell_col, cell_len)) break;
        offset = text_pos + state->query_ucs4_len;
    }
}
```

- [ ] **Step 3: Add the full scan function**

```c
void
search_run_scan(SearchState *state, void *screen_ptr) {
    Screen *screen = (Screen*)screen_ptr;
    state->match_count = 0;

    if (state->query_ucs4_len == 0) {
        state->is_dirty = false;
        return;
    }

    ANSIBuf buf = {0};
    size_t history_count = 0;

    // Only scan history when on main screen (not alternate)
    if (screen->linebuf == screen->main_linebuf && screen->historybuf->count > 0) {
        history_count = screen->historybuf->count;
        // IMPORTANT: historybuf_init_line uses reverse indexing (lnum=0 = newest).
        // To iterate oldest-to-newest, use (count - 1 - i) as lnum.
        for (size_t i = 0; i < history_count && state->match_count < SEARCH_MAX_MATCHES; i++) {
            index_type lnum = (index_type)(history_count - 1 - i);
            historybuf_init_line(screen->historybuf, lnum, screen->historybuf->line);
            screen->historybuf->line->xnum = screen->historybuf->xnum;
            search_scan_line(state, screen->historybuf->line, i, &buf);
        }
    }

    // Scan visible screen (top to bottom)
    for (index_type y = 0; y < screen->lines && state->match_count < SEARCH_MAX_MATCHES; y++) {
        linebuf_init_line_at(screen->linebuf, y, screen->linebuf->line);
        search_scan_line(state, screen->linebuf->line, history_count + y, &buf);
    }

    free(buf.buf);
    state->is_dirty = false;

    // Auto-jump to nearest match relative to current scroll position
    if (state->match_count > 0) {
        size_t visible_start;
        if (screen->scrolled_by > 0 && history_count > 0) {
            visible_start = history_count - (size_t)screen->scrolled_by;
        } else {
            visible_start = history_count;
        }
        // Binary search for first match >= visible_start
        size_t lo = 0, hi = state->match_count;
        while (lo < hi) {
            size_t mid = lo + (hi - lo) / 2;
            if (state->matches[mid].line < visible_start) lo = mid + 1;
            else hi = mid;
        }
        // lo is the first match at or after visible_start; pick closest
        if (lo < state->match_count) {
            state->current_match = lo;
        } else {
            state->current_match = state->match_count - 1;  // last match
        }
        search_scroll_to_match(state, screen);
    }
}
```

- [ ] **Step 4: Add scroll-to-match function**

```c
void
search_scroll_to_match(SearchState *state, void *screen_ptr) {
    Screen *screen = (Screen*)screen_ptr;
    if (state->match_count == 0) return;

    SearchMatch *m = &state->matches[state->current_match];
    size_t hist_count = (screen->linebuf == screen->main_linebuf) ? screen->historybuf->count : 0;

    if (m->line < hist_count) {
        // Match is in history. scrolled_by = lines scrolled up from bottom.
        // To show match line, we need: scrolled_by = hist_count - m->line
        // Then offset to center the match on screen.
        size_t lines_from_bottom = hist_count - m->line;
        size_t half_screen = screen->lines / 2;
        unsigned int target;
        if (lines_from_bottom > half_screen) {
            target = (unsigned int)(lines_from_bottom - half_screen);
        } else {
            target = 0;
        }
        if (target > screen->historybuf->count) target = screen->historybuf->count;
        screen_history_scroll_to_absolute(screen, (double)target);
    } else {
        // Match is on screen buffer. Scroll to bottom to make it visible.
        size_t screen_line = m->line - hist_count;
        (void)screen_line;  // The line is in the visible screen area
        if (screen->scrolled_by > 0) {
            screen_history_scroll_to_absolute(screen, 0);
        }
    }
    state->render_dirty = true;
}
```

- [ ] **Step 5: Build and verify**

Run: `cd /Users/tomi/kitty && python3 setup.py build`

Fix any include issues (you'll need `#include "history.h"`, `#include "line-buf.h"` in search.c).

- [ ] **Step 6: Commit**

```bash
git add kitty/search.c
git commit -m "Implement search engine with UCS-4 scanning and scroll-to-match"
```

### Task 5: Expose search functions as Screen Python methods

**Files:**
- Modify: `kitty/screen.c`

- [ ] **Step 1: Add Python wrapper functions in screen.c**

Add before the `methods[]` array:

```c
static PyObject*
screen_search_activate(Screen *self, PyObject *args UNUSED) {
    search_activate(&self->search);
    Py_RETURN_NONE;
}

static PyObject*
screen_search_deactivate(Screen *self, PyObject *args UNUSED) {
    search_deactivate(&self->search);
    Py_RETURN_NONE;
}

static PyObject*
screen_search_set_query(Screen *self, PyObject *args) {
    const char *query;
    Py_ssize_t query_len;
    if (!PyArg_ParseTuple(args, "s#", &query, &query_len)) return NULL;
    if (search_set_query(&self->search, query, (size_t)query_len)) {
        search_run_scan(&self->search, self);
        Py_RETURN_TRUE;
    }
    Py_RETURN_FALSE;
}

static PyObject*
screen_search_is_active(Screen *self, PyObject *args UNUSED) {
    if (search_is_active(&self->search)) Py_RETURN_TRUE;
    Py_RETURN_FALSE;
}

static PyObject*
screen_search_match_count(Screen *self, PyObject *args UNUSED) {
    return PyLong_FromSize_t(self->search.match_count);
}

static PyObject*
screen_search_current_match(Screen *self, PyObject *args UNUSED) {
    return PyLong_FromSize_t(self->search.current_match);
}

static PyObject*
screen_search_next(Screen *self, PyObject *args UNUSED) {
    SearchState *s = &self->search;
    if (s->match_count == 0) Py_RETURN_NONE;
    s->current_match = (s->current_match + 1) % s->match_count;
    search_scroll_to_match(s, self);
    Py_RETURN_NONE;
}

static PyObject*
screen_search_prev(Screen *self, PyObject *args UNUSED) {
    SearchState *s = &self->search;
    if (s->match_count == 0) Py_RETURN_NONE;
    if (s->current_match == 0) s->current_match = s->match_count - 1;
    else s->current_match--;
    search_scroll_to_match(s, self);
    Py_RETURN_NONE;
}
```

- [ ] **Step 2: Register in methods[] array**

```c
{"search_activate", (PyCFunction)screen_search_activate, METH_NOARGS, ""},
{"search_deactivate", (PyCFunction)screen_search_deactivate, METH_NOARGS, ""},
{"search_set_query", (PyCFunction)screen_search_set_query, METH_VARARGS, ""},
{"search_is_active", (PyCFunction)screen_search_is_active, METH_NOARGS, ""},
{"search_match_count", (PyCFunction)screen_search_match_count, METH_NOARGS, ""},
{"search_current_match", (PyCFunction)screen_search_current_match, METH_NOARGS, ""},
{"search_next", (PyCFunction)screen_search_next, METH_NOARGS, ""},
{"search_prev", (PyCFunction)screen_search_prev, METH_NOARGS, ""},
```

- [ ] **Step 3: Build and verify**

Run: `cd /Users/tomi/kitty && python3 setup.py build`

- [ ] **Step 4: Commit**

```bash
git add kitty/screen.c
git commit -m "Expose search functions as Screen Python methods"
```

---

## Chunk 3: Key Input Interception

### Task 6: Add toggle_search action and keybinding

**Files:**
- Modify: `kitty/window.py` - add action + key handler
- Modify: `kitty/boss.py` - intercept keys during search
- Modify: `kitty/options/definition.py` - REPLACE existing cmd+f binding

- [ ] **Step 1: Add search state and methods to Window class (window.py)**

In `Window.__init__`, add:
```python
self._search_query_text: str = ''
```

In the `# actions {{{` section (around line 2229), add after the scrollback actions:

```python
@ac('sc', 'Toggle search overlay for finding text in scrollback')
def toggle_search(self) -> None:
    if self.screen.search_is_active():
        self.screen.search_deactivate()
        self._search_query_text = ''
    else:
        self.screen.search_activate()
        self._search_query_text = ''

def handle_search_key_event(self, ev: KeyEvent) -> bool:
    """Handle a key event when search is active. Returns True if consumed."""
    from kitty.fast_data_types import (
        GLFW_FKEY_ESCAPE, GLFW_FKEY_ENTER, GLFW_FKEY_BACKSPACE,
        GLFW_MOD_SHIFT, GLFW_MOD_SUPER, GLFW_MOD_CONTROL,
        GLFW_PRESS, GLFW_REPEAT,
    )
    import sys

    if ev.action not in (GLFW_PRESS, GLFW_REPEAT):
        return True  # consume release events

    key = ev.key
    mods = ev.mods
    cmd_mod = GLFW_MOD_SUPER if sys.platform == 'darwin' else GLFW_MOD_CONTROL

    # Escape: close search
    if key == GLFW_FKEY_ESCAPE:
        self.screen.search_deactivate()
        self._search_query_text = ''
        return True

    # Enter / Shift+Enter: navigate matches
    if key == GLFW_FKEY_ENTER:
        if mods & GLFW_MOD_SHIFT:
            self.screen.search_prev()
        else:
            self.screen.search_next()
        return True

    # Backspace
    if key == GLFW_FKEY_BACKSPACE:
        if mods & cmd_mod:
            self._search_query_text = ''
        elif self._search_query_text:
            self._search_query_text = self._search_query_text[:-1]
        self.screen.search_set_query(self._search_query_text)
        return True

    # Paste: Cmd+V (macOS) or Ctrl+Shift+V (Linux)
    if key == ord('v') and (mods & cmd_mod):
        from kitty.clipboard import get_clipboard_string
        try:
            text = get_clipboard_string()
            if text:
                text = text.replace('\n', ' ').replace('\r', '')
                self._search_query_text += text
                self.screen.search_set_query(self._search_query_text)
        except Exception:
            pass
        return True

    # Printable text
    if ev.text:
        self._search_query_text += ev.text
        self.screen.search_set_query(self._search_query_text)
        return True

    return True  # consume all keys when search is active
```

- [ ] **Step 2: Intercept keys in boss.py**

In `boss.py`, find `dispatch_possible_special_key` (line ~1640). It currently does:
```python
def dispatch_possible_special_key(self, ev: KeyEvent) -> bool:
    return self.mappings.dispatch_possible_special_key(ev)
```

Replace with:
```python
def dispatch_possible_special_key(self, ev: KeyEvent) -> bool:
    w = self.active_window
    if w is not None and w.screen.search_is_active():
        # Let normal dispatch try first (so Cmd+F can toggle search off)
        if self.mappings.dispatch_possible_special_key(ev):
            return True
        # Route remaining keys to search handler
        return w.handle_search_key_event(ev)
    return self.mappings.dispatch_possible_special_key(ev)
```

- [ ] **Step 3: Replace cmd+f binding in definition.py**

Find the existing binding at line ~4173:
```python
map('Search the scrollback within a pager', 'search_scrollback cmd+f search_scrollback', only='macos')
```

Replace it with:
```python
map('Search in scrollback',
    'toggle_search cmd+f toggle_search',
    only='macos')
map('Search in scrollback',
    'toggle_search ctrl+shift+f toggle_search',
    only='!macos')
```

Also keep the old `search_scrollback` action available but unbound (users can remap if they prefer the pager-based search).

- [ ] **Step 4: Build and test manually**

Run: `cd /Users/tomi/kitty && python3 setup.py build`

Test: Launch kitty. Cmd+F should activate/deactivate search. Type text, press Escape, Enter. Keys should NOT reach the shell while search is active.

- [ ] **Step 5: Commit**

```bash
git add kitty/window.py kitty/boss.py kitty/options/definition.py
git commit -m "Add toggle_search action with key interception"
```

---

## Chunk 4: Match Highlighting

### Task 7: Draw match highlight rectangles

**Files:**
- Modify: `kitty/shaders.c` - add highlight drawing, call from both render paths

Match highlights are drawn as semi-transparent yellow rectangles using `TINT_PROGRAM` with viewport clipping. Drawn after cells but before UI elements.

- [ ] **Step 1: Add draw_search_highlights function to shaders.c**

Add after `draw_visual_bell` (around line 788). Include `#include "search.h"` at the top of shaders.c.

```c
static void
draw_search_highlights(const UIRenderData *ui) {
    Screen *screen = ui->screen;
    SearchState *search = &screen->search;
    if (!search->is_active || search->match_count == 0 || search->query_ucs4_len == 0) return;

    size_t hist_count = (screen->linebuf == screen->main_linebuf) ? screen->historybuf->count : 0;

    // Calculate visible line range in absolute coordinates
    size_t visible_start = (screen->scrolled_by > 0 && hist_count > 0)
        ? (hist_count - (size_t)screen->scrolled_by)
        : hist_count;
    size_t visible_end = visible_start + screen->lines;

    // Binary search for first match in visible range
    size_t lo = 0, hi = search->match_count;
    while (lo < hi) {
        size_t mid = lo + (hi - lo) / 2;
        if (search->matches[mid].line < visible_start) lo = mid + 1;
        else hi = mid;
    }

    unsigned cw = ui->cell_width;
    unsigned ch = ui->cell_height;

    bind_program(TINT_PROGRAM);

    for (size_t i = lo; i < search->match_count; i++) {
        SearchMatch *m = &search->matches[i];
        if (m->line >= visible_end) break;

        unsigned visual_row = (unsigned)(m->line - visible_start);
        unsigned x = ui->screen_left + (unsigned)(m->column * cw);
        unsigned y = ui->screen_top + visual_row * ch;
        unsigned w = (unsigned)(m->length * cw);
        unsigned h = ch;

        // Clamp to screen bounds
        if (x + w > ui->screen_left + ui->screen_width) w = ui->screen_left + ui->screen_width - x;

        bool is_current = (i == search->current_match);

        save_viewport_using_top_left_origin(x, y, w, h, ui->full_framebuffer_height);
        if (is_current) {
            // Bright yellow (premultiplied: rgb * alpha, alpha)
            glUniform4f(tint_program_layout.uniforms.tint_color,
                        srgb_color(249) * 0.5f, srgb_color(226) * 0.5f,
                        srgb_color(175) * 0.5f, 0.5f);
        } else {
            // Dim yellow
            glUniform4f(tint_program_layout.uniforms.tint_color,
                        srgb_color(249) * 0.2f, srgb_color(226) * 0.2f,
                        srgb_color(175) * 0.2f, 0.2f);
        }
        glUniform4f(tint_program_layout.uniforms.edges, -1, 1, 1, -1);
        draw_quad(true, 0);
        restore_viewport();
    }
}
```

- [ ] **Step 2: Call from BOTH render paths**

In `draw_cells_with_layers` (line ~1124), add after positive-refs graphics:
```c
    draw_search_highlights(ui);  // ADD before draw_visual_bell
    draw_visual_bell(ui);
    draw_scrollbar(ui);
    ...
```

In `draw_cells_without_layers` (line ~1111), add after the cell program call:
```c
static void
draw_cells_without_layers(const UIRenderData *ui, ssize_t vao_idx) {
    call_cell_program(CELL_PROGRAM, ui, vao_idx, true, DRAW_BOTH_BG);
    draw_search_highlights(ui);  // ADD
}
```

- [ ] **Step 3: Build and test**

Run: `cd /Users/tomi/kitty && python3 setup.py build`

Test: Generate scrollback, Cmd+F, type a term. Matches should highlight in yellow.

- [ ] **Step 4: Commit**

```bash
git add kitty/shaders.c
git commit -m "Draw search match highlight rectangles via TINT_PROGRAM"
```

---

## Chunk 5: Search Bar Rendering

### Task 8: Draw the search bar (background + border)

**Files:**
- Modify: `kitty/shaders.c`

The background is a filled rect via `TINT_PROGRAM` (since `draw_rounded_rect` with thickness=0 draws nothing). The border uses `ROUNDED_RECT_PROGRAM`.

- [ ] **Step 1: Add draw_search_bar function**

```c
static void
draw_search_bar(const UIRenderData *ui) {
    Screen *screen = ui->screen;
    if (!screen->search.is_active) return;

    unsigned cw = ui->cell_width;
    unsigned ch = ui->cell_height;

    // Calculate bar dimensions
    unsigned min_width = 20 * cw;
    unsigned max_width = (unsigned)(ui->screen_width * 0.6f);
    unsigned query_cells = (unsigned)screen->search.query_ucs4_len;
    if (query_cells < 10) query_cells = 10;
    unsigned content_cells = query_cells + 14;  // space for match count
    unsigned bar_width = content_cells * cw + 24;
    if (bar_width < min_width) bar_width = min_width;
    if (bar_width > max_width) bar_width = max_width;

    unsigned bar_height = ch + 16;
    unsigned padding = 8;

    unsigned bar_left = ui->screen_left + ui->screen_width - bar_width - padding;
    unsigned bar_top = ui->screen_top + padding;

    // 1. Draw filled background using TINT_PROGRAM (dark semi-transparent)
    save_viewport_using_top_left_origin(bar_left, bar_top, bar_width, bar_height,
                                        ui->full_framebuffer_height);
    bind_program(TINT_PROGRAM);
    // Dark gray background, 90% opacity (premultiplied)
    glUniform4f(tint_program_layout.uniforms.tint_color,
                srgb_color(48) * 0.9f, srgb_color(48) * 0.9f, srgb_color(48) * 0.9f, 0.9f);
    glUniform4f(tint_program_layout.uniforms.edges, -1, 1, 1, -1);
    draw_quad(true, 0);
    restore_viewport();

    // 2. Draw rounded border using ROUNDED_RECT_PROGRAM
    Viewport rect = { .left = bar_left, .top = bar_top, .width = bar_width, .height = bar_height };
    draw_rounded_rect(ui->os_window, rect, ui->full_framebuffer_height,
                      1, 8, 0x585b70, 0, 0.0f);  // gray border, thickness_level=1, radius=8

    // 3. Draw text (next task)
}
```

- [ ] **Step 2: Call from both render paths**

Add `draw_search_bar(ui);` after `draw_search_highlights(ui);` in both `draw_cells_with_layers` and `draw_cells_without_layers`.

- [ ] **Step 3: Build and test**

Test: Cmd+F shows a dark rectangle with a rounded border at top-right.

- [ ] **Step 4: Commit**

```bash
git add kitty/shaders.c
git commit -m "Render search bar background and border"
```

### Task 9: Render search bar text

**Files:**
- Modify: `kitty/shaders.c`

Use `render_simple_text(os_window->fonts_data, text)` to render text to a `StringCanvas`, then draw it with `draw_centered_alpha_mask` (same pattern as `draw_resizing_text` in shaders.c ~line 1369).

- [ ] **Step 1: Study the existing pattern**

Read `draw_resizing_text` in shaders.c (around line 1369) and `draw_centered_alpha_mask` (nearby). These show the exact pattern:

```c
// Existing pattern from draw_resizing_text:
StringCanvas rendered = render_simple_text(w->fonts_data, text);
if (rendered.canvas) {
    draw_centered_alpha_mask(width, height, rendered.width, rendered.height,
                             rendered.canvas, opacity);
    free(rendered.canvas);
}
```

`draw_centered_alpha_mask` uploads the bitmap as a texture and draws it centered in the given area using `GRAPHICS_ALPHA_MASK_PROGRAM`.

- [ ] **Step 2: Add text rendering to draw_search_bar**

After drawing the background and border, add:

```c
    // 3. Build display text
    char display_text[512];
    size_t mc = screen->search.match_count;
    size_t cm = screen->search.current_match;
    if (mc > 0 && screen->search.query_utf8_len > 0) {
        if (mc >= SEARCH_MAX_MATCHES) {
            snprintf(display_text, sizeof(display_text), "%.*s   %d+",
                     (int)screen->search.query_utf8_len, screen->search.query_utf8,
                     SEARCH_MAX_MATCHES);
        } else {
            snprintf(display_text, sizeof(display_text), "%.*s   %zu of %zu",
                     (int)screen->search.query_utf8_len, screen->search.query_utf8,
                     cm + 1, mc);
        }
    } else if (screen->search.query_utf8_len > 0) {
        snprintf(display_text, sizeof(display_text), "%.*s   0 matches",
                 (int)screen->search.query_utf8_len, screen->search.query_utf8);
    } else {
        snprintf(display_text, sizeof(display_text), "Search...");
    }

    // 4. Render text to canvas and draw
    // Note: render_simple_text only handles ASCII chars (renders via FreeType).
    // For UTF-8 query text with non-ASCII chars, this will only render the ASCII portion.
    // A more robust approach would use the full cell rendering pipeline, but this works for v1.
    StringCanvas rendered = render_simple_text(ui->os_window->fonts_data, display_text);
    if (rendered.canvas) {
        // Position text inside the bar with left padding
        unsigned text_left = bar_left + 12;
        unsigned text_top = bar_top + (bar_height - (unsigned)rendered.height) / 2;

        // Use GRAPHICS_ALPHA_MASK_PROGRAM to draw the text
        // The draw_centered_alpha_mask function centers in a given area.
        // We need to position at (text_left, text_top) instead.
        // Use the same texture upload + draw pattern but with custom viewport.
        save_viewport_using_top_left_origin(text_left, text_top,
                                            (unsigned)rendered.width, (unsigned)rendered.height,
                                            ui->full_framebuffer_height);
        // Upload texture and draw using the alpha mask pattern from draw_centered_alpha_mask
        load_alpha_mask_texture(rendered.width, rendered.height, rendered.canvas);
        bind_program(GRAPHICS_ALPHA_MASK_PROGRAM);
        // Set text color (light gray)
        glUniform4f(graphics_program_layouts[GRAPHICS_ALPHA_MASK_PROGRAM].uniforms.tint_color,
                    srgb_color(205), srgb_color(214), srgb_color(244), 1.0f);
        draw_quad(true, 0);
        restore_viewport();
        free(rendered.canvas);
    }
```

Note: The exact `load_alpha_mask_texture` and alpha mask program uniform names need to be verified against the existing code in shaders.c. Study `draw_centered_alpha_mask` and `draw_window_number` for the precise API. The implementer should adapt this code to match the exact function signatures available.

- [ ] **Step 3: Build and test**

Test: Cmd+F shows "Search..." placeholder. Typing shows the query and match count.

- [ ] **Step 4: Commit**

```bash
git add kitty/shaders.c
git commit -m "Render search bar text via render_simple_text"
```

---

## Chunk 6: Polish & Edge Cases

### Task 10: Handle resize, alternate screen, and edge cases

**Files:**
- Modify: `kitty/window.py` - re-scan on resize

- [ ] **Step 1: Re-scan search on window resize**

In `window.py`, find the `set_geometry` method (around line 1000). After the `self.screen.resize(...)` call, add:

```python
if self.screen.search_is_active() and self._search_query_text:
    self.screen.search_set_query(self._search_query_text)
```

This re-scans matches after the screen dimensions change.

- [ ] **Step 2: Build and test**

Test: Search for something, then resize the window. Matches should update correctly.

- [ ] **Step 3: Commit**

```bash
git add kitty/window.py
git commit -m "Re-scan search matches on window resize"
```

### Task 11: Final testing

- [ ] **Step 1: Clean build**

```bash
cd /Users/tomi/kitty && python3 setup.py clean && python3 setup.py build
```

- [ ] **Step 2: Run existing tests**

```bash
cd /Users/tomi/kitty && python3 setup.py test
```

Expected: All existing tests pass (no regressions)

- [ ] **Step 3: Manual integration testing checklist**

Test all of these:
1. Cmd+F opens search bar at top-right with "Search..." placeholder
2. Typing updates the query and highlights matches
3. Match count shows "N of M" in the bar
4. Enter jumps to next match, scrolling into history if needed
5. Shift+Enter jumps to previous match
6. Escape closes search, scroll position stays where it is
7. Cmd+F again reopens with empty query
8. Backspace deletes last character
9. Cmd+Backspace clears entire query
10. Cmd+V pastes clipboard text
11. Keys are NOT sent to shell while search is open
12. No matches: shows "0 matches"
13. 10000+ matches: shows "10000+"
14. Works in alternate screen (vim, less) - searches visible only
15. Window resize during search: re-scans correctly
16. Current match = bright yellow, other matches = dim yellow

- [ ] **Step 4: Fix any issues found**

- [ ] **Step 5: Commit**

```bash
git add kitty/search.c kitty/search.h kitty/screen.c kitty/screen.h kitty/shaders.c kitty/window.py kitty/boss.py kitty/options/definition.py
git commit -m "Native search overlay: final fixes"
```
