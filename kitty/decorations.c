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

static unsigned
add_intensity(uint8_t *buf, unsigned x, unsigned y, uint8_t val, unsigned max_y, unsigned position, unsigned cell_width) {
    y += position;
    y = min(y, max_y);
    unsigned idx = cell_width * y + x;
    buf[idx] = min(255, buf[idx] + val);
    return y;
}

DecorationGeometry
add_curl_underline(uint8_t *buf, FontCellMetrics fcm) {
    unsigned max_x = fcm.cell_width - 1, max_y = fcm.cell_height - 1;
    double xfactor = ((OPT(undercurl_style) & 1) ? 4.0 : 2.0) * M_PI / max_x;
    unsigned half_thickness = fcm.underline_thickness / 2;
    unsigned top = fcm.underline_position > half_thickness ? fcm.underline_position - half_thickness : 0;
    unsigned max_height = fcm.cell_height - top;  // descender from the font
    unsigned half_height = max(1u, max_height / 4u);
    unsigned thickness;
    if (OPT(undercurl_style) & 2) thickness = max(half_height, fcm.underline_thickness);
    else thickness = max(1u, fcm.underline_thickness) - (fcm.underline_thickness < 3u ? 1u : 2u);
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
        unsigned intensity = (unsigned)(255. * fabs(y - floor(y)));
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
        for (unsigned x = offset; x < offset + width; x++) ans[x] = 0xff;
    }
}

static unsigned
horz(uint8_t *ans, bool is_top_edge, double height_pt, double dpi_y, FontCellMetrics fcm) {
    unsigned height = max(1u, min((unsigned)(round(height_pt * dpi_y / 72.0)), fcm.cell_height));
    const unsigned top = is_top_edge ? 0 : (fcm.cell_height > height ? fcm.cell_height - height : 0);
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
typedef struct Range {
    uint start, end;
} Range;

typedef struct Canvas {
    uint8_t *mask;
    uint width, height, supersample_factor;
    struct { double x, y; } dpi;
    Range *holes; uint holes_count, holes_capacity;
    struct { double upper, lower; } *y_limits; uint y_limits_count, y_limits_capacity;
} Canvas;

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


static uint
thickness(Canvas *self, uint level, bool horizontal) {
    level = min(level, arraysz(OPT(box_drawing_scale)));
    double pts = OPT(box_drawing_scale)[level];
    double dpi = horizontal ? self->dpi.x : self->dpi.y;
    return self->supersample_factor * (uint)ceil(pts * dpi / 72.0);
}

static uint
minus(uint a, uint b) {  // saturating subtraction (a > b ? a - b : 0)
    uint res = a - b;
    res &= -(res <= a);
    return res;
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
        memset(py + x1, 255, minus(x2, x1));
    }
}

static void
draw_vline(Canvas *self, uint y1, uint y2, uint x, uint level) {
    // Draw a vertical line between [y1, y2) centered at x with the thickness given by level and self->supersample_factor
    uint sz = thickness(self, level, true);
    uint start = minus(x, sz / 2), end = min(start + sz, self->width), xsz = minus(end, start);
    for (uint y = y1; y < y2; y++) {
        uint8_t *py = self->mask + y * self->width;
        memset(py + start, 255, xsz);
    }
}

static void
half_hline(Canvas *self, uint level, bool right_half, uint extend_by) {
    uint x1, x2;
    if (right_half) {
        x1 = minus(self->width / 2u, extend_by); x2 = self->width;
    } else {
        x1 = 0; x2 = self->width / 2 + extend_by;
    }
    draw_hline(self, x1, x2, self->height / 2, level);
}


