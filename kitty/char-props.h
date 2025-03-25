/*
 * char-props.h
 * Copyright (C) 2025 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#pragma once

#include "data-types.h"

// CharPropsDeclaration
// Uses 23 bits
typedef union CharProps {
    struct {
        uint8_t shifted_width : 3;
        uint8_t is_extended_pictographic : 1;
        uint8_t grapheme_break : 4;
        uint8_t indic_conjunct_break : 2;
        uint8_t category : 5;
        uint8_t is_emoji : 1;
        uint8_t is_emoji_presentation_base : 1;
        uint8_t is_invalid : 1;
        uint8_t is_non_rendered : 1;
        uint8_t is_symbol : 1;
        uint8_t is_combining_char : 1;
        uint8_t is_word_char : 1;
        uint8_t is_punctuation : 1;
    };
    uint32_t val;
} CharProps;
static_assert(sizeof(CharProps) == sizeof(uint32_t), "Fix the ordering of CharProps");
// EndCharPropsDeclaration


// UCBDeclaration
typedef enum UnicodeCategory {
	UC_Cn,
	UC_Cc,
	UC_Zs,
	UC_Po,
	UC_Sc,
	UC_Ps,
	UC_Pe,
	UC_Sm,
	UC_Pd,
	UC_Nd,
	UC_Lu,
	UC_Sk,
	UC_Pc,
	UC_Ll,
	UC_So,
	UC_Lo,
	UC_Pi,
	UC_Cf,
	UC_No,
	UC_Pf,
	UC_Lt,
	UC_Lm,
	UC_Mn,
	UC_Me,
	UC_Mc,
	UC_Nl,
	UC_Zl,
	UC_Zp,
	UC_Cs,
	UC_Co,
} UnicodeCategory;

// EndUCBDeclaration


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

CharProps char_props_for(char_type ch);
void grapheme_segmentation_reset(GraphemeSegmentationState *s);
bool grapheme_segmentation_step(GraphemeSegmentationState *s, CharProps ch);
static inline int wcwidth_std(CharProps ch) { return (int)ch.shifted_width - 4/*=width_shift*/; }
static inline bool is_private_use(CharProps ch) { return ch.category == UC_Co; }
static inline const char* char_category(CharProps cp) {
#define a(x) case UC_##x: return #x
    switch((UnicodeCategory)cp.category) {
        a(Cn); a(Cc); a(Zs); a(Po); a(Sc); a(Ps); a(Pe); a(Sm); a(Pd); a(Nd); a(Lu); a(Sk); a(Pc); a(Ll); a(So); a(Lo); a(Pi); a(Cf);
        a(No); a(Pf); a(Lt); a(Lm); a(Mn); a(Me); a(Mc); a(Nl); a(Zl); a(Zp); a(Cs); a(Co);
    }
    return "Cn";
#undef a
}
