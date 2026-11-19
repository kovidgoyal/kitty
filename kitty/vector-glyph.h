/*
 * vector-glyph.h
 * Copyright (C) 2026 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

// Vector glyphs in the vg format of the glyph protocol: layers of SVG path
// data that are filled, stroked or used as clips, painted with the foreground
// color, a fixed color or a gradient.

#pragma once

#include "glyph-protocol.h"

// Limits from the spec
#define VG_MAX_LAYERS 128u
#define VG_MAX_CLIP_LAYERS 127u
#define VG_MAX_STOPS 16u
#define VG_MIN_STOPS 2u
#define VG_MAX_SEGMENTS 2048u
// Total path length, in multiples of the viewBox size
#define VG_MAX_PATH_LENGTH 64.
// The maximum factor by which a matrix may stretch or shrink lengths
#define VG_MAX_MATRIX_SCALE 4096.
#define VG_MIN_MITER_LIMIT 1.f
#define VG_MAX_MITER_LIMIT 1000.f
#define VG_DEFAULT_MITER_LIMIT 4.f

typedef enum VGError {
    VG_OK,
    VG_MALFORMED,
    VG_TOO_LARGE,
    VG_OUT_OF_MEMORY,
} VGError;

typedef enum VGLayerKind { VG_LAYER_FILL, VG_LAYER_STROKE, VG_LAYER_CLIP } VGLayerKind;
typedef enum VGFillRule { VG_RULE_NONZERO, VG_RULE_EVENODD } VGFillRule;
typedef enum VGCap { VG_CAP_ROUND, VG_CAP_BUTT, VG_CAP_SQUARE } VGCap;
typedef enum VGJoin { VG_JOIN_ROUND, VG_JOIN_BEVEL, VG_JOIN_MITER } VGJoin;
typedef enum VGSpread { VG_SPREAD_PAD, VG_SPREAD_REFLECT, VG_SPREAD_REPEAT } VGSpread;
typedef enum VGPaintType { VG_PAINT_SOLID, VG_PAINT_LINEAR, VG_PAINT_RADIAL } VGPaintType;
// Path verbs, the number of points each uses is in vg_verb_num_points
typedef enum VGVerb { VG_MOVE, VG_LINE, VG_QUAD, VG_CUBIC, VG_CLOSE } VGVerb;

static inline unsigned
vg_verb_num_points(VGVerb v) {
    switch (v) {
        case VG_MOVE:
        case VG_LINE: return 1;
        case VG_QUAD: return 2;
        case VG_CUBIC: return 3;
        case VG_CLOSE: return 0;
    }
    return 0;
}

// An affine matrix, as SVG's matrix(a b c d e f): x' = a*x + c*y + e, y' = b*x + d*y + f
typedef struct VGMatrix {
    double a, b, c, d, e, f;
} VGMatrix;

static inline VGMatrix
vg_identity_matrix(void) {
    return (VGMatrix){.a = 1, .d = 1};
}

// Returns the matrix that applies first then second
static inline VGMatrix
vg_matrix_multiply(VGMatrix first, VGMatrix second) {
    return (VGMatrix){
        .a = second.a * first.a + second.c * first.b,
        .b = second.b * first.a + second.d * first.b,
        .c = second.a * first.c + second.c * first.d,
        .d = second.b * first.c + second.d * first.d,
        .e = second.a * first.e + second.c * first.f + second.e,
        .f = second.b * first.e + second.d * first.f + second.f,
    };
}

static inline void
vg_matrix_apply(const VGMatrix *m, double x, double y, double *ox, double *oy) {
    *ox = m->a * x + m->c * y + m->e;
    *oy = m->b * x + m->d * y + m->f;
}

// The smallest and largest factors by which the matrix scales lengths
void vg_matrix_singular_values(const VGMatrix *m, double *smallest, double *largest);
// Returns false if the matrix is not invertible
bool vg_matrix_invert(const VGMatrix *m, VGMatrix *ans);

// A color that is either the foreground color multiplied by alpha or a fixed
// sRGB color with alpha. Components are in [0, 1], not premultiplied.
typedef struct VGColor {
    bool is_fg;
    float r, g, b, a;
} VGColor;

typedef struct VGStop {
    float offset;
    VGColor color;
} VGStop;

typedef struct VGPaint {
    VGPaintType type;
    // For solid paints
    VGColor color;
    // For linear gradients: x1 y1 x2 y2, for radial gradients: fx fy fr cx cy r
    float params[6];
    VGSpread spread;
    // Maps gradient space to the coordinates of the layer
    bool has_matrix;
    VGMatrix matrix;
    unsigned num_stops;
    VGStop stops[VG_MAX_STOPS];
} VGPaint;

typedef struct VGLayer {
    VGLayerKind kind;
    VGFillRule rule;
    // For clip layers, the number of following layers that are clipped
    unsigned clip_count;
    // For stroke layers
    float stroke_width, miter_limit;
    VGCap cap;
    VGJoin join;
    // Maps the coordinates of the layer to the viewBox
    bool has_matrix;
    VGMatrix matrix;
    // Unused for clip layers
    VGPaint paint;
    // The path of the layer
    uint32_t first_verb, num_verbs, first_point;
} VGLayer;

typedef struct VGGlyph {
    unsigned refcnt;
    GlyphPlacement placement;
    uint32_t num_layers;
    VGLayer *layers;
    uint32_t num_verbs, num_points;
    uint8_t *verbs;
    // Pairs of x, y in the coordinates of the layer that uses them
    float *points;
    // Whether any color is the foreground color and whether any color is a fixed color
    bool uses_fg, uses_fixed_color;
    // The number of bytes of memory used by this glyph
    size_t memory_size;
} VGGlyph;

// Parse a vg payload. On success returns a glyph with a reference count of one.
// On failure returns NULL and sets *err and *err_msg, which points to a static string.
VGGlyph *vg_parse(const uint8_t *payload, size_t sz, const GlyphPlacement *placement, VGError *err, const char **err_msg);
VGGlyph *vg_incref(VGGlyph *g);

// The result of rendering a glyph into an area of width x height pixels.
// The rendered pixel with foreground color fg is color.rgb + fg * fg_weight
// with alpha color.a, all premultiplied.
typedef struct VGRender {
    unsigned width, height;
    // Premultiplied RGBA, 4 bytes per pixel. NULL if the glyph uses only the
    // foreground color, in which case the color is fg * fg_weight with alpha
    // fg_weight.
    uint8_t *color;
    // The weight of the foreground color, 1 byte per pixel. NULL if the glyph
    // does not use the foreground color.
    uint8_t *fg;
    // The work done by the renderer, see vg_render_work_budget()
    uint64_t work;
} VGRender;

typedef enum VGRenderResult {
    VG_RENDER_OK,
    VG_RENDER_OUT_OF_MEMORY,
    // Rendering would take more than vg_render_work_budget()
    VG_RENDER_TOO_COMPLEX,
} VGRenderResult;

// The maximum work rendering a glyph into an area of width x height pixels
// may take, in units of roughly one cheap operation per point, sub-scanline
// crossing or pixel
#define VG_RENDER_WORK_BASE (1u << 20)
#define VG_RENDER_WORK_PER_PIXEL 96u
uint64_t vg_render_work_budget(unsigned width, unsigned height);

// Render the glyph, placing its viewBox in the area according to its
// placement and clipping to the area.
VGRenderResult vg_render(const VGGlyph *g, unsigned width, unsigned height, VGRender *out);
void vg_render_free(VGRender *r);
// Always returns NULL
VGGlyph *vg_decref(VGGlyph *g);

// Registrations {{{
// The memory budget for registered glyphs, across all sessions
#define VG_REGISTRY_MEMORY_BUDGET (64u * 1024u * 1024u)

// The glyphs registered for the codepoints of the registration block in one
// session (screen)
typedef struct GlyphRegistry {
    VGGlyph *glyphs[GLYPH_BLOCK_SIZE];
    uint32_t num_registered;
    // Incremented whenever a registration changes
    uint32_t generation;
} GlyphRegistry;

GlyphRegistry *glyph_registry_alloc(void);
void glyph_registry_free(GlyphRegistry *self);
// Returns a borrowed reference or NULL
static inline VGGlyph *
glyph_registry_get(const GlyphRegistry *self, char_type cp) {
    return is_glyph_block_codepoint(cp) ? self->glyphs[cp - GLYPH_BLOCK_FIRST] : NULL;
}
// Register g for cp, taking a new reference to g. cp must be in the
// registration block. Returns false if this would exceed the memory budget.
bool glyph_registry_set(GlyphRegistry *self, char_type cp, VGGlyph *g);
void glyph_registry_clear(GlyphRegistry *self, char_type cp);
void glyph_registry_clear_all(GlyphRegistry *self);
// The memory used by all registrations in all sessions
size_t glyph_registry_total_memory(void);
// }}}
