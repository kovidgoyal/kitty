/*
 * style-table.c
 * Copyright (C) 2026 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#include "style-table.h"
#include <xxhash.h>

static uint64_t
hash_style(CellStyle k) {
    return XXH3_64bits(&k, sizeof(k));
}

static bool
cmpr_style(CellStyle a, CellStyle b) {
    return style_eq(&a, &b);
}

// Maps styles to indices, used only to find approximate matches when the table is full
#define NAME style_map
#define KEY_TY CellStyle
#define VAL_TY uint32_t
#define HASH_FN hash_style
#define CMPR_FN cmpr_style
#include "kitty-verstable.h"

// The main map is a set of style indices, hashing and comparing the styles
// they refer to, which keeps it four times smaller than a map with styles as
// keys. That matters as with many distinct styles, for example, text with a
// different 24-bit color for every char, a larger map evicts the data being
// parsed from the CPU cache. Hash and compare functions get no context, so the
// styles array of the table being operated on is in a static variable, set
// before every operation on the set. Tables are only used on the main thread.
// A style not in the table is looked up using the PROBE_KEY index which refers to probe_style.
#define PROBE_KEY UINT32_MAX
static const CellStyle *ctx_styles = NULL;
static CellStyle probe_style = {0};

static inline const CellStyle *
resolve_key(uint32_t k) {
    return k == PROBE_KEY ? &probe_style : ctx_styles + k;
}

static uint64_t
hash_style_idx(uint32_t k) {
    return XXH3_64bits(resolve_key(k), sizeof(CellStyle));
}

static bool
cmpr_style_idx(uint32_t a, uint32_t b) {
    return style_eq(resolve_key(a), resolve_key(b));
}

#define NAME style_set
#define KEY_TY uint32_t
#define HASH_FN hash_style_idx
#define CMPR_FN cmpr_style_idx
#include "kitty-verstable.h"

// Number of slots in the cache of recently interned styles, a power of two
#define RECENT_CACHE_BITS 6u

typedef struct StyleTableImpl {
    CellStyleTable pub; // must be first
    uint32_t capacity, max_count;
    style_set map;
    // Indices of recently interned styles, indexed by a cheap hash of the
    // style, to avoid hashing and looking up styles that are used repeatedly.
    // Entries need no invalidation as they are checked against the style.
    uint32_t recent[1u << RECENT_CACHE_BITS];
    // Used to find approximate matches for new styles when the table is full
    struct {
        style_map fine, coarse;
        bool valid;
    } approx;
    uint32_t misses_since_gc;
    uint64_t gc_count;
    unsigned last_gc_quantize_bits;
    bool degraded, lossy_reported;
} StyleTableImpl;

#define INITIAL_CAPACITY 256u
#define FINE_BITS 4u
#define COARSE_BITS 2u

CellStyleTable *
style_table_alloc(void) {
    StyleTableImpl *self = calloc(1, sizeof(StyleTableImpl));
    if (!self) return NULL;
    self->capacity = INITIAL_CAPACITY;
    self->pub.styles = calloc(self->capacity, sizeof(CellStyle));
    if (!self->pub.styles) {
        free(self);
        return NULL;
    }
    self->pub.count = 1; // the default style
    self->pub.generation = 1;
    self->max_count = MAX_NUM_OF_STYLES;
    vt_init(&self->map);
    vt_init(&self->approx.fine);
    vt_init(&self->approx.coarse);
    return &self->pub;
}

void
style_table_free(CellStyleTable *pub) {
    if (!pub) return;
    StyleTableImpl *self = (StyleTableImpl *)pub;
    vt_cleanup(&self->map);
    vt_cleanup(&self->approx.fine);
    vt_cleanup(&self->approx.coarse);
    free(self->pub.styles);
    free(self);
}

static void
invalidate_approx(StyleTableImpl *self) {
    if (self->approx.valid) {
        vt_clear(&self->approx.fine);
        vt_clear(&self->approx.coarse);
        self->approx.valid = false;
    }
}

static void
bump_generation(StyleTableImpl *self) {
    if (++self->pub.generation == 0) self->pub.generation = 1;
}

void
style_table_reset(CellStyleTable *pub) {
    // Remove all styles except the default style, freeing memory
    StyleTableImpl *self = (StyleTableImpl *)pub;
    if (self->capacity > INITIAL_CAPACITY) {
        CellStyle *n = realloc(self->pub.styles, INITIAL_CAPACITY * sizeof(CellStyle));
        if (n) {
            self->pub.styles = n;
            self->capacity = INITIAL_CAPACITY;
        }
    }
    self->pub.count = 1;
    vt_cleanup(&self->map);
    vt_init(&self->map);
    invalidate_approx(self);
    vt_cleanup(&self->approx.fine);
    vt_init(&self->approx.fine);
    vt_cleanup(&self->approx.coarse);
    vt_init(&self->approx.coarse);
    bump_generation(self);
    self->misses_since_gc = 0;
    self->last_gc_quantize_bits = 0;
    self->degraded = false;
}

bool
style_table_is_worth_resetting(const CellStyleTable *pub) {
    const StyleTableImpl *self = (const StyleTableImpl *)pub;
    return self->pub.count > MAX(1u, self->max_count / 64);
}

void
style_table_set_max_count(CellStyleTable *pub, uint32_t max_count) {
    StyleTableImpl *self = (StyleTableImpl *)pub;
    self->max_count = MAX(2u, MIN(max_count, MAX_NUM_OF_STYLES));
}

uint32_t
style_table_max_count(const CellStyleTable *pub) {
    return ((const StyleTableImpl *)pub)->max_count;
}

static color_type
quantize_color(color_type c, unsigned bits) {
    // Reduce the precision of RGB colors to bits per channel, rounding to the
    // middle of the range of values each reduced value represents
    if ((c & 0xff) != 2) return c;
    const uint32_t mask = (0xffu << (8 - bits)) & 0xffu, half = 1u << (7 - bits);
    uint32_t ans = 2;
    for (unsigned shift = 8; shift < 32; shift += 8) ans |= ((((c >> shift) & 0xff) & mask) | half) << shift;
    return ans;
}

CellStyle
style_quantize(const CellStyle *s, unsigned bits) {
    if (!bits || bits >= 8) return *s;
    CellStyle ans = *s;
    ans.fg = quantize_color(s->fg, bits);
    ans.bg = quantize_color(s->bg, bits);
    ans.decoration_fg = quantize_color(s->decoration_fg, bits);
    return ans;
}

static void
build_approx(StyleTableImpl *self) {
    for (uint32_t i = 0; i < self->pub.count; i++) {
        const CellStyle *s = self->pub.styles + i;
        CellStyle q = style_quantize(s, FINE_BITS);
        if (vt_is_end(vt_get_or_insert(&self->approx.fine, q, i))) fatal("Out of memory building approximate style map");
        q = style_quantize(s, COARSE_BITS);
        if (vt_is_end(vt_get_or_insert(&self->approx.coarse, q, i))) fatal("Out of memory building approximate style map");
    }
    self->approx.valid = true;
}

static uint32_t
approximate_match(StyleTableImpl *self, const CellStyle *style) {
    // The table is full, use an existing style with the same attributes and close colors
    if (!self->approx.valid) build_approx(self);
    style_map_itr itr = vt_get(&self->approx.fine, style_quantize(style, FINE_BITS));
    if (!vt_is_end(itr)) return itr.data->val;
    itr = vt_get(&self->approx.coarse, style_quantize(style, COARSE_BITS));
    if (!vt_is_end(itr)) return itr.data->val;
    return 0;
}

static inline uint32_t
recent_slot(const CellStyle *s) {
    const uint32_t h = (s->fg * 0x9E3779B1u) ^ (s->bg * 0x85EBCA77u) ^ (s->decoration_fg * 0xC2B2AE3Du) ^ (s->attrs.val * 0x27D4EB2Fu);
    return h >> (32 - RECENT_CACHE_BITS);
}

uint32_t
style_table_intern(CellStyleTable *pub, const CellStyle *style) {
    static const CellStyle default_style = {0};
    if (style_eq(style, &default_style)) return 0;
    StyleTableImpl *self = (StyleTableImpl *)pub;
    const uint32_t slot = recent_slot(style), recent = self->recent[slot];
    if (recent < self->pub.count && style_eq(self->pub.styles + recent, style)) return recent;
    ctx_styles = self->pub.styles;
    probe_style = *style;
    style_set_itr itr = vt_get(&self->map, PROBE_KEY);
    if (!vt_is_end(itr)) return (self->recent[slot] = itr.data->key);
    if (self->pub.count >= self->max_count) {
        // The owner of the table compacts it when it is safe to do so, see style_table_needs_gc()
        self->misses_since_gc++;
        return approximate_match(self, style);
    }
    if (self->pub.count >= self->capacity) {
        const uint32_t new_capacity = MIN(self->capacity * 2, MAX_NUM_OF_STYLES);
        CellStyle *n = realloc(self->pub.styles, new_capacity * sizeof(CellStyle));
        if (!n) fatal("Out of memory growing the style table");
        self->pub.styles = n;
        self->capacity = new_capacity;
    }
    const uint32_t idx = self->pub.count++;
    self->pub.styles[idx] = *style;
    ctx_styles = self->pub.styles; // may have been changed by realloc() above
    if (vt_is_end(vt_insert(&self->map, idx))) fatal("Out of memory inserting into the style table");
    return (self->recent[slot] = idx);
}

// Garbage collection {{{

bool
style_table_needs_gc(const CellStyleTable *pub) {
    const StyleTableImpl *self = (const StyleTableImpl *)pub;
    if (self->pub.count < self->max_count) return false;
    // When even the styles on screen do not fit, collecting cannot free much,
    // so wait until many new styles have been used before trying again
    if (self->degraded) return self->misses_since_gc >= self->max_count / 2;
    return true;
}

struct StyleTableGC {
    CellStyle *old_styles;
    uint32_t old_count, *remap, *quantized_remap; // old index -> new index + 1, 0 means not yet remapped
    unsigned quantize_bits;
};

StyleTableGC *
style_table_gc_begin(CellStyleTable *pub, unsigned quantize_bits) {
    StyleTableImpl *self = (StyleTableImpl *)pub;
    StyleTableGC *gc = calloc(1, sizeof(StyleTableGC));
    if (!gc) return NULL;
    gc->old_count = self->pub.count;
    gc->quantize_bits = quantize_bits;
    gc->old_styles = malloc(gc->old_count * sizeof(CellStyle));
    gc->remap = calloc(gc->old_count, sizeof(uint32_t));
    if (quantize_bits) gc->quantized_remap = calloc(gc->old_count, sizeof(uint32_t));
    if (!gc->old_styles || !gc->remap || (quantize_bits && !gc->quantized_remap)) {
        free(gc->old_styles);
        free(gc->remap);
        free(gc->quantized_remap);
        free(gc);
        return NULL;
    }
    memcpy(gc->old_styles, self->pub.styles, gc->old_count * sizeof(CellStyle));
    vt_clear(&self->map);
    self->pub.count = 1;
    invalidate_approx(self);
    return gc;
}

uint32_t
style_table_gc_map(CellStyleTable *pub, StyleTableGC *gc, uint32_t old_idx, bool quantize) {
    // Called for every live cell, returns its new style index. quantize is ignored unless
    // the GC was started with quantize_bits. Cannot overflow the table as the number of
    // styles re-interned is at most the number there were before.
    if (!old_idx || old_idx >= gc->old_count) return 0;
    uint32_t *map = gc->remap;
    if (quantize && gc->quantized_remap) map = gc->quantized_remap;
    if (!map[old_idx]) {
        const CellStyle s = map == gc->remap ? gc->old_styles[old_idx] : style_quantize(gc->old_styles + old_idx, gc->quantize_bits);
        map[old_idx] = style_table_intern(pub, &s) + 1;
    }
    return map[old_idx] - 1;
}

void
style_table_gc_end(CellStyleTable *pub, StyleTableGC *gc, bool degraded) {
    StyleTableImpl *self = (StyleTableImpl *)pub;
    bump_generation(self);
    self->misses_since_gc = 0;
    self->gc_count++;
    self->degraded = degraded;
    self->last_gc_quantize_bits = gc->quantize_bits;
    if (gc->quantize_bits && !self->lossy_reported) {
        self->lossy_reported = true;
        log_error("Too many distinct cell styles, reducing the color precision of cells in the scrollback");
    }
    free(gc->old_styles);
    free(gc->remap);
    free(gc->quantized_remap);
    free(gc);
}

unsigned
style_table_last_gc_quantize_bits(const CellStyleTable *pub) {
    return ((const StyleTableImpl *)pub)->last_gc_quantize_bits;
}

uint64_t
style_table_gc_count(const CellStyleTable *pub) {
    return ((const StyleTableImpl *)pub)->gc_count;
}

bool
style_table_is_degraded(const CellStyleTable *pub) {
    return ((const StyleTableImpl *)pub)->degraded;
}
// }}}
