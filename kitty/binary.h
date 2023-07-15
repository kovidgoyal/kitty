/*
 * Copyright (C) 2023 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#pragma once

#include <stdint.h>

inline static uint16_t le16(const uint8_t b[const static 2]) {
    return b[0]|(uint16_t)b[1]<<8;
}
inline static uint32_t le32(const uint8_t b[const static 4]) {
    return le16(b)|(uint32_t)le16(b+2)<<16;
}
inline static uint64_t le64(const uint8_t b[const static 8]) {
    return le32(b)|(uint64_t)le32(b+4)<<32;
}
inline static void le16b(uint8_t b[const static 2], const uint16_t n) {
    b[0] = n;
    b[1] = n>>8;
}
inline static void le32b(uint8_t b[const static 4], const uint32_t n) {
    le16b(b, n);
    le16b(b+2, n>>16);
}
inline static void le64b(uint8_t b[const static 8], const uint64_t n) {
    le32b(b, n);
    le32b(b+4, n>>32);
}
