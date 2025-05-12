/*
 * decorations.c
 * Copyright (C) 2024 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#include "decorations.h"
#include "state.h"

typedef uint32_t uint;

static uint max(uint a, uint b) { return a > b ? a : b; }
static uint min(uint a, uint b) { return a < b ? a : b; }

// Decorations {{{
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
    unsigned thickness = min(fcm.underline_thickness, fcm.strikethrough_thickness);
    thickness = min(thickness, fcm.cell_width);
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
    a = min(a, fcm.cell_height - 1);
    unsigned b = min(fcm.underline_position, fcm.cell_height - 1);
    unsigned top = min(a, b), bottom = max(a, b);
    int deficit = 2 - (bottom - top);
    if (deficit > 0) {
        if (bottom + deficit < fcm.cell_height) bottom += deficit;
        else if (bottom < fcm.cell_height - 1) {
            bottom += 1;
            if (deficit > 1) top -= deficit - 1;
        } else top -= deficit;
    }
    top = max(0u, min(top, fcm.cell_height - 1u));
    bottom = max(0u, min(bottom, fcm.cell_height - 1u));
    memset(buf + fcm.cell_width * top, 0xff, fcm.cell_width);
    memset(buf + fcm.cell_width * bottom, 0xff, fcm.cell_width);
    DecorationGeometry ans = {.top=top, .height = bottom + 1 - top};
    return ans;
}

static unsigned
distribute_dots(unsigned available_space, unsigned num_of_dots, unsigned *summed_gaps, unsigned *gaps) {
    unsigned dot_size = max(1u, available_space / (2u * num_of_dots));
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
    unsigned num_of_dots = MAX(1u, fcm.cell_width / (2 * MAX(1u, fcm.underline_thickness)));
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

static unsigned
add_intensity(uint8_t *buf, unsigned x, int y, uint8_t val, unsigned max_y, unsigned position, unsigned cell_width) {
    y += position;
    y = min(MAX(0, y), max_y);
    unsigned idx = cell_width * y + x;
    buf[idx] = min(255, buf[idx] + val);
    return y;
}

static uint
minus(uint a, uint b) {  // saturating subtraction (a > b ? a - b : 0)
    uint res = a - b;
    res &= -(res <= a);
    return res;
}

DecorationGeometry
add_curl_underline(uint8_t *buf, FontCellMetrics fcm) {
    unsigned max_x = fcm.cell_width - 1, max_y = fcm.cell_height - 1;
    double xfactor = ((OPT(undercurl_style) & 1) ? 4.0 : 2.0) * M_PI / max_x;
    div_t d = div(fcm.underline_thickness, 2);
    /*printf("cell_width: %u cell_height: %u underline_position: %u underline_thickness: %u\n",*/
    /*        fcm.cell_width, fcm.cell_height, fcm.underline_position, fcm.underline_thickness);*/
    unsigned position = min(fcm.underline_position, minus(fcm.cell_height, d.quot + d.rem));
    unsigned thickness = max(1u, min(fcm.underline_thickness, minus(fcm.cell_height, position + 1)));
    unsigned max_height = fcm.cell_height - minus(position, thickness / 2);  // descender from the font
    unsigned half_height = max(1u, max_height / 4u);  // 4 so as to be not too large
    if (OPT(undercurl_style) & 2) thickness = max(half_height, thickness);
    else thickness = max(1u, thickness) - (thickness < 3u ? 1u : 2u);

    position += half_height * 2;
    if (position + half_height > max_y) position = max_y - half_height;
    /*printf("position: %u half_height: %u thickness: %u\n", position, half_height, thickness);*/

    unsigned miny = fcm.cell_height, maxy = 0;
    // Use the Wu antialias algorithm to draw the curve
    // cosine waves always have slope <= 1 so are never steep
    for (unsigned x = 0; x < fcm.cell_width; x++) {
        double y = half_height * cos(x * xfactor);
        int y1 = (int)(floor(y - thickness)), y2 = (int)(ceil(y));
        unsigned intensity = (unsigned)((255. * fabs(y - floor(y))));
        unsigned i1 = 255 - intensity, i2 = intensity;
        unsigned yc = add_intensity(buf, x, y1, i1, max_y, position, fcm.cell_width);  // upper bound
        if (i1) { if (yc < miny) miny = yc; if (yc > maxy) maxy = yc; }
        yc = add_intensity(buf, x, y2, i2, max_y, position, fcm.cell_width);  // lower bound
        if (i2) { if (yc < miny) miny = yc; if (yc > maxy) maxy = yc; }
        // fill between upper and lower bound
        for (unsigned t = 1; t <= thickness; t++) add_intensity(buf, x, y1 + t, 255, max_y, position, fcm.cell_width);
    }
    DecorationGeometry ans = {.top=miny, .height=maxy-miny + 1};
    return ans;
}

static void
vert(uint8_t *ans, bool is_left_edge, double width_pt, double dpi_x, FontCellMetrics fcm) {
    unsigned width = max(1u, min((unsigned)(round(width_pt * dpi_x / 72.0)), fcm.cell_width));
    const unsigned left = is_left_edge ? 0 : (fcm.cell_width > width ? fcm.cell_width - width : 0);
    for (unsigned y = 0; y < fcm.cell_height; y++) {
        const unsigned offset = y * fcm.cell_width + left;
        memset(ans + offset, 0xff, width);
    }
}

