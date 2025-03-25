/*
 * char-props.c
 * Copyright (C) 2025 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#include "char-props.h"
#include "char-props-data.h"


#define is_linker_or_extend(incb) ((incb) == ICB_Linker || (incb) == ICB_Extend)

CharProps
char_props_for(char_type ch) {
    return CharProps_t3[CharProps_t2[(CharProps_t1[ch >> CharProps_shift] << CharProps_shift) + (ch & CharProps_mask)]];
}

void
grapheme_segmentation_reset(GraphemeSegmentationState *s) {
    *s = (GraphemeSegmentationState){0};
}

bool
grapheme_segmentation_step(GraphemeSegmentationState *s, CharProps ch) {
    // Grapheme segmentation as per UAX29-C1-1 as defined in https://www.unicode.org/reports/tr29/
    // Returns true iff ch should be added to the current cell based on s which
    // must reflect the state of the current cell. s is updated by ch.
    GraphemeBreakProperty prop = ch.grapheme_break;
    IndicConjunctBreak incb = ch.indic_conjunct_break;
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
        else if (s->last_char_prop == GBP_ZWJ && s->emoji_modifier_sequence_before_last_char && ch.is_extended_pictographic) add_to_cell = true;
        /* No break between RI if there is an odd number of RI characters before (GB12, GB13).  */
        else if (prop == GBP_Regional_Indicator && (s->ri_count % 2) != 0) add_to_cell = true;
        /* Break everywhere else */
        else {}
    }

    s->incb_consonant_extended_linker = s->incb_consonant_extended && incb == ICB_Linker;
    s->incb_consonant_extended_linker_extended = (s->incb_consonant_extended_linker || (
            s->incb_consonant_extended_linker_extended && is_linker_or_extend(incb)));
    s->incb_consonant_extended = (incb == ICB_Consonant || (
        s->incb_consonant_extended && is_linker_or_extend(incb)));
    s->emoji_modifier_sequence_before_last_char = s->emoji_modifier_sequence;
    s->emoji_modifier_sequence = (s->emoji_modifier_sequence && prop == GBP_Extend) || ch.is_extended_pictographic;
    s->last_char_prop = prop;

    if (prop == GBP_Regional_Indicator) s->ri_count++; else s->ri_count = 0;
    return add_to_cell;
}

