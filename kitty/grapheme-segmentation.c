/*
 * grapheme-segmentation.c
 * Copyright (C) 2025 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#include "text-cache.h"
#include "grapheme-segmentation-data.h"

typedef struct GraphemeSegmentationState {
    GraphemeBreakProperty last_char_prop;

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
#define is_linker_or_extend(incb) ((incb) == ICB_Linker || (incb) == ICB_Extend)

void
grapheme_segmentation_reset(GraphemeSegmentationState *s) {
    *s = (GraphemeSegmentationState){0};
}

bool
grapheme_segmentation_step(GraphemeSegmentationState *s, char_type ch) {
    // Grapheme segmentation as per UAX29-C1-1 as defined in https://www.unicode.org/reports/tr29/
    GraphemeBreakProperty prop = grapheme_break_property(ch);
    IndicConjunctBreak incb = indic_conjunct_break(ch);
    bool add_to_cell = false;
    if (s->last_char_prop == GBP_AtStart) {
        add_to_cell = true;
    } else {
        /* No break between CR and LF (GB3).  */
        if (s->last_char_prop == GBP_CR && prop == GBP_LF) add_to_cell = true;
        /* Break before and after newlines (GB4, GB5).  */
        else if ((s->last_char_prop == GBP_CR || s->last_char_prop == GBP_LF || s->last_char_prop == GBP_Control)
            || (prop == GBP_CR || prop == GBP_LF || prop == GBP_Control)
        ) {}
        /* No break between Hangul syllable sequences (GB6, GB7, GB8).  */
        else if ((s->last_char_prop == GBP_L && (prop == GBP_L || prop == GBP_V || prop == GBP_LV || prop == GBP_LVT))
            || ((s->last_char_prop == GBP_LV || s->last_char_prop == GBP_V) && (prop == GBP_V || prop == GBP_T))
            || ((s->last_char_prop == GBP_LVT || s->last_char_prop == GBP_T) && prop == GBP_T)
        ) add_to_cell = true;
        /* No break before: extending characters or ZWJ (GB9), SpacingMarks (GB9a), Prepend characters (GB9b)  */
        else if (prop == GBP_Extend || prop == GBP_ZWJ || prop == GBP_SpacingMark || s->last_char_prop == GBP_Prepend) add_to_cell = true;
        /* No break within certain combinations of Indic_Conjunct_Break values:
         * Between consonant {extend|linker}* linker {extend|linker}* and consonant (GB9c).  */
        else if (s->incb_consonant_extended_linker_extended && incb == ICB_Consonant) add_to_cell = true;
        /* No break within emoji modifier sequences or emoji zwj sequences (GB11).  */
        else if (s->last_char_prop == GBP_ZWJ && s->emoji_modifier_sequence_before_last_char && is_extended_pictographic(ch)) add_to_cell = true;
        else {} // break everywhere else
    }

    s->incb_consonant_extended_linker = s->incb_consonant_extended && incb == ICB_Linker;
    s->incb_consonant_extended_linker_extended = (s->incb_consonant_extended_linker || (
            s->incb_consonant_extended_linker_extended && is_linker_or_extend(incb)));
    s->incb_consonant_extended = (incb == ICB_Consonant || (
        s->incb_consonant_extended && is_linker_or_extend(incb)));
    s->emoji_modifier_sequence_before_last_char = s->emoji_modifier_sequence;
    s->emoji_modifier_sequence = (s->emoji_modifier_sequence && prop == GBP_Extend) || is_extended_pictographic(ch);
    s->last_char_prop = prop;

    if (prop == GBP_Regional_Indicator) s->ri_count++; else s->ri_count = 0;
    return add_to_cell;
}