static unsigned
horz(uint8_t *ans, bool is_top_edge, double height_pt, double dpi_y, FontCellMetrics fcm) {
    unsigned height = max(1u, min((unsigned)(round(height_pt * dpi_y / 72.0)), fcm.cell_height));
    const unsigned top = is_top_edge ? 0 : (fcm.cell_height > height ? fcm.cell_height - height : 0);
    for (unsigned y = top; y < top + height; y++) {
        const unsigned offset = y * fcm.cell_width;
        memset(ans + offset, 0xff, fcm.cell_width);
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
    ans.top = horz(buf, false, OPT(cursor_underline_thickness), dpi_y, fcm);
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

// }}}

typedef struct Range {
    uint start, end;
} Range;

typedef struct Limit { double upper, lower; } Limit;

typedef struct Canvas {
    uint8_t *mask;
    uint width, height, supersample_factor;
    struct { double x, y; } dpi;
    double scale;  // used to scale line thickness with font size for multicell rendering
    Range *holes; uint holes_count, holes_capacity;
    Limit *y_limits; uint y_limits_count, y_limits_capacity;
} Canvas;

static void
fill_canvas(Canvas *self, int byte) { memset(self->mask, byte, sizeof(self->mask[0]) * self->width * self->height); }

static void
append_hole(Canvas *self, Range hole) {
    ensure_space_for(self, holes, self->holes[0], self->holes_count + 1, holes_capacity, self->width, false);
    self->holes[self->holes_count++] = hole;
}

static void
append_limit(Canvas *self, double upper, double lower) {
    ensure_space_for(self, y_limits, self->y_limits[0], self->y_limits_count + 1, y_limits_capacity, self->width, false);
    self->y_limits[self->y_limits_count].upper = upper;
    self->y_limits[self->y_limits_count++].lower = lower;
}

static double
thickness_as_float(Canvas *self, uint level, bool horizontal) {
    level = min(level, arraysz(OPT(box_drawing_scale)));
    double pts = OPT(box_drawing_scale)[level];
    double dpi = horizontal ? self->dpi.x : self->dpi.y;
    return self->supersample_factor * self->scale * pts * dpi / 72.0;
}

static uint
thickness(Canvas *self, uint level, bool horizontal) {
    return (uint)ceil(thickness_as_float(self, level, horizontal));
}

static const uint hole_factor = 8;

static void
get_holes(Canvas *self, uint sz, uint hole_sz, uint num) {
    uint all_holes_use = (num + 1) * hole_sz;
    uint individual_block_size = max(1u, minus(sz, all_holes_use) / (num + 1));
    uint half_hole_sz = hole_sz / 2;
    int pos = - half_hole_sz;
    while (pos < (int)sz) {
        uint left = pos > 0 ? pos : 0;
        uint right = min(sz, pos + hole_sz);
        if (right > left) append_hole(self, (Range){left, right});
        pos = right + individual_block_size;
    }
}

static void
add_hholes(Canvas *self, uint level, uint num) {
    uint line_sz = thickness(self, level, true);
    uint hole_sz = self->width / hole_factor;
    uint start = minus(self->height / 2, line_sz / 2);
    get_holes(self, self->width, hole_sz, num);
    for (uint y = 0; y < start + line_sz; y++) {
        uint offset = y * self->width;
        for (uint i = 0; i < self->holes_count; i++) memset(self->mask + offset + self->holes[i].start, 0, self->holes[i].end - self->holes[i].start);
    }
}

static void
add_vholes(Canvas *self, uint level, uint num) {
    uint line_sz = thickness(self, level, false);
    uint hole_sz = self->height / hole_factor;
    uint start = minus(self->width / 2, line_sz / 2);
    get_holes(self, self->height, hole_sz, num);
    for (uint i = 0; i < self->holes_count; i++) {
        for (uint y = self->holes[i].start; y < self->holes[i].end; y++) {
            uint offset = y * self->width;
            memset(self->mask + offset + start, 0, line_sz);
        }
    }
}


static void
draw_hline(Canvas *self, uint x1, uint x2, uint y, uint level) {
    // Draw a horizontal line between [x1, x2) centered at y with the thickness given by level and self->supersample_factor
    uint sz = thickness(self, level, false);
    uint start = minus(y, sz / 2);
    for (uint y = start; y < min(start + sz, self->height); y++) {
        uint8_t *py = self->mask + y * self->width;
        memset(py + x1, 255, minus(min(x2, self->width), x1));
    }
}

static void
draw_vline(Canvas *self, uint y1, uint y2, uint x, uint level) {
    // Draw a vertical line between [y1, y2) centered at x with the thickness given by level and self->supersample_factor
    uint sz = thickness(self, level, true);
    uint start = minus(x, sz / 2), end = min(start + sz, self->width), xsz = minus(end, start);
    for (uint y = y1; y < min(y2, self->height); y++) {
        uint8_t *py = self->mask + y * self->width;
        memset(py + start, 255, xsz);
    }
}

static uint
half_width(Canvas *self) {  // align with non-supersampled co-ords
    return self->supersample_factor * (self->width / 2 / self->supersample_factor);
}

static uint
half_height(Canvas *self) { // align with non-supersampled co-ords
    return self->supersample_factor * (self->height / 2 / self->supersample_factor);
}


static void
half_hline(Canvas *self, uint level, bool right_half, uint extend_by) {
    uint x1, x2;
    if (right_half) {
        x1 = minus(half_width(self), extend_by); x2 = self->width;
    } else {
        x1 = 0; x2 = half_width(self) + extend_by;
    }
    draw_hline(self, x1, x2, half_height(self), level);
}

typedef union Point {
    struct {
        int32_t x: 32, y: 32;
    };
    int64_t val;
} Point;


static Point
half_dhline(Canvas *self, uint level, bool right_half, Edge which) {
    uint x1 = 0, x2 = 0;
    if (right_half) { x1 = self->width / 2; x2 = self->width; } else x2 = self->width / 2;
    uint gap = thickness(self, level + 1, false);
    Point ans = {.x=self->height / 2 - gap, .y=self->height / 2 + gap};
    if (which & TOP_EDGE) draw_hline(self, x1, x2, ans.x, level);
    if (which & BOTTOM_EDGE) draw_hline(self, x1, x2, ans.y, level);
    return ans;
}

static Point
half_dvline(Canvas *self, uint level, bool bottom_half, Edge which) {
    uint y1 = 0, y2 = 0;
    if (bottom_half) { y1 = self->height / 2; y2 = self->height; } else y2 = self->height / 2;
    uint gap = thickness(self, level + 1, true);
    Point ans = {.x=self->width / 2 - gap, .y=self->width / 2 + gap};
    if (which & LEFT_EDGE) draw_vline(self, y1, y2, ans.x, level);
    if (which & RIGHT_EDGE) draw_vline(self, y1, y2, ans.y, level);
    return ans;
}

static Point
dhline(Canvas *self, uint level, Edge which) {
    half_dhline(self, level, false, which);
    return half_dhline(self, level, true, which);
}

static Point
dvline(Canvas *self, uint level, Edge which) {
    half_dvline(self, level, false, which);
    return half_dvline(self, level, true, which);
}


static void
half_vline(Canvas *self, uint level, bool bottom_half, uint extend_by) {
    uint y1, y2;
    if (bottom_half) {
        y1 = minus(half_height(self), extend_by); y2 = self->height;
    } else {
        y1 = 0; y2 = half_height(self) + extend_by;
    }
    draw_vline(self, y1, y2, half_width(self), level);
}

static void
hline(Canvas *self, uint level) {
    half_hline(self, level, false, 0);
    half_hline(self, level, true, 0);
}

static void
vline(Canvas *self, uint level) {
    half_vline(self, level, false, 0);
    half_vline(self, level, true, 0);
}

static void
hholes(Canvas *self, uint level, uint num) {
    hline(self, level);
    add_hholes(self, level, num);
}

static void
vholes(Canvas *self, uint level, uint num) {
    vline(self, level);
    add_vholes(self, level, num);
}

static uint8_t
plus(uint8_t a, uint8_t b) {
    uint8_t res = a + b;
    res |= -(res < a);
    return res;
}

static uint8_t
average_intensity(const Canvas *src, uint dest_x, uint dest_y) {
    uint src_x = dest_x * src->supersample_factor, src_y = dest_y * src->supersample_factor;
    uint total = 0;
    for (uint y = src_y; y < src_y + src->supersample_factor; y++) {
        uint offset = src->width * y;
        for (uint x = src_x; x < src_x + src->supersample_factor; x++) total += src->mask[offset + x];
    }
    return (total / (src->supersample_factor * src->supersample_factor)) & 0xff;
}

static void
downsample(const Canvas *src, Canvas *dest) {
    for (uint y = 0; y < dest->height; y++) {
        uint offset = dest->width * y;
        for (uint x = 0; x < dest->width; x++) {
            dest->mask[offset + x] = plus(dest->mask[offset + x], average_intensity(src, x, y));
        }
    }
}

typedef struct StraightLine {
    double m, c;
} StraightLine;


static StraightLine
line_from_points(double x1, double y1, double x2, double y2) {
    StraightLine ans = {.m = (y2 - y1) / (x2 - x1)};
    ans.c = y1 - ans.m * x1;
    return ans;
}

static double
line_y(StraightLine l, int x) {
    return l.m * x + l.c;
}

#define calc_limits(self, lower_y, upper_y) { \
    if (!self->y_limits) { \
        self->y_limits_count = self->width; self->y_limits = malloc(sizeof(self->y_limits[0]) * self->y_limits_count); \
        if (!self->y_limits) fatal("Out of memory"); \
    } \
    for (uint x = 0; x < self->width; x++) { self->y_limits[x].lower = lower_y; self->y_limits[x].upper = upper_y; } \
}

static void
fill_region(Canvas *self, bool inverted) {
    uint8_t full = 0, empty = 0; if (inverted) empty = 255; else full = 255;
    for (uint y = 0; y < self->height; y++) {
        uint offset = y * self->width;
        for (uint x = 0; x < self->width && x < self->y_limits_count; x++) {
            self->mask[offset + x] = self->y_limits[x].lower <= y && y <= self->y_limits[x].upper ? full : empty;
        }
    }
}

static void
triangle(Canvas *self, bool left, bool inverted) {
    int ay1 = 0, by1 = self->height - 1, y2 = self->height / 2, x1 = 0, x2 = 0;
    if (left) x2 = self->width - 1; else x1 = self->width - 1;
    StraightLine uppery = line_from_points(x1, ay1, x2, y2);
    StraightLine lowery = line_from_points(x1, by1, x2, y2);
    calc_limits(self, line_y(uppery, x), line_y(lowery, x));
    fill_region(self, inverted);
}

typedef enum Corner {
    TOP_LEFT = LEFT_EDGE | TOP_EDGE, TOP_RIGHT = TOP_EDGE | RIGHT_EDGE,
    BOTTOM_LEFT = BOTTOM_EDGE | LEFT_EDGE, BOTTOM_RIGHT = BOTTOM_EDGE | RIGHT_EDGE,
} Corner;

static void
thick_line(Canvas *self, uint thickness_in_pixels, Point p1, Point p2) {
    if (p1.x > p2.x) SWAP(p1, p2);
    StraightLine l = line_from_points(p1.x, p1.y, p2.x, p2.y);
    div_t d = div(thickness_in_pixels, 2);
    int delta = d.quot, extra = d.rem;
    for (int x = p1.x > 0 ? p1.x : 0; x < (int)self->width && x < p2.x + 1; x++) {
        int y_p = (int)line_y(l, x);
        for (int y = MAX(0, y_p - delta); y < MIN(y_p + delta + extra, (int)self->height); y++) {
            self->mask[x + y * self->width] = 255;
        }
    }
}

static void
frame(Canvas *self, uint level, Edge edges) {
    uint h = thickness(self, level, true), v = thickness(self, level, false);
#define line(x1, x2, y1, y2) { \
    for (uint y=y1; y < min(y2, self->height); y++) memset(self->mask + y * self->width + x1, 255, minus(min(x2, self->width), x1)); }
#define hline(y1, y2) line(0, self->width, y1, y2)
#define vline(x1, x2) line(x1, x2, 0, self->height)
    if (edges & TOP_EDGE) hline(0, h + 1);
    if (edges & BOTTOM_EDGE) hline(self->height - h - 1, self->height);
    if (edges & LEFT_EDGE) vline(0, v + 1);
    if (edges & RIGHT_EDGE) vline(self->width - v - 1, self->width);
#undef hline
#undef vline
#undef line
}

typedef enum Segment { LEFT, MIDDLE, RIGHT } Segment;

static void
progress_bar(Canvas *self, Segment which, bool filled) {
    const Edge edges = TOP_EDGE | BOTTOM_EDGE;
    switch(which) {
        case LEFT: frame(self, 1, LEFT_EDGE | edges); break;
        case MIDDLE: frame(self, 1, edges); break;
        case RIGHT: frame(self, 1, RIGHT_EDGE | edges); break;
    }
    if (!filled) return;
    uint h = thickness(self, 1, true), v = thickness(self, 1, false);
    static const uint gap_factor = 3;
    uint y1 = gap_factor * h, y2 = minus(self->height, gap_factor*h), x1 = 0, x2 = 0;
    switch(which) {
        case LEFT: x1 = gap_factor * v; x2 = self->width; break;
        case MIDDLE: x2 = self->width; break;
        case RIGHT: x2 = minus(self->width, gap_factor * v); break;
    }
    for (uint y = y1; y < y2; y++) memset(self->mask + y * self->width + x1, 255, minus(min(x2, self->width), x1));
}

static void
half_cross_line(Canvas *self, uint level, Corner corner) {
    uint my = minus(self->height, 1) / 2; Point p1 = {0}, p2 = {0};
    switch (corner) {
        case TOP_LEFT: p2.x = minus(self->width, 1); p2.y = my; break;
        case BOTTOM_LEFT: p1.x = minus(self->width, 1); p1.y = my; p2.y = self->height -1; break;
        case TOP_RIGHT: p1.x = minus(self->width, 1); p2.y = my; break;
        case BOTTOM_RIGHT: p2.x = minus(self->width, 1), p2.y = minus(self->height, 1); p1.y = my; break;
    }
    thick_line(self, thickness(self, level, true), p1, p2);
}

static void
cross_line(Canvas *self, uint level, bool left) {
    uint w = minus(self->width, 1), h = minus(self->height, 1);
    Point p1 = {0}, p2 = {0};
    if (left) p2 = (Point){.x=w, .y=h}; else { p1.x = w; p2.y = h; }
    thick_line(self, thickness(self, level, true), p1, p2);
}

typedef struct CubicBezier {
    Point start, c1, c2, end;
} CubicBezier;

#define bezier_eq(which) { \
    const CubicBezier *cb = v; \
    const double u = 1. - t; \
    const double u_3 = u * u * u; \
    const double t_3 = t * t * t; \
    return u_3 * cb->start.which + 3 * t * u * (u * cb->c1.which + t * cb->c2.which) + t_3 * cb->end.which; \
}

#define bezier_prime_eq(which) { \
    const CubicBezier *cb = v; \
    const double u = 1. - t; \
    const double u_2 = u * u; \
    const double t_2 = t * t; \
    return 3 * u_2 * (cb->c1.which - cb->start.which) + 6 * t * u * (cb->c2.which - cb->c1.which) + 3 * t_2 * (cb->end.which - cb->c2.which); \
}

static double bezier_x(const void *v, double t) { bezier_eq(x); }
static double bezier_y(const void *v, double t) { bezier_eq(y); }
static double bezier_prime_x(const void *v, double t) { bezier_prime_eq(x); }
static double bezier_prime_y(const void *v, double t) { bezier_prime_eq(y); }
#undef bezier_eq
#undef bezier_prime_eq

static int
find_bezier_for_D(int width, int height) {
    int cx = width - 1, last_cx = cx;
    CubicBezier cb = {.end={.x=0, .y=height - 1}, .c2={.x=0, .y=height - 1}};
    while (true) {
        cb.c1.x = cx; cb.c2.x = cx;
        if (bezier_x(&cb, 0.5) > width - 1) return last_cx;
        last_cx = cx++;
    }
}

static double
find_t_for_x(const CubicBezier *cb, int x, double start_t) {
    if (fabs(bezier_x(cb, start_t) - x) < 0.1) return start_t;
    static const double t_limit = 0.5;
    double increment = t_limit - start_t;
    if (increment <= 0) return start_t;
    while (true) {
        double q = bezier_x(cb, start_t + increment);
        if (fabs(q - x) < 0.1) return start_t + increment;
        if (q > x) {
            increment /= 2.0;
            if (increment < 1e-6) {
                log_error("Failed to find cubic bezier t for x=%d\n", x);
                return start_t;
            }
        } else {
            start_t += increment;
            increment = t_limit - start_t;
            if (increment <= 0) return start_t;
        }
    }
}


