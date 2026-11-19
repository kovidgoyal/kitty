/*
 * vector-glyph.c
 * Copyright (C) 2026 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

// Parsing of the vg payload format of the glyph protocol, see vector-glyph.h

#include "vector-glyph.h"
#include <math.h>

// Matrices {{{
void
vg_matrix_singular_values(const VGMatrix *m, double *smallest, double *largest) {
    // The singular values of [a c; b d] are the square roots of the
    // eigenvalues of its product with its transpose
    const double t = m->a * m->a + m->b * m->b + m->c * m->c + m->d * m->d;
    const double det = m->a * m->d - m->b * m->c;
    const double disc = sqrt(fmax(0, t * t - 4 * det * det));
    *largest = sqrt(fmax(0, (t + disc) / 2));
    // Computed via the determinant for accuracy when the matrix is close to singular
    *smallest = *largest > 0 ? fabs(det) / *largest : 0;
}

bool
vg_matrix_invert(const VGMatrix *m, VGMatrix *ans) {
    const double det = m->a * m->d - m->b * m->c;
    if (det == 0 || !isfinite(det)) return false;
    const double id = 1 / det;
    ans->a = m->d * id;
    ans->b = -m->b * id;
    ans->c = -m->c * id;
    ans->d = m->a * id;
    ans->e = -(ans->a * m->e + ans->c * m->f);
    ans->f = -(ans->b * m->e + ans->d * m->f);
    return true;
}
// }}}

// Memory management {{{
VGGlyph *
vg_incref(VGGlyph *g) {
    if (g) g->refcnt++;
    return g;
}

static void
vg_free(VGGlyph *g) {
    free(g->layers);
    free(g->verbs);
    free(g->points);
    free(g);
}

VGGlyph *
vg_decref(VGGlyph *g) {
    if (g) {
        if (g->refcnt < 2) vg_free(g);
        else g->refcnt--;
    }
    return NULL;
}
// }}}

typedef struct Parser {
    const uint8_t *buf;
    size_t pos;
    VGGlyph *g;
    VGError err;
    const char *err_msg;
    uint32_t verbs_capacity, points_capacity;
    // The viewBox size and the region all points must lie in
    double vb_size, min_x, max_x, min_y, max_y;
    // Counts towards the limits
    uint32_t num_segments;
    double path_length, max_path_length;
    // State for the layer currently being parsed
    VGLayer *layer;
    VGMatrix layer_matrix;
    double stroke_cost;
} Parser;

#define fail(code, msg)   \
    {                     \
        p->err = code;    \
        p->err_msg = msg; \
        return false;     \
    }
#define malformed(msg) fail(VG_MALFORMED, msg)
#define too_large(msg) fail(VG_TOO_LARGE, msg)

// Tokens {{{
static inline bool
is_digit(uint8_t ch) {
    return '0' <= ch && ch <= '9';
}

static inline bool
can_start_number(uint8_t ch) {
    return is_digit(ch) || ch == '+' || ch == '-' || ch == '.';
}

static void
skip_spaces(Parser *p, size_t end) {
    while (p->pos < end && p->buf[p->pos] == ' ') p->pos++;
}

// Skip the separator between numbers: spaces, with at most one comma.
// Returns true if a comma was skipped.
static bool
skip_comma_wsp(Parser *p, size_t end) {
    skip_spaces(p, end);
    if (p->pos < end && p->buf[p->pos] == ',') {
        p->pos++;
        skip_spaces(p, end);
        return true;
    }
    return false;
}

static bool
parse_num(Parser *p, size_t end, float *ans, const char *msg) {
    bool overflow;
    if (glyph_parse_number(p->buf, end, &p->pos, ans, &overflow)) return true;
    if (overflow) too_large("number does not fit in a 32-bit float");
    malformed(msg);
}

// Read a number. If after_separator is true the number may be preceded by a
// separator, otherwise only by spaces.
static bool
read_number(Parser *p, size_t end, bool after_separator, float *ans) {
    if (after_separator) skip_comma_wsp(p, end);
    else skip_spaces(p, end);
    if (!parse_num(p, end, ans, "invalid or missing number")) return false;
    return true;
}

static bool
read_numbers(Parser *p, size_t end, float *ans, unsigned count) {
    for (unsigned i = 0; i < count; i++) {
        if (!read_number(p, end, i > 0, ans + i)) return false;
    }
    return true;
}

static bool
consume(Parser *p, size_t end, const char *word) {
    const size_t n = strlen(word);
    if (p->pos + n <= end && memcmp(p->buf + p->pos, word, n) == 0) {
        p->pos += n;
        return true;
    }
    return false;
}

static bool
read_matrix(Parser *p, size_t end, VGMatrix *m) {
    float v[6];
    if (!read_numbers(p, end, v, 6)) return false;
    *m = (VGMatrix){.a = v[0], .b = v[1], .c = v[2], .d = v[3], .e = v[4], .f = v[5]};
    double smallest, largest;
    vg_matrix_singular_values(m, &smallest, &largest);
    if (!(smallest >= 1. / VG_MAX_MATRIX_SCALE && largest <= VG_MAX_MATRIX_SCALE)) malformed("matrix scales lengths by too much");
    return true;
}

static int
hex_digit(uint8_t ch) {
    if (is_digit(ch)) return ch - '0';
    if ('a' <= ch && ch <= 'f') return ch - 'a' + 10;
    if ('A' <= ch && ch <= 'F') return ch - 'A' + 10;
    return -1;
}
// }}}

// Colors and paints {{{
static bool
read_solid_color(Parser *p, size_t end, VGColor *c) {
    zero_at_ptr(c);
    if (consume(p, end, "fg")) {
        c->is_fg = true;
        c->a = 1;
        if (consume(p, end, "@")) {
            float alpha;
            if (!parse_num(p, end, &alpha, "invalid foreground alpha")) return false;
            if (!(0 <= alpha && alpha <= 1)) malformed("foreground alpha out of range");
            c->a = alpha;
        }
        p->g->uses_fg = true;
        return true;
    }
    if (consume(p, end, "#")) {
        int digits[8];
        unsigned n = 0;
        while (p->pos < end && n < 8 && (digits[n] = hex_digit(p->buf[p->pos])) > -1) {
            n++;
            p->pos++;
        }
        if ((n != 6 && n != 8) || (p->pos < end && hex_digit(p->buf[p->pos]) > -1)) malformed("invalid hex color");
        c->r = (digits[0] * 16 + digits[1]) / 255.f;
        c->g = (digits[2] * 16 + digits[3]) / 255.f;
        c->b = (digits[4] * 16 + digits[5]) / 255.f;
        c->a = n == 8 ? (digits[6] * 16 + digits[7]) / 255.f : 1.f;
        p->g->uses_fixed_color = true;
        return true;
    }
    malformed("invalid color");
}

static bool
read_gradient(Parser *p, size_t end, VGPaint *paint) {
    const unsigned num_params = paint->type == VG_PAINT_LINEAR ? 4 : 6;
    if (!read_numbers(p, end, paint->params, num_params)) return false;
    if (paint->type == VG_PAINT_RADIAL && (paint->params[2] < 0 || paint->params[5] < 0)) malformed("negative radius in radial gradient");
    bool had_comma = skip_comma_wsp(p, end);
    if (consume(p, end, "pad")) paint->spread = VG_SPREAD_PAD;
    else if (consume(p, end, "reflect")) paint->spread = VG_SPREAD_REFLECT;
    else if (consume(p, end, "repeat")) paint->spread = VG_SPREAD_REPEAT;
    else goto after_spread;
    had_comma = skip_comma_wsp(p, end);
after_spread:
    if (consume(p, end, "m")) {
        paint->has_matrix = true;
        if (!read_matrix(p, end, &paint->matrix)) return false;
        had_comma = skip_comma_wsp(p, end);
    }
    if (had_comma) malformed("unexpected comma in gradient");
    paint->num_stops = 0;
    while (consume(p, end, "/")) {
        if (paint->num_stops >= VG_MAX_STOPS) too_large("too many gradient stops");
        VGStop *s = paint->stops + paint->num_stops;
        skip_spaces(p, end);
        if (!parse_num(p, end, &s->offset, "invalid gradient stop offset")) return false;
        if (!(0 <= s->offset && s->offset <= 1)) malformed("gradient stop offset out of range");
        if (paint->num_stops && s->offset < paint->stops[paint->num_stops - 1].offset) malformed("gradient stop offsets decrease");
        const size_t before = p->pos;
        skip_spaces(p, end);
        if (p->pos == before) malformed("no space between gradient stop offset and color");
        if (!read_solid_color(p, end, &s->color)) return false;
        paint->num_stops++;
        skip_spaces(p, end);
    }
    if (paint->num_stops < VG_MIN_STOPS) malformed("too few gradient stops");
    if (!consume(p, end, ")")) malformed("gradient not terminated by )");
    return true;
}

static bool
read_paint(Parser *p, size_t end, VGPaint *paint) {
    zero_at_ptr(paint);
    if (consume(p, end, "lin(")) {
        paint->type = VG_PAINT_LINEAR;
        return read_gradient(p, end, paint);
    }
    if (consume(p, end, "rad(")) {
        paint->type = VG_PAINT_RADIAL;
        return read_gradient(p, end, paint);
    }
    paint->type = VG_PAINT_SOLID;
    return read_solid_color(p, end, &paint->color);
}
// }}}

// Layer headers {{{
static bool
read_fill_rule(Parser *p, size_t end, VGFillRule *rule) {
    if (consume(p, end, "nonzero")) *rule = VG_RULE_NONZERO;
    else if (consume(p, end, "evenodd")) *rule = VG_RULE_EVENODD;
    else malformed("invalid fill rule");
    return true;
}

static bool
read_optional_layer_matrix(Parser *p, size_t end, VGLayer *layer) {
    if (p->pos >= end) return true;
    if (!consume(p, end, ",m")) malformed("unexpected characters in layer header");
    layer->has_matrix = true;
    if (!read_matrix(p, end, &layer->matrix)) return false;
    if (p->pos != end) malformed("unexpected characters after layer matrix");
    return true;
}

static bool
read_stroke_params(Parser *p, size_t end, VGLayer *layer) {
    if (!parse_num(p, end, &layer->stroke_width, "invalid stroke width")) return false;
    if (!(layer->stroke_width > 0)) malformed("stroke width must be positive");
    layer->cap = VG_CAP_ROUND;
    layer->join = VG_JOIN_ROUND;
    layer->miter_limit = VG_DEFAULT_MITER_LIMIT;
    if (!consume(p, end, "/")) return true;
    if (consume(p, end, "round")) layer->cap = VG_CAP_ROUND;
    else if (consume(p, end, "butt")) layer->cap = VG_CAP_BUTT;
    else if (consume(p, end, "square")) layer->cap = VG_CAP_SQUARE;
    else malformed("invalid stroke cap");
    if (!consume(p, end, "/")) return true;
    if (consume(p, end, "round")) layer->join = VG_JOIN_ROUND;
    else if (consume(p, end, "bevel")) layer->join = VG_JOIN_BEVEL;
    else if (consume(p, end, "miter")) {
        layer->join = VG_JOIN_MITER;
        if (p->pos < end && can_start_number(p->buf[p->pos])) {
            if (!parse_num(p, end, &layer->miter_limit, "invalid miter limit")) return false;
            if (!(VG_MIN_MITER_LIMIT <= layer->miter_limit && layer->miter_limit <= VG_MAX_MITER_LIMIT)) malformed("miter limit out of range");
        }
    } else malformed("invalid stroke join");
    return true;
}

static bool
read_layer_header(Parser *p, size_t end, VGLayer *layer) {
    if (consume(p, end, "fill=")) {
        layer->kind = VG_LAYER_FILL;
        if (!read_fill_rule(p, end, &layer->rule)) return false;
        if (!consume(p, end, ",")) malformed("missing color in fill layer");
        if (!read_paint(p, end, &layer->paint)) return false;
    } else if (consume(p, end, "stroke=")) {
        layer->kind = VG_LAYER_STROKE;
        if (!read_stroke_params(p, end, layer)) return false;
        if (!consume(p, end, ",")) malformed("missing color in stroke layer");
        if (!read_paint(p, end, &layer->paint)) return false;
    } else if (consume(p, end, "clip=")) {
        layer->kind = VG_LAYER_CLIP;
        float n;
        if (!parse_num(p, end, &n, "invalid clip layer count")) return false;
        if (n != floorf(n) || n < 1 || n > VG_MAX_CLIP_LAYERS) malformed("clip layer count out of range");
        layer->clip_count = (unsigned)n;
        if (!consume(p, end, ",")) malformed("missing fill rule in clip layer");
        if (!read_fill_rule(p, end, &layer->rule)) return false;
    } else malformed("unknown layer type");
    return read_optional_layer_matrix(p, end, layer);
}
// }}}

// Path data {{{
static bool
ensure_space(Parser *p, unsigned num_points) {
    VGGlyph *g = p->g;
    if (g->num_verbs + 1 > p->verbs_capacity) {
        uint32_t cap = MAX(64u, p->verbs_capacity * 2);
        uint8_t *v = realloc(g->verbs, cap * sizeof(g->verbs[0]));
        if (!v) fail(VG_OUT_OF_MEMORY, "out of memory");
        g->verbs = v;
        p->verbs_capacity = cap;
    }
    if (g->num_points + num_points > p->points_capacity) {
        uint32_t cap = MAX(128u, MAX(p->points_capacity * 2, g->num_points + num_points));
        float *pts = realloc(g->points, cap * 2 * sizeof(g->points[0]));
        if (!pts) fail(VG_OUT_OF_MEMORY, "out of memory");
        g->points = pts;
        p->points_capacity = cap;
    }
    return true;
}

typedef struct Point {
    double x, y;
} Point;

typedef struct PathState {
    // In the coordinates of the layer
    Point current, subpath_start;
    // In viewBox coordinates, for measuring length
    Point current_vb, subpath_start_vb;
    bool needs_implied_move, last_was_close;
} PathState;

static Point
to_viewbox(Parser *p, Point pt) {
    Point ans;
    vg_matrix_apply(&p->layer_matrix, pt.x, pt.y, &ans.x, &ans.y);
    return ans;
}

static double
distance(Point a, Point b) {
    return hypot(a.x - b.x, a.y - b.y);
}

static bool
add_segment(Parser *p, double length) {
    if (++p->num_segments > VG_MAX_SEGMENTS) too_large("too many path segments");
    p->path_length += length + p->stroke_cost;
    if (p->path_length > p->max_path_length) too_large("path too long");
    return true;
}

// Add a verb and its points, which are in layer coordinates. Checks that the
// points are in bounds and returns the points converted to the viewBox
// coordinates in vb.
static bool
emit(Parser *p, VGVerb verb, const Point *pts, unsigned n, Point *vb) {
    if (!ensure_space(p, n)) return false;
    VGGlyph *g = p->g;
    g->verbs[g->num_verbs++] = verb;
    for (unsigned i = 0; i < n; i++) {
        // The points are stored as floats so check bounds after rounding
        const float x = (float)pts[i].x, y = (float)pts[i].y;
        if (!isfinite(x) || !isfinite(y)) too_large("path coordinate too large");
        vb[i] = to_viewbox(p, (Point){x, y});
        if (!(p->min_x <= vb[i].x && vb[i].x <= p->max_x && p->min_y <= vb[i].y && vb[i].y <= p->max_y)) too_large("path point too far outside the viewBox");
        g->points[2 * g->num_points] = x;
        g->points[2 * g->num_points + 1] = y;
        g->num_points++;
    }
    return true;
}

static bool
emit_move(Parser *p, PathState *s, Point pt) {
    Point vb;
    if (!emit(p, VG_MOVE, &pt, 1, &vb)) return false;
    if (!add_segment(p, 0)) return false;
    s->current = s->subpath_start = pt;
    s->current_vb = s->subpath_start_vb = vb;
    s->needs_implied_move = false;
    s->last_was_close = false;
    return true;
}

// Called before every drawing command, drawing after a close starts a new subpath
static bool
start_drawing(Parser *p, PathState *s) {
    if (s->needs_implied_move) return emit_move(p, s, s->subpath_start);
    return true;
}

static bool
emit_line(Parser *p, PathState *s, Point pt) {
    if (!start_drawing(p, s)) return false;
    Point vb;
    if (!emit(p, VG_LINE, &pt, 1, &vb)) return false;
    if (!add_segment(p, distance(s->current_vb, vb))) return false;
    s->current = pt;
    s->current_vb = vb;
    s->last_was_close = false;
    return true;
}

static bool
emit_quad(Parser *p, PathState *s, Point c, Point pt) {
    if (!start_drawing(p, s)) return false;
    Point pts[2] = {c, pt}, vb[2];
    if (!emit(p, VG_QUAD, pts, 2, vb)) return false;
    if (!add_segment(p, distance(s->current_vb, vb[0]) + distance(vb[0], vb[1]))) return false;
    s->current = pt;
    s->current_vb = vb[1];
    s->last_was_close = false;
    return true;
}

static bool
emit_cubic(Parser *p, PathState *s, Point c1, Point c2, Point pt) {
    if (!start_drawing(p, s)) return false;
    Point pts[3] = {c1, c2, pt}, vb[3];
    if (!emit(p, VG_CUBIC, pts, 3, vb)) return false;
    if (!add_segment(p, distance(s->current_vb, vb[0]) + distance(vb[0], vb[1]) + distance(vb[1], vb[2]))) return false;
    s->current = pt;
    s->current_vb = vb[2];
    s->last_was_close = false;
    return true;
}

static bool
emit_close(Parser *p, PathState *s) {
    // A close right after another closes nothing
    if (s->last_was_close) return true;
    Point vb;
    if (!emit(p, VG_CLOSE, NULL, 0, &vb)) return false;
    if (!add_segment(p, distance(s->current_vb, s->subpath_start_vb))) return false;
    s->current = s->subpath_start;
    s->current_vb = s->subpath_start_vb;
    s->needs_implied_move = true;
    s->last_was_close = true;
    return true;
}

// Convert an arc to cubic Béziers, following the implementation notes of SVG 2
static bool
emit_arc(Parser *p, PathState *s, double rx, double ry, double rotation_degrees, bool large_arc, bool sweep, Point end) {
    const Point start = s->current;
    if (start.x == end.x && start.y == end.y) return true; // draws nothing
    rx = fabs(rx);
    ry = fabs(ry);
    if (rx == 0 || ry == 0) return emit_line(p, s, end);
    const double phi = rotation_degrees * M_PI / 180., cos_phi = cos(phi), sin_phi = sin(phi);
    const double dx2 = (start.x - end.x) / 2, dy2 = (start.y - end.y) / 2;
    const double x1p = cos_phi * dx2 + sin_phi * dy2, y1p = -sin_phi * dx2 + cos_phi * dy2;
    // Scale up radii that are too small
    const double lambda = (x1p * x1p) / (rx * rx) + (y1p * y1p) / (ry * ry);
    if (lambda > 1) {
        const double sl = sqrt(lambda);
        rx *= sl;
        ry *= sl;
    }
    const double rx2 = rx * rx, ry2 = ry * ry;
    const double num = rx2 * ry2 - rx2 * y1p * y1p - ry2 * x1p * x1p, den = rx2 * y1p * y1p + ry2 * x1p * x1p;
    double coef = den > 0 ? sqrt(fmax(0, num / den)) : 0;
    if (large_arc == sweep) coef = -coef;
    const double cxp = coef * rx * y1p / ry, cyp = -coef * ry * x1p / rx;
    const double cx = cos_phi * cxp - sin_phi * cyp + (start.x + end.x) / 2, cy = sin_phi * cxp + cos_phi * cyp + (start.y + end.y) / 2;
    const double ux = (x1p - cxp) / rx, uy = (y1p - cyp) / ry, vx = (-x1p - cxp) / rx, vy = (-y1p - cyp) / ry;
    const double theta1 = atan2(uy, ux);
    double dtheta = atan2(ux * vy - uy * vx, ux * vx + uy * vy);
    if (!sweep && dtheta > 0) dtheta -= 2 * M_PI;
    else if (sweep && dtheta < 0) dtheta += 2 * M_PI;
    // One cubic for each quarter turn or part of one
    int n = (int)ceil(fabs(dtheta) / (M_PI / 2) - 1e-9);
    n = MAX(1, MIN(4, n));
    const double seg = dtheta / n, k = 4. / 3. * tan(seg / 4);
#define POINT(t) (Point){cx + rx * cos(t) * cos_phi - ry * sin(t) * sin_phi, cy + rx * cos(t) * sin_phi + ry * sin(t) * cos_phi}
#define DERIV(t) \
    (Point) { -rx *sin(t) * cos_phi - ry *cos(t) * sin_phi, -rx *sin(t) * sin_phi + ry *cos(t) * cos_phi }
    for (int i = 0; i < n; i++) {
        const double t1 = theta1 + i * seg, t2 = t1 + seg;
        const Point p1 = i ? POINT(t1) : start, d1 = DERIV(t1), d2 = DERIV(t2);
        const Point p2 = i == n - 1 ? end : POINT(t2);
        const Point c1 = {p1.x + k * d1.x, p1.y + k * d1.y}, c2 = {p2.x - k * d2.x, p2.y - k * d2.y};
        if (!emit_cubic(p, s, c1, c2, p2)) return false;
    }
#undef POINT
#undef DERIV
    return true;
}

static bool
read_flag(Parser *p, size_t end, bool *flag) {
    skip_comma_wsp(p, end);
    if (p->pos < end && (p->buf[p->pos] == '0' || p->buf[p->pos] == '1')) {
        *flag = p->buf[p->pos++] == '1';
        return true;
    }
    malformed("invalid arc flag");
}

static unsigned
num_args_for_command(uint8_t cmd) {
    switch (cmd | 0x20) {
        case 'm':
        case 'l':
        case 't': return 2;
        case 'h':
        case 'v': return 1;
        case 'c': return 6;
        case 's':
        case 'q': return 4;
        case 'a': return 7;
        case 'z': return 0;
    }
    return UINT_MAX;
}

static bool
parse_path(Parser *p, size_t end) {
    PathState s = {0};
    // The second control point of the previous cubic and the control point of the previous quadratic
    Point last_cubic_ctrl = {0}, last_quad_ctrl = {0};
    uint8_t prev_cmd = 0;
    skip_spaces(p, end);
    if (p->pos >= end || (p->buf[p->pos] | 0x20) != 'm') malformed("path data must start with a moveto");
    while (true) {
        skip_spaces(p, end);
        if (p->pos >= end) break;
        uint8_t cmd = p->buf[p->pos++];
        const unsigned nargs = num_args_for_command(cmd);
        if (nargs == UINT_MAX) malformed("invalid path command");
        const bool relative = cmd >= 'a';
        bool first_set = true;
        do {
            float a[7];
            bool large_arc = false, sweep = false;
            if (cmd == 'a' || cmd == 'A') {
                if (!read_number(p, end, !first_set, a) || !read_number(p, end, true, a + 1) || !read_number(p, end, true, a + 2)) return false;
                if (!read_flag(p, end, &large_arc) || !read_flag(p, end, &sweep)) return false;
                if (!read_number(p, end, true, a + 5) || !read_number(p, end, true, a + 6)) return false;
            } else if (nargs) {
                if (!read_number(p, end, !first_set, a)) return false;
                for (unsigned i = 1; i < nargs; i++) {
                    if (!read_number(p, end, true, a + i)) return false;
                }
            }
            const Point cur = s.current;
            const double ox = relative ? cur.x : 0, oy = relative ? cur.y : 0;
            uint8_t effective = cmd | 0x20;
            // The extra pairs of a moveto are linetos
            if (effective == 'm' && !first_set) effective = 'l';
            switch (effective) {
                case 'm':
                    if (!emit_move(p, &s, (Point){a[0] + ox, a[1] + oy})) return false;
                    break;
                case 'l':
                    if (!emit_line(p, &s, (Point){a[0] + ox, a[1] + oy})) return false;
                    break;
                case 'h':
                    if (!emit_line(p, &s, (Point){a[0] + ox, cur.y})) return false;
                    break;
                case 'v':
                    if (!emit_line(p, &s, (Point){cur.x, a[0] + oy})) return false;
                    break;
                case 'c':
                    last_cubic_ctrl = (Point){a[2] + ox, a[3] + oy};
                    if (!emit_cubic(p, &s, (Point){a[0] + ox, a[1] + oy}, last_cubic_ctrl, (Point){a[4] + ox, a[5] + oy})) return false;
                    break;
                case 's': {
                    const uint8_t pc = prev_cmd | 0x20;
                    const Point c1 = (pc == 'c' || pc == 's') ? (Point){2 * cur.x - last_cubic_ctrl.x, 2 * cur.y - last_cubic_ctrl.y} : cur;
                    last_cubic_ctrl = (Point){a[0] + ox, a[1] + oy};
                    if (!emit_cubic(p, &s, c1, last_cubic_ctrl, (Point){a[2] + ox, a[3] + oy})) return false;
                } break;
                case 'q':
                    last_quad_ctrl = (Point){a[0] + ox, a[1] + oy};
                    if (!emit_quad(p, &s, last_quad_ctrl, (Point){a[2] + ox, a[3] + oy})) return false;
                    break;
                case 't': {
                    const uint8_t pc = prev_cmd | 0x20;
                    last_quad_ctrl = (pc == 'q' || pc == 't') ? (Point){2 * cur.x - last_quad_ctrl.x, 2 * cur.y - last_quad_ctrl.y} : cur;
                    if (!emit_quad(p, &s, last_quad_ctrl, (Point){a[0] + ox, a[1] + oy})) return false;
                } break;
                case 'a':
                    if (!emit_arc(p, &s, a[0], a[1], a[2], large_arc, sweep, (Point){a[5] + ox, a[6] + oy})) return false;
                    break;
                case 'z':
                    if (!emit_close(p, &s)) return false;
                    break;
            }
            prev_cmd = cmd;
            first_set = false;
            if (!nargs) break;
            // Implicit repetition of the command if another set of arguments follows
            const size_t before = p->pos;
            const bool had_comma = skip_comma_wsp(p, end);
            if (p->pos < end && can_start_number(p->buf[p->pos])) {
                p->pos = before;
                continue;
            }
            if (had_comma) malformed("comma not followed by a number");
            p->pos = before;
            break;
        } while (true);
    }
    return true;
}
// }}}

static bool
parse_layer(Parser *p, size_t start, size_t end) {
    VGGlyph *g = p->g;
    if (g->num_layers >= VG_MAX_LAYERS) too_large("too many layers");
    VGLayer *layer = g->layers + g->num_layers++;
    zero_at_ptr(layer);
    const uint8_t *colon = memchr(p->buf + start, ':', end - start);
    if (!colon) malformed("layer has no path data");
    const size_t header_end = colon - p->buf;
    p->pos = start;
    if (!read_layer_header(p, header_end, layer)) return false;
    p->layer = layer;
    p->layer_matrix = layer->has_matrix ? layer->matrix : vg_identity_matrix();
    p->stroke_cost = 0;
    if (layer->kind == VG_LAYER_STROKE) {
        double smallest, largest;
        vg_matrix_singular_values(&p->layer_matrix, &smallest, &largest);
        p->stroke_cost = layer->stroke_width * largest;
        if (p->stroke_cost > p->vb_size) malformed("stroke too wide");
    }
    layer->first_verb = g->num_verbs;
    layer->first_point = g->num_points;
    p->pos = header_end + 1;
    if (!parse_path(p, end)) return false;
    layer->num_verbs = g->num_verbs - layer->first_verb;
    return true;
}

static bool
validate_clips(Parser *p) {
    const VGGlyph *g = p->g;
    for (uint32_t i = 0; i < g->num_layers; i++) {
        if (g->layers[i].kind != VG_LAYER_CLIP) continue;
        if (i + g->layers[i].clip_count >= g->num_layers) malformed("clip layer applies to layers that do not exist");
        for (uint32_t j = i + 1; j <= i + g->layers[i].clip_count; j++) {
            if (g->layers[j].kind == VG_LAYER_CLIP) malformed("clip layers cannot be clipped");
        }
    }
    return true;
}

static bool
parse(Parser *p, const uint8_t *payload, size_t sz) {
    if (sz > GLYPH_MAX_PAYLOAD_SIZE) too_large("payload too large");
    for (size_t i = 0; i < sz; i++) {
        if (payload[i] < 0x20 || payload[i] > 0x7e || payload[i] == ';') malformed("payload contains invalid characters");
    }
    size_t start = 0;
    for (size_t i = 0; i <= sz; i++) {
        if (i == sz || payload[i] == '|') {
            if (!parse_layer(p, start, i)) return false;
            start = i + 1;
        }
    }
    return validate_clips(p);
}

VGGlyph *
vg_parse(const uint8_t *payload, size_t sz, const GlyphPlacement *placement, VGError *err, const char **err_msg) {
    *err = VG_OUT_OF_MEMORY;
    *err_msg = "out of memory";
    VGGlyph *g = calloc(1, sizeof(VGGlyph));
    if (!g) return NULL;
    g->refcnt = 1;
    g->placement = *placement;
    g->layers = malloc(VG_MAX_LAYERS * sizeof(g->layers[0]));
    if (!g->layers) return vg_decref(g);
    Parser parser = {.buf = payload, .g = g}, *p = &parser;
    const float *vb = placement->vb;
    p->vb_size = MAX(vb[2], vb[3]);
    p->min_x = vb[0] - p->vb_size;
    p->max_x = vb[0] + vb[2] + p->vb_size;
    p->min_y = vb[1] - p->vb_size;
    p->max_y = vb[1] + vb[3] + p->vb_size;
    p->max_path_length = VG_MAX_PATH_LENGTH * p->vb_size;
    if (!parse(p, payload, sz)) {
        *err = p->err;
        *err_msg = p->err_msg;
        return vg_decref(g);
    }
    // Release unused space
    VGLayer *layers = realloc(g->layers, MAX(1u, g->num_layers) * sizeof(g->layers[0]));
    if (layers) g->layers = layers;
    g->memory_size =
        sizeof(VGGlyph) + g->num_layers * sizeof(g->layers[0]) + p->verbs_capacity * sizeof(g->verbs[0]) + p->points_capacity * 2 * sizeof(g->points[0]);
    *err = VG_OK;
    *err_msg = NULL;
    return g;
}

// Registrations {{{
static size_t total_registered_memory = 0;

size_t
glyph_registry_total_memory(void) {
    return total_registered_memory;
}

GlyphRegistry *
glyph_registry_alloc(void) {
    return calloc(1, sizeof(GlyphRegistry));
}

void
glyph_registry_free(GlyphRegistry *self) {
    if (self) {
        glyph_registry_clear_all(self);
        free(self);
    }
}

static void
release(GlyphRegistry *self, unsigned idx) {
    VGGlyph *g = self->glyphs[idx];
    if (g) {
        total_registered_memory -= MIN(total_registered_memory, g->memory_size);
        self->glyphs[idx] = vg_decref(g);
        self->num_registered--;
    }
}

bool
glyph_registry_set(GlyphRegistry *self, char_type cp, VGGlyph *g) {
    const unsigned idx = cp - GLYPH_BLOCK_FIRST;
    const VGGlyph *existing = self->glyphs[idx];
    const size_t freed = existing ? existing->memory_size : 0;
    if (total_registered_memory - MIN(freed, total_registered_memory) + g->memory_size > VG_REGISTRY_MEMORY_BUDGET) return false;
    release(self, idx);
    self->glyphs[idx] = vg_incref(g);
    total_registered_memory += g->memory_size;
    self->num_registered++;
    self->generation++;
    return true;
}

void
glyph_registry_clear(GlyphRegistry *self, char_type cp) {
    if (!is_glyph_block_codepoint(cp)) return;
    const unsigned idx = cp - GLYPH_BLOCK_FIRST;
    if (self->glyphs[idx]) {
        release(self, idx);
        self->generation++;
    }
}

void
glyph_registry_clear_all(GlyphRegistry *self) {
    if (!self->num_registered) return;
    for (unsigned i = 0; i < GLYPH_BLOCK_SIZE && self->num_registered; i++) release(self, i);
    self->generation++;
}
// }}}

// Python interface {{{
static PyObject *
color_as_python(const VGColor *c) {
    if (c->is_fg) {
        if (c->a == 1) return PyUnicode_FromString("fg");
        char buf[64];
        snprintf(buf, sizeof(buf), "fg@%.6g", (double)c->a);
        return PyUnicode_FromString(buf);
    }
    return Py_BuildValue("(dddd)", (double)c->r, (double)c->g, (double)c->b, (double)c->a);
}

static PyObject *
matrix_as_python(const VGMatrix *m) {
    return Py_BuildValue("(dddddd)", m->a, m->b, m->c, m->d, m->e, m->f);
}

static PyObject *
paint_as_python(const VGPaint *paint) {
    if (paint->type == VG_PAINT_SOLID) return color_as_python(&paint->color);
    static const char *spreads[] = {"pad", "reflect", "repeat"};
    RAII_PyObject(stops, PyTuple_New(paint->num_stops));
    if (!stops) return NULL;
    for (unsigned i = 0; i < paint->num_stops; i++) {
        PyObject *s = Py_BuildValue("(dN)", (double)paint->stops[i].offset, color_as_python(&paint->stops[i].color));
        if (!s) return NULL;
        PyTuple_SET_ITEM(stops, i, s);
    }
    const unsigned n = paint->type == VG_PAINT_LINEAR ? 4 : 6;
    RAII_PyObject(params, PyTuple_New(n));
    if (!params) return NULL;
    for (unsigned i = 0; i < n; i++) {
        PyObject *x = PyFloat_FromDouble(paint->params[i]);
        if (!x) return NULL;
        PyTuple_SET_ITEM(params, i, x);
    }
    return Py_BuildValue(
        "{ss sO ss sN sO}",
        "type",
        paint->type == VG_PAINT_LINEAR ? "lin" : "rad",
        "params",
        params,
        "spread",
        spreads[paint->spread],
        "matrix",
        paint->has_matrix ? matrix_as_python(&paint->matrix) : Py_NewRef(Py_None),
        "stops",
        stops);
}

static PyObject *
path_as_python(const VGGlyph *g, const VGLayer *layer) {
    // A string representation using absolute SVG path commands
    static const char cmds[] = {'M', 'L', 'Q', 'C', 'Z'};
    RAII_PyObject(parts, PyList_New(0));
    if (!parts) return NULL;
    const float *pts = g->points + 2 * layer->first_point;
    for (uint32_t i = 0; i < layer->num_verbs; i++) {
        const VGVerb v = g->verbs[layer->first_verb + i];
        RAII_PyObject(cmd, PyUnicode_FromFormat("%c", cmds[v]));
        if (!cmd || PyList_Append(parts, cmd) != 0) return NULL;
        for (unsigned k = 0; k < 2 * vg_verb_num_points(v); k++) {
            char buf[64];
            snprintf(buf, sizeof(buf), "%.6g", (double)*pts++);
            RAII_PyObject(n, PyUnicode_FromString(buf));
            if (!n || PyList_Append(parts, n) != 0) return NULL;
        }
    }
    RAII_PyObject(sep, PyUnicode_FromString(" "));
    if (!sep) return NULL;
    return PyUnicode_Join(sep, parts);
}

static PyObject *
layer_as_python(const VGGlyph *g, const VGLayer *layer) {
    static const char *kinds[] = {"fill", "stroke", "clip"}, *rules[] = {"nonzero", "evenodd"}, *caps[] = {"round", "butt", "square"},
                      *joins[] = {"round", "bevel", "miter"};
    RAII_PyObject(
        ans,
        Py_BuildValue(
            "{ss sN sN}",
            "kind",
            kinds[layer->kind],
            "path",
            path_as_python(g, layer),
            "matrix",
            layer->has_matrix ? matrix_as_python(&layer->matrix) : Py_NewRef(Py_None)));
    if (!ans) return NULL;
#define S(key, val)                                                    \
    {                                                                  \
        RAII_PyObject(v, val);                                         \
        if (!v || PyDict_SetItemString(ans, key, v) != 0) return NULL; \
    }
    if (layer->kind != VG_LAYER_STROKE) S("rule", PyUnicode_FromString(rules[layer->rule]));
    if (layer->kind == VG_LAYER_CLIP) S("clip_count", PyLong_FromUnsignedLong(layer->clip_count));
    if (layer->kind != VG_LAYER_CLIP) S("paint", paint_as_python(&layer->paint));
    if (layer->kind == VG_LAYER_STROKE) {
        S("width", PyFloat_FromDouble(layer->stroke_width));
        S("cap", PyUnicode_FromString(caps[layer->cap]));
        S("join", PyUnicode_FromString(joins[layer->join]));
        S("miter_limit", PyFloat_FromDouble(layer->miter_limit));
    }
#undef S
    return Py_NewRef(ans);
}

static PyObject *
py_parse_vg(PyObject *self UNUSED, PyObject *args) {
    const char *data;
    Py_ssize_t sz;
    GlyphPlacement placement = {.fit = GLYPH_FIT_CONTAIN, .align_h = GLYPH_ALIGN_CENTER, .align_v = GLYPH_ALIGN_CENTER};
    if (!PyArg_ParseTuple(args, "y#(ffff)", &data, &sz, placement.vb, placement.vb + 1, placement.vb + 2, placement.vb + 3)) return NULL;
    VGError err;
    const char *err_msg;
    VGGlyph *g = vg_parse((const uint8_t *)data, sz, &placement, &err, &err_msg);
    if (!g) {
        if (err == VG_OUT_OF_MEMORY) return PyErr_NoMemory();
        PyErr_Format(PyExc_ValueError, "%s: %s", err == VG_TOO_LARGE ? "outline_too_large" : "malformed_payload", err_msg);
        return NULL;
    }
    PyObject *layers = PyTuple_New(g->num_layers);
    if (layers) {
        for (uint32_t i = 0; i < g->num_layers; i++) {
            PyObject *l = layer_as_python(g, g->layers + i);
            if (!l) {
                Py_CLEAR(layers);
                break;
            }
            PyTuple_SET_ITEM(layers, i, l);
        }
    }
    PyObject *ans = layers ? Py_BuildValue(
                                 "{sN sO sO sI}",
                                 "layers",
                                 layers,
                                 "uses_fg",
                                 g->uses_fg ? Py_True : Py_False,
                                 "uses_fixed_color",
                                 g->uses_fixed_color ? Py_True : Py_False,
                                 "num_verbs",
                                 g->num_verbs)
                           : NULL;
    vg_decref(g);
    return ans;
}

static PyMethodDef methods[] = {
    {"parse_vg", py_parse_vg, METH_VARARGS, "Parse a vg payload with the specified viewBox, for testing"},
    {NULL, NULL, 0, NULL},
};

bool
init_vector_glyph(PyObject *module) {
    if (PyModule_AddFunctions(module, methods) != 0) return false;
    return true;
}
// }}}