static void
half_vline(Canvas *self, uint level, bool bottom_half, uint extend_by) {
    uint y1, y2;
    if (bottom_half) {
        y1 = minus(self->height / 2u, extend_by); y2 = self->height;
    } else {
        y1 = 0; y2 = self->height / 2 + extend_by;
    }
    draw_vline(self, y1, y2, self->width / 2, level);
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
line_from_points(int x1, int y1, int x2, int y2) {
    StraightLine ans = {.m = (y2 - y1) / ((double)(x2 - x1))};
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

typedef union Point {
    struct {
        int32_t x: 32, y: 32;
    };
    int64_t val;
} Point;

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
    double tm1 = 1 - t; \
    double tm1_3 = tm1 * tm1 * tm1; \
    double t_3 = t * t * t; \
    return tm1_3 * cb.start.which + 3 * t * tm1 * (tm1 * cb.c1.which + t * cb.c2.which) + t_3 * cb.end.which; \
}
static double
bezier_x(CubicBezier cb, double t) { bezier_eq(x); }
static double
bezier_y(CubicBezier cb, double t) { bezier_eq(y); }
#undef bezier_eq

static int
find_bezier_for_D(int width, int height) {
    int cx = width - 1, last_cx = cx;
    CubicBezier cb = {.end={.x=0, .y=height - 1}, .c2={.x=0, .y=height - 1}};
    while (true) {
        cb.c1.x = cx; cb.c2.x = cx;
        if (bezier_x(cb, 0.5) > width - 1) return last_cx;
        last_cx = cx++;
    }
}

static double
find_t_for_x(CubicBezier cb, int x, double start_t) {
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
get_bezier_limits(Canvas *self, CubicBezier cb) {
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
    get_bezier_limits(self, cb);
    if (left) fill_region(self, false);
    else mirror_horizontally(fill_region(self, false));
}

#define NAME position_set
#define KEY_TY Point
#define HASH_FN hash_point
#define CMPR_FN cmpr_point
static uint64_t hash_point(Point p);
static bool cmpr_point(Point, Point);
#include "kitty-verstable.h"
static uint64_t hash_point(Point p) { return vt_hash_integer(p.val); }
static bool cmpr_point(Point a, Point b) { return a.val == b.val; }

#define draw_parametrized_curve(self, level, xfunc, yfunc) { \
    div_t d = div(thickness(self, level, true), 2u); \
    int delta = d.quot, extra = d.rem; \
    uint num_samples = self->height * 8; \
    position_set seen; vt_init(&seen); \
    for (uint i = 0; i < num_samples; i++) { \
        double t = i / (double)num_samples; \
        Point p = {.x=(int32_t)xfunc, .y=(int32_t)yfunc};  \
        position_set_itr q = vt_get(&seen, p); \
        if (!vt_is_end(q)) continue; \
        if (vt_is_end(vt_insert(&seen, p))) fatal("Out of memory"); \
        for (int y = MAX(0, p.y - delta); y < MIN(p.y + delta + extra, (int)self->height); y++) { \
            uint offset = y * self->width, start = MAX(0, p.x - delta); \
            memset(self->mask + offset + start, 255, minus((uint)MIN(p.x + delta + extra, (int)self->width), start)); \
        } \
    } \
    vt_cleanup(&seen); \
}

static void
rounded_separator(Canvas *self, uint level, bool left) {
    uint gap = thickness(self, level, true);
    int c1x = find_bezier_for_D(minus(self->width, gap), self->height);
    CubicBezier cb = {.end={.y=self->height - 1}, .c1={.x=c1x}, .c2={.x=c1x, .y=self->height - 1}};
    if (left) { draw_parametrized_curve(self, level, bezier_x(cb, t), bezier_y(cb, t)); }
    else { mirror_horizontally(draw_parametrized_curve(self, level, bezier_x(cb, t), bezier_y(cb, t))); }
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

void
render_box_char(char_type ch, uint8_t *buf, unsigned width, unsigned height, double dpi_x, double dpi_y) {
    Canvas canvas = {.mask=buf, .width = width, .height = height, .dpi={.x=dpi_x, .y=dpi_y}, .supersample_factor=1u}, ss = canvas;
    ss.mask = buf + width*height; ss.supersample_factor = SUPERSAMPLE_FACTOR; ss.width *= SUPERSAMPLE_FACTOR; ss.height *= SUPERSAMPLE_FACTOR;
    memset(canvas.mask, 0, width * height * sizeof(canvas.mask[0]));
    Canvas *c = &canvas;

#define CC(expr) expr; break
#define SS(expr) memset(ss.mask, 0, ss.width * ss.height * sizeof(ss.mask[0])); c = &ss, expr; downsample(&ss, &canvas); break
#define C(ch, func, ...) case ch: CC(func(c, __VA_ARGS__))
#define S(ch, func, ...) case ch: SS(func(c, __VA_ARGS__))

    switch(ch) {
        default: log_error("Unknown box drawing character: U+%x rendered as blank", ch); break;
        case L'█': memset(canvas.mask, 255, width * height * sizeof(canvas.mask[0])); break;

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
        case L'╾': CC(half_hline(c, 3, false, 0); half_hline(c, 1, true, 0));
        case L'╼': CC(half_hline(c, 1, false, 0); half_hline(c, 3, true, 0));
        case L'╿': CC(half_vline(c, 3, false, 0); half_vline(c, 1, true, 0));
        case L'╽': CC(half_vline(c, 1, false, 0); half_vline(c, 3, true, 0));

        S(L'', triangle, true, false);
        S(L'', triangle, true, true);
        case L'': SS(half_cross_line(c, 1, TOP_LEFT); half_cross_line(c, 1, BOTTOM_LEFT));
        S(L'', triangle, false, false);
        S(L'', triangle, false, true);
        case L'': SS(half_cross_line(c, 1, TOP_RIGHT); half_cross_line(c, 1, BOTTOM_RIGHT));

        S(L'', filled_D, true);
        S(L'◗', filled_D, true);
        S(L'', filled_D, false);
        S(L'◖', filled_D, false);
        S(L'', rounded_separator, 1, true);
        S(L'', rounded_separator, 1, false);

        S(L'', cross_line, 1, true);
        S(L'', cross_line, 1, true);
        S(L'', cross_line, 1, false);
        S(L'', cross_line, 1, false);

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

    }
#undef CC
#undef SS
#undef C
#undef S
    free(canvas.holes); free(canvas.y_limits);
    free(ss.holes); free(ss.y_limits);
}