static void
get_bezier_limits(Canvas *self, const CubicBezier *cb) {
    int start_x = (int)bezier_x(cb, 0), max_x = (int)bezier_x(cb, 0.5);
    double last_t = 0.;
    for (int x = start_x; x < max_x + 1; x++) {
        if (x > start_x) last_t = find_t_for_x(cb, x, last_t);
        double upper = bezier_y(cb, last_t), lower = bezier_y(cb, 1.0 - last_t);
        if (fabs(upper - lower) <= 2.0) break;  // avoid pip on end of D
        append_limit(self, lower, upper);
    }
}

#define mirror_horizontally(expr) { \
    RAII_ALLOC(uint8_t, mbuf, calloc(self->width, self->height)); \
    if (!mbuf) fatal("Out of memory"); \
    uint8_t *buf = self->mask; \
    self->mask = mbuf; \
    expr; \
    self->mask = buf; \
    for (uint y = 0; y < self->height; y++) { \
        uint offset = y * self->width; \
        for (uint src_x = 0; src_x < self->width; src_x++) { \
            uint dest_x = self->width - 1 - src_x; \
            buf[offset + dest_x] = mbuf[offset + src_x]; \
        } \
    } \
}

static void
filled_D(Canvas *self, bool left) {
    int c1x = find_bezier_for_D(self->width, self->height);
    CubicBezier cb = {.end={.y=self->height-1}, .c1 = {.x=c1x}, .c2 = {.x=c1x, .y=self->height - 1}};
    get_bezier_limits(self, &cb);
    if (left) fill_region(self, false);
    else mirror_horizontally(fill_region(self, false));
}

static double
distance(double x1, double y1, double x2, double y2) {
    const double dx = x1 - x2;
    const double dy = y1 - y2;
    return sqrt(dx * dx + dy * dy);
}

typedef double(*curve_func)(const void *, double t);

#define NAME position_set
#define KEY_TY Point
#define HASH_FN hash_point
#define CMPR_FN cmpr_point
static uint64_t hash_point(Point p);
static bool cmpr_point(Point, Point);
#include "kitty-verstable.h"
static uint64_t hash_point(Point p) { return vt_hash_integer(p.val); }
static bool cmpr_point(Point a, Point b) { return a.val == b.val; }

#define draw_parametrized_thin_curve(self, line_width, xfunc, yfunc, x_offset, y_offset) { \
    uint th = (uint)ceil(line_width); \
    div_t d = div(th, 2u); \
    int delta = d.quot, extra = d.rem; \
    uint num_samples = self->height * 8; \
    position_set seen; vt_init(&seen); \
    for (uint i = 0; i < num_samples + 1; i++) { \
        double t = i / (double)num_samples; \
        Point p = {.x=(int32_t)xfunc, .y=(int32_t)yfunc};  \
        position_set_itr q = vt_get(&seen, p); \
        if (!vt_is_end(q)) continue; \
        if (vt_is_end(vt_insert(&seen, p))) fatal("Out of memory"); \
        p.x += x_offset; \
        for (int y = MAX(0, p.y - delta); y < MIN(p.y + delta + extra, (int)self->height); y++) { \
            uint offset = y * self->width, start = MAX(0, p.x - delta); \
            memset(self->mask + offset + start, 255, minus((uint)MIN(p.x + delta + extra, (int)self->width), start)); \
        } \
    } \
    vt_cleanup(&seen); \
}

static void
draw_parametrized_curve_with_derivative(
    Canvas *self, void *curve_data, double line_width, curve_func xfunc, curve_func yfunc, curve_func x_prime, curve_func y_prime,
    int x_offset, int yoffset, double thickness_fudge
) {
    if (line_width <= 2 * self->supersample_factor) {
        // The old algorithm looks better for very thin lines
        draw_parametrized_thin_curve(self, line_width, xfunc(curve_data, t), yfunc(curve_data, t), x_offset, y_offset);
        return;
    }
    double larger_dim = fmax(self->height, self->width);
    double step = 1.0 / larger_dim;
    const double min_step = step / 100., max_step = step;
    line_width = fmax(1., line_width);
    const double half_thickness = line_width / 2.0;
    const double distance_limit = half_thickness + thickness_fudge;
    double t = 0;
    while(true) {
        double x = xfunc(curve_data, t), y = yfunc(curve_data, t);
        for (double dy = -line_width; dy <= line_width; dy++) {
            for (double dx = -line_width; dx <= line_width; dx++) {
                double px = x + dx, py = y + dy;
                double dist = distance(x, y, px, py);
                int row = (int)py + yoffset, col = (int)px + x_offset;
                if (dist > distance_limit || row >= (int)self->height || row < 0 || col >= (int)self->width || col < 0) continue;
                const int offset = row * self->width + col;
                double alpha = 1.0 - (dist / half_thickness);
                uint8_t old_alpha = self->mask[offset];
                self->mask[offset] = (uint8_t)(alpha * 255 + (1 - alpha) * old_alpha);
            }
        }
        if (t >= 1.0) break;
        // Dynamically adjust step size based on curve's derivative
        double dx = x_prime(curve_data, t), dy = y_prime(curve_data, t);
        double d = sqrt(dx * dx + dy * dy);
        step = 1.0 / fmax(1e-6, d);
        step = fmax(min_step, fmin(step, max_step));
        t = fmin(t + step, 1.0);
    }
}

static void
rounded_separator(Canvas *self, uint level, bool left) {
    uint gap = thickness(self, level, true);
    int c1x = find_bezier_for_D(minus(self->width, gap), self->height);
    CubicBezier cb = {.end={.y=self->height - 1}, .c1={.x=c1x}, .c2={.x=c1x, .y=self->height - 1}};
    double line_width = thickness_as_float(self, level, true);
#define d draw_parametrized_curve_with_derivative(self, &cb, line_width, bezier_x, bezier_y, bezier_prime_x, bezier_prime_y, 0, 0, 0)
    if (left) { d; } else { mirror_horizontally(d); }
#undef d
}

static void
corner_triangle(Canvas *self, const Corner corner) {
    StraightLine diag;
    const uint w = minus(self->width, 1), h = minus(self->height, 1);
    bool top = corner == TOP_RIGHT || corner == TOP_LEFT;
    if (corner == TOP_RIGHT || corner == BOTTOM_LEFT) diag = line_from_points(0, 0, w, h);
    else diag = line_from_points(w, 0, 0, h);
    for (uint x = 0; x < self->width; x++) {
        if (top) append_limit(self, line_y(diag, x), 0);
        else append_limit(self, h, line_y(diag, x));
    }
    fill_region(self, false);
}

typedef struct Circle {
    double x, y, radius;
    double start, end, amt;
} Circle;

static Circle
circle(double x, double y, double radius, double start_at, double end_at) {
    double conv = M_PI / 180.;
    Circle ans = {.x=x, .y=y, .radius=radius, .start=start_at*conv, .end=end_at*conv};
    ans.amt = ans.end - ans.start;
    return ans;
}

static double circle_x(const void *v, double t) { const Circle *c=v; return c->x + c->radius * cos(c->start + c->amt * t); }
static double circle_y(const void *v, double t) { const Circle *c=v; return c->y + c->radius * sin(c->start + c->amt * t); }
static double circle_prime_x(const void *v, double t) { const Circle *c=v; return -c->radius * sin(c->start + c->amt * t); }
static double circle_prime_y(const void *v, double t) { const Circle *c=v; return c->radius * cos(c->start + c->amt * t); }

static void
spinner(Canvas *self, uint level, double start_degrees, double end_degrees) {
    double x = self->width / 2.0, y = self->height / 2.0;
    double line_width = thickness_as_float(self, level, true);
    double radius = fmax(0, fmin(x, y) - line_width / 2.0);
    Circle c = circle(x, y, radius, start_degrees, end_degrees);
    draw_parametrized_curve_with_derivative(self, &c, line_width, circle_x, circle_y, circle_prime_x, circle_prime_y, 0, 0, 0);
}

static void
fill_circle_of_radius(Canvas *self, double origin_x, double origin_y, double radius, uint8_t alpha) {
    const double limit = radius * radius;
    for (uint y = 0; y < self->height; y++) {
        for (uint x = 0; x < self->width; x++) {
            double xw = (double)x - origin_x, yh = (double)y - origin_y;
            if (xw * xw + yh * yh <= limit) self->mask[y * self->width + x] = alpha;
        }
    }
}

static void
fill_circle(Canvas *self, double scale, double gap, bool invert) {
    const uint w = self->width / 2, h = self->height / 2;
    const double radius = (int)(scale * min(w, h) - gap / 2);
    const uint8_t fill = invert ? 0 : 255;
    fill_circle_of_radius(self, w, h, radius, fill);
}

static void
draw_fish_eye(Canvas *self, uint level UNUSED) {
    double x = self->width / 2., y = self->height / 2.;
    double radius = fmin(x, y);
    double central_radius = (2./3.) * radius;
    fill_circle_of_radius(self, x, y, central_radius, 255);
    double line_width = fmax(1. * self->supersample_factor, (radius - central_radius) / 2.5);
    radius = fmax(0, fmin(x, y) - line_width / 2.);
    Circle c = circle(x, y, radius, 0, 360);
    draw_parametrized_curve_with_derivative(self, &c, line_width, circle_x, circle_y, circle_prime_x, circle_prime_y, 0, 0, 0);
}

static void
inner_corner(Canvas *self, uint level, Corner corner) {
    uint hgap = thickness(self, level + 1, true), vgap = thickness(self, level + 1, false);
    uint vthick = thickness(self, level, true) / 2;
    uint x1 = 0, x2 = self->width, y1 = 0, y2 = self->height; int xd = 1, yd = 1;
    if (corner & LEFT_EDGE) {
        x2 = minus(self->width / 2 + vthick + 1, hgap); xd = -1;
    } else x1 = minus(self->width / 2 + hgap, vthick);
    if (corner & TOP_EDGE) {
        y2 = minus(self->height / 2, vgap); yd = -1;
    } else y1 = self->height / 2 + vgap;
    draw_hline(self, x1, x2, self->height / 2 + (yd * vgap), level);
    draw_vline(self, y1, y2, self->width / 2 + (xd * hgap), level);
}

static Range
fourth_range(uint size, uint which) {
    uint thickness = max(1, size / 4);
    uint block = thickness * 4;
    if (block == size) return (Range){.start=thickness * which, .end=thickness * (which + 1)};
    if (block > size) {
        uint start = min(which * thickness, minus(size, thickness));
        return (Range){.start=start, .end=start + thickness};
    }
    uint extra = minus(size, block);
    uint thicknesses[4] = {thickness, thickness, thickness, thickness};
    uint pos = 0;
    if (extra) {
#define d(i) thicknesses[i]++; if (!--extra) goto done;
        // ensures the thickness of first and last are least likely to be changed
        d(1); d(2); d(3); d(0);
#undef d
    }
done:
    for (uint i = 0; i < which; i++) pos += thicknesses[i];
    return (Range){.start=pos, .end=pos + thicknesses[which]};
}


static Range
eight_range(uint size, uint which) {
    uint thickness = max(1, size / 8);
    uint block = thickness * 8;
    if (block == size) return (Range){.start=thickness * which, .end=thickness * (which + 1)};
    if (block > size) {
        uint start = min(which * thickness, minus(size, thickness));
        return (Range){.start=start, .end=start + thickness};
    }
    uint extra = minus(size, block);
    uint thicknesses[8] = {thickness, thickness, thickness, thickness, thickness, thickness, thickness, thickness};
    uint pos = 0;
    if (extra) {
#define d(i) thicknesses[i]++; if (!--extra) goto done;
        // ensures the thickness of first and last are least likely to be changed
        d(3); d(4); d(2); d(5); d(6); d(1); d(7); d(0);
#undef d
    }
done:
    for (uint i = 0; i < which; i++) pos += thicknesses[i];
    return (Range){.start=pos, .end=pos + thicknesses[which]};
}

