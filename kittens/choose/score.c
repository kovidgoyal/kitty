/*
 * score.c
 * Copyright (C) 2017 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#include "choose-data-types.h"
#include <stdlib.h>
#include <string.h>
#include <float.h>
#include <stdio.h>

typedef struct {
    len_t *positions_buf;  // buffer to store positions for every char in needle
    len_t **positions;  // Array of pointers into positions_buf
    len_t *positions_count; // Array of counts for positions
    len_t needle_len;  // Length of the needle
    len_t max_haystack_len;  // Max length of a string in the haystack
    len_t haystack_len; // Length of the current string in the haystack
    len_t *address; // Array of offsets into the positions array
    double max_score_per_char;
    uint8_t *level_factors;  // Array of score factors for every character in the current haystack that matches a character in the needle
    text_t *level1, *level2, *level3;  // The characters in the levels
    len_t level1_len, level2_len, level3_len;
    text_t *needle;  // The current needle
    text_t *haystack; //The current haystack
} WorkSpace;

void*
alloc_workspace(len_t max_haystack_len, GlobalData *global) {
    WorkSpace *ans = calloc(1, sizeof(WorkSpace));
    if (ans == NULL) return NULL;
    ans->positions_buf = (len_t*) calloc(global->needle_len, sizeof(len_t) * max_haystack_len);
    ans->positions = (len_t**)calloc(global->needle_len, sizeof(len_t*));
    ans->positions_count = (len_t*)calloc(2*global->needle_len, sizeof(len_t));
    ans->level_factors = (uint8_t*)calloc(max_haystack_len, sizeof(uint8_t));
    if (ans->positions == NULL || ans->positions_buf == NULL || ans->positions_count == NULL || ans->level_factors == NULL) { free_workspace(ans); return NULL; }
    ans->needle = global->needle;
    ans->needle_len = global->needle_len;
    ans->max_haystack_len = max_haystack_len;
    ans->level1 = global->level1; ans->level2 = global->level2; ans->level3 = global->level3;
    ans->level1_len = global->level1_len; ans->level2_len = global->level2_len; ans->level3_len = global->level3_len;
    ans->address = ans->positions_count + sizeof(len_t) * global->needle_len;
    for (len_t i = 0; i < global->needle_len; i++) ans->positions[i] = ans->positions_buf + i * max_haystack_len;
    return ans;
}

#define NUKE(x) free(x); x = NULL;

void*
free_workspace(void *v) {
    WorkSpace *w = (WorkSpace*)v;
    NUKE(w->positions_buf);
    NUKE(w->positions);
    NUKE(w->positions_count);
    NUKE(w->level_factors);
    free(w);
    return NULL;
}

static inline bool
has_char(text_t *text, len_t sz, text_t ch) {
    for(len_t i = 0; i < sz; i++) {
        if(text[i] == ch) return true;
    }
    return false;
}

static inline uint8_t
level_factor_for(text_t current, text_t last, WorkSpace *w) {
    text_t lch = LOWERCASE(last);
    if (has_char(w->level1, w->level1_len, lch)) return 90;
    if (has_char(w->level2, w->level2_len, lch)) return 80;
    if (IS_LOWERCASE(last) && IS_UPPERCASE(current)) return 80; // CamelCase
    if (has_char(w->level3, w->level3_len, lch)) return 70;
    return 0;
}

static void
init_workspace(WorkSpace *w, text_t *haystack, len_t haystack_len) {
    // Calculate the positions and level_factors arrays for the specified haystack
    bool level_factor_calculated = false;
    memset(w->positions_count, 0, sizeof(*(w->positions_count)) * 2 * w->needle_len);
    memset(w->level_factors, 0, sizeof(*(w->level_factors)) * w->max_haystack_len);
    for (len_t i = 0; i < haystack_len; i++) {
        level_factor_calculated = false;
        for (len_t j = 0; j < w->needle_len; j++) {
            if (w->needle[j] == LOWERCASE(haystack[i])) {
                if (!level_factor_calculated) {
                    level_factor_calculated = true;
                    w->level_factors[i] = i > 0 ? level_factor_for(haystack[i], haystack[i-1], w) : 0;
                }
                w->positions[j][w->positions_count[j]++] = i;
            }
        }
    }
    w->haystack = haystack;
    w->haystack_len = haystack_len;
    w->max_score_per_char = (1.0 / haystack_len + 1.0 / w->needle_len) / 2.0;
}


static inline bool
has_atleast_one_match(WorkSpace *w) {
    int p = -1;
    bool found;
    for (len_t i = 0; i < w->needle_len; i++) {
        if (w->positions_count[i] == 0) return false;  // All characters of the needle are not present in the haystack
        found = false;
        for (len_t j = 0; j < w->positions_count[i]; j++) {
            if (w->positions[i][j] > p) { p = w->positions[i][j]; found = true; break; }
        }
        if (!found) return false; // Characters of needle not present in sequence in haystack
    }
    return true;
}

#define POSITION(x) w->positions[x][w->address[x]]

static inline bool
increment_address(WorkSpace *w) {
    len_t pos = w->needle_len - 1;
    while(true) {
        w->address[pos]++;
        if (w->address[pos] < w->positions_count[pos]) return true;
        if (pos == 0) break;
        w->address[pos--] = 0;
    }
    return false;
}

static inline bool
address_is_monotonic(WorkSpace *w) {
    // Check if the character positions pointed to by the current address are monotonic
    for (len_t i = 1; i < w->needle_len; i++) {
        if (POSITION(i) <= POSITION(i-1)) return false;
    }
    return true;
}

static inline double
calc_score(WorkSpace *w) {
    double ans = 0;
    len_t distance, pos;
    for (len_t i = 0; i < w->needle_len; i++) {
        pos = POSITION(i);
        if (i == 0) distance = pos < LEN_MAX ? pos + 1 : LEN_MAX;
        else {
            distance = pos - POSITION(i-1);
            if (distance < 2) {
                ans += w->max_score_per_char; // consecutive characters
                continue;
            }
        }
        if (w->level_factors[pos]) ans += (100 * w->max_score_per_char) / w->level_factors[pos];  // at a special location
        else ans += (0.75 * w->max_score_per_char) / distance;
    }
    return ans;
}

static double
process_item(WorkSpace *w, len_t *match_positions) {
    double highscore = 0, score;
    do {
        if (!address_is_monotonic(w)) continue;
        score = calc_score(w);
        if (score > highscore) {
            highscore = score;
            for (len_t i = 0; i < w->needle_len; i++) match_positions[i] = POSITION(i);
        }
    } while(increment_address(w));
    return highscore;
}

double
score_item(void *v, text_t *haystack, len_t haystack_len, len_t *match_positions) {
    WorkSpace *w = (WorkSpace*)v;
    init_workspace(w, haystack, haystack_len);
    if (!has_atleast_one_match(w)) return 0;
    return process_item(w, match_positions);
}
