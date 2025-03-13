/*
 * grapheme-segmentation.h
 * Copyright (C) 2025 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#pragma once

#include "data-types.h"

typedef struct GraphemeSegmentationState {
    int last_char_prop;

    /* True if the last character ends a sequence of Indic_Conjunct_Break
values:  consonant {extend|linker}*  */
    bool incb_consonant_extended;
    /* True if the last character ends a sequence of Indic_Conjunct_Break
values:  consonant {extend|linker}* linker  */
    bool incb_consonant_extended_linker;
    /* True if the last character ends a sequence of Indic_Conjunct_Break
values:  consonant {extend|linker}* linker {extend|linker}*  */
    bool incb_consonant_extended_linker_extended;

    /* True if the last character ends an emoji modifier sequence
       \p{Extended_Pictographic} Extend*.  */
    bool emoji_modifier_sequence;
    /* True if the last character was immediately preceded by an
       emoji modifier sequence   \p{Extended_Pictographic} Extend*.  */
    bool emoji_modifier_sequence_before_last_char;

    /* Number of consecutive regional indicator (RI) characters seen
       immediately before the current point.  */
    size_t ri_count;
} GraphemeSegmentationState;

void grapheme_segmentation_reset(GraphemeSegmentationState *s);
bool grapheme_segmentation_step(GraphemeSegmentationState *s, char_type ch);