static void
eight_bar(Canvas *self, uint which, bool horizontal) {
    Range x_range, y_range;
    if (horizontal) {
        x_range = (Range){0, self->width};
        y_range = eight_range(self->height, which);
    } else {
        y_range = (Range){0, self->height};
        x_range = eight_range(self->width, which);
    }
    for (uint y = y_range.start; y < y_range.end; y++) {
        uint offset = y * self->width;
        memset(self->mask + offset + x_range.start, 255, minus(x_range.end, x_range.start));
    }
}


static void
octant_segment(Canvas *self, uint8_t which, bool left) {
    Range x_range = left ? (Range){0, self->width / 2} : (Range){self->width/2, self->width};
    Range y_range = fourth_range(self->height, which);
    for (uint y = y_range.start; y < y_range.end; y++) {
        uint offset = y * self->width;
        memset(self->mask + offset + x_range.start, 255, minus(x_range.end, x_range.start));
    }
}

static void
octant(Canvas *self, uint8_t which) {
    enum flags { a = 1, b = 2, c = 4, d = 8, m = 16, n = 32, o = 64, p = 128 };
    static const enum flags mapping[232] = {
        // 00 - 0f
        b,     b|m,   a|b|m, n,       a|n,   a|m|n,   b|n,     a|b|n,     b|m|n, c,   a|c, c|m,   a|c|m, a|b|c, b|c|m, a|b|c|m,
        // 10 - 1f
        c|n,   a|c|n, c|m|n, a|c|m|n, b|c|n, a|b|c|n, b|c|m|n, a|b|c|m|n, o,     a|o, m|o, a|m|o, b|o,   a|b|o, b|m|o, a|b|m|o,
        // 20 - 2f
        a|n|o, m|n|o, a|m|n|o, b|n|o, a|b|n|o, b|m|n|o, a|b|m|n|o, c|o, a|c|o, c|m|o, a|c|m|o, b|c|o, a|b|c|o, b|c|m|o, a|b|c|m|o, c|n|o,
        // 30 - 3f
        a|c|n|o, c|m|n|o, a|c|m|n|o, b|c|n|o, a|b|c|n|o, b|c|m|n|o, a|d, d|m, a|d|m, b|d, a|b|d, b|d|m, a|b|d|m, d|n, a|d|n, d|m|n,
        // 40 - 4f
        a|d|m|n, b|d|n, a|b|d|n, b|d|m|n, a|b|d|m|n, a|c|d, c|d|m, a|c|d|m, b|c|d, b|c|d|m, a|b|c|d|m, c|d|n, a|c|d|n, a|c|d|m|n, b|c|d|n, a|b|c|d|n,
        // 50 - 5f
        b|c|d|m|n, d|o, a|d|o, d|m|o, a|d|m|o, b|d|o, a|b|d|o, b|d|m|o, a|b|d|m|o, d|n|o, a|d|n|o, d|m|n|o, a|d|m|n|o, b|d|n|o, a|b|d|n|o, b|d|m|n|o,
        // 60 - 6f
        ~(c|p), c|d|o, a|c|d|o, c|d|m|o, a|c|d|m|o, b|c|d|o, ~(m|n|p), b|c|d|m|o, ~(n|p), c|d|n|o, a|c|d|n|o, c|d|m|n|o, ~(b|p), b|c|d|n|o, ~(m|p), ~(a|p),
        // 70 - 7f
        ~p, a|p, m|p, a|m|p, b|p, a|b|p, b|m|p, a|b|m|p, n|p, a|n|p, m|n|p, a|m|n|p, b|n|p, a|b|n|p, b|m|n|p, ~(c|d|o),
        // 80 - 8f
        c|p, a|c|p, c|m|p, a|c|m|p, b|c|p, a|b|c|p, b|c|m|p, ~(d|n|o), c|n|p, a|c|n|p, c|m|n|p, ~(b|d|o), b|c|n|p, ~(d|m|o), ~(a|d|o), ~(d|o),
        // 90 - 9f
        a|o|p, m|o|p, a|m|o|p, b|o|p, b|m|o|p, a|b|m|o|p, n|o|p, a|n|o|p, a|m|n|o|p, b|n|o|p, a|b|n|o|p, b|m|n|o|p, c|o|p, a|c|o|p, c|m|o|p, a|c|m|o|p,
        // a0 - af
        b|c|o|p, a|b|c|o|p, b|c|m|o|p, ~(n|d), c|n|o|p, a|c|n|o|p, c|m|n|o|p, ~(b|d), b|c|n|o|p, ~(d|m), ~(a|d), ~d, a|d|p, d|m|p, a|d|m|p, b|d|p,
        // b0 - bf
        a|b|d|p, b|d|m|p, a|b|d|m|p, d|n|p, a|d|n|p, d|m|n|p, a|d|m|n|p, b|d|n|p, a|b|d|n|p, b|d|m|n|p, ~(c|o), c|d|p, a|c|d|p, c|d|m|p, a|c|d|m|p, b|c|d|p,

        // c0 -cf
        a|b|c|d|p, b|c|d|m|p, ~(n|o), c|d|n|p, a|c|d|n|p, c|d|m|n|p, ~(b|o), b|c|d|n|p, ~(m|o), ~(a|o), ~o, d|o|p, a|d|o|p, d|m|o|p, a|d|m|o|p, b|d|o|p,

        // d0 - df
        a|b|d|o|p, b|d|m|o|p, ~(c|n), d|n|o|p, a|d|n|o|p, d|m|n|o|p, ~(b|c), b|d|n|o|p, ~(c|m), ~(a|c), ~c, a|c|d|o|p, c|d|m|o|p, ~(b|n), b|c|d|o|p, ~(a|n),
        // e0 - e7
        ~n, c|d|n|o|p, ~(b|m), ~b, ~m, ~a, b|c, n|o,

    };
    which = mapping[which];
    if (which & a) octant_segment(self, 0, true);
    if (which & b) octant_segment(self, 1, true);
    if (which & c) octant_segment(self, 2, true);
    if (which & d) octant_segment(self, 3, true);
    if (which & m) octant_segment(self, 0, false);
    if (which & n) octant_segment(self, 1, false);
    if (which & o) octant_segment(self, 2, false);
    if (which & p) octant_segment(self, 3, false);

}

static void
eight_block(Canvas *self, int horizontal, ...) {
    va_list args; va_start(args, horizontal);
    int which;
    while ((which = va_arg(args, int)) >= 0) eight_bar(self, which, horizontal);
    va_end(args);
}

typedef struct Shade {
    bool light, invert, fill_blank;
    Edge which_half;
    uint xnum, ynum;
} Shade;

#define is_odd(x) ((x) & 1u)

static void
shade(Canvas *self, Shade s) {
    const uint square_width = max(1, self->width / s.xnum);
    const uint square_height = max(1, s.ynum ? (self->height / s.ynum) : square_width);
    uint number_of_rows = self->height / square_height;
    uint number_of_cols = self->width / square_width;

    // Make sure the parity is correct
    // (except when that would cause division by zero)
    if (number_of_cols > 1 && is_odd(number_of_cols) != is_odd(s.xnum)) number_of_cols--;
    if (number_of_rows > 1 && is_odd(number_of_rows) != is_odd(s.ynum)) number_of_rows--;

    // Calculate how much space remains unused, and how frequently
    // to insert an extra column/row to fill all of it
    uint excess_cols = minus(self->width, square_width * number_of_cols);
    double square_width_extension = (double)excess_cols / number_of_cols;

    uint excess_rows = minus(self->height, square_height * number_of_rows);
    double square_height_extension = (double)excess_rows / number_of_rows;

    Range rows = {.end=number_of_rows}, cols = {.end=number_of_cols};
    switch(s.which_half) {
        // this is to remove gaps between half-filled characters
        case TOP_EDGE: rows.end /= 2; square_height_extension *= 2; break;
        case BOTTOM_EDGE: rows.start = number_of_rows / 2; square_height_extension *= 2; break;
        case LEFT_EDGE: cols.end /= 2; square_width_extension *= 2; break;
        case RIGHT_EDGE: cols.start = number_of_cols / 2; square_width_extension *= 2; break;
    }

    bool extra_row = false;
    uint ey = 0, old_ey = 0, drawn_rows = 0;

    for (uint r = rows.start; r < rows.end; r++) {
        // Keep track of how much extra height has accumulated, and add an extra row at every passed integer, including 0
        old_ey = ey;
        ey = (uint)ceil(drawn_rows * square_height_extension);
        extra_row = ey != old_ey;
        drawn_rows += 1;
        bool extra_col = false;
        uint ex = 0, old_ex = 0, drawn_cols = 0;
        for (uint c = cols.start; c < cols.end; c++) {
            old_ex = ex;
            ex = (uint)ceil(drawn_cols * square_width_extension);
            extra_col = ex != old_ex;
            drawn_cols += 1;

            // Fill extra rows with semi-transparent pixels that match the pattern
            if (extra_row) {
                uint y = r * square_height + old_ey;
                uint offset = self->width * y;
                for (uint xc = 0; xc < square_width; xc++) {
                    uint x = c * square_width + xc + ex;
                    if (s.light) {
                        if (s.invert) self->mask[offset + x] = is_odd(c) ? 255 : 70;
                        else self->mask[offset + x] = is_odd(c) ? 0 : 70;
                    } else self->mask[offset + x] = is_odd(c) == s.invert ? 120 : 30;
                }
            }
            // Do the same for the extra columns
            if (extra_col) {
                uint x = c * square_width + old_ex;
                for (uint yr = 0; yr < square_height; yr++) {
                    uint y = r * square_height + yr + ey;
                    uint offset = self->width * y;
                    if (s.light) {
                        if (s.invert) self->mask[offset + x] = is_odd(r) ? 255 : 70;
                        else self->mask[offset + x] = is_odd(r) ? 0 : 70;
                    } else self->mask[offset + x] = is_odd(r) == s.invert ? 120 : 30;
                }
            }
            // And in case they intersect, set the corner pixel too
            if (extra_row && extra_col) {
                uint x = c * square_width + old_ex;
                uint y = r * square_height + old_ey;
                uint offset = self->width * y;
                self->mask[offset + x] = 50;
            }

            const bool is_blank = s.invert ^ (is_odd(r) != is_odd(c) || (s.light && is_odd(r)));
            if (!is_blank) {
                // Fill the square
                for (uint yr = 0; yr < square_height; yr++) {
                    uint y = r * square_height + yr + ey;
                    uint offset = self->width * y;
                    for (uint xc = 0; xc < square_width; xc++) {
                        uint x = c * square_width + xc + ex;
                        self->mask[offset + x] = 255;
                    }
                }
            }
        }
    }
    if (!s.fill_blank) return;
    cols = (Range){.end=self->width}; rows = (Range){.end=self->height};
    switch(s.which_half) {
        case BOTTOM_EDGE: rows.end = self->height / 2; break;
        case TOP_EDGE: rows.start = minus(self->height / 2, 1); break;
        case RIGHT_EDGE: cols.end = self->width / 2; break;
        case LEFT_EDGE: cols.start = minus(self->width / 2, 1); break;
    }
    for (uint r = rows.start; r < rows.end; r++) memset(self->mask + r * self->width + cols.start, 255, cols.end - cols.start);
}

