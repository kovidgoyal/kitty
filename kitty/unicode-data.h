#pragma once
#include "data-types.h"
#include "state.h"
#include "char-props.h"

// Converts row/column diacritics to numbers.
int diacritic_to_num(char_type ch);

static inline bool
is_excluded_from_url(uint32_t ch) {
    if (OPT(url_excluded_characters)) {
        for (const char_type *p = OPT(url_excluded_characters); *p; p++) {
            if (ch == *p) return true;
        }
    }
    return false;
}

static inline bool
is_url_legal_char(uint32_t ch) {
    START_ALLOW_CASE_RANGE
    // See https://url.spec.whatwg.org/#url-code-points
    if (ch < 0xa0) {
        switch (ch) {
            case '!': case '$': case '&': case '\'': case '/': case ':': case ';': case '@': case '_': case '~':
            case '(': case ')': case '*': case '+': case ',': case '-': case '.': case '=': case '?': case '%': case '#':
            case 'a' ... 'z':
            case 'A' ... 'Z':
            case '0' ... '9':
                return true;
            default:
                return false;
        }
    }
    if (ch > 0x10fffd) return false;  // outside valid unicode range
    if (0xd800 <= ch && ch <= 0xdfff) return false; // leading or trailing surrogate
    // non-characters
    switch (ch) {
        case 0xfdd0 ... 0xfdef:
        case 0xFFFE: case 0xFFFF: case 0x1FFFE: case 0x1FFFF: case 0x2FFFE: case 0x2FFFF:
        case 0x3FFFE: case 0x3FFFF: case 0x4FFFE: case 0x4FFFF: case 0x5FFFE: case 0x5FFFF:
        case 0x6FFFE: case 0x6FFFF: case 0x7FFFE: case 0x7FFFF: case 0x8FFFE: case 0x8FFFF:
        case 0x9FFFE: case 0x9FFFF: case 0xAFFFE: case 0xAFFFF: case 0xBFFFE: case 0xBFFFF:
        case 0xCFFFE: case 0xCFFFF: case 0xDFFFE: case 0xDFFFF: case 0xEFFFE: case 0xEFFFF:
        case 0xFFFFE: case 0xFFFFF:
            return false;
        default:
            return true;
    }
    END_ALLOW_CASE_RANGE
}

static inline bool
is_url_char(uint32_t ch) {
    return is_url_legal_char(ch) && !is_excluded_from_url(ch);
}

static inline bool
can_strip_from_end_of_url(uint32_t ch) {
    // remove trailing punctuation
    return (char_props_for(ch).is_punctuation && ch != '/' && ch != '&' && ch != '-' && ch != ')' && ch != ']' && ch != '}');
}

static inline bool
is_flag_codepoint(char_type ch) {
    return 0x1F1E6 <= ch && ch <= 0x1F1FF;
}
