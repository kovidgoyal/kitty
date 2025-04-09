/*
 * char-props.h
 * Copyright (C) 2025 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#pragma once

#include "data-types.h"

// CharPropsDeclaration: uses 23 bits {{{
typedef union CharProps {
    struct __attribute__((packed)) {
#if __BYTE_ORDER__ == __ORDER_BIG_ENDIAN__
        uint8_t is_extended_pictographic : 1;
        uint8_t indic_conjunct_break : 2;
        uint8_t grapheme_break : 4;
        uint8_t is_punctuation : 1;
        uint8_t is_word_char : 1;
        uint8_t is_combining_char : 1;
        uint8_t is_symbol : 1;
        uint8_t is_non_rendered : 1;
        uint8_t is_invalid : 1;
        uint8_t is_emoji_presentation_base : 1;
        uint8_t category : 5;
        uint8_t is_emoji : 1;
        uint8_t shifted_width : 3;
        uint16_t : 9;
#elif __BYTE_ORDER__ == __ORDER_LITTLE_ENDIAN__
        uint16_t : 9;
        uint8_t shifted_width : 3;
        uint8_t is_emoji : 1;
        uint8_t category : 5;
        uint8_t is_emoji_presentation_base : 1;
        uint8_t is_invalid : 1;
        uint8_t is_non_rendered : 1;
        uint8_t is_symbol : 1;
        uint8_t is_combining_char : 1;
        uint8_t is_word_char : 1;
        uint8_t is_punctuation : 1;
        uint8_t grapheme_break : 4;
        uint8_t indic_conjunct_break : 2;
        uint8_t is_extended_pictographic : 1;
#else
#error "Unsupported endianness"
#endif
    };
    struct __attribute__((packed)) {
#if __BYTE_ORDER__ == __ORDER_BIG_ENDIAN__
        uint8_t grapheme_segmentation_property : 7;
        uint32_t : 25;
#elif __BYTE_ORDER__ == __ORDER_LITTLE_ENDIAN__
        uint32_t : 25;
        uint8_t grapheme_segmentation_property : 7;
#else
#error "Unsupported endianness"
#endif
    };
    uint32_t val;
} CharProps;
static_assert(sizeof(CharProps) == sizeof(uint32_t), "Fix the ordering of CharProps");
// EndCharPropsDeclaration }}}

// GraphemeSegmentationResultDeclaration: uses 10 bits {{{
typedef union GraphemeSegmentationResult {
    struct __attribute__((packed)) {
#if __BYTE_ORDER__ == __ORDER_BIG_ENDIAN__
        uint8_t emoji_modifier_sequence_before_last_char : 1;
        uint8_t emoji_modifier_sequence : 1;
        uint8_t incb_consonant_extended_linker_extended : 1;
        uint8_t incb_consonant_extended_linker : 1;
        uint8_t incb_consonant_extended : 1;
        uint8_t grapheme_break : 4;
        uint8_t add_to_current_cell : 1;
        uint8_t : 6;
#elif __BYTE_ORDER__ == __ORDER_LITTLE_ENDIAN__
        uint8_t : 6;
        uint8_t add_to_current_cell : 1;
        uint8_t grapheme_break : 4;
        uint8_t incb_consonant_extended : 1;
        uint8_t incb_consonant_extended_linker : 1;
        uint8_t incb_consonant_extended_linker_extended : 1;
        uint8_t emoji_modifier_sequence : 1;
        uint8_t emoji_modifier_sequence_before_last_char : 1;
#else
#error "Unsupported endianness"
#endif
    };
    struct __attribute__((packed)) {
#if __BYTE_ORDER__ == __ORDER_BIG_ENDIAN__
        uint16_t state : 9;
        uint8_t : 7;
#elif __BYTE_ORDER__ == __ORDER_LITTLE_ENDIAN__
        uint8_t : 7;
        uint16_t state : 9;
#else
#error "Unsupported endianness"
#endif
    };
    uint16_t val;
} GraphemeSegmentationResult;
static_assert(sizeof(GraphemeSegmentationResult) == sizeof(uint16_t), "Fix the ordering of GraphemeSegmentationResult");
// EndGraphemeSegmentationResultDeclaration }}}

// UCBDeclaration {{{
#define MAX_UNICODE (1114111u)
typedef enum GraphemeBreakProperty {
	GBP_AtStart,
	GBP_None,
	GBP_Prepend,
	GBP_CR,
	GBP_LF,
	GBP_Control,
	GBP_Extend,
	GBP_Regional_Indicator,
	GBP_SpacingMark,
	GBP_L,
	GBP_V,
	GBP_T,
	GBP_LV,
	GBP_LVT,
	GBP_ZWJ,
	GBP_Private_Expecting_RI,
} GraphemeBreakProperty;

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

// EndUCBDeclaration }}}


CharProps char_props_for(char_type ch);
void grapheme_segmentation_reset(GraphemeSegmentationResult *s);
GraphemeSegmentationResult grapheme_segmentation_step(GraphemeSegmentationResult r, CharProps ch);
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