static void
apply_mask(Canvas *self, uint8_t *mask) {
    for (uint y = 0; y < self->height; y++) {
        uint offset = y * self->width;
        for (uint x = 0; x < self->width; x++) {
            uint p = offset + x;
            self->mask[p] = (uint8_t)round((mask[p] / 255.0) * self->mask[p]);
        }
    }
}

static void
cross_shade(Canvas *self, bool rotate) {
    static const uint num_of_lines = 7;
    uint line_thickness = max(self->supersample_factor, self->width / num_of_lines);
    uint delta = 2 * line_thickness;
    uint y1 = 0, y2 = self->height;
    if (rotate) SWAP(y1, y2);
    for (uint x = 0; x < self->width; x += delta) {
        thick_line(self, line_thickness, (Point){.x=0 + x, .y=y1}, (Point){.x=self->width + x, .y=y2});
        thick_line(self, line_thickness, (Point){.x=0 - x, .y=y1}, (Point){.x=self->width - x, .y=y2});
    }
}

static void
quad(Canvas *self, Corner which) {
    uint x = which & LEFT_EDGE ? 0 : 1, y = which & TOP_EDGE ? 0 : 1;
    uint num_cols = self->width / 2;
    uint left = x * num_cols;
    uint right = x ? self->width : num_cols;
    uint num_rows = self->height / 2;
    uint top = y * num_rows;
    uint bottom = y ? self->height : num_rows;
    for (uint r = top; r < bottom; r++) {
        uint off = r * self->width;
        memset(self->mask + off + left, 255, right - left);
    }
}

static void
quads(Canvas *self, ...) {
    va_list args; va_start(args, self);
    int which;
    while ((which = va_arg(args, int))) quad(self, which);
    va_end(args);
}

static void
smooth_mosaic(Canvas *self, bool lower, double ax, double ay, double bx, double by) {
    StraightLine l = line_from_points(
        ax * minus(self->width, 1), ay * minus(self->height, 1), bx * minus(self->width, 1), by * minus(self->height, 1));
    for (uint y = 0; y < self->height; y++) {
        uint offset = y * self->width;
        for (uint x = 0; x < self->width; x++) {
            double edge = line_y(l, x);
            if ((lower && y >= edge) || (!lower && y <= edge)) self->mask[offset + x] = 255;
        }
    }
}

static void
half_triangle(Canvas *self, Edge which, bool inverted) {
    uint mid_x = self->width / 2, mid_y = self->height / 2;
    StraightLine u, l;
    append_limit(self, 0, 0); // ensure space for limits
#define set_limits(startx, endx, a, b) for (uint x = startx; x < endx; x++) self->y_limits[x] = (Limit){.upper=b, .lower=a};
    switch (which) {
        case LEFT_EDGE:
            u = line_from_points(0, 0, mid_x, mid_y);
            l = line_from_points(0, minus(self->height, 1), mid_x, mid_y);
            set_limits(0, self->width, line_y(u, x), line_y(l, x));
            break;
        case TOP_EDGE:
            l = line_from_points(0, 0, mid_x, mid_y);
            set_limits(0, mid_x, 0, line_y(l, x));
            l = line_from_points(mid_x, mid_y, minus(self->width, 1), 0);
            set_limits(mid_x, self->width, 0, line_y(l, x));
            break;
        case RIGHT_EDGE:
            u = line_from_points(mid_x, mid_y, minus(self->width, 1), 0);
            l = line_from_points(mid_x, mid_y, minus(self->width, 1), minus(self->height, 1));
            set_limits(0, self->width, line_y(u, x), line_y(l, x));
            break;
        case BOTTOM_EDGE:
            l = line_from_points(0, minus(self->height, 1), mid_x, mid_y);
            set_limits(0, mid_x, line_y(l, x), minus(self->height, 1));
            l = line_from_points(mid_x, mid_y, minus(self->width, 1), minus(self->height, 1));
            set_limits(mid_x, self->width, line_y(l, x), minus(self->height, 1));
            break;
    }
    self->y_limits_count = self->width;
    fill_region(self, inverted);
#undef set_limits
}

static void
mid_lines(Canvas *self, uint level, ...) {
    uint mid_x = self->width / 2, mid_y = self->height / 2;
    const uint th = thickness(self, level, true);
    const Point l = {.x=0, .y=mid_y}, t={.x=mid_x, .y=0}, r={.x=minus(self->width, 1), .y=mid_y}, b={.x=mid_x, .y=minus(self->height, 1)};
    va_list args; va_start(args, level);
    Corner which;
    while ((which = va_arg(args, int)) > 0) {
        Point p1, p2;
        switch(which) {
            case TOP_LEFT: p1 = l; p2 = t; break;
            case TOP_RIGHT: p1 = r; p2 = t; break;
            case BOTTOM_LEFT: p1 = l; p2 = b; break;
            case BOTTOM_RIGHT: p1 = r; p2 = b; break;
        }
        thick_line(self, th, p1, p2);
    }
    va_end(args);
}

static Point*
get_fading_lines(uint total_length, uint num, Edge fade) {
    uint step = total_length / num, d1 = 0; int dir = 1;
    if (fade == LEFT_EDGE || fade == TOP_EDGE) { dir = -1; d1 = total_length; }
    Point *ans = malloc(num * sizeof(Point));
    if (!ans) fatal("Out of memory");
    for (uint i = 0; i < num; i++) {
        uint sz = step * (num - i) / (num + 1);
        if (step > 2 && sz >= step - 1) sz = step - 2;
        int d2 = d1 + dir * sz; if (d2 < 0) d2 = 0;
        if (d1 <= (uint)d2) { ans[i].x = d1; ans[i].y = d2; }
        else { ans[i].x = d2; ans[i].y = d1; }
        d1 += step * dir;
    }
    return ans;
}

static void
fading_hline(Canvas *self, uint level, uint num, Edge fade) {
    uint y = self->height / 2;
    RAII_ALLOC(Point, pts, get_fading_lines(self->width, num, fade));
    for (uint i = 0; i < num; i++) {
        uint x1 = pts[i].x, x2 = pts[i].y;
        draw_hline(self, x1, x2, y, level);
    }
}

static void
fading_vline(Canvas *self, uint level, uint num, Edge fade) {
    uint x = self->width / 2;
    RAII_ALLOC(Point, pts, get_fading_lines(self->height, num, fade));
    for (uint i = 0; i < num; i++) {
        uint y1 = pts[i].x, y2 = pts[i].y;
        draw_vline(self, y1, y2, x, level);
    }
}

typedef struct Rectircle Rectircle;

typedef struct Rectircle {
    double a, b, yexp, xexp, x_sign, y_sign, x_start, y_start;
    double x_prime_coeff, x_prime_exp, y_prime_coeff, y_prime_exp;
} Rectircle;

static double
rectircle_x(const void *v, double t) {
    const Rectircle *r = v;
    return r->x_start + r->x_sign * r->a * pow(cos(t * (M_PI / 2.0)), r->xexp);
}

static double
rectircle_x_prime(const void *v, double t) {
    const Rectircle *r = v;
    t *= (M_PI / 2.0);
    return r->x_prime_coeff * pow(cos(t), r->x_prime_exp) * sin(t);
}

static double
rectircle_y_prime(const void *v, double t) {
    const Rectircle *r = v;
    t *= (M_PI / 2.0);
    return r->y_prime_coeff * pow(sin(t), r->y_prime_exp) * cos(t);
}

static double
rectircle_y(const void *v, double t) {
    const Rectircle *r = v;
    return r->y_start + r->y_sign * r->b * pow(sin(t * (M_PI / 2.0)), r->yexp);
}

static Rectircle
rectcircle(Canvas *self, Corner which) {
    /*
    Return two functions, x(t) and y(t) that map the parameter t which must be
    in the range [0, 1] to x and y coordinates in the cell. The rectircle equation
    we use is:
    (|x| / a) ^ (2a / r) + (|y| / b) ^ (2b / r) = 1
    where 2a = width, 2b = height and r is radius
    See https://math.stackexchange.com/questions/1649714

    This is a super-ellipse, its parametrized form is:
    x = ± a * (cos(theta) ^ (r / a)); y = ± b * (sin(theta) ^ (r / b)); theta is in [0, pi/2]
    https://en.wikipedia.org/wiki/Superellipse
    The plus minus signs are chosen to give the four quadrants.

    The entire rectircle fits in four cells, each cell being one quadrant
    of the full rectircle and the origin being the center of the rectircle.
    The functions we return do the mapping for the specified cell.
    ╭╮  ╭─╮
    ╰╯  │ │
        ╰─╯
    */
    double radius = self->width / 2., a = self->width / 2., b = self->height / 2.;
    Rectircle ans = {
        .a = a, .b = b,
        .xexp = radius / a, .yexp = radius / b,
        .x_prime_coeff = radius, .x_prime_exp = radius / a - 1.,
        .y_prime_coeff = radius, .y_prime_exp = radius / b - 1.,
        .x_sign = which & RIGHT_EDGE ? 1. : -1,
        .x_start = which & RIGHT_EDGE ? 0. : 2 * a,
        .y_start = which & BOTTOM_EDGE ? 0. : 2 * b,
        .y_sign = which & BOTTOM_EDGE ? 1. : -1,
    };

    return ans;
}

static void
rounded_corner(Canvas *self, uint level, Corner which) {
    Rectircle r = rectcircle(self, which);
    uint cell_width_is_odd = (self->width / self->supersample_factor) & 1;
    uint cell_height_is_odd = (self->height / self->supersample_factor) & 1;
    // adjust for odd cell dimensions to line up with box drawing lines
    int x_offset = -(cell_width_is_odd & 1), y_offset = -(cell_height_is_odd & 1);
    double line_width = thickness_as_float(self, level, true);
    draw_parametrized_curve_with_derivative(self, &r, line_width, rectircle_x, rectircle_y, rectircle_x_prime, rectircle_y_prime, x_offset, y_offset, 0.1);
}

static void
commit(Canvas *self, Edge lines, bool solid) {
    static const uint level = 1; static const double scale = 0.9;
    uint hw = half_width(self), hh = half_height(self);
    if (lines & RIGHT_EDGE) draw_hline(self, hw, self->width, hh, level);
    if (lines & LEFT_EDGE) draw_hline(self, 0, hw, hh, level);
    if (lines & TOP_EDGE) draw_vline(self, 0, hh, hw, level);
    if (lines & BOTTOM_EDGE) draw_vline(self, hh, self->height, hw, level);
    fill_circle(self, scale, 0, false);
    if (!solid) fill_circle(self, scale, thickness(self, level, true), true);
}

// thin and fat line levels
#define t 1u
#define f 3u

static void
corner(Canvas *self, uint hlevel, uint vlevel, Corner which) {
    half_hline(self, hlevel, which & RIGHT_EDGE, thickness(self, vlevel, true) / 2);
    half_vline(self, vlevel, which & BOTTOM_EDGE, 0);
}

