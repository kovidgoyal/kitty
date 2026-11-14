/*
 * char-props.c
 * Copyright (C) 2025 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#include "char-props.h"
#include "char-props-data.h"

static char_type
ensure_char_in_range(const char_type value) {
    // Branchless: if (value > MAX_UNICODE) value = 0
    const int64_t diff = ((int64_t)value) - ((int64_t)(MAX_UNICODE + 1u));
    // The right shift gives all ones for negative diff and all zeros for positive diff
    const char_type mask = diff >> 63;
    return value & mask;
}

CharProps
char_props_for(char_type ch) {
    ch = ensure_char_in_range(ch);
    return CharProps_t3[CharProps_t2[(CharProps_t1[ch >> CharProps_shift] << CharProps_shift) + (ch & CharProps_mask)]];
}

void
grapheme_segmentation_reset(GraphemeSegmentationResult *s) {
    s->val = 0;
}

GraphemeSegmentationResult
grapheme_segmentation_step(GraphemeSegmentationResult r, CharProps ch) {
    unsigned key = GraphemeSegmentationKey(r, ch);
    unsigned t1 = ((unsigned)GraphemeSegmentationResult_t1[key >> GraphemeSegmentationResult_shift]) << GraphemeSegmentationResult_shift;
    GraphemeSegmentationResult ans = GraphemeSegmentationResult_t2[t1 + (key & GraphemeSegmentationResult_mask)];
    // printf("state: %u gsp: %u -> key: %u t1: %u -> add_to_cell: %u\n", r.state, ch.grapheme_segmentation_property, key, t1, ans.add_to_current_cell);
    return ans;
}
