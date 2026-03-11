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
    bool content_dirty;  // terminal output changed, needs re-scan

    // Cached text rendering (avoid calling render_simple_text every frame)
    uint8_t *cached_query_canvas;
    size_t cached_query_width;
    size_t cached_query_height;
    char cached_query_text[512];

    uint8_t *cached_count_canvas;
    size_t cached_count_width;
    size_t cached_count_height;
    char cached_count_text[128];
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