static void
cross(Canvas *self, uint which) {
    static const uint level_map[16][4] = {
        {t, t, t, t}, {f, t, t, t}, {t, f, t, t}, {f, f, t, t}, {t, t, f, t}, {t, t, t, f}, {t, t, f, f},
        {f, t, f, t}, {t, f, f, t}, {f, t, t, f}, {t, f, t, f}, {f, f, f, t}, {f, f, t, f}, {f, t, f, f},
        {t, f, f, f}, {f, f, f, f}
    };
    const uint *m = level_map[which];
    half_hline(self, m[0], false, 0); half_hline(self, m[1], true, 0);
    half_vline(self, m[2], false, 0); half_vline(self, m[3], true, 0);
}

static void
vert_t(Canvas *self, uint base_char, uint variation) {
    static const uint level_map[8][3] = {
        {t, t, t}, {t, f, t}, {f, t, t}, {t, t, f}, {f, t, f}, {f, f, t}, {t, f, f}, {f, f, f}
    };
    const uint *m = level_map[variation];
    half_vline(self, m[0], false, 0);
    half_hline(self, m[1], base_char != L'┤', 0);
    half_vline(self, m[2], true, 0);
}

static void
horz_t(Canvas *self, uint base_char, uint variation) {
    static const uint level_map[8][3] = {
        {t, t, t}, {f, t, t}, {t, f, t}, {f, f, t}, {t, t, f}, {f, t, f}, {t, f, f}, {f, f, f}
    };
    const uint *m = level_map[variation];
    half_hline(self, m[0], false, 0);
    half_hline(self, m[1], true, 0);
    half_vline(self, m[2], base_char != L'┴', 0);
}

static void
dvcorner(Canvas *self, uint level, Corner which) {
    half_dhline(self, level, which & LEFT_EDGE, TOP_EDGE | BOTTOM_EDGE);
    uint gap = thickness(self, level + 1, false);
    half_vline(self, level, which & TOP_EDGE, gap / 2 + thickness(self, level, false));
}

static void
dhcorner(Canvas *self, uint level, Corner which) {
    half_dvline(self, level, which & TOP_EDGE, LEFT_EDGE | RIGHT_EDGE);
    uint gap = thickness(self, level + 1, true);
    half_hline(self, level, which & LEFT_EDGE, gap / 2 + thickness(self, level, true));
}

static void
dcorner(Canvas *self, uint level, Corner which) {
    uint hgap = thickness(self, level + 1, false);
    uint vgap = thickness(self, level + 1, true);
    uint x1 = self->width / 2, x2 = self->width / 2;
    if (which & RIGHT_EDGE) x1 = 0; else x2 = self->width;
    uint ypos = self->height / 2;
    int ydelta = which & BOTTOM_EDGE ? hgap : -hgap;
    if (which & RIGHT_EDGE) x2 += vgap; else x1 = minus(x1, vgap);
    draw_hline(self, x1, x2, ypos + ydelta, level);
    if (which & RIGHT_EDGE) x2 = minus(x2, 2 * vgap); else x1 += 2 * vgap;
    draw_hline(self, x1, x2, ypos - ydelta, level);
    uint y1 = self->height / 2, y2 = self->height / 2;
    if (which & BOTTOM_EDGE) y1 = 0; else y2 = self->height;
    uint xpos = self->width / 2;
    int xdelta = (which & LEFT_EDGE) ? vgap : -vgap;
    uint yd = thickness(self, level, true) / 2;
    if (which & BOTTOM_EDGE) y2 += hgap + yd; else y1 -= hgap + yd;
    draw_vline(self, y1, y2, xpos - xdelta, level);
    if (which & BOTTOM_EDGE) y2 -= 2 * hgap; else y1 += 2 * hgap;
    draw_vline(self, y1, y2, xpos + xdelta, level);
}


static void
dpip(Canvas *self, uint level, Edge which) {
    uint x1, x2, y1, y2;
    if (which & (LEFT_EDGE | RIGHT_EDGE)) {
        Point p = dvline(self, level, LEFT_EDGE | RIGHT_EDGE);
        if (which & LEFT_EDGE) { x1 = 0; x2 = p.x; } else { x1 = p.y; x2 =self->width; }
        draw_hline(self, x1, x2, self->height / 2, level);
    } else {
        Point p = dhline(self, level, TOP_EDGE | BOTTOM_EDGE);
        if (which & TOP_EDGE) { y1 = 0; y2 = p.x; } else { y1 = p.y; y2 = self->height; }
        draw_vline(self, y1, y2, self->width / 2, level);
    }
}

static void
braille_dot(Canvas *self, uint col, uint row) {
    static const uint num_x_dots = 2, num_y_dots = 4;
    unsigned x_gaps[num_x_dots * 2], y_gaps[num_y_dots * 2];
    unsigned dot_width = distribute_dots(self->width, num_x_dots, x_gaps, x_gaps + num_x_dots);
    unsigned dot_height = distribute_dots(self->height, num_y_dots, y_gaps, y_gaps + num_y_dots);
    uint x_start = x_gaps[col] + col * dot_width;
    uint y_start = y_gaps[row] + row * dot_height;
    if (y_start < self->height && x_start < self->width) {
        for (uint y = y_start; y < min(self->height, y_start + dot_height); y++) {
            uint offset = y * self->width;
            memset(self->mask + offset + x_start, 255, minus(min(self->width, x_start + dot_width), x_start));
        }
    }
}


static void
braille(Canvas *self, uint8_t which) {
    if (!which) return;
    for (uint8_t i = 0, mask = 1; i < 8; i++, mask <<= 1) {
        if (which & mask) {
            uint q = i + 1, col, row;
            switch(q) { case 1: case 2: case 3: case 7: col = 0; break; default: col = 1; break; }
            switch(q) { case 1: case 4: row = 0; break; case 2: case 5: row = 1; break; case 3: case 6: row = 2; break; default: row = 3; }
            braille_dot(self, col, row);
        }
    }
}

static void
draw_sextant(Canvas *self, uint row, uint col) {
    Point start = {0}, end = {.x=self->width, .y = self->height};
    switch(row) {
        case 0: end.y = self->height / 3; break;
        case 1: start.y = self->height / 3; end.y = 2 * self->height / 3; break;
        case 2: start.y = 2 * self->height / 3; break;
    }
    switch(col) {
        case 0: end.x = self->width / 2; break;
        default: start.x = self->width / 2; break;
    }
    for (int r = start.y; r < end.y; r++) {
        uint off = r * self->width;
        memset(self->mask + off + start.x, 255, end.x - start.x);
    }
}

static void
sextant(Canvas *self, uint which) {
#define add_row(q, r) if (q & 1) { draw_sextant(self, r, 0); } if (q & 2) { draw_sextant(self, r, 1); }
    add_row(which % 4, 0)
    add_row(which / 4, 1)
    add_row(which / 16, 2)
#undef add_row
}

