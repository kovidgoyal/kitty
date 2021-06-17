#pragma once
#include "data-types.h"
#include "state.h"
#define VS15 1285
#define VS16 1286

bool is_combining_char(char_type ch);
bool is_ignored_char(char_type ch);
bool is_word_char(char_type ch);
bool is_CZ_category(char_type);
bool is_P_category(char_type);
char_type codepoint_for_mark(combining_type m);
combining_type mark_for_codepoint(char_type c);

static inline bool
is_url_char(uint32_t ch) {
    for (size_t i = 0; i < OPT(url_excluded_characters_count); i++)
        if (ch == OPT(url_excluded_characters)[i]) return false;
    return ch && !is_CZ_category(ch);
}

static inline bool
can_strip_from_end_of_url(uint32_t ch) {
    // remove trailing punctuation
    return (is_P_category(ch) && ch != '/' && ch != '&' && ch != '-' && ch != ')' && ch != ']' && ch != '}');
}

static inline bool
is_private_use(char_type ch) {
    return (0xe000 <= ch && ch <= 0xf8ff) || (0xF0000 <= ch && ch <= 0xFFFFF) || (0x100000 <= ch && ch <= 0x10FFFF);
}


static inline bool
is_flag_codepoint(char_type ch) {
    return 0x1F1E6 <= ch && ch <= 0x1F1FF;
}
