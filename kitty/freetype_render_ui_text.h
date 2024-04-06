/*
 * Copyright (C) 2021 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#pragma once

#include "data-types.h"
#include <hb-ft.h>

typedef struct {bool created;} *FreeTypeRenderCtx;

FreeTypeRenderCtx create_freetype_render_context(const char *family, bool bold, bool italic);
void set_main_face_family(FreeTypeRenderCtx ctx, const char *family, bool bold, bool italic);
bool render_single_line(FreeTypeRenderCtx ctx, const char *text, unsigned sz_px, uint32_t fg, uint32_t bg, uint8_t *output_buf, size_t width, size_t height, float x_offset, float y_offset, size_t right_margin, bool horizontally_center_runs);
uint8_t* render_single_ascii_char_as_mask(FreeTypeRenderCtx ctx_, const char ch, size_t *result_width, size_t *result_height);
void release_freetype_render_context(FreeTypeRenderCtx ctx);

typedef struct FontConfigFace {
    char *path;
    int index;
    int hinting;
    int hintstyle;
} FontConfigFace;

bool information_for_font_family(const char *family, bool bold, bool italic, FontConfigFace *ans);
FT_Face native_face_from_path(const char *path, int index);
bool fallback_font(char_type ch, const char *family, bool bold, bool italic, bool prefer_color, FontConfigFace *ans);
bool freetype_convert_mono_bitmap(FT_Bitmap *src, FT_Bitmap *dest);
FT_Library freetype_library(void);
void set_freetype_error(const char* prefix, int err_code);
int downsample_32bit_image(uint8_t *src, unsigned src_width, unsigned src_height, unsigned src_stride, uint8_t *dest, unsigned dest_width, unsigned dest_height);
