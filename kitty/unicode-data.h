#pragma once

#include <unictype.h>

static inline bool 
is_combining_char(uint32_t ch) {
    return uc_combining_class(ch) != UC_CCC_NR;
}
    

static inline bool 
is_ignored_char(uint32_t ch) {
    return uc_is_general_category_withtable(ch, UC_CATEGORY_MASK_Cc | UC_CATEGORY_MASK_Cf | UC_CATEGORY_MASK_Cs);
}

static inline bool 
is_word_char(uint32_t ch) {
    return uc_is_general_category_withtable(ch, UC_CATEGORY_MASK_L | UC_CATEGORY_MASK_N);
}
