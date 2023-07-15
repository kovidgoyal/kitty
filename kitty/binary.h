/*
 * Copyright (C) 2023 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#pragma once

#include <stdint.h>

#if __BYTE_ORDER__ == __ORDER_LITTLE_ENDIAN__
inline static uint16_t le16(const uint8_t b[sizeof(uint16_t)]) { return *((uint16_t*)b); }
inline static uint16_t le32(const uint8_t b[sizeof(uint32_t)]) { return *((uint32_t*)b); }
inline static uint16_t le64(const uint8_t b[sizeof(uint64_t)]) { return *((uint64_t*)b); }
inline static void le16b(uint8_t b[sizeof(uint16_t)], const uint16_t n) { *((uint16_t*)b) = n; }
inline static void le32b(uint8_t b[sizeof(uint32_t)], const uint32_t n) { *((uint32_t*)b) = n; }
inline static void le64b(uint8_t b[sizeof(uint64_t)], const uint64_t n) { *((uint64_t*)b) = n; }
#else
inline static uint16_t le16(const uint8_t b[sizeof(uint16_t)]) {
    return b[0]|(uint16_t)b[1]<<8;
}

inline static uint32_t le32(const uint8_t b[sizeof(uint32_t)]) {
    return le16(b)|(uint32_t)le16(b+2)<<16;
}

inline static uint64_t le64(const uint8_t b[sizeof(uint64_t)]) {
    return le32(b)|(uint64_t)le32(b+4)<<32;
}

inline static void le16b(uint8_t b[sizeof(uint16_t)], const uint16_t n) {
    b[0] = n;
    b[1] = n>>8;
}

inline static void le32b(uint8_t b[sizeof(uint32_t)], const uint32_t n) {
    le16b(b, n);
    le16b(b+2, n>>16);
}

inline static void le64b(uint8_t b[sizeof(uint64_t)], const uint64_t n) {
    le32b(b, n);
    le32b(b+4, n>>32);
}
#endif
