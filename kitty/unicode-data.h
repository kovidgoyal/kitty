#pragma once

#include <unictype.h>
#include <uninorm.h>

static inline bool
is_combining_char(uint32_t ch) {
    return uc_combining_class(ch) != UC_CCC_NR || uc_is_general_category_withtable(ch, UC_CATEGORY_MASK_Mc | UC_CATEGORY_MASK_Me | UC_CATEGORY_MASK_Mn);
}


static inline bool
is_ignored_char(uint32_t ch) {
    return uc_is_general_category_withtable(ch, UC_CATEGORY_MASK_Cc | UC_CATEGORY_MASK_Cf | UC_CATEGORY_MASK_Cs);
}

static inline bool
is_word_char(uint32_t ch) {
    return uc_is_general_category_withtable(ch, UC_CATEGORY_MASK_L | UC_CATEGORY_MASK_N);
}

static inline bool
is_url_char(uint32_t ch) {
    return ch && !uc_is_general_category_withtable(ch, UC_CATEGORY_MASK_C | UC_CATEGORY_MASK_Z);
}

static inline uint32_t
normalize(uint32_t ch, uint32_t cc1, uint32_t cc2) {
    uint32_t ans = uc_composition(ch, cc1);
    if (ans && cc2) ans = uc_composition(ans, cc2);
    return ans;
}

static inline bool
can_strip_from_end_of_url(uint32_t ch) {
    // remove trailing punctuation
    return (
        (uc_is_general_category_withtable(ch, UC_CATEGORY_MASK_P) && ch != '/') ||
        ch == '>'
    ) ? true : false;
}