void
render_box_char(char_type ch, uint8_t *buf, unsigned width, unsigned height, double dpi_x, double dpi_y, double scale) {
    Canvas canvas = {.mask=buf, .width = width, .height = height, .dpi={.x=dpi_x, .y=dpi_y}, .supersample_factor=1u, .scale=scale}, ss = canvas;
    ss.mask = buf + width*height; ss.supersample_factor = SUPERSAMPLE_FACTOR; ss.width *= SUPERSAMPLE_FACTOR; ss.height *= SUPERSAMPLE_FACTOR;
    fill_canvas(&canvas, 0);
    Canvas *c = &canvas;

#define SB(ch, ...) case ch: fill_canvas(&ss, 0); c = &ss, __VA_ARGS__; downsample(&ss, &canvas);
#define CC(ch, ...) case ch: __VA_ARGS__; break
#define SS(ch, ...) SB(ch, __VA_ARGS__); break
#define C(ch, func, ...) CC(ch, func(c, __VA_ARGS__))
#define S(ch, func, ...) SS(ch, func(c, __VA_ARGS__))
START_ALLOW_CASE_RANGE

    switch(ch) {
        default: log_error("Unknown box drawing character: U+%x rendered as blank", ch); break;
        case L'█': fill_canvas(c, 255); break;

        C(L'─', hline, 1);
        C(L'━', hline, 3);
        C(L'│', vline, 1);
        C(L'┃', vline, 3);

        C(L'╌', hholes, 1, 1);
        C(L'╍', hholes, 3, 1);
        C(L'┄', hholes, 1, 2);
        C(L'┅', hholes, 3, 2);
        C(L'┈', hholes, 1, 3);
        C(L'┉', hholes, 3, 3);

        C(L'╎', vholes, 1, 1);
        C(L'╏', vholes, 3, 1);
        C(L'┆', vholes, 1, 2);
        C(L'┇', vholes, 3, 2);
        C(L'┊', vholes, 1, 3);
        C(L'┋', vholes, 3, 3);

        C(L'╴', half_hline, 1, false, 0);
        C(L'╵', half_vline, 1, false, 0);
        C(L'╶', half_hline, 1, true, 0);
        C(L'╷', half_vline, 1, true, 0);
        C(L'╸', half_hline, 3, false, 0);
        C(L'╹', half_vline, 3, false, 0);
        C(L'╺', half_hline, 3, true, 0);
        C(L'╻', half_vline, 3, true, 0);
        CC(L'╾', half_hline(c, 3, false, 0); half_hline(c, 1, true, 0));
        CC(L'╼', half_hline(c, 1, false, 0); half_hline(c, 3, true, 0));
        CC(L'╿', half_vline(c, 3, false, 0); half_vline(c, 1, true, 0));
        CC(L'╽', half_vline(c, 1, false, 0); half_vline(c, 3, true, 0));

        S(L'', triangle, true, false);
        S(L'', triangle, true, true);
        SS(L'', half_cross_line(c, 1, TOP_LEFT); half_cross_line(c, 1, BOTTOM_LEFT));
        S(L'', triangle, false, false);
        S(L'', triangle, false, true);
        SS(L'', half_cross_line(c, 1, TOP_RIGHT); half_cross_line(c, 1, BOTTOM_RIGHT));

        S(L'', filled_D, true);
        S(L'◗', filled_D, true);
        S(L'', filled_D, false);
        S(L'◖', filled_D, false);
        S(L'', rounded_separator, 1, true);
        S(L'', rounded_separator, 1, false);

        S(L'', cross_line, 1, true);
        S(L'', cross_line, 1, true);
        S(L'╲', cross_line, 1, true);
        S(L'', cross_line, 1, false);
        S(L'', cross_line, 1, false);
        S(L'╱', cross_line, 1, false);
        SS(L'╳', cross_line(c, 1, false); cross_line(c, 1, true));

        S(L'', corner_triangle, BOTTOM_LEFT);
        S(L'◣', corner_triangle, BOTTOM_LEFT);
        S(L'', corner_triangle, BOTTOM_RIGHT);
        S(L'◢', corner_triangle, BOTTOM_RIGHT);
        S(L'', corner_triangle, TOP_LEFT);
        S(L'◤', corner_triangle, TOP_LEFT);
        S(L'', corner_triangle, TOP_RIGHT);
        S(L'◥', corner_triangle, TOP_RIGHT);

        C(L'', progress_bar, LEFT, false);
        C(L'', progress_bar, MIDDLE, false);
        C(L'', progress_bar, RIGHT, false);
        C(L'', progress_bar, LEFT, true);
        C(L'', progress_bar, MIDDLE, true);
        C(L'', progress_bar, RIGHT, true);

        S(L'', spinner, 1, 235, 305);
        S(L'', spinner, 1, 270, 390);
        S(L'', spinner, 1, 315, 470);
        S(L'', spinner, 1, 360, 540);
        S(L'', spinner, 1, 80, 220);
        S(L'', spinner, 1, 170, 270);
        S(L'○', spinner, 0, 0, 360);
        S(L'◜', spinner, 1, 180, 270);
        S(L'◝', spinner, 1, 270, 360);
        S(L'◞', spinner, 1, 360, 450);
        S(L'◟', spinner, 1, 450, 540);
        S(L'◠', spinner, 1, 180, 360);
        S(L'◡', spinner, 1, 0, 180);
        S(L'●', fill_circle, 1.0, 0, false);
        S(L'◉', draw_fish_eye, 0);

        C(L'═', dhline, 1, TOP_EDGE | BOTTOM_EDGE);
        C(L'║', dvline, 1, LEFT_EDGE | RIGHT_EDGE);
        CC(L'╞', vline(c, 1); half_dhline(c, 1, true, TOP_EDGE | BOTTOM_EDGE));
        CC(L'╡', vline(c, 1); half_dhline(c, 1, false, TOP_EDGE | BOTTOM_EDGE));
        CC(L'╥', hline(c, 1); half_dvline(c, 1, true, LEFT_EDGE | RIGHT_EDGE));
        CC(L'╨', hline(c, 1); half_dvline(c, 1, false, LEFT_EDGE | RIGHT_EDGE));
        CC(L'╪', vline(c, 1); dhline(c, 1, TOP_EDGE | BOTTOM_EDGE));
        CC(L'╫', hline(c, 1), dvline(c, 1, LEFT_EDGE | RIGHT_EDGE));
        CC(L'╬', inner_corner(c, 1, TOP_LEFT); inner_corner(c, 1, TOP_RIGHT); inner_corner(c, 1, BOTTOM_LEFT); inner_corner(c, 1, BOTTOM_RIGHT));
        CC(L'╠', inner_corner(c, 1, TOP_RIGHT); inner_corner(c, 1, BOTTOM_RIGHT); dvline(c, 1, LEFT_EDGE));
        CC(L'╣', inner_corner(c, 1, TOP_LEFT); inner_corner(c, 1, BOTTOM_LEFT); dvline(c, 1, RIGHT_EDGE));
        CC(L'╦', inner_corner(c, 1, BOTTOM_LEFT); inner_corner(c, 1, BOTTOM_RIGHT); dhline(c, 1, TOP_EDGE));
        CC(L'╩', inner_corner(c, 1, TOP_LEFT); inner_corner(c, 1, TOP_RIGHT); dhline(c, 1, BOTTOM_EDGE));

#define EH(ch, ...) C(ch, eight_block, true, __VA_ARGS__, -1);
        EH(L'▔', 0);
        EH(L'▀', 0, 1, 2, 3);
        EH(L'▁', 7);
        EH(L'▂', 6, 7);
        EH(L'▃', 5, 6, 7);
        EH(L'▄', 4, 5, 6, 7);
        EH(L'▅', 3, 4, 5, 6, 7);
        EH(L'▆', 2, 3, 4, 5, 6, 7);
        EH(L'▇', 1, 2, 3, 4, 5, 6, 7);
#undef EH
#define EV(ch, ...) C(ch, eight_block, false, __VA_ARGS__, -1);
        EV(L'▉', 0, 1, 2, 3, 4, 5, 6);
        EV(L'▊', 0, 1, 2, 3, 4, 5);
        EV(L'▋', 0, 1, 2, 3, 4);
        EV(L'▌', 0, 1, 2, 3);
        EV(L'▍', 0, 1, 2);
        EV(L'▎', 0, 1);
        EV(L'▏', 0);
        EV(L'▕', 7);
        EV(L'▐', 4, 5, 6, 7);
#undef EV
#define SH(ch, ...) C(ch, shade, (Shade){ __VA_ARGS__ });
        SH(L'░', .xnum=12, .light=true);
        SH(L'▒', .xnum=12);
        SH(L'▓', .xnum=12, .light=true, .invert=true);
        SH(L'🮌', .xnum=12, .which_half=LEFT_EDGE);
        SH(L'🮍', .xnum=12, .which_half=RIGHT_EDGE);
        SH(L'🮎', .xnum=12, .which_half=TOP_EDGE);
        SH(L'🮏', .xnum=12, .which_half=BOTTOM_EDGE);
        SH(L'🮐', .xnum=12, .invert=true);
        SH(L'🮑', .xnum=12, .invert=true, .fill_blank=true, .which_half=BOTTOM_EDGE);
        SH(L'🮒', .xnum=12, .invert=true, .fill_blank=true, .which_half=TOP_EDGE);
        SH(L'🮓', .xnum=12, .invert=true, .fill_blank=true, .which_half=RIGHT_EDGE);
        SH(L'🮔', .xnum=12, .invert=true, .fill_blank=true, .which_half=LEFT_EDGE);
        SH(L'🮕', .xnum=4, .ynum=4);
        SH(L'🮖', .xnum=4, .ynum=4, .invert=true);
        SH(L'🮗', .xnum=1, .ynum=4, .invert=true);
#define M(ch, corner) SB(ch, corner_triangle(c, corner)); \
            memcpy(ss.mask, canvas.mask, sizeof(canvas.mask[0]) * canvas.width * canvas.height); \
            fill_canvas(&canvas, 0); shade(&canvas, (Shade){.xnum=12}); \
            apply_mask(&canvas, ss.mask); break;
        M(L'🮜', TOP_LEFT);
        M(L'🮝', TOP_RIGHT);
        M(L'🮞', BOTTOM_RIGHT);
        M(L'🮟', BOTTOM_LEFT);
#undef M
#undef SH
        S(L'🮘', cross_shade, false);
        S(L'🮙', cross_shade, true);

        C(L'▖', quad, BOTTOM_LEFT);
        C(L'▗', quad, BOTTOM_RIGHT);
        C(L'▘', quad, TOP_LEFT);
        C(L'▝', quad, TOP_RIGHT);
        C(L'▙', quads, TOP_LEFT, BOTTOM_LEFT, BOTTOM_RIGHT, 0);
        C(L'▚', quads, TOP_LEFT, BOTTOM_RIGHT, 0);
        C(L'▛', quads, TOP_LEFT, TOP_RIGHT, BOTTOM_LEFT, 0);
        C(L'▜', quads, TOP_LEFT, TOP_RIGHT, BOTTOM_RIGHT, 0);
        C(L'▞', quads, TOP_RIGHT, BOTTOM_LEFT, 0);
        C(L'▟', quads, TOP_RIGHT, BOTTOM_LEFT, BOTTOM_RIGHT, 0);

        S(L'🬼', smooth_mosaic, true, 0, 2. / 3, 0.5, 1);
        S(L'🬽', smooth_mosaic, true, 0, 2. / 3, 1, 1);
        S(L'🬾', smooth_mosaic, true, 0, 1. / 3, 0.5, 1);
        S(L'🬿', smooth_mosaic, true, 0, 1. / 3, 1, 1);
        S(L'🭀', smooth_mosaic, true, 0, 0, 0.5, 1);

        S(L'🭁', smooth_mosaic, true, 0, 1. / 3, 0.5, 0);
        S(L'🭂', smooth_mosaic, true, 0, 1. / 3, 1, 0);
        S(L'🭃', smooth_mosaic, true, 0, 2. / 3, 0.5, 0);
        S(L'🭄', smooth_mosaic, true, 0, 2. / 3, 1, 0);
        S(L'🭅', smooth_mosaic, true, 0, 1, 0.5, 0);
        S(L'🭆', smooth_mosaic, true, 0, 2. / 3, 1, 1. / 3);

        S(L'🭇', smooth_mosaic, true, 0.5, 1, 1, 2. / 3);
        S(L'🭈', smooth_mosaic, true, 0, 1, 1, 2. / 3);
        S(L'🭉', smooth_mosaic, true, 0.5, 1, 1, 1. / 3);
        S(L'🭊', smooth_mosaic, true, 0, 1, 1, 1. / 3);
        S(L'🭋', smooth_mosaic, true, 0.5, 1, 1, 0);

        S(L'🭌', smooth_mosaic, true, 0.5, 0, 1, 1. / 3);
        S(L'🭍', smooth_mosaic, true, 0, 0, 1, 1. / 3);
        S(L'🭎', smooth_mosaic, true, 0.5, 0, 1, 2. / 3);
        S(L'🭏', smooth_mosaic, true, 0, 0, 1, 2. / 3);
        S(L'🭐', smooth_mosaic, true, 0.5, 0, 1, 1);
        S(L'🭑', smooth_mosaic, true, 0, 1. / 3, 1, 2. / 3);

        S(L'🭒', smooth_mosaic, false, 0, 2. / 3, 0.5, 1);
        S(L'🭓', smooth_mosaic, false, 0, 2. / 3, 1, 1);
        S(L'🭔', smooth_mosaic, false, 0, 1. / 3, 0.5, 1);
        S(L'🭕', smooth_mosaic, false, 0, 1. / 3, 1, 1);
        S(L'🭖', smooth_mosaic, false, 0, 0, 0.5, 1);

        S(L'🭗', smooth_mosaic, false, 0, 1. / 3, 0.5, 0);
        S(L'🭘', smooth_mosaic, false, 0, 1. / 3, 1, 0);
        S(L'🭙', smooth_mosaic, false, 0, 2. / 3, 0.5, 0);
        S(L'🭚', smooth_mosaic, false, 0, 2. / 3, 1, 0);
        S(L'🭛', smooth_mosaic, false, 0, 1, 0.5, 0);

        S(L'🭜', smooth_mosaic, false, 0, 2. / 3, 1, 1. / 3);
        S(L'🭝', smooth_mosaic, false, 0.5, 1, 1, 2. / 3);
        S(L'🭞', smooth_mosaic, false, 0, 1, 1, 2. / 3);
        S(L'🭟', smooth_mosaic, false, 0.5, 1, 1, 1. / 3);
        S(L'🭠', smooth_mosaic, false, 0, 1, 1, 1. / 3);
        S(L'🭡', smooth_mosaic, false, 0.5, 1, 1, 0);

        S(L'🭢', smooth_mosaic, false, 0.5, 0, 1, 1. / 3);
        S(L'🭣', smooth_mosaic, false, 0, 0, 1, 1. / 3);
        S(L'🭤', smooth_mosaic, false, 0.5, 0, 1, 2. / 3);
        S(L'🭥', smooth_mosaic, false, 0, 0, 1, 2. / 3);
        S(L'🭦', smooth_mosaic, false, 0.5, 0, 1, 1);
        S(L'🭧', smooth_mosaic, false, 0, 1. / 3, 1, 2. / 3);

        S(L'🭨', half_triangle, LEFT_EDGE, true);
        S(L'🭩', half_triangle, TOP_EDGE, true);
        S(L'🭪', half_triangle, RIGHT_EDGE, true);
        S(L'🭫', half_triangle, BOTTOM_EDGE, true);
        S(L'🭬', half_triangle, LEFT_EDGE, false);
        SS(L'🮛', half_triangle(c, LEFT_EDGE, false), half_triangle(c, RIGHT_EDGE, false));
        S(L'🭭', half_triangle, TOP_EDGE, false);
        S(L'🭮', half_triangle, RIGHT_EDGE, false);
        S(L'🭯', half_triangle, BOTTOM_EDGE, false);
        SS(L'🮚', half_triangle(c, BOTTOM_EDGE, false), half_triangle(c, TOP_EDGE, false));

        CC(L'🭼', eight_bar(c, 0, false); eight_bar(c, 7, true));
        CC(L'🭽', eight_bar(c, 0, false); eight_bar(c, 0, true));
        CC(L'🭾', eight_bar(c, 7, false); eight_bar(c, 0, true));
        CC(L'🭿', eight_bar(c, 7, false); eight_bar(c, 7, true));
        CC(L'🮀', eight_bar(c, 0, true); eight_bar(c, 7, true));
        CC(L'🮁', eight_bar(c, 0, true); eight_bar(c, 2, true); eight_bar(c, 4, true); eight_bar(c, 7, true));

        C(L'🮂', eight_block, true, 0, 1, -1);
        C(L'🮃', eight_block, true, 0, 1, 2, -1);
        C(L'🮄', eight_block, true, 0, 1, 2, 3, 4, -1);
        C(L'🮅', eight_block, true, 0, 1, 2, 3, 4, 5, -1);
        C(L'🮆', eight_block, true, 0, 1, 2, 3, 4, 5, 6, -1);
        C(L'🮇', eight_block, false, 6, 7, -1);
        C(L'🮈', eight_block, false, 5, 6, 7, -1);
        C(L'🮉', eight_block, false, 3, 4, 5, 6, 7, -1);
        C(L'🮊', eight_block, false, 2, 3, 4, 5, 6, 7, -1);
        C(L'🮋', eight_block, false, 1, 2, 3, 4, 5, 6, 7, -1);

        S(L'🮠', mid_lines, 1, TOP_LEFT, 0);
        S(L'🮡', mid_lines, 1, TOP_RIGHT, 0);
        S(L'🮢', mid_lines, 1, BOTTOM_LEFT, 0);
        S(L'🮣', mid_lines, 1, BOTTOM_RIGHT, 0);
        S(L'🮤', mid_lines, 1, TOP_LEFT, BOTTOM_LEFT, 0);
        S(L'🮥', mid_lines, 1, TOP_RIGHT, BOTTOM_RIGHT, 0);
        S(L'🮦', mid_lines, 1, BOTTOM_RIGHT, BOTTOM_LEFT, 0);
        S(L'🮧', mid_lines, 1, TOP_RIGHT, TOP_LEFT, 0);
        S(L'🮨', mid_lines, 1, BOTTOM_RIGHT, TOP_LEFT, 0);
        S(L'🮩', mid_lines, 1, BOTTOM_LEFT, TOP_RIGHT, 0);
        S(L'🮪', mid_lines, 1, BOTTOM_LEFT, TOP_RIGHT, BOTTOM_RIGHT, 0);
        S(L'🮫', mid_lines, 1, BOTTOM_LEFT, TOP_LEFT, BOTTOM_RIGHT, 0);
        S(L'🮬', mid_lines, 1, TOP_RIGHT, TOP_LEFT, BOTTOM_RIGHT, 0);
        S(L'🮭', mid_lines, 1, TOP_RIGHT, TOP_LEFT, BOTTOM_LEFT, 0);
        S(L'🮮', mid_lines, 1, TOP_RIGHT, BOTTOM_RIGHT, TOP_LEFT, BOTTOM_LEFT, 0);

        C(L'', hline, 1);
        C(L'', vline, 1);
        C(L'', fading_hline, 1, 4, RIGHT_EDGE);
        C(L'', fading_hline, 1, 4, LEFT_EDGE);
        C(L'', fading_vline, 1, 5, BOTTOM_EDGE);
        C(L'', fading_vline, 1, 5, TOP_EDGE);

        S(L'', rounded_corner, 1, TOP_LEFT);
        S(L'', rounded_corner, 1, TOP_RIGHT);
        S(L'', rounded_corner, 1, BOTTOM_LEFT);
        S(L'', rounded_corner, 1, BOTTOM_RIGHT);

        SS(L'', vline(c, 1); rounded_corner(c, 1, BOTTOM_LEFT));
        SS(L'', vline(c, 1); rounded_corner(c, 1, TOP_LEFT));
        SS(L'', rounded_corner(c, 1, BOTTOM_LEFT), rounded_corner(c, 1, TOP_LEFT));
        SS(L'', vline(c, 1); rounded_corner(c, 1, BOTTOM_RIGHT));
        SS(L'', vline(c, 1); rounded_corner(c, 1, TOP_RIGHT));
        SS(L'', rounded_corner(c, 1, TOP_RIGHT), rounded_corner(c, 1, BOTTOM_RIGHT));
        SS(L'', hline(c, 1); rounded_corner(c, 1, TOP_RIGHT));
        SS(L'', hline(c, 1); rounded_corner(c, 1, TOP_LEFT));
        SS(L'', rounded_corner(c, 1, TOP_LEFT), rounded_corner(c, 1, TOP_RIGHT));
        SS(L'', hline(c, 1); rounded_corner(c, 1, BOTTOM_RIGHT));
        SS(L'', hline(c, 1); rounded_corner(c, 1, BOTTOM_LEFT));
        SS(L'', rounded_corner(c, 1, BOTTOM_LEFT), rounded_corner(c, 1, BOTTOM_RIGHT));
        SS(L'', vline(c, 1); rounded_corner(c, 1, BOTTOM_LEFT), rounded_corner(c, 1, BOTTOM_RIGHT));
        SS(L'', vline(c, 1); rounded_corner(c, 1, TOP_LEFT), rounded_corner(c, 1, TOP_RIGHT));
        SS(L'', hline(c, 1); rounded_corner(c, 1, TOP_RIGHT), rounded_corner(c, 1, BOTTOM_RIGHT));
        SS(L'', hline(c, 1); rounded_corner(c, 1, BOTTOM_LEFT), rounded_corner(c, 1, TOP_LEFT));
        SS(L'', vline(c, 1); rounded_corner(c, 1, TOP_LEFT), rounded_corner(c, 1, BOTTOM_RIGHT));
        SS(L'', vline(c, 1); rounded_corner(c, 1, TOP_RIGHT), rounded_corner(c, 1, BOTTOM_LEFT));
        SS(L'', hline(c, 1); rounded_corner(c, 1, TOP_LEFT), rounded_corner(c, 1, BOTTOM_RIGHT));
        SS(L'', hline(c, 1); rounded_corner(c, 1, TOP_RIGHT), rounded_corner(c, 1, BOTTOM_LEFT));

#define P(ch, lines) S(ch, commit, lines, true); S(ch+1, commit, lines, false);
        P(L'', 0);
        P(L'', RIGHT_EDGE);
        P(L'', LEFT_EDGE);
        P(L'', LEFT_EDGE | RIGHT_EDGE);
        P(L'', BOTTOM_EDGE);
        P(L'', TOP_EDGE);
        P(L'', BOTTOM_EDGE | TOP_EDGE);
        P(L'', RIGHT_EDGE | BOTTOM_EDGE);
        P(L'', LEFT_EDGE | BOTTOM_EDGE);
        P(L'', RIGHT_EDGE | TOP_EDGE);
        P(L'', LEFT_EDGE | TOP_EDGE);
        P(L'', TOP_EDGE | BOTTOM_EDGE | RIGHT_EDGE);
        P(L'', TOP_EDGE | BOTTOM_EDGE | LEFT_EDGE);
        P(L'', LEFT_EDGE | RIGHT_EDGE | BOTTOM_EDGE);
        P(L'', LEFT_EDGE | RIGHT_EDGE | TOP_EDGE);
        P(L'', LEFT_EDGE | RIGHT_EDGE | TOP_EDGE | BOTTOM_EDGE);
#undef P
#define Q(ch, which) C(ch, corner, t, t, which); C(ch + 1, corner, f, t, which); C(ch + 2, corner, t, f, which); C(ch + 3, corner, f, f, which);
        Q(L'┌', BOTTOM_RIGHT); Q(L'┐', BOTTOM_LEFT); Q(L'└', TOP_RIGHT); Q(L'┘', TOP_LEFT);
#undef Q
        S(L'╭', rounded_corner, 1, TOP_LEFT);
        S(L'╮', rounded_corner, 1, TOP_RIGHT);
        S(L'╰', rounded_corner, 1, BOTTOM_LEFT);
        S(L'╯', rounded_corner, 1, BOTTOM_RIGHT);

        case L'┼' ... L'┼' + 15: cross(c, ch - L'┼'); break;
#define T(q, func) case q ... q + 7: func(c, q, ch - q); break;
        T(L'├', vert_t); T(L'┤', vert_t);
        T(L'┬', horz_t); T(L'┴', horz_t);
#undef T
        C(L'╒', dvcorner, 1, TOP_LEFT);
        C(L'╕', dvcorner, 1, TOP_RIGHT);
        C(L'╘', dvcorner, 1, BOTTOM_LEFT);
        C(L'╛', dvcorner, 1, BOTTOM_RIGHT);
        C(L'╓', dhcorner, 1, TOP_LEFT);
        C(L'╖', dhcorner, 1, TOP_RIGHT);
        C(L'╙', dhcorner, 1, BOTTOM_LEFT);
        C(L'╜', dhcorner, 1, BOTTOM_RIGHT);
        C(L'╔', dcorner, 1, TOP_LEFT);
        C(L'╗', dcorner, 1, TOP_RIGHT);
        C(L'╚', dcorner, 1, BOTTOM_LEFT);
        C(L'╝', dcorner, 1, BOTTOM_RIGHT);
        C(L'╟', dpip, 1, RIGHT_EDGE);
        C(L'╢', dpip, 1, LEFT_EDGE);
        C(L'╤', dpip, 1, BOTTOM_EDGE);
        C(L'╧', dpip, 1, TOP_EDGE);

        case 0x2800 ... 0x2800 + 255: braille(c, ch - 0x2800); break;
        case 0x1fb00 ... 0x1fb00 + 19: sextant(c, ch - 0x1fb00 + 1); break;
        case 0x1fb14 ... 0x1fb14 + 19: sextant(c, ch - 0x1fb00 + 2); break;
        case 0x1fb28 ... 0x1fb28 + 19: sextant(c, ch - 0x1fb00 + 3); break;
        case 0x1fb70 ... 0x1fb70 + 5: eight_bar(c, ch - 0x1fb6f, false); break;
        case 0x1fb76 ... 0x1fb76 + 5: eight_bar(c, ch - 0x1fb75, true); break;
        case 0x1fbe6: octant(c, 0xe6); break;
        case 0x1fbe7: octant(c, 0xe7); break;
        case 0x1cd00 ... 0x1cde5: octant(c, ch - 0x1cd00); break;
    }
    free(canvas.holes); free(canvas.y_limits);
    free(ss.holes); free(ss.y_limits);
END_ALLOW_CASE_RANGE
#undef CC
#undef SS
#undef C
#undef S
#undef SB
#undef t
#undef f
}
