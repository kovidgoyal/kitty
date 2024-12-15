/*
 * decorations.c
 * Copyright (C) 2024 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#include "decorations.h"
#include "state.h"

#define STRAIGHT_UNDERLINE_LOOP \
    unsigned half = fcm.underline_thickness / 2; \
    DecorationGeometry ans = {.top = half > fcm.underline_position ? 0 : fcm.underline_position - half}; \
    for (unsigned y = ans.top; fcm.underline_thickness > 0 && y < fcm.cell_height; fcm.underline_thickness--, y++, ans.height++)

DecorationGeometry
add_straight_underline(uint8_t *buf, FontCellMetrics fcm) {
    STRAIGHT_UNDERLINE_LOOP {
        memset(buf + fcm.cell_width * y, 0xff, fcm.cell_width * sizeof(buf[0]));
    }
    return ans;
}

DecorationGeometry
add_strikethrough(uint8_t *buf, FontCellMetrics fcm) {
    unsigned half = fcm.strikethrough_thickness / 2;
    DecorationGeometry ans = {.top = half > fcm.strikethrough_position ? 0 : fcm.strikethrough_position - half};
    for (unsigned y = ans.top; fcm.strikethrough_thickness > 0 && y < fcm.cell_height; fcm.strikethrough_thickness--, y++, ans.height++) {
        memset(buf + fcm.cell_width * y, 0xff, fcm.cell_width * sizeof(buf[0]));
    }
    return ans;
}


DecorationGeometry
add_missing_glyph(uint8_t *buf, FontCellMetrics fcm) {
    DecorationGeometry ans = {.height=fcm.cell_height};
    unsigned thickness = MIN(fcm.underline_thickness, fcm.strikethrough_thickness);
    thickness = MIN(thickness, fcm.cell_width);
    for (unsigned y = 0; y < ans.height; y++) {
        uint8_t *line = buf + fcm.cell_width * y;
        if (y < thickness || y >= ans.height - thickness) memset(line, 0xff, fcm.cell_width);
        else {
            memset(line, 0xff, thickness);
            memset(line + fcm.cell_width - thickness, 0xff, thickness);
        }
    }
    return ans;
}

DecorationGeometry
add_double_underline(uint8_t *buf, FontCellMetrics fcm) {
    unsigned a = fcm.underline_position > fcm.underline_thickness ? fcm.underline_position - fcm.underline_thickness : 0;
    a = MIN(a, fcm.cell_height - 1);
    unsigned b = MIN(fcm.underline_position, fcm.cell_height - 1);
    unsigned top = MIN(a, b), bottom = MAX(a, b);
    int deficit = 2 - (bottom - top);
    if (deficit > 0) {
        if (bottom + deficit < fcm.cell_height) bottom += deficit;
        else if (bottom < fcm.cell_height - 1) {
            bottom += 1;
            if (deficit > 1) top -= deficit - 1;
        } else top -= deficit;
    }
    top = MAX(0u, MIN(top, fcm.cell_height - 1u));
    bottom = MAX(0u, MIN(bottom, fcm.cell_height - 1u));
    memset(buf + fcm.cell_width * top, 0xff, fcm.cell_width);
    memset(buf + fcm.cell_width * bottom, 0xff, fcm.cell_width);
    DecorationGeometry ans = {.top=top, .height = bottom + 1 - top};
    return ans;
}

static unsigned
distribute_dots(unsigned available_space, unsigned num_of_dots, unsigned *summed_gaps, unsigned *gaps) {
    unsigned dot_size = MAX(1u, available_space / (2u * num_of_dots));
    unsigned extra = 2 * num_of_dots * dot_size;
    extra = available_space > extra ? available_space - extra : 0;
    for (unsigned i = 0; i < num_of_dots; i++) gaps[i] = dot_size;
    if (extra > 0) {
        unsigned idx = 0;
        while (extra > 0) {
            gaps[idx] += 1;
            idx = (idx + 1) % num_of_dots;
            extra--;
        }
    }
    gaps[0] /= 2;
    for (unsigned i = 0; i < num_of_dots; i++) {
        summed_gaps[i] = 0;
        for (unsigned g = 0; g <= i; g++) summed_gaps[i] += gaps[g];
    }
    return dot_size;
}

DecorationGeometry
add_dotted_underline(uint8_t *buf, FontCellMetrics fcm) {
    unsigned num_of_dots = fcm.cell_width / (2 * fcm.underline_thickness);
    RAII_ALLOC(unsigned, spacing, malloc(num_of_dots * 2 * sizeof(unsigned)));
    if (!spacing) fatal("Out of memory");
    unsigned size = distribute_dots(fcm.cell_width, num_of_dots, spacing, spacing + num_of_dots);
    STRAIGHT_UNDERLINE_LOOP {
        uint8_t *offset = buf + fcm.cell_width * y;
        for (unsigned j = 0; j < num_of_dots; j++) {
            unsigned s = spacing[j];
            memset(offset + j * size + s, 0xff, size);
        }
    }
    return ans;
}

DecorationGeometry
add_dashed_underline(uint8_t *buf, FontCellMetrics fcm) {
    unsigned quarter_width = fcm.cell_width / 4;
    unsigned dash_width = fcm.cell_width - 3 * quarter_width;
    unsigned second_dash_start = 3 * quarter_width;
    STRAIGHT_UNDERLINE_LOOP {
        uint8_t *offset = buf + fcm.cell_width * y;
        memset(offset, 0xff, dash_width);
        memset(offset + second_dash_start, 0xff, dash_width);
    }
    return ans;
}

static void
add_intensity(uint8_t *buf, unsigned x, unsigned y, uint8_t val, unsigned max_y, unsigned position, unsigned cell_width) {
    y += position;
    y = MIN(y, max_y);
    unsigned idx = cell_width * y + x;
    buf[idx] = MIN(255, buf[idx] + val);
}

DecorationGeometry
add_curl_underline(uint8_t *buf, FontCellMetrics fcm) {
    unsigned max_x = fcm.cell_width - 1, max_y = fcm.cell_height - 1;
    double xfactor = ((OPT(undercurl_style) & 1) ? 4.0 : 2.0) * M_PI / max_x;
    unsigned half_thickness = fcm.underline_thickness / 2;
    unsigned top = fcm.underline_position > half_thickness ? fcm.underline_position - half_thickness : 0;
    unsigned max_height = fcm.cell_height - top;  // descender from the font
    unsigned half_height = MAX(1u, max_height / 4u);
    unsigned thickness;
    if (OPT(undercurl_style) & 2) thickness = MAX(half_height, fcm.underline_thickness);
    else thickness = MAX(1u, fcm.underline_thickness) - (fcm.underline_thickness < 3u ? 1u : 2u);
    unsigned position = fcm.underline_position;

    // Ensure curve doesn't exceed cell boundary at the bottom
    position += half_height * 2;
    if (position + half_height > max_y) position = max_y - half_height;

    unsigned miny = fcm.cell_height, maxy = 0;
    // Use the Wu antialias algorithm to draw the curve
    // cosine waves always have slope <= 1 so are never steep
    for (unsigned x = 0; x < fcm.cell_width; x++) {
        double y = half_height * cos(x * xfactor);
        unsigned y1 = (unsigned)floor(y - thickness), y2 = (unsigned)ceil(y);
        unsigned i1 = (unsigned)(255. * fabs(y - floor(y)));
        miny = MIN(miny, y1); maxy = MAX(maxy, y2);
        add_intensity(buf, x, y1, 255 - i1, max_y, position, fcm.cell_width);  // upper bound
        add_intensity(buf, x, y2, i1, max_y, position, fcm.cell_width);  // lower bound
        // fill between upper and lower bound
        for (unsigned t = 1; t <= thickness; t++) add_intensity(buf, x, y1 + t, 255, max_y, position, fcm.cell_width);
    }
    DecorationGeometry ans = {.top=miny, .height=maxy-miny + 1};
    return ans;
}

static void
vert(uint8_t *ans, bool is_left_edge, double width_pt, double dpi_x, FontCellMetrics fcm) {
    unsigned width = MAX(1u, MIN((unsigned)(round(width_pt * dpi_x / 72.0)), fcm.cell_width));
    const unsigned left = is_left_edge ? 0 : MAX(0u, fcm.cell_width - width);
    for (unsigned y = 0; y < fcm.cell_height; y++) {
        const unsigned offset = y * fcm.cell_width + left;
        for (unsigned x = offset; x < offset + width; x++) ans[x] = 0xff;
    }
}

static unsigned
horz(uint8_t *ans, bool is_top_edge, double height_pt, double dpi_y, FontCellMetrics fcm) {
    unsigned height = MAX(1u, MIN((unsigned)(round(height_pt * dpi_y / 72.0)), fcm.cell_height));
    const unsigned top = is_top_edge ? 0 : MAX(0u, fcm.cell_height - height);
    for (unsigned y = top; y < top + height; y++) {
        const unsigned offset = y * fcm.cell_width;
        for (unsigned x = 0; x < fcm.cell_width; x++) ans[offset + x] = 0xff;
    }
    return top;
}


DecorationGeometry
add_beam_cursor(uint8_t *buf, FontCellMetrics fcm, double dpi_x) {
    vert(buf, true, OPT(cursor_beam_thickness), dpi_x, fcm);
    DecorationGeometry ans = {.height=fcm.cell_height};
    return ans;
}

DecorationGeometry
add_underline_cursor(uint8_t *buf, FontCellMetrics fcm, double dpi_y) {
    DecorationGeometry ans = {0};
    ans.top = horz(buf, true, OPT(cursor_underline_thickness), dpi_y, fcm);
    ans.height = fcm.cell_height - ans.top;
    return ans;
}

DecorationGeometry
add_hollow_cursor(uint8_t *buf, FontCellMetrics fcm, double dpi_x, double dpi_y) {
    vert(buf, true, 1.0, dpi_x, fcm); vert(buf, false, 1.0, dpi_x, fcm);
    horz(buf, true, 1.0, dpi_y, fcm); horz(buf, false, 1.0, dpi_y, fcm);
    DecorationGeometry ans = {.height=fcm.cell_height};
    return ans;
}
