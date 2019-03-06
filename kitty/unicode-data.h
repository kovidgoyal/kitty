#pragma once
#include "data-types.h"
#define VS15 1280
#define VS16 1281

bool is_combining_char(char_type ch);
bool is_ignored_char(char_type ch);
bool is_word_char(char_type ch);
bool is_CZ_category(char_type);
bool is_P_category(char_type);
char_type codepoint_for_mark(combining_type m);
combining_type mark_for_codepoint(char_type c);

static inline bool
is_url_char(uint32_t ch) {
    return ch && !is_CZ_category(ch);
}

static inline bool
can_strip_from_end_of_url(uint32_t ch) {
    // remove trailing punctuation
    return (
        (is_P_category(ch) && ch != '/') ||
        ch == '>'
    ) ? true : false;
}
