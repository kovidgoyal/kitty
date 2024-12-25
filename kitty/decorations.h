/*
 * decorations.h
 * Copyright (C) 2024 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#pragma once

#include "data-types.h"

typedef struct DecorationGeometry {
    uint32_t top, height;
} DecorationGeometry;

DecorationGeometry add_straight_underline(uint8_t *buf, FontCellMetrics fcm);
DecorationGeometry add_double_underline(uint8_t *buf, FontCellMetrics fcm);
DecorationGeometry add_dotted_underline(uint8_t *buf, FontCellMetrics fcm);
DecorationGeometry add_dashed_underline(uint8_t *buf, FontCellMetrics fcm);
DecorationGeometry add_curl_underline(uint8_t *buf, FontCellMetrics fcm);
DecorationGeometry add_strikethrough(uint8_t *buf, FontCellMetrics fcm);
DecorationGeometry add_missing_glyph(uint8_t *buf, FontCellMetrics fcm);
DecorationGeometry add_beam_cursor(uint8_t *buf, FontCellMetrics fcm, double dpi_x);
DecorationGeometry add_underline_cursor(uint8_t *buf, FontCellMetrics fcm, double dpi_y);
DecorationGeometry add_hollow_cursor(uint8_t *buf, FontCellMetrics fcm, double dpi_x, double dpi_y);
void render_box_char(char_type ch, uint8_t *buf, unsigned width, unsigned height, double dpi_x, double dpi_y, double scale);
#define SUPERSAMPLE_FACTOR 4u
