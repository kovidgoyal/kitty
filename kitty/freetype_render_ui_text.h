/*
 * Copyright (C) 2021 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#pragma once

#include "data-types.h"
#include <hb-ft.h>

typedef struct FontConfigFace {
    char *path;
    int index;
    int hinting;
    int hintstyle;
} FontConfigFace;

bool information_for_font_family(const char *family, bool bold, bool italic, FontConfigFace *ans);
FT_Face native_face_from_path(const char *path, int index);


void set_main_face_family(const char *family, bool bold, bool italic);
