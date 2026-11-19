/*
 * vector-glyph-render.c
 * Copyright (C) 2026 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

// Rendering of vg glyphs, see vector-glyph.h
//
// Paths are flattened into polygons in device (pixel) space and rasterized
// with an anti-aliasing scanline rasterizer that computes winding numbers on
// VG_SUBSAMPLES sub-scanlines per pixel row with exact horizontal coverage of
// the resulting spans. Since winding numbers are computed exactly, both fill
// rules and the union of overlapping polygons are handled correctly.
//
// Strokes are generated in the coordinates of their layer, where the pen is
// circular, as a union of positively oriented polygons: one quadrilateral per
// segment, plus joins and caps, which is then transformed to device space.
// Under a non-uniform layer matrix this gives the elliptical pen of SVG.
//
// Painting is linear in the foreground color, since the foreground color is
// opaque and so does not affect the alpha of any layer. The result of
// painting all layers with src-over is therefore representable as a
// premultiplied color K, an alpha A and a foreground weight F with the final
// color being K + fg * F. This allows the foreground to be supplied at draw
// time.

#include "vector-glyph.h"
#include <math.h>

// The number of sub-scanlines per pixel row
#define VG_SUBSAMPLES 16
// The maximum distance in pixels between a curve and its flattened approximation
#define VG_TOLERANCE 0.1
// Bounds the number of line segments a single curve or circle is flattened into
#define VG_MAX_CURVE_SEGMENTS 256u

// The libm min/max functions are not inlined, so use these in hot loops
// Also maps NaN to zero
static inline double
clamp01(double v) {
    return !(v > 0) ? 0 : (v > 1 ? 1 : v);
}

// Growable arrays {{{
typedef struct Edge {
    // y0 < y1, dir is +1 if the edge goes down in the original polygon and -1 otherwise
    double x0, y0, x1, y1, dxdy;
    int dir;
} Edge;

typedef struct Point {
    double x, y;
} Point;

// A point of a flattened subpath. Points that are not corners are interior to
// a curve, which affects how they are joined when stroking.
typedef struct SubPoint {
    double x, y;
    bool corner;
} SubPoint;

typedef struct Rasterizer {
    Edge *edges;
    size_t num_edges, edges_capacity;
    // Scratch space for the polygon currently being built
    Point *poly;
    size_t poly_count, poly_capacity;
    // Scratch space for a flattened subpath
    SubPoint *sub;
    size_t sub_count, sub_capacity;
    // For each pixel row, coverage and difference array for runs of full coverage
    double *row_cov, *row_diff;
    size_t row_capacity;
    // Crossings of the current sub-scanline
    struct Crossing {
        double x;
        int dir;
        size_t edge;
    } *crossings;
    size_t crossings_capacity;
    // Active edges indices
    size_t *active;
    unsigned width, height;
    // Set when rendering must be abandoned, because of an allocation failure
    // or because over_budget is set
    bool oom;
    // The work done so far and the maximum allowed, see charge()
    uint64_t work, budget;
    bool over_budget;
} Rasterizer;

// Account for work done in units of roughly one cheap per point or per
// pixel operation. The limits of the vg format bound the work in units of the
// viewBox, but not in pixels, so the renderer enforces its own bound.
static inline void
charge(Rasterizer *r, uint64_t work) {
    r->work += work;
    if (r->work > r->budget) {
        r->over_budget = true;
        r->oom = true;
    }
}

#define ENSURE(arr, count, capacity, needed)                            \
    if ((needed) > (capacity)) {                                        \
        size_t newcap = MAX((capacity) * 2, MAX((size_t)64, (needed))); \
        void *p = realloc((arr), newcap * sizeof((arr)[0]));            \
        if (!p) {                                                       \
            r->oom = true;                                              \
            return;                                                     \
        }                                                               \
        (arr) = p;                                                      \
        (capacity) = newcap;                                            \
    }

static void
poly_add(Rasterizer *r, Point p) {
    if (r->oom) return;
    charge(r, 1);
    ENSURE(r->poly, r->poly_count, r->poly_capacity, r->poly_count + 1);
    r->poly[r->poly_count++] = p;
}

static void
sub_add(Rasterizer *r, Point p, bool corner) {
    if (r->oom) return;
    charge(r, 1);
    // Skip consecutive duplicate points
    if (r->sub_count && r->sub[r->sub_count - 1].x == p.x && r->sub[r->sub_count - 1].y == p.y) {
        if (corner) r->sub[r->sub_count - 1].corner = true;
        return;
    }
    ENSURE(r->sub, r->sub_count, r->sub_capacity, r->sub_count + 1);
    r->sub[r->sub_count++] = (SubPoint){.x = p.x, .y = p.y, .corner = corner};
}

static void
add_edge(Rasterizer *r, Point a, Point b) {
    if (a.y == b.y) return; // horizontal edges do not cross any sub-scanline
    // Edges entirely outside the vertical range do not affect coverage
    if ((a.y <= 0 && b.y <= 0) || (a.y >= r->height && b.y >= r->height)) return;
    if (r->oom) return;
    // Rasterizing computes a crossing of the edge with every sub-scanline it spans
    const double top = fmax(0, fmin(a.y, b.y)), bottom = fmin(r->height, fmax(a.y, b.y));
    charge(r, 1 + (uint64_t)(ceil(bottom - top) + 1) * VG_SUBSAMPLES);
    if (r->oom) return;
    ENSURE(r->edges, r->num_edges, r->edges_capacity, r->num_edges + 1);
    Edge *e = r->edges + r->num_edges++;
    if (a.y < b.y) {
        *e = (Edge){.x0 = a.x, .y0 = a.y, .x1 = b.x, .y1 = b.y, .dir = 1};
    } else {
        *e = (Edge){.x0 = b.x, .y0 = b.y, .x1 = a.x, .y1 = a.y, .dir = -1};
    }
    e->dxdy = (e->x1 - e->x0) / (e->y1 - e->y0);
}

// Add the polygon in r->poly as edges. If normalize is true the polygon is
// reversed if needed so that it has positive orientation.
static void
commit_polygon(Rasterizer *r, bool normalize) {
    const size_t n = r->poly_count;
    if (n < 3) {
        r->poly_count = 0;
        return;
    }
    int flip = 1;
    if (normalize) {
        // Pieces of a stroke are unioned, so pieces entirely outside the
        // canvas do not affect coverage. This is not true for fills where
        // edges to the left of the canvas affect the winding number.
        double min_x = r->poly[0].x, max_x = min_x, min_y = r->poly[0].y, max_y = min_y;
        for (size_t i = 1; i < n; i++) {
            min_x = fmin(min_x, r->poly[i].x);
            max_x = fmax(max_x, r->poly[i].x);
            min_y = fmin(min_y, r->poly[i].y);
            max_y = fmax(max_y, r->poly[i].y);
        }
        if (max_x <= 0 || max_y <= 0 || min_x >= r->width || min_y >= r->height) {
            r->poly_count = 0;
            return;
        }
        double area = 0;
        for (size_t i = 0, j = n - 1; i < n; j = i++) area += r->poly[j].x * r->poly[i].y - r->poly[i].x * r->poly[j].y;
        if (area < 0) flip = -1;
        else if (area == 0) {
            r->poly_count = 0;
            return;
        }
    }
    const size_t before = r->num_edges;
    for (size_t i = 0, j = n - 1; i < n; j = i++) add_edge(r, r->poly[j], r->poly[i]);
    if (flip < 0) {
        for (size_t i = before; i < r->num_edges; i++) r->edges[i].dir = -r->edges[i].dir;
    }
    r->poly_count = 0;
}
// }}}

// Rasterization {{{
static int
cmp_edges(const void *a_, const void *b_) {
    const Edge *a = a_, *b = b_;
    return a->y0 < b->y0 ? -1 : (a->y0 > b->y0 ? 1 : 0);
}

static void
add_span(Rasterizer *r, double xa, double xb) {
    const double w = r->width;
    xa = xa < 0 ? 0 : xa;
    xb = xb > w ? w : xb;
    if (xb <= xa) return;
    const double weight = 1.0 / VG_SUBSAMPLES;
    const unsigned ia = (unsigned)xa, ib = (unsigned)xb;
    if (ia == ib) {
        r->row_cov[ia] += (xb - xa) * weight;
        return;
    }
    r->row_cov[ia] += (ia + 1 - xa) * weight;
    if (ib > ia + 1) {
        r->row_diff[ia + 1] += weight;
        r->row_diff[ib] -= weight;
    }
    if (ib < r->width) r->row_cov[ib] += (xb - ib) * weight;
}

typedef struct Bounds {
    unsigned left, top, right, bottom;
} Bounds;

// Rasterize all edges with the specified fill rule, writing coverage to out,
// which must be width * height and is overwritten in the returned bounds,
// which may be empty. Pixels outside the bounds are not written to and have
// no coverage. Removes all edges.
static Bounds
rasterize(Rasterizer *r, VGFillRule rule, float *out) {
    Bounds b = {0};
    const size_t num = r->num_edges;
    if (!num) return b;
    qsort(r->edges, num, sizeof(r->edges[0]), cmp_edges);
    if (r->crossings_capacity < num) {
        void *p = realloc(r->crossings, num * sizeof(r->crossings[0]));
        if (!p) {
            r->oom = true;
            r->num_edges = 0;
            return b;
        }
        r->crossings = p;
        r->crossings_capacity = num;
    }
    double min_x = r->width, max_x = 0;
    double min_y = r->edges[0].y0, max_y = 0;
    for (size_t i = 0; i < num; i++) {
        max_y = fmax(max_y, r->edges[i].y1);
        min_x = fmin(min_x, fmin(r->edges[i].x0, r->edges[i].x1));
        max_x = fmax(max_x, fmax(r->edges[i].x0, r->edges[i].x1));
    }
    if (max_x <= 0 || min_x >= r->width) {
        r->num_edges = 0;
        return b;
    }
    b.top = (unsigned)fmax(0, floor(min_y));
    b.bottom = (unsigned)fmin(r->height, ceil(max_y));
    // Spans start and end at edges, so coverage is within the bounds of the edges
    b.left = (unsigned)fmax(0, floor(min_x));
    b.right = (unsigned)fmin(r->width, ceil(max_x));
    if (b.left >= b.right || b.top >= b.bottom) {
        r->num_edges = 0;
        return (Bounds){0};
    }
    const unsigned row_width = b.right - b.left;
    size_t next_edge = 0, num_active = 0;
    // active holds indices of edges that intersect the current sub-scanline
    size_t *active = r->active;
    for (unsigned y = b.top; y < b.bottom; y++) {
        memset(r->row_cov + b.left, 0, sizeof(r->row_cov[0]) * (row_width + 1));
        memset(r->row_diff + b.left, 0, sizeof(r->row_diff[0]) * (row_width + 1));
        bool row_has_coverage = false;
        for (unsigned s = 0; s < VG_SUBSAMPLES; s++) {
            const double sy = y + (s + 0.5) / VG_SUBSAMPLES;
            // Remove edges that end above this sub-scanline
            size_t k = 0;
            for (size_t i = 0; i < num_active; i++) {
                if (r->edges[active[i]].y1 > sy) active[k++] = active[i];
            }
            num_active = k;
            // Add edges that start above this sub-scanline
            while (next_edge < num && r->edges[next_edge].y0 <= sy) {
                if (r->edges[next_edge].y1 > sy) active[num_active++] = next_edge;
                next_edge++;
            }
            if (!num_active) continue;
            size_t nc = 0;
            for (size_t i = 0; i < num_active; i++) {
                const Edge *e = r->edges + active[i];
                r->crossings[nc].x = e->x0 + (sy - e->y0) * e->dxdy;
                r->crossings[nc].dir = e->dir;
                r->crossings[nc].edge = active[i];
                nc++;
            }
            // Insertion sort, crossings are usually nearly sorted already
            for (size_t i = 1; i < nc; i++) {
                struct Crossing c = r->crossings[i];
                size_t j = i;
                while (j > 0 && r->crossings[j - 1].x > c.x) {
                    r->crossings[j] = r->crossings[j - 1];
                    j--;
                }
                r->crossings[j] = c;
            }
            // Keep the active edges sorted by x so that the crossings of the
            // next sub-scanline are nearly sorted
            for (size_t i = 0; i < nc; i++) active[i] = r->crossings[i].edge;
            int winding = 0;
            for (size_t i = 0; i < nc; i++) {
                const bool was_inside = rule == VG_RULE_NONZERO ? winding != 0 : (winding & 1) != 0;
                winding += r->crossings[i].dir;
                const bool is_inside = rule == VG_RULE_NONZERO ? winding != 0 : (winding & 1) != 0;
                if (is_inside && !was_inside) {
                    // find the end of the span
                    size_t j = i + 1;
                    int w = winding;
                    for (; j < nc; j++) {
                        w += r->crossings[j].dir;
                        if (!(rule == VG_RULE_NONZERO ? w != 0 : (w & 1) != 0)) break;
                    }
                    const double xb = j < nc ? r->crossings[j].x : r->width;
                    add_span(r, r->crossings[i].x, xb);
                    row_has_coverage = true;
                    winding = w;
                    i = j;
                }
            }
        }
        float *row = out + (size_t)y * r->width;
        if (!row_has_coverage) {
            memset(row + b.left, 0, sizeof(row[0]) * row_width);
            continue;
        }
        double run = 0;
        for (unsigned x = b.left; x < b.right; x++) {
            run += r->row_diff[x];
            row[x] = (float)clamp01(run + r->row_cov[x]);
        }
    }
    r->num_edges = 0;
    return b;
}
#undef ENSURE
// }}}

// Path flattening {{{
typedef struct Transform {
    // Maps layer coordinates to device coordinates
    VGMatrix m;
    // Tolerance for flattening in layer coordinates
    double layer_tolerance;
    // The largest factor by which the transform scales lengths
    double scale;
} Transform;

static Point
xform(const Transform *t, Point p) {
    Point ans;
    vg_matrix_apply(&t->m, p.x, p.y, &ans.x, &ans.y);
    return ans;
}

static unsigned
segments_for_deviation(double deviation, double factor, double tolerance) {
    // Wang's formula
    const double n = ceil(sqrt(factor * deviation / tolerance));
    if (!(n >= 1)) return 1;
    return n > VG_MAX_CURVE_SEGMENTS ? VG_MAX_CURVE_SEGMENTS : (unsigned)n;
}

static void
flatten_quad(Rasterizer *r, Point p0, Point p1, Point p2, double tolerance) {
    const double dev = hypot(p0.x - 2 * p1.x + p2.x, p0.y - 2 * p1.y + p2.y);
    const unsigned n = segments_for_deviation(dev, 0.25, tolerance);
    for (unsigned i = 1; i <= n; i++) {
        const double t = (double)i / n, mt = 1 - t;
        sub_add(r, (Point){mt * mt * p0.x + 2 * mt * t * p1.x + t * t * p2.x, mt * mt * p0.y + 2 * mt * t * p1.y + t * t * p2.y}, i == n);
    }
}

static void
flatten_cubic(Rasterizer *r, Point p0, Point p1, Point p2, Point p3, double tolerance) {
    const double dev = fmax(hypot(p0.x - 2 * p1.x + p2.x, p0.y - 2 * p1.y + p2.y), hypot(p1.x - 2 * p2.x + p3.x, p1.y - 2 * p2.y + p3.y));
    const unsigned n = segments_for_deviation(dev, 0.75, tolerance);
    for (unsigned i = 1; i <= n; i++) {
        const double t = (double)i / n, mt = 1 - t;
        const double a = mt * mt * mt, b = 3 * mt * mt * t, c = 3 * mt * t * t, d = t * t * t;
        sub_add(r, (Point){a * p0.x + b * p1.x + c * p2.x + d * p3.x, a * p0.y + b * p1.y + c * p2.y + d * p3.y}, i == n);
    }
}

// Iterate over the subpaths of a layer, flattening each into r->sub, in
// layer coordinates. The callback is called with each subpath.
typedef struct SubpathInfo {
    bool closed;
    // Whether the subpath has any drawing command, a subpath with only a
    // moveto does not draw anything even when stroked
    bool has_drawing;
} SubpathInfo;

typedef void (*subpath_callback)(Rasterizer *r, const SubpathInfo *info, void *data);

static void
iterate_subpaths(Rasterizer *r, const VGGlyph *g, const VGLayer *layer, double tolerance, subpath_callback cb, void *data) {
    const float *pts = g->points + 2 * layer->first_point;
    SubpathInfo info = {0};
    Point current = {0};
    r->sub_count = 0;
#define FLUSH                             \
    if (r->sub_count) cb(r, &info, data); \
    r->sub_count = 0;                     \
    info = (SubpathInfo){0};
#define NEXT                 \
    (Point){pts[0], pts[1]}; \
    pts += 2
    for (uint32_t i = 0; i < layer->num_verbs && !r->oom; i++) {
        switch ((VGVerb)g->verbs[layer->first_verb + i]) {
            case VG_MOVE: {
                FLUSH;
                current = NEXT;
                sub_add(r, current, true);
            } break;
            case VG_LINE: {
                current = NEXT;
                info.has_drawing = true;
                sub_add(r, current, true);
            } break;
            case VG_QUAD: {
                Point c = NEXT;
                Point e = NEXT;
                info.has_drawing = true;
                flatten_quad(r, current, c, e, tolerance);
                current = e;
            } break;
            case VG_CUBIC: {
                Point c1 = NEXT;
                Point c2 = NEXT;
                Point e = NEXT;
                info.has_drawing = true;
                flatten_cubic(r, current, c1, c2, e, tolerance);
                current = e;
            } break;
            case VG_CLOSE: {
                info.closed = true;
                info.has_drawing = true;
                // The start of the next subpath, if it is an implied moveto, is the start of this one
                FLUSH;
            } break;
        }
    }
    FLUSH;
#undef FLUSH
#undef NEXT
}
// }}}

// Fill {{{
static void
fill_subpath(Rasterizer *r, const SubpathInfo *info UNUSED, void *data) {
    const Transform *t = data;
    // Fills implicitly close every subpath
    if (r->sub_count < 3) return;
    Point first = xform(t, (Point){r->sub[0].x, r->sub[0].y}), prev = first;
    for (size_t i = 1; i < r->sub_count; i++) {
        Point p = xform(t, (Point){r->sub[i].x, r->sub[i].y});
        add_edge(r, prev, p);
        prev = p;
    }
    add_edge(r, prev, first);
}
// }}}

// Stroke {{{
typedef struct StrokeData {
    const Transform *t;
    const VGLayer *layer;
    double half_width;
    // Number of segments for a full circle of the pen
    unsigned circle_segments;
} StrokeData;

static void
add_circle(Rasterizer *r, const StrokeData *sd, Point c) {
    for (unsigned i = 0; i < sd->circle_segments; i++) {
        const double a = 2 * M_PI * i / sd->circle_segments;
        poly_add(r, xform(sd->t, (Point){c.x + sd->half_width * cos(a), c.y + sd->half_width * sin(a)}));
    }
    commit_polygon(r, true);
}

static void
add_quad(Rasterizer *r, const StrokeData *sd, Point a, Point b, Point c, Point d) {
    poly_add(r, xform(sd->t, a));
    poly_add(r, xform(sd->t, b));
    poly_add(r, xform(sd->t, c));
    poly_add(r, xform(sd->t, d));
    commit_polygon(r, true);
}

static void
add_triangle(Rasterizer *r, const StrokeData *sd, Point a, Point b, Point c) {
    poly_add(r, xform(sd->t, a));
    poly_add(r, xform(sd->t, b));
    poly_add(r, xform(sd->t, c));
    commit_polygon(r, true);
}

static Point
unit_direction(Point a, Point b) {
    const double len = hypot(b.x - a.x, b.y - a.y);
    return (Point){(b.x - a.x) / len, (b.y - a.y) / len};
}

// Join at vertex v between a segment with direction d0 and one with direction d1
static void
add_join(Rasterizer *r, const StrokeData *sd, Point v, Point d0, Point d1, bool is_corner) {
    const double hw = sd->half_width;
    const double cross = d0.x * d1.y - d0.y * d1.x, dot = d0.x * d1.x + d0.y * d1.y;
    if (cross == 0 && dot > 0) return; // collinear, no gap to fill
    VGJoin join = sd->layer->join;
    if (!is_corner) {
        // Within a curve, the join fills in the gap between the
        // quadrilaterals of the flattened segments. A bevel is a good enough
        // approximation when the angle is small.
        const double angle = atan2(fabs(cross), dot);
        join = hw * sd->t->scale * (1 - cos(angle / 2)) < VG_TOLERANCE ? VG_JOIN_BEVEL : VG_JOIN_ROUND;
    }
    if (join == VG_JOIN_ROUND) {
        add_circle(r, sd, v);
        return;
    }
    // The outer side is the one the path turns away from
    const double side = cross > 0 ? -1 : 1;
    const Point n0 = {-d0.y * side * hw, d0.x * side * hw}, n1 = {-d1.y * side * hw, d1.x * side * hw};
    const Point a = {v.x + n0.x, v.y + n0.y}, b = {v.x + n1.x, v.y + n1.y};
    if (join == VG_JOIN_MITER) {
        // The ratio of the miter length to the stroke width is 1 / sin(theta / 2)
        // where theta is the angle between the segments
        const double theta = M_PI - atan2(fabs(cross), dot);
        const double s = sin(theta / 2);
        if (s > 0 && 1 / s <= sd->layer->miter_limit) {
            // The miter point is along the bisector of the outer normals
            const Point bis = {n0.x + n1.x, n0.y + n1.y};
            const double bl = hypot(bis.x, bis.y);
            if (bl > 0) {
                const double ml = hw / s;
                const Point m = {v.x + bis.x / bl * ml, v.y + bis.y / bl * ml};
                add_quad(r, sd, v, a, m, b);
                return;
            }
        }
    }
    add_triangle(r, sd, v, a, b);
}

static void
add_cap(Rasterizer *r, const StrokeData *sd, Point p, Point d) {
    // d points outwards from the end of the path
    const double hw = sd->half_width;
    switch (sd->layer->cap) {
        case VG_CAP_BUTT: break;
        case VG_CAP_ROUND: add_circle(r, sd, p); break;
        case VG_CAP_SQUARE: {
            const Point n = {-d.y * hw, d.x * hw}, e = {d.x * hw, d.y * hw};
            add_quad(
                r,
                sd,
                (Point){p.x + n.x, p.y + n.y},
                (Point){p.x + n.x + e.x, p.y + n.y + e.y},
                (Point){p.x - n.x + e.x, p.y - n.y + e.y},
                (Point){p.x - n.x, p.y - n.y});
        } break;
    }
}

static void
stroke_subpath(Rasterizer *r, const SubpathInfo *info, void *data) {
    const StrokeData *sd = data;
    if (!info->has_drawing) return;
    size_t n = r->sub_count;
    // Convert to an array of points, reusing the polygon scratch space is not
    // possible as it is used for the pieces of the stroke
    RAII_ALLOC(Point, p, malloc(n * sizeof(Point)));
    if (!p) {
        r->oom = true;
        return;
    }
    for (size_t i = 0; i < n; i++) p[i] = (Point){r->sub[i].x, r->sub[i].y};
    bool closed = info->closed;
    if (closed && n > 1 && p[0].x == p[n - 1].x && p[0].y == p[n - 1].y) n--;
    if (n == 1) {
        // A zero length subpath is drawn as a dot with round or square caps,
        // square caps being aligned with the x-axis
        if (sd->layer->cap != VG_CAP_BUTT) {
            add_cap(r, sd, p[0], (Point){1, 0});
            add_cap(r, sd, p[0], (Point){-1, 0});
        }
        return;
    }
    const double hw = sd->half_width;
    const size_t num_segments = closed ? n : n - 1;
    for (size_t i = 0; i < num_segments && !r->oom; i++) {
        const Point a = p[i], b = p[(i + 1) % n];
        const Point d = unit_direction(a, b), nrm = {-d.y * hw, d.x * hw};
        add_quad(
            r, sd, (Point){a.x + nrm.x, a.y + nrm.y}, (Point){b.x + nrm.x, b.y + nrm.y}, (Point){b.x - nrm.x, b.y - nrm.y}, (Point){a.x - nrm.x, a.y - nrm.y});
    }
    // Joins at interior vertices
    for (size_t i = 1; i < n - (closed ? 0 : 1) && !r->oom; i++) {
        const Point d0 = unit_direction(p[i - 1], p[i]), d1 = unit_direction(p[i], p[(i + 1) % n]);
        add_join(r, sd, p[i], d0, d1, r->sub[i].corner);
    }
    if (closed) {
        const Point d0 = unit_direction(p[n - 1], p[0]), d1 = unit_direction(p[0], p[1]);
        add_join(r, sd, p[0], d0, d1, true);
    } else {
        add_cap(r, sd, p[0], unit_direction(p[1], p[0]));
        add_cap(r, sd, p[n - 1], unit_direction(p[n - 2], p[n - 1]));
    }
}
// }}}

// Paint {{{
// A color in the decomposed form: premultiplied fixed color, premultiplied
// foreground weight and alpha
typedef struct PaintColor {
    float r, g, b, fg, a;
} PaintColor;

static PaintColor
premultiplied(const VGColor *c) {
    if (c->is_fg) return (PaintColor){.fg = c->a, .a = c->a};
    return (PaintColor){.r = c->r * c->a, .g = c->g * c->a, .b = c->b * c->a, .a = c->a};
}

// The number of entries in the color lookup table of a gradient
#define VG_GRADIENT_LUT_SIZE 1024

typedef struct GradientEvaluator {
    const VGPaint *paint;
    bool degenerate;
    // t for linear gradients and the gradient space coordinates for radial
    // gradients are affine functions of the device coordinates: v = vx * x + vy * y + v0
    double tx, ty, t0;
    double gxx, gxy, gx0, gyx, gyy, gy0;
    // radial gradient parameters
    double cdx, cdy, dr, a, fr, fx, fy;
    PaintColor lut[VG_GRADIENT_LUT_SIZE];
} GradientEvaluator;

static double
apply_spread(VGSpread spread, double t) {
    switch (spread) {
        case VG_SPREAD_PAD: return clamp01(t);
        case VG_SPREAD_REPEAT: return t - floor(t);
        case VG_SPREAD_REFLECT: {
            t = fabs(t);
            t = t - 2 * floor(t / 2);
            return t > 1 ? 2 - t : t;
        }
    }
    return t;
}

// The color at t in [0, 1]
static PaintColor
color_at(const VGPaint *paint, double t) {
    const VGStop *s = paint->stops;
    const unsigned n = paint->num_stops;
    const VGColor *c0 = &s[0].color, *c1 = c0;
    double f = 0;
    if (t <= s[0].offset) c1 = c0;
    else if (t >= s[n - 1].offset) c0 = c1 = &s[n - 1].color;
    else {
        for (unsigned i = 0; i + 1 < n; i++) {
            if (t < s[i + 1].offset) {
                c0 = &s[i].color;
                c1 = &s[i + 1].color;
                const double span = s[i + 1].offset - s[i].offset;
                f = span > 0 ? (t - s[i].offset) / span : 1;
                break;
            }
        }
    }
    // Interpolate non-premultiplied colors, as SVG does, then premultiply.
    // The foreground color is represented by its weight in the color.
    const double mf = 1 - f;
    const double fgw = mf * (c0->is_fg ? 1 : 0) + f * (c1->is_fg ? 1 : 0);
    const double r = mf * (c0->is_fg ? 0 : c0->r) + f * (c1->is_fg ? 0 : c1->r);
    const double g = mf * (c0->is_fg ? 0 : c0->g) + f * (c1->is_fg ? 0 : c1->g);
    const double b = mf * (c0->is_fg ? 0 : c0->b) + f * (c1->is_fg ? 0 : c1->b);
    const double a = mf * c0->a + f * c1->a;
    return (PaintColor){.r = (float)(r * a), .g = (float)(g * a), .b = (float)(b * a), .fg = (float)(fgw * a), .a = (float)a};
}

static bool
init_gradient(GradientEvaluator *ge, const VGPaint *paint, const Transform *t) {
    ge->paint = paint;
    ge->degenerate = false;
    VGMatrix to_device = paint->has_matrix ? vg_matrix_multiply(paint->matrix, t->m) : t->m, inv;
    if (!vg_matrix_invert(&to_device, &inv)) return false;
    // Gradient space coordinates of the center of the pixel at (x, y)
    ge->gxx = inv.a;
    ge->gxy = inv.c;
    ge->gx0 = inv.a * 0.5 + inv.c * 0.5 + inv.e;
    ge->gyx = inv.b;
    ge->gyy = inv.d;
    ge->gy0 = inv.b * 0.5 + inv.d * 0.5 + inv.f;
    const float *p = paint->params;
    if (paint->type == VG_PAINT_LINEAR) {
        const double dx = (double)p[2] - p[0], dy = (double)p[3] - p[1], len2 = dx * dx + dy * dy;
        ge->degenerate = len2 == 0;
        if (!ge->degenerate) {
            ge->tx = (ge->gxx * dx + ge->gyx * dy) / len2;
            ge->ty = (ge->gxy * dx + ge->gyy * dy) / len2;
            ge->t0 = ((ge->gx0 - p[0]) * dx + (ge->gy0 - p[1]) * dy) / len2;
        }
    } else {
        // focal circle fx fy fr, end circle cx cy r
        ge->fx = p[0];
        ge->fy = p[1];
        ge->fr = p[2];
        ge->cdx = (double)p[3] - p[0];
        ge->cdy = (double)p[4] - p[1];
        ge->dr = (double)p[5] - p[2];
        ge->a = ge->cdx * ge->cdx + ge->cdy * ge->cdy - ge->dr * ge->dr;
        ge->degenerate = ge->cdx == 0 && ge->cdy == 0 && ge->dr == 0;
    }
    if (ge->degenerate) {
        // A gradient with no extent paints its last stop
        ge->lut[0] = premultiplied(&paint->stops[paint->num_stops - 1].color);
    } else {
        for (unsigned i = 0; i < VG_GRADIENT_LUT_SIZE; i++) ge->lut[i] = color_at(paint, (double)i / (VG_GRADIENT_LUT_SIZE - 1));
    }
    return true;
}

static const PaintColor *
lookup(const GradientEvaluator *ge, double t) {
    // clamp01 also maps NaN, which can arise from extreme values, to zero
    t = clamp01(apply_spread(ge->paint->spread, t));
    return ge->lut + (unsigned)(t * (VG_GRADIENT_LUT_SIZE - 1) + 0.5);
}

// Returns NULL if the pixel is not painted by the gradient
static const PaintColor *
gradient_at(const GradientEvaluator *ge, unsigned x, unsigned y) {
    if (ge->degenerate) return ge->lut;
    if (ge->paint->type == VG_PAINT_LINEAR) return lookup(ge, ge->tx * x + ge->ty * y + ge->t0);
    // Two point conical gradient: find the largest t for which the point
    // is on the circle with center f + t * (c - f) and radius fr + t * (r - fr) >= 0
    const double gx = ge->gxx * x + ge->gxy * y + ge->gx0, gy = ge->gyx * x + ge->gyy * y + ge->gy0;
    const double pdx = gx - ge->fx, pdy = gy - ge->fy, fr = ge->fr;
    const double b = pdx * ge->cdx + pdy * ge->cdy + fr * ge->dr;
    const double c = pdx * pdx + pdy * pdy - fr * fr;
    double t;
    if (fabs(ge->a) < 1e-12) {
        if (b == 0) return NULL;
        t = c / (2 * b);
        if (fr + t * ge->dr < 0) return NULL;
    } else {
        const double disc = b * b - ge->a * c;
        if (disc < 0) return NULL;
        const double sq = sqrt(disc);
        const double t1 = (b + sq) / ge->a, t2 = (b - sq) / ge->a;
        const double hi = t1 > t2 ? t1 : t2, lo = t1 > t2 ? t2 : t1;
        if (fr + hi * ge->dr >= 0) t = hi;
        else if (fr + lo * ge->dr >= 0) t = lo;
        else return NULL;
    }
    return lookup(ge, t);
}
// }}}

// Rendering {{{
// Buffers reused between renders, rendering happens only on the main thread
typedef struct Canvas {
    unsigned width, height;
    bool mask_only, has_fg;
    float *coverage, *clip;
    // The decomposed result: premultiplied fixed color, foreground weight and
    // alpha. For glyphs that use only the foreground color only fg is used,
    // as alpha is the same as fg.
    float *k, *fg, *alpha;
    size_t capacity;
    // The region of the accumulators that has been initialized
    Bounds dirty;
    GradientEvaluator gradient;
} Canvas;

static Canvas canvas = {0};
static Rasterizer rasterizer = {0};
// Scratch space above this many pixels is freed after rendering
#define VG_SCRATCH_KEEP_PIXELS (512u * 1024u)

static void
free_scratch(void) {
    free(canvas.coverage);
    free(canvas.clip);
    free(canvas.k);
    free(canvas.fg);
    free(canvas.alpha);
    zero_at_ptr(&canvas);
    Rasterizer *r = &rasterizer;
    free(r->edges);
    free(r->poly);
    free(r->sub);
    free(r->row_cov);
    free(r->row_diff);
    free(r->crossings);
    free(r->active);
    zero_at_ptr(r);
}

static bool
ensure_canvas(unsigned width, unsigned height) {
    const size_t npix = (size_t)width * height;
    Canvas *c = &canvas;
    if (c->capacity < npix) {
        free(c->coverage);
        free(c->clip);
        free(c->k);
        free(c->fg);
        free(c->alpha);
        c->coverage = malloc(npix * sizeof(float));
        c->clip = malloc(npix * sizeof(float));
        c->k = malloc(npix * 3 * sizeof(float));
        c->fg = malloc(npix * sizeof(float));
        c->alpha = malloc(npix * sizeof(float));
        c->capacity = npix;
        if (!c->coverage || !c->clip || !c->k || !c->fg || !c->alpha) {
            free_scratch();
            return false;
        }
    }
    Rasterizer *r = &rasterizer;
    if (r->row_capacity < width + 2) {
        free(r->row_cov);
        free(r->row_diff);
        r->row_cov = malloc((width + 2) * sizeof(double));
        r->row_diff = malloc((width + 2) * sizeof(double));
        if (!r->row_cov || !r->row_diff) {
            free_scratch();
            return false;
        }
        r->row_capacity = width + 2;
    }
    r->width = width;
    r->height = height;
    r->oom = false;
    r->num_edges = 0;
    r->poly_count = 0;
    r->sub_count = 0;
    c->width = width;
    c->height = height;
    c->dirty = (Bounds){0};
    return true;
}

static Transform
placement_transform(const GlyphPlacement *pl, unsigned width, unsigned height) {
    const double vx = pl->vb[0], vy = pl->vb[1], vw = pl->vb[2], vh = pl->vb[3];
    double sx = width / vw, sy = height / vh;
    switch (pl->fit) {
        case GLYPH_FIT_CONTAIN: sx = sy = fmin(sx, sy); break;
        case GLYPH_FIT_COVER: sx = sy = fmax(sx, sy); break;
        case GLYPH_FIT_STRETCH: break;
    }
    const double extra_x = width - vw * sx, extra_y = height - vh * sy;
    double tx = -vx * sx, ty = -vy * sy;
    switch (pl->align_h) {
        case GLYPH_ALIGN_START: break;
        case GLYPH_ALIGN_CENTER: tx += extra_x / 2; break;
        case GLYPH_ALIGN_END: tx += extra_x; break;
    }
    switch (pl->align_v) {
        case GLYPH_ALIGN_START: break;
        case GLYPH_ALIGN_CENTER: ty += extra_y / 2; break;
        case GLYPH_ALIGN_END: ty += extra_y; break;
    }
    return (Transform){.m = {.a = sx, .d = sy, .e = tx, .f = ty}};
}

static bool
bounds_empty(Bounds b) {
    return b.left >= b.right || b.top >= b.bottom;
}

static void
zero_accumulators(Canvas *c, unsigned top, unsigned bottom, unsigned left, unsigned right) {
    if (left >= right) return;
    const size_t n = right - left;
    for (unsigned y = top; y < bottom; y++) {
        const size_t i = (size_t)y * c->width + left;
        memset(c->fg + i, 0, n * sizeof(float));
        if (!c->mask_only) {
            memset(c->alpha + i, 0, n * sizeof(float));
            memset(c->k + 3 * i, 0, 3 * n * sizeof(float));
        }
    }
}

// Ensure the accumulators are initialized in b
static void
extend_dirty(Canvas *c, Bounds b) {
    Bounds d = c->dirty;
    if (bounds_empty(d)) {
        zero_accumulators(c, b.top, b.bottom, b.left, b.right);
        c->dirty = b;
        return;
    }
    const Bounds u = {.left = MIN(d.left, b.left), .top = MIN(d.top, b.top), .right = MAX(d.right, b.right), .bottom = MAX(d.bottom, b.bottom)};
    zero_accumulators(c, u.top, d.top, u.left, u.right);
    zero_accumulators(c, d.bottom, u.bottom, u.left, u.right);
    zero_accumulators(c, d.top, d.bottom, u.left, d.left);
    zero_accumulators(c, d.top, d.bottom, d.right, u.right);
    c->dirty = u;
}

static void
composite_layer(Canvas *c, Bounds b, const VGLayer *layer, const Transform *t, bool clipped) {
    PaintColor solid = {0};
    GradientEvaluator *ge = &c->gradient;
    const bool is_solid = layer->paint.type == VG_PAINT_SOLID;
    if (is_solid) solid = premultiplied(&layer->paint.color);
    else if (!init_gradient(ge, &layer->paint, t)) return;
    extend_dirty(c, b);
    for (unsigned y = b.top; y < b.bottom; y++) {
        const size_t row = (size_t)y * c->width;
        for (unsigned x = b.left; x < b.right; x++) {
            const size_t i = row + x;
            float cov = c->coverage[i];
            if (clipped) cov *= c->clip[i];
            if (cov <= 0) continue;
            const PaintColor *pc = is_solid ? &solid : gradient_at(ge, x, y);
            if (!pc) continue;
            const float sa = pc->a * cov, inv = 1 - sa;
            c->fg[i] = pc->fg * cov + c->fg[i] * inv;
            if (!c->mask_only) {
                c->k[3 * i] = pc->r * cov + c->k[3 * i] * inv;
                c->k[3 * i + 1] = pc->g * cov + c->k[3 * i + 1] * inv;
                c->k[3 * i + 2] = pc->b * cov + c->k[3 * i + 2] * inv;
                c->alpha[i] = sa + c->alpha[i] * inv;
            }
        }
    }
}

static inline uint8_t
to_byte(float v) {
    return (uint8_t)(clamp01(v) * 255. + 0.5);
}

static bool
render_layers(const VGGlyph *g, Canvas *c, Rasterizer *r) {
    const Transform placement = placement_transform(&g->placement, c->width, c->height);
    unsigned clip_remaining = 0;
    Bounds clip_bounds = {0};
    for (uint32_t li = 0; li < g->num_layers; li++) {
        const VGLayer *layer = g->layers + li;
        Transform t = {.m = layer->has_matrix ? vg_matrix_multiply(layer->matrix, placement.m) : placement.m};
        double smallest;
        vg_matrix_singular_values(&t.m, &smallest, &t.scale);
        const bool clipped = clip_remaining > 0;
        if (clip_remaining) clip_remaining--;
        if (!(t.scale > 0)) continue;
        t.layer_tolerance = VG_TOLERANCE / t.scale;
        if (layer->kind == VG_LAYER_STROKE) {
            StrokeData sd = {.t = &t, .layer = layer, .half_width = layer->stroke_width / 2.};
            const double device_radius = sd.half_width * t.scale;
            // Enough segments that the polygon deviates from the circle by at most the tolerance
            unsigned n = 8;
            if (device_radius > VG_TOLERANCE) {
                const double step = 2 * acos(1 - VG_TOLERANCE / device_radius);
                n = (unsigned)fmin(VG_MAX_CURVE_SEGMENTS, fmax(8, ceil(2 * M_PI / step)));
            }
            sd.circle_segments = n;
            iterate_subpaths(r, g, layer, t.layer_tolerance, stroke_subpath, &sd);
        } else {
            iterate_subpaths(r, g, layer, t.layer_tolerance, fill_subpath, &t);
        }
        if (r->oom) return false;
        // Rasterizing requires space for the active edges
        if (r->num_edges) {
            size_t *active = realloc(r->active, r->num_edges * sizeof(size_t));
            if (!active) return false;
            r->active = active;
        }
        const VGFillRule rule = layer->kind == VG_LAYER_STROKE ? VG_RULE_NONZERO : layer->rule;
        if (layer->kind == VG_LAYER_CLIP) {
            // Clipped layers are composited only within the bounds of the
            // clip, where rasterize() sets the clip coverage
            clip_bounds = rasterize(r, rule, c->clip);
            if (r->oom) return false;
            clip_remaining = layer->clip_count;
            continue;
        }
        Bounds b = rasterize(r, rule, c->coverage);
        if (r->oom) return false;
        if (!bounds_empty(b)) {
            // Gradients are a few times more expensive per pixel than solid colors
            charge(r, (uint64_t)(b.right - b.left) * (b.bottom - b.top) * (layer->paint.type == VG_PAINT_SOLID ? 1 : 4));
            if (r->oom) return false;
        }
        if (clipped) {
            b.left = MAX(b.left, clip_bounds.left);
            b.top = MAX(b.top, clip_bounds.top);
            b.right = MIN(b.right, clip_bounds.right);
            b.bottom = MIN(b.bottom, clip_bounds.bottom);
        }
        if (!bounds_empty(b)) composite_layer(c, b, layer, &t, clipped);
    }
    return true;
}

static VGRenderResult
render(const VGGlyph *g, unsigned width, unsigned height, VGRender *out) {
    const size_t npix = (size_t)width * height;
    if (!ensure_canvas(width, height)) return VG_RENDER_OUT_OF_MEMORY;
    Canvas *c = &canvas;
    c->mask_only = !g->uses_fixed_color;
    c->has_fg = g->uses_fg;
    rasterizer.work = 0;
    rasterizer.over_budget = false;
    rasterizer.budget = vg_render_work_budget(width, height);
    bool ok = render_layers(g, c, &rasterizer);
    const bool over_budget = rasterizer.over_budget;
    out->work = rasterizer.work;
    if (ok) {
        out->width = width;
        out->height = height;
        if (!c->mask_only) {
            ok = (out->color = calloc(npix, 4)) != NULL;
            if (ok && c->has_fg) ok = (out->fg = calloc(npix, 1)) != NULL;
        } else ok = (out->fg = calloc(npix, 1)) != NULL;
    }
    if (ok) {
        const Bounds d = c->dirty;
        for (unsigned y = d.top; y < d.bottom; y++) {
            for (unsigned x = d.left; x < d.right; x++) {
                const size_t i = (size_t)y * width + x;
                if (out->color) {
                    out->color[4 * i] = to_byte(c->k[3 * i]);
                    out->color[4 * i + 1] = to_byte(c->k[3 * i + 1]);
                    out->color[4 * i + 2] = to_byte(c->k[3 * i + 2]);
                    out->color[4 * i + 3] = to_byte(c->alpha[i]);
                }
                if (out->fg) out->fg[i] = to_byte(c->fg[i]);
            }
        }
    } else {
        const uint64_t work = out->work;
        vg_render_free(out);
        out->work = work;
    }
    if (!ok || npix > VG_SCRATCH_KEEP_PIXELS) free_scratch();
    if (ok) return VG_RENDER_OK;
    return over_budget ? VG_RENDER_TOO_COMPLEX : VG_RENDER_OUT_OF_MEMORY;
}

uint64_t
vg_render_work_budget(unsigned width, unsigned height) {
    return VG_RENDER_WORK_BASE + VG_RENDER_WORK_PER_PIXEL * (uint64_t)width * height;
}

VGRenderResult
vg_render(const VGGlyph *g, unsigned width, unsigned height, VGRender *out) {
    zero_at_ptr(out);
    if (!width || !height) return VG_RENDER_OUT_OF_MEMORY;
    return render(g, width, height, out);
}

void
vg_render_free(VGRender *r) {
    free(r->color);
    free(r->fg);
    zero_at_ptr(r);
}
// }}}

// Python interface {{{
static bool
placement_from_python(PyObject *fit, PyObject *align, GlyphPlacement *pl) {
    pl->fit = GLYPH_FIT_CONTAIN;
    pl->align_h = pl->align_v = GLYPH_ALIGN_CENTER;
    if (fit) {
        const char *f = PyUnicode_AsUTF8(fit);
        if (!f) return false;
        if (strcmp(f, "contain") == 0) pl->fit = GLYPH_FIT_CONTAIN;
        else if (strcmp(f, "cover") == 0) pl->fit = GLYPH_FIT_COVER;
        else if (strcmp(f, "stretch") == 0) pl->fit = GLYPH_FIT_STRETCH;
        else {
            PyErr_Format(PyExc_ValueError, "Unknown fit: %s", f);
            return false;
        }
    }
    if (align) {
        const char *h, *v;
        if (!PyArg_ParseTuple(align, "ss", &h, &v)) return false;
        GlyphAlign *targets[2] = {&pl->align_h, &pl->align_v};
        const char *vals[2] = {h, v};
        for (unsigned i = 0; i < 2; i++) {
            if (strcmp(vals[i], "start") == 0) *targets[i] = GLYPH_ALIGN_START;
            else if (strcmp(vals[i], "center") == 0) *targets[i] = GLYPH_ALIGN_CENTER;
            else if (strcmp(vals[i], "end") == 0) *targets[i] = GLYPH_ALIGN_END;
            else {
                PyErr_Format(PyExc_ValueError, "Unknown align: %s", vals[i]);
                return false;
            }
        }
    }
    return true;
}

static PyObject *
py_render_vg(PyObject *self UNUSED, PyObject *args, PyObject *kw) {
    const char *data;
    Py_ssize_t sz;
    unsigned width, height, repeat = 1;
    PyObject *fit = NULL, *align = NULL;
    GlyphPlacement pl = {0};
    static const char *kwds[] = {"payload", "vb", "width", "height", "fit", "align", "repeat", NULL};
    if (!PyArg_ParseTupleAndKeywords(
            args,
            kw,
            "y#(ffff)II|UO!I",
            (char **)kwds,
            &data,
            &sz,
            pl.vb,
            pl.vb + 1,
            pl.vb + 2,
            pl.vb + 3,
            &width,
            &height,
            &fit,
            &PyTuple_Type,
            &align,
            &repeat))
        return NULL;
    if (!placement_from_python(fit, align, &pl)) return NULL;
    if (!width || !height || width > 4096 || height > 4096) {
        PyErr_SetString(PyExc_ValueError, "Invalid size");
        return NULL;
    }
    VGError err;
    const char *err_msg;
    VGGlyph *g = vg_parse((const uint8_t *)data, sz, &pl, &err, &err_msg);
    if (!g) {
        if (err == VG_OUT_OF_MEMORY) return PyErr_NoMemory();
        PyErr_Format(PyExc_ValueError, "%s: %s", err == VG_TOO_LARGE ? "outline_too_large" : "malformed_payload", err_msg);
        return NULL;
    }
    VGRender out = {0};
    VGRenderResult res = VG_RENDER_OK;
    // repeat is used for benchmarking
    for (unsigned i = 0; i < MAX(1u, repeat) && res == VG_RENDER_OK; i++) {
        vg_render_free(&out);
        res = vg_render(g, width, height, &out);
    }
    vg_decref(g);
    switch (res) {
        case VG_RENDER_OK: break;
        case VG_RENDER_OUT_OF_MEMORY: return PyErr_NoMemory();
        case VG_RENDER_TOO_COMPLEX: PyErr_Format(PyExc_ValueError, "too_complex: work: %llu", (unsigned long long)out.work); return NULL;
    }
    PyObject *ans = Py_BuildValue(
        "{sK sN sN}",
        "work",
        (unsigned long long)out.work,
        "color",
        out.color ? PyBytes_FromStringAndSize((const char *)out.color, (Py_ssize_t)width * height * 4) : Py_NewRef(Py_None),
        "fg",
        out.fg ? PyBytes_FromStringAndSize((const char *)out.fg, (Py_ssize_t)width * height) : Py_NewRef(Py_None));
    vg_render_free(&out);
    return ans;
}

static PyMethodDef methods[] = {
    {"render_vg", (PyCFunction)(void (*)(void))py_render_vg, METH_VARARGS | METH_KEYWORDS, "Render a vg payload, for testing"},
    {NULL, NULL, 0, NULL},
};

bool
init_vector_glyph_render(PyObject *module) {
    if (PyModule_AddFunctions(module, methods) != 0) return false;
    return true;
}
// }}}
