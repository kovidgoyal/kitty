/*
 * Copyright (C) 2019 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#pragma once

#include <stdint.h>
#include <stddef.h>

uint32_t decode_utf8(uint32_t*, uint32_t*, uint8_t byte);
size_t decode_utf8_string(const char *src, size_t sz, uint32_t *dest);
unsigned int encode_utf8(uint32_t ch, char* dest);
uint32_t* translation_table(uint32_t which);
