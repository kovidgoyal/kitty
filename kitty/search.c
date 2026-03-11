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
