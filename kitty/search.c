#include "search.h"
#include "lineops.h"
#include "line.h"
#include "screen.h"
#include <stdlib.h>
#include <string.h>

void
search_init(SearchState *state) {
    memset(state, 0, sizeof(SearchState));
}

void
search_destroy(SearchState *state) {
    free(state->matches);
    free(state->cached_query_canvas);
    free(state->cached_count_canvas);
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
    free(state->cached_query_canvas);
    state->cached_query_canvas = NULL;
    state->cached_query_width = 0;
    state->cached_query_height = 0;
    state->cached_query_text[0] = '\0';
    free(state->cached_count_canvas);
    state->cached_count_canvas = NULL;
    state->cached_count_width = 0;
    state->cached_count_height = 0;
    state->cached_count_text[0] = '\0';
}

bool
search_is_active(const SearchState *state) {
    return state->is_active;
}

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

// Map codepoint index (from unicode_in_range output) to cell column.
// Must replicate unicode_in_range's skipping logic: multicell continuation
// cells AND tab-padding space cells are skipped in the codepoint output.
static size_t
codepoint_offset_to_cell_column(const Line *line, size_t cp_offset) {
    size_t cp_idx = 0;
    for (size_t c = 0; c < line->xnum; c++) {
        if (line->cpu_cells[c].is_multicell && line->cpu_cells[c].x) continue;
        if (cp_idx == cp_offset) return c;
        cp_idx++;
        // Tab: unicode_in_range outputs 1 codepoint but skips trailing space cells
        if (cell_is_char(line->cpu_cells + c, '\t')) {
            while (c + 1 < line->xnum && cell_is_char(line->cpu_cells + c + 1, ' ')) c++;
        }
    }
    return line->xnum;
}

static size_t
count_cells_for_codepoints(const Line *line, size_t start_cell, size_t num_codepoints) {
    size_t cells = 0;
    size_t cps = 0;
    for (size_t c = start_cell; c < line->xnum && cps < num_codepoints; c++) {
        cells++;
        if (line->cpu_cells[c].is_multicell && line->cpu_cells[c].x) continue;
        cps++;
        if (cell_is_char(line->cpu_cells + c, '\t')) {
            while (c + 1 < line->xnum && cell_is_char(line->cpu_cells + c + 1, ' ')) {
                c++;
                cells++;
            }
        }
    }
    return cells;
}

static void
search_scan_line(SearchState *state, Line *line, size_t line_idx, ANSIBuf *buf) {
    if (state->query_ucs4_len == 0) return;
    if (state->match_count >= SEARCH_MAX_MATCHES) return;

    buf->len = 0;
    if (!unicode_in_range(line, 0, line->xnum, false, false, false, false, buf)) return;
    if (buf->len == 0) return;

    const char_type *text = (const char_type*)buf->buf;
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

static bool
query_is_only_whitespace(const char_type *query, size_t len) {
    for (size_t i = 0; i < len; i++) {
        if (query[i] != ' ' && query[i] != '\t') return false;
    }
    return true;
}

void
search_run_scan(SearchState *state, void *screen_ptr) {
    Screen *screen = (Screen*)screen_ptr;

    // Save previous match position to restore after re-scan
    bool had_previous_match = state->match_count > 0 && state->current_match < state->match_count;
    size_t prev_line = 0, prev_column = 0;
    if (had_previous_match) {
        prev_line = state->matches[state->current_match].line;
        prev_column = state->matches[state->current_match].column;
    }

    state->match_count = 0;

    if (state->query_ucs4_len == 0 || query_is_only_whitespace(state->query_ucs4, state->query_ucs4_len)) {
        state->is_dirty = false;
        state->content_dirty = false;
        return;
    }

    ANSIBuf buf = {0};
    size_t history_count = 0;

    if (screen->linebuf == screen->main_linebuf && screen->historybuf && screen->historybuf->count > 0) {
        history_count = screen->historybuf->count;
        for (size_t i = 0; i < history_count && state->match_count < SEARCH_MAX_MATCHES; i++) {
            index_type lnum = (index_type)(history_count - 1 - i);
            historybuf_init_line(screen->historybuf, lnum, screen->historybuf->line);
            screen->historybuf->line->xnum = screen->historybuf->xnum;
            search_scan_line(state, screen->historybuf->line, i, &buf);
        }
    }

    for (index_type y = 0; y < screen->lines && state->match_count < SEARCH_MAX_MATCHES; y++) {
        linebuf_init_line_at(screen->linebuf, y, screen->linebuf->line);
        search_scan_line(state, screen->linebuf->line, history_count + y, &buf);
    }

    free(buf.buf);
    state->is_dirty = false;
    state->content_dirty = false;
    state->render_dirty = true;

    if (state->match_count > 0) {
        if (had_previous_match) {
            // Restore position: find the same match (or closest after it) by line/column
            // History lines shift when new content arrives, so adjust for that
            bool found = false;
            for (size_t i = 0; i < state->match_count; i++) {
                if (state->matches[i].line > prev_line ||
                    (state->matches[i].line == prev_line && state->matches[i].column >= prev_column)) {
                    state->current_match = i;
                    found = true;
                    break;
                }
            }
            if (!found) {
                // Previous match was past all current matches, wrap to end
                state->current_match = state->match_count - 1;
            }
        } else {
            // First scan: set current_match to the first match visible on screen
            size_t visible_start;
            if (screen->scrolled_by > 0 && history_count > 0 && (size_t)screen->scrolled_by <= history_count) {
                visible_start = history_count - (size_t)screen->scrolled_by;
            } else {
                visible_start = history_count;
            }
            size_t visible_end = visible_start + screen->lines;
            size_t lo = 0, hi = state->match_count;
            while (lo < hi) {
                size_t mid = lo + (hi - lo) / 2;
                if (state->matches[mid].line < visible_start) lo = mid + 1;
                else hi = mid;
            }
            if (lo < state->match_count && state->matches[lo].line < visible_end) {
                state->current_match = lo;
            } else {
                state->current_match = 0;
            }
        }
    }
}

void
search_scroll_to_match(SearchState *state, void *screen_ptr) {
    Screen *screen = (Screen*)screen_ptr;
    if (state->match_count == 0) return;

    SearchMatch *m = &state->matches[state->current_match];
    size_t hist_count = (screen->linebuf == screen->main_linebuf) ? screen->historybuf->count : 0;

    if (m->line < hist_count) {
        // scrolled_by = N means viewport top is at unified line (hist_count - N)
        // To center match at line L: hist_count - N + half_screen = L
        // So N = hist_count - L + half_screen
        size_t half_screen = screen->lines / 2;
        size_t target = hist_count - m->line + half_screen;
        if (target > screen->historybuf->count) target = screen->historybuf->count;
        screen_history_scroll_to_absolute(screen, (double)target);
    } else {
        // Match is on the visible screen buffer
        size_t screen_line = m->line - hist_count;
        if (screen->scrolled_by > 0 && screen_line < (size_t)screen->scrolled_by) {
            // Match is hidden behind scroll, unscroll enough to show it
            screen_history_scroll_to_absolute(screen, 0);
        }
    }
    state->render_dirty = true;
}
