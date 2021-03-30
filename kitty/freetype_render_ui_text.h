/*
 * Copyright (C) 2021 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#pragma once

#include "data-types.h"
#include <hb-ft.h>

bool render_single_line(const char *text, uint32_t fg, uint32_t bg, uint8_t *output_buf, size_t width, size_t height, bool alpha_first);

typedef struct FontConfigFace {
    char *path;
    int index;
    int hinting;
    int hintstyle;
} FontConfigFace;

bool information_for_font_family(const char *family, bool bold, bool italic, FontConfigFace *ans);
FT_Face native_face_from_path(const char *path, int index);
bool fallback_font(char_type ch, const char *family, bool bold, bool italic, FontConfigFace *ans);

void set_main_face_family(const char *family, bool bold, bool italic);
