/*
 * Copyright (C) 2017 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#pragma once

typedef struct {
    unsigned char action, transmission_type;
    uint32_t format, more, id;
    uint32_t width, height, x_offset, y_offset, data_height, data_width, num_cells, num_lines;
    int32_t z_index;
    size_t payload_sz;
} GraphicsCommand;
