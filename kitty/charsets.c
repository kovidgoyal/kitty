/*
 * consolemap.c
 * Copyright (C) 2016 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

// Taken from consolemap.c in the linux vt driver sourcecode

#include "data-types.h"


// UTF-8 decode taken from: https://bjoern.hoehrmann.de/utf-8/decoder/dfa/

static const uint8_t utf8_data[] = {
  0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0, // 00..1f
  0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0, // 20..3f
  0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0, // 40..5f
  0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0, // 60..7f
  1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,9,9,9,9,9,9,9,9,9,9,9,9,9,9,9,9, // 80..9f
  7,7,7,7,7,7,7,7,7,7,7,7,7,7,7,7,7,7,7,7,7,7,7,7,7,7,7,7,7,7,7,7, // a0..bf
  8,8,2,2,2,2,2,2,2,2,2,2,2,2,2,2,2,2,2,2,2,2,2,2,2,2,2,2,2,2,2,2, // c0..df
  0xa,0x3,0x3,0x3,0x3,0x3,0x3,0x3,0x3,0x3,0x3,0x3,0x3,0x4,0x3,0x3, // e0..ef
  0xb,0x6,0x6,0x6,0x5,0x8,0x8,0x8,0x8,0x8,0x8,0x8,0x8,0x8,0x8,0x8, // f0..ff
  0x0,0x1,0x2,0x3,0x5,0x8,0x7,0x1,0x1,0x1,0x4,0x6,0x1,0x1,0x1,0x1, // s0..s0
  1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,0,1,1,1,1,1,0,1,0,1,1,1,1,1,1, // s1..s2
  1,2,1,1,1,1,1,2,1,2,1,1,1,1,1,1,1,1,1,1,1,1,1,2,1,1,1,1,1,1,1,1, // s3..s4
  1,2,1,1,1,1,1,1,1,2,1,1,1,1,1,1,1,1,1,1,1,1,1,3,1,3,1,1,1,1,1,1, // s5..s6
  1,3,1,1,1,1,1,3,1,3,1,1,1,1,1,1,1,3,1,1,1,1,1,1,1,1,1,1,1,1,1,1, // s7..s8
};

uint32_t
decode_utf8(UTF8State* state, uint32_t* codep, uint8_t byte) {
  uint32_t type = utf8_data[byte];

  *codep = (*state != UTF8_ACCEPT) ?
    (byte & 0x3fu) | (*codep << 6) :
    (0xff >> type) & (byte);

  *state = utf8_data[256 + *state*16 + type];
  return *state;
}

size_t
decode_utf8_string(const char *src, size_t sz, uint32_t *dest) {
    // dest must be a zeroed array of size at least sz
    uint32_t codep = 0;
    UTF8State state = 0, prev = UTF8_ACCEPT;
    size_t i, d;
    for (i = 0, d = 0; i < sz; i++) {
        switch(decode_utf8(&state, &codep, src[i])) {
            case UTF8_ACCEPT:
                dest[d++] = codep;
                break;
            case UTF8_REJECT:
                state = UTF8_ACCEPT;
                if (prev != UTF8_ACCEPT && i > 0) i--;
                break;
        }
        prev = state;
    }
    return d;
}

unsigned int
encode_utf8(uint32_t ch, char* dest) {
    if (ch < 0x80) { // only lower 7 bits can be 1
        dest[0] = (char)ch;  // 0xxxxxxx
        return 1;
    }
    if (ch < 0x800) { // only lower 11 bits can be 1
        dest[0] = (ch>>6) | 0xC0; // 110xxxxx
        dest[1] = (ch & 0x3F) | 0x80;  // 10xxxxxx
        return 2;
    }
    if (ch < 0x10000) { // only lower 16 bits can be 1
        dest[0] = (ch>>12) | 0xE0; // 1110xxxx
        dest[1] = ((ch>>6) & 0x3F) | 0x80;  // 10xxxxxx
        dest[2] = (ch & 0x3F) | 0x80;       // 10xxxxxx
        return 3;
    }
    if (ch < 0x110000) { // only lower 21 bits can be 1
        dest[0] = (ch>>18) | 0xF0; // 11110xxx
        dest[1] = ((ch>>12) & 0x3F) | 0x80; // 10xxxxxx
        dest[2] = ((ch>>6) & 0x3F) | 0x80;  // 10xxxxxx
        dest[3] = (ch & 0x3F) | 0x80; // 10xxxxxx
        return 4;
    }
    return 0;
}
