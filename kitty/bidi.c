/*
 * bidi.c
 *
 * Distributed under terms of the GPL3 license.
 */

#include "bidi.h"
#include <xxhash.h>

// Isolates fed to FriBidi as isolates per paragraph; later ones are neutrals. FriBidi's NEWS lists quadratic time in FSIs
// before 1.0.17 and in back-to-back isolates before 1.0.18.
#define BIDI_MAX_ISOLATES 32
// The longest walk from a bracket pair back to the previous strong char fed to a FriBidi before 1.0.17, which takes quadratic
// time in such walks
#define BIDI_N0_MAX_WALK 32
// Flags in cell_of_char: a char that takes no column, fed in its cell's column, and the separator fed for a scaled cell
#define BIDI_EXTRA_CHAR (1u << 31)
#define BIDI_FIXED_CELL (1u << 30)

static inline bool
is_bidi_mark(char_type ch) {
    return (ch | 1) == 0x200f || ch == 0x61c;
}

// Stores in buf the isolate controls and marks among the chars after the cell's first char
static inline unsigned
cell_extra_chars(const CPUCell *c, const TextCache *tc, char_type buf[MAX_NUM_CODEPOINTS_PER_CELL]) {
    if (!c->ch_is_idx || (c->is_multicell && (c->x || c->y))) return 0;
    ListOfChars lc = {.chars = buf, .capacity = MAX_NUM_CODEPOINTS_PER_CELL};
    if (!tc_chars_at_index_without_alloc(tc, c->ch_or_idx, &lc)) return 0;
    unsigned n = 0;
    // A tab's second char is the number of cells it skips
    for (size_t i = lc.chars[0] == '\t' ? 2 : 1; i < lc.count; i++) {
        const char_type ch = lc.chars[i];
        if (ch - 0x2066u <= 0x2069u - 0x2066u || is_bidi_mark(ch)) buf[n++] = ch;
    }
    return n;
}

// The char a cell is fed as. A scale-1 multicell is shaped at the level resolved for it, so it is fed as one char: its first
// letter, or its first char when it has none. Embeddings and overrides are strong to FriBidi but fed as neutrals
// (retype_controls()), so only letters count, and of them not the marks, which draw nothing.
static inline char_type
cell_lead_char(const CPUCell *c, const TextCache *tc) {
    if (!c->is_multicell || !c->ch_is_idx || c->x || c->y) return cell_first_char(c, tc);
    char_type buf[MAX_NUM_CODEPOINTS_PER_CELL];
    ListOfChars lc = {.chars = buf, .capacity = MAX_NUM_CODEPOINTS_PER_CELL};
    if (tc_chars_at_index_without_alloc(tc, c->ch_or_idx, &lc)) {
        for (size_t i = 0; i < lc.count; i++) {
            if (FRIBIDI_IS_LETTER(fribidi_get_bidi_type(lc.chars[i])) && !is_bidi_mark(lc.chars[i])) return lc.chars[i];
        }
    }
    return cell_first_char(c, tc);
}

// The number of cells after a tab cell that the tab skipped, see screen_tab()
static inline unsigned
tab_cell_skip(const CPUCell *c, const TextCache *tc) {
    char_type buf[MAX_NUM_CODEPOINTS_PER_CELL];
    ListOfChars lc = {.chars = buf, .capacity = MAX_NUM_CODEPOINTS_PER_CELL};
    return tc_chars_at_index_without_alloc(tc, c->ch_or_idx, &lc) && lc.count > 1 ? lc.chars[1] : 0;
}

static void
bidi_scratch_free(BidiScratch *s) {
    free(s->text);
    free(s->types);
    free(s->brackets);
    free(s->levels);
    free(s->cell_of_char);
    free(s->row_start);
    zero_at_ptr(s);
}

// Frees the buffers when far larger than the paragraphs resolved since the last call needed
static void
bidi_scratch_trim(BidiScratch *s) {
    if (s->peak && s->levels_cap > MAX(8 * s->peak, (size_t)1 << 16)) bidi_scratch_free(s);
    s->peak = 0;
}

// Whether some cell may be right-to-left, holds an RLI, RLM or ALM, or is scaled
bool
bidi_cells_may_reorder(const CPUCell *cells, index_type num, const TextCache *tc) {
    char_type buf[MAX_NUM_CODEPOINTS_PER_CELL];
    for (const CPUCell *c = cells, *end = cells + num; c < end; c++) {
        // Resolved so that its rows have levels, at which it is shaped in the direction guessed from its text
        if (c->is_multicell && c->scale > 1) return true;
        char_type ch = c->ch_or_idx;
        if (c->ch_is_idx) {
            if (c->is_multicell) {
                if (c->x || c->y) continue;
                // Any of its chars may be the one it is fed as
                ListOfChars lc = {.chars = buf, .capacity = MAX_NUM_CODEPOINTS_PER_CELL};
                if (tc_chars_at_index_without_alloc(tc, ch, &lc)) {
                    for (size_t i = 1; i < lc.count; i++) {
                        if (bidi_codepoint_may_reorder(lc.chars[i])) return true;
                    }
                }
            }
            ch = tc_first_char_at_index(tc, ch);
        }
        // An RLM written by OSC 66 as the only char of a cell is fed as a strong char
        if (bidi_codepoint_may_reorder(ch) || ch == 0x200f) return true;
        if (!c->ch_is_idx) continue;
        // Likewise an RLI, RLM or ALM after the first char
        for (unsigned i = 0, k = cell_extra_chars(c, tc, buf); i < k; i++) {
            if (buf[i] == 0x2067 || buf[i] == 0x200f || buf[i] == 0x61c) return true;
        }
    }
    return false;
}

// Whether the char in the columns [start, end) has a cell in a fixed column or crosses the edge of a span
static bool
bidi_char_is_fixed(const BidiFixedColumns *fixed, index_type start, index_type end) {
    for (unsigned i = 0; i < fixed->count; i++) {
        if (fixed->at[2 * i + 1] > start && fixed->at[2 * i] < end) return true;
    }
    for (unsigned i = 0; i < fixed->num_edges; i++) {
        if (fixed->edges[i] > start && fixed->edges[i] < end) return true;
    }
    return false;
}

// Appends the row's chars to s->text and returns the new length. Each column of a scaled cell, which spans several rows each
// showing a slice of the same glyphs, is a segment separator: the text on either side is reordered within its span. So is each
// column of fixed, whose cells scroll sideways one column at a time, and each column of a char with a cell there or across a span
// edge: its cells keep their columns, as a char's cells are drawn at one level.
static inline uint32_t
feed_row(BidiScratch *s, const CPUCell *cells, index_type cols, const TextCache *tc, const BidiFixedColumns *fixed, uint32_t n) {
    FriBidiChar *restrict text = s->text + n, *const text_start = text;
    uint32_t *restrict cell_of_char = s->cell_of_char + n;
    const unsigned num_fixed = fixed ? fixed->count : 0;
    index_type col = 0;
    for (unsigned f = 0;; f++) {
        const index_type end = f < num_fixed ? fixed->at[2 * f] : cols;
        for (; col < end; col++) {
            const CPUCell *c = cells + col;
            if (c->is_multicell) {
                if (c->scale > 1) {
                    *text++ = '\t';
                    *cell_of_char++ = col | BIDI_FIXED_CELL;
                    continue;
                }
                if (col && c->x) continue;
                // Its first cell here, or its cells from column 0 on
                if (fixed && bidi_char_is_fixed(fixed, col, MIN(col + mcd_x_limit(c) - c->x, cols))) {
                    *text++ = '\t';
                    *cell_of_char++ = col | BIDI_FIXED_CELL;
                    continue;
                }
            }
            const char_type ch = cell_lead_char(c, tc);
            *text++ = ch ? ch : ' ';
            *cell_of_char++ = col;
            if (!c->ch_is_idx) continue;
            char_type buf[MAX_NUM_CODEPOINTS_PER_CELL];
            // Within the scratch: bidi_resolve_paragraph() sized it for MAX_NUM_CODEPOINTS_PER_CELL chars per cell
            for (unsigned i = 0, k = cell_extra_chars(c, tc, buf); i < k; i++) {
                *text++ = buf[i];
                *cell_of_char++ = col | BIDI_EXTRA_CHAR;
            }
            if (ch != '\t') continue;
            // The cells the tab skipped, while they hold the spaces it wrote, are fed as it is: at the paragraph level (L1) they
            // keep the text after the tab at the tab stop, as with bidi mode off
            for (unsigned k = tab_cell_skip(c, tc); k && col + 1 < end && cell_is_char(cells + col + 1, ' '); k--) {
                *text++ = '\t';
                *cell_of_char++ = ++col;
            }
        }
        if (f == num_fixed) break;
        for (; col < fixed->at[2 * f + 1]; col++) {
            *text++ = '\t';
            *cell_of_char++ = col | BIDI_FIXED_CELL;
        }
    }
    return n + (uint32_t)(text - text_start);
}

// Embeddings, overrides and isolate controls that start a cell (OSC 66) are fed as neutrals, and so are the isolates over
// the BIDI_MAX_ISOLATES cap. A PDI matches a capped initiator while any is open, as those open after the honoured ones.
static void
retype_controls(BidiScratch *s, uint32_t n) {
    unsigned honoured = 0, open_honoured = 0, open_capped = 0;
    for (uint32_t i = 0; i < n; i++) {
        const FriBidiCharType t = s->types[i];
        if (!(t & (FRIBIDI_MASK_EXPLICIT | FRIBIDI_MASK_ISOLATE))) continue;
        if ((t & FRIBIDI_MASK_EXPLICIT) || !(s->cell_of_char[i] & BIDI_EXTRA_CHAR)) s->types[i] = FRIBIDI_TYPE_ON;
        else if (t == FRIBIDI_TYPE_PDI) {
            if (open_capped) {
                open_capped--;
                s->types[i] = FRIBIDI_TYPE_ON;
            } else if (open_honoured) open_honoured--;
        } else if (honoured < BIDI_MAX_ISOLATES) {
            honoured++;
            open_honoured++;
        } else {
            open_capped++;
            s->types[i] = FRIBIDI_TYPE_ON;
        }
    }
}

#define BIDI_FRIBIDI_AT(major, minor, micro) ((int64_t)(major) << 40 | (int64_t)(minor) << 20 | (int64_t)(micro))

// The version loaded, not the one built against: 1.0.16 to 1.0.18 share a soname. A version that does not parse is older than
// any.
static int64_t
fribidi_loaded_version(void) {
    static int64_t version = -1;
    if (version < 0) {
        unsigned major, minor, micro;
        version = sscanf(fribidi_version_info, "(GNU FriBidi) %u.%u.%u", &major, &minor, &micro) == 3 ? BIDI_FRIBIDI_AT(major, minor, micro) : 0;
    }
    return version;
}

bool
bidi_n0_walk_is_slow(void) {
    return fribidi_loaded_version() < BIDI_FRIBIDI_AT(1, 0, 17);
}

// Brackets that BD16 does not pair within their isolating run sequence are fed as neutrals: FriBidi keeps pairs inside it only
// from 1.0.18, which needs none of this. FriBidi before 1.0.17 also walks back from the opening bracket of every pair (N0) to the
// previous strong char, so with it a pair whose walk is longer than BIDI_N0_MAX_WALK chars is fed as two neutrals too.
static void
limit_bracket_pairs(BidiScratch *s, uint32_t n) {
    if (fribidi_loaded_version() >= BIDI_FRIBIDI_AT(1, 0, 18)) return;
    const bool slow_walk = bidi_n0_walk_is_slow();
    enum { DEPTHS = BIDI_MAX_ISOLATES + 1, STACK = FRIBIDI_BIDI_MAX_NESTED_BRACKET_PAIRS };
    struct {
        uint32_t at;
        bool near;
    } open[DEPTHS * STACK];
    struct {
        uint32_t base;
        bool full;
    } seq[DEPTHS] = {{0}};
    int64_t last_strong[DEPTHS];
    for (unsigned d = 0; d < DEPTHS; d++) last_strong[d] = -1;
    FriBidiBracketType *br = s->brackets;
    unsigned depth = 0;
    uint32_t top = 0;
#define unpair_open_down_to(bottom) \
    for (; top > (bottom); top--) br[open[top - 1].at] = FRIBIDI_NO_BRACKET
    for (uint32_t i = 0; i < n; i++) {
        const FriBidiCharType t = s->types[i];
        const FriBidiBracketType b = br[i];
        if (t & (FRIBIDI_MASK_LETTER | FRIBIDI_MASK_NUMBER)) last_strong[depth] = i;
        else if (FRIBIDI_IS_ISOLATE(t)) {
            if (t != FRIBIDI_TYPE_PDI) {
                depth++;
                last_strong[depth] = i;
                seq[depth].base = top;
                seq[depth].full = false;
            } else if (depth) {
                unpair_open_down_to(seq[depth].base);
                depth--;
            }
        } else if (b == FRIBIDI_NO_BRACKET) continue;
        else if (seq[depth].full) br[i] = FRIBIDI_NO_BRACKET;
        else if (FRIBIDI_IS_BRACKET_OPEN(b)) {
            if (top - seq[depth].base == STACK) {
                // BD16 stops for the rest of the isolating run sequence
                seq[depth].full = true;
                unpair_open_down_to(seq[depth].base);
                br[i] = FRIBIDI_NO_BRACKET;
            } else {
                open[top].at = i;
                open[top++].near = !slow_walk || (int64_t)i - last_strong[depth] <= BIDI_N0_MAX_WALK;
            }
        } else {
            uint32_t p = top;
            while (p > seq[depth].base && FRIBIDI_BRACKET_ID(br[open[p - 1].at]) != FRIBIDI_BRACKET_ID(b)) p--;
            if (p == seq[depth].base) br[i] = FRIBIDI_NO_BRACKET;
            else {
                unpair_open_down_to(p);
                if (!open[--top].near) br[open[top].at] = br[i] = FRIBIDI_NO_BRACKET;
            }
        }
    }
    unpair_open_down_to(0);
#undef unpair_open_down_to
}

// Resolves the paragraph rows[0..num_rows) from base into levels[r * cols + x], after UAX #9 L1 per row. A scaled cell, and each
// cell of fixed[r] when fixed is not NULL, is a segment separator at BIDI_LEVEL_FIXED. Returns false, leaving levels unwritten,
// when every level is 0.
static bool
bidi_resolve_paragraph(
    BidiScratch *s,
    const CPUCell *const *rows,
    unsigned num_rows,
    index_type cols,
    const TextCache *tc,
    FriBidiParType base,
    const BidiFixedColumns *fixed,
    uint8_t *levels) {
    ensure_space_for(s, row_start, uint32_t, num_rows + 1, row_start_cap, num_rows + 1, false);
    uint32_t n = 0;
    for (unsigned r = 0; r < num_rows; r++) {
        // A cell feeds one char plus at most one for each char after its first, a scaled or fixed cell one char per column
        const size_t cap = n + (size_t)cols * MAX_NUM_CODEPOINTS_PER_CELL;
        ensure_space_for(s, text, FriBidiChar, cap, text_cap, cap, false);
        ensure_space_for(s, cell_of_char, uint32_t, cap, cell_of_char_cap, cap, false);
        s->row_start[r] = n;
        n = feed_row(s, rows[r], cols, tc, fixed ? fixed + r : NULL, n);
    }
    s->row_start[num_rows] = n;
    s->peak = MAX(s->peak, (size_t)n);
    ensure_space_for(s, types, FriBidiCharType, n, types_cap, n, false);
    ensure_space_for(s, brackets, FriBidiBracketType, n, brackets_cap, n, false);
    ensure_space_for(s, levels, FriBidiLevel, n, levels_cap, n, false);
    // FriBidi 1.0.17 and 1.0.18 as released carry the character data of Unicode 14, so later code points, such as newer emoji,
    // come back as L. Up to 1.0.16 an FSI with no letter takes the direction of a letter in a later isolate, and up to 1.0.17 a
    // bracket pair at the start of an isolate takes its direction from a letter in an earlier isolate at the same depth.
    fribidi_get_bidi_types(s->text, (FriBidiStrIndex)n, s->types);
    retype_controls(s, n);
    fribidi_get_bracket_types(s->text, (FriBidiStrIndex)n, s->types, s->brackets);
    limit_bracket_pairs(s, n);
    FriBidiParType dir = base;
    // Returns the highest level plus one, 0 on failure; 1 means every level is 0, so nothing to reorder, though a scaled cell
    // still needs its level to be shaped at
    const FriBidiLevel max_level = fribidi_get_par_embedding_levels_ex(s->types, s->brackets, (FriBidiStrIndex)n, &dir, s->levels);
    if (!max_level) return false;
    if (max_level == 1) {
        bool fixed = false;
        for (uint32_t i = 0; i < n && !fixed; i++) fixed = s->cell_of_char[i] & BIDI_FIXED_CELL;
        if (!fixed) return false;
    }
    const FriBidiLevel base_level = FRIBIDI_DIR_TO_LEVEL(dir);
    for (unsigned r = 0; r < num_rows; r++) {
        const uint32_t row_first = s->row_start[r], row_end = s->row_start[r + 1];
        // L1 for the whitespace and isolate controls ending the row, which FriBidi resets only at the paragraph's end
        for (uint32_t i = row_end; i > row_first && (FRIBIDI_IS_EXPLICIT_OR_BN_OR_WS(s->types[i - 1]) || FRIBIDI_IS_ISOLATE(s->types[i - 1])); i--)
            s->levels[i - 1] = base_level;
        uint8_t *row = levels + (size_t)r * cols;
        index_type col = 0;
        uint8_t level = base_level;
        for (uint32_t i = row_first; i < row_end; i++) {
            const uint32_t entry = s->cell_of_char[i];
            if (entry & BIDI_EXTRA_CHAR) continue;
            for (const index_type c = entry & ~BIDI_FIXED_CELL; col < c; col++) row[col] = level;
            level = entry & BIDI_FIXED_CELL ? BIDI_LEVEL_FIXED : (uint8_t)s->levels[i];
        }
        for (; col < cols; col++) row[col] = level;
    }
    return true;
}

// Puts in v2l[v] the logical cell shown at visual column v of a row with these levels (UAX #9 L2), BIDI_LEVEL_FIXED counting
// as 0. Returns false for the identity.
static bool
bidi_visual_order(const uint8_t *levels, index_type cols, uint16_t *v2l) {
#define level_at(x) ((uint8_t)(levels[x] & (BIDI_LEVEL_FIXED - 1)))
    uint8_t max_level = 0, min_level = UINT8_MAX;
    for (index_type x = 0; x < cols; x++) {
        max_level = MAX(max_level, level_at(x));
        min_level = MIN(min_level, level_at(x));
    }
    const unsigned min_odd = min_level | 1u;
    if (max_level < min_odd) return false;
    for (index_type x = 0; x < cols; x++) v2l[x] = (uint16_t)x;
    for (unsigned level = max_level; level >= min_odd; level--) {
        for (index_type x = 0; x < cols;) {
            if (level_at(x) < level) {
                x++;
                continue;
            }
            index_type end = x + 1;
            while (end < cols && level_at(end) >= level) end++;
            for (index_type a = x, b = end - 1; a < b; a++, b--) {
                const uint16_t t = v2l[a];
                v2l[a] = v2l[b];
                v2l[b] = t;
            }
            x = end;
        }
    }
#undef level_at
    for (index_type x = 0; x < cols; x++) {
        if (v2l[x] != x) return true;
    }
    return false;
}

void
bidi_copy_row_bytes(const uint16_t *v2l, index_type cols, const uint8_t *src, uint8_t *dest, size_t stride) {
    for (index_type v = 0; v < cols; v++) memcpy(dest + v * stride, src + v2l[v] * stride, stride);
}

static void
bidi_maps_free_rows(BidiMaps *b) {
    free(b->levels);
    free(b->v2l);
    free(b->active);
    free(b->has_levels);
    free(b->relevel);
    free(b->below_hash);
    free(b->below_valid);
}

void
bidi_maps_free(BidiMaps *b) {
    if (!b) return;
    bidi_scratch_free(&b->scratch);
    bidi_maps_free_rows(b);
    free(b->row_levels);
    free(b->row_v2l);
    free(b->para_levels);
    free(b->para_rows);
    free(b->para_fixed);
    free(b);
}

void
bidi_maps_invalidate_row_hashes(Screen *self) {
    BidiMaps *b = self->bidi_maps;
    if (b && b->below_valid) memset(b->below_valid, 0, b->rows * sizeof(b->below_valid[0]));
}

// NULL for a screen wider than v2l can index, shown in logical order
BidiMaps *
bidi_maps_for_upload(Screen *self, const LineBuf *source, index_type rows) {
    if (self->columns > UINT16_MAX + 1u) return NULL;
    if (!self->bidi_maps && !(self->bidi_maps = calloc(1, sizeof(BidiMaps)))) fatal("Out of memory allocating bidi maps");
    BidiMaps *b = self->bidi_maps;
    const index_type cols = self->columns;
    if (b->rows != rows || b->cols != cols) {
        const size_t cells = (size_t)rows * cols;
        bidi_maps_free_rows(b);
        b->levels = calloc(cells, sizeof(b->levels[0]));
        b->v2l = malloc(cells * sizeof(b->v2l[0]));
        b->active = calloc(rows, sizeof(b->active[0]));
        b->has_levels = calloc(rows, sizeof(b->has_levels[0]));
        b->relevel = calloc(rows, sizeof(b->relevel[0]));
        b->below_hash = malloc(rows * sizeof(b->below_hash[0]));
        b->below_valid = calloc(rows, sizeof(b->below_valid[0]));
        if (!b->levels || !b->v2l || !b->active || !b->has_levels || !b->relevel || !b->below_hash || !b->below_valid)
            fatal("Out of memory allocating bidi maps");
        b->rows = rows;
        b->cols = cols;
        b->changed = true;
        b->reusable = false;
    }
    ensure_space_for(b, row_levels, uint8_t, cols, row_levels_cap, cols, false);
    ensure_space_for(b, row_v2l, uint16_t, cols, row_v2l_cap, cols, false);
    if (b->source != source) b->reusable = false;
    b->source = source;
    return b;
}

// y < 0 is history line -(y + 1)
typedef struct BidiRows {
    Screen *screen;
    int lowest, end; // the rows that exist: [lowest, end)
    int top;         // the row shown in render row 0
    int pushed;      // the history rows y >= pushed were pushed since the last walk of a view of history rows only
} BidiRows;

static const CPUCell *
bidi_row_cells(const BidiRows *src, int y) {
    return y < 0 ? historybuf_cpu_cells(src->screen->historybuf, -(y + 1)) : linebuf_cpu_cells_for_line(src->screen->linebuf, y);
}

static LineAttrs *
bidi_row_attrs(const BidiRows *src, int y) {
    return y < 0 ? historybuf_attrs(src->screen->historybuf, -(y + 1)) : src->screen->linebuf->line_attrs + y;
}

// Whether row y has a record, see line_has_bidi_record()
static bool
bidi_row_has_record(const BidiRows *src, int y, index_type cols) {
    LineAttrs *a = bidi_row_attrs(src, y);
    if (a->bidi_stamp == BIDI_STAMP_NONE) return false;
    Line line = {.xnum = cols};
    if (y < 0) historybuf_init_line(src->screen->historybuf, -(y + 1), &line);
    else linebuf_init_line_at(src->screen->linebuf, y, &line);
    return line_has_bidi_record(a, &line);
}

// A history row has its render cells only in the history render cache, which holds the rows on view, so y must be on view or a
// linebuf row
static const RenderCell *
bidi_row_render_cells(const BidiRows *src, int y) {
    Line line;
    if (y < 0) historybuf_init_line_for_render(src->screen->historybuf, -(y + 1), &line, render_lines_for_screen(src->screen));
    else linebuf_init_line_at(src->screen->linebuf, y, &line);
    return line.render_cells;
}

static bool
bidi_levels_differ(const RenderCell *rc, const uint8_t *levels, index_type cols) {
    for (index_type x = 0; x < cols; x++) {
        if (rc[x].level != levels[x]) return true;
    }
    return false;
}

// Puts in v2l the visual order of render row r with these levels. The edges of the regions narrower than the screen on its screen
// row split it into spans, each ordered on its own. Returns false for the identity.
static bool
bidi_row_order(const BidiMaps *b, index_type r, const uint8_t *levels, uint16_t *v2l) {
    const Screen *screen = b->walk->screen;
    const int y = b->walk->top + (int)r;
    index_type edges[2 * MAX_SMOOTH_SCROLL_REGIONS];
    const unsigned n = y >= 0 && screen->smooth_scroll.count ? screen_bidi_span_edges(screen, y, edges) : 0;
    if (!n) return bidi_visual_order(levels, b->cols, v2l);
    bool any = false;
    for (unsigned i = 0, start = 0; i <= n; i++) {
        const index_type end = i < n ? edges[i] : b->cols;
        if (bidi_visual_order(levels + start, end - start, v2l + start)) {
            for (index_type x = start; x < end; x++) v2l[x] += start;
            any = true;
        } else {
            for (index_type x = start; x < end; x++) v2l[x] = x;
        }
        start = end;
    }
    return any;
}

static void
bidi_set_row_levels(BidiMaps *b, index_type r, const uint8_t *levels) {
    const index_type cols = b->cols;
    uint8_t *dest = b->levels + (size_t)r * cols;
    if (!b->edges_changed && !memcmp(dest, levels, cols)) return;
    memcpy(dest, levels, cols);
    bool any = false;
    for (index_type x = 0; x < cols && !any; x++) any = dest[x] != 0;
    b->has_levels[r] = any;
    b->active[r] = any && bidi_row_order(b, r, dest, b->v2l + (size_t)r * cols);
    b->changed = true;
}

// What bidi_set_row_levels() does for a row of zero levels, which is in logical order whatever the edges
static void
bidi_set_row_no_levels(BidiMaps *b, index_type r) {
    if (!b->has_levels[r]) return;
    memset(b->levels + (size_t)r * b->cols, 0, b->cols);
    b->has_levels[r] = b->active[r] = false;
    b->changed = true;
}

void
bidi_maps_edges_changed(BidiMaps *b) {
    b->edges_changed = true;
}

static FriBidiParType
bidi_record_base(LineAttrs a) {
    return a.bidi_auto ? (a.bidi_rtl ? FRIBIDI_PAR_WRTL : FRIBIDI_PAR_WLTR) : (a.bidi_rtl ? FRIBIDI_PAR_RTL : FRIBIDI_PAR_LTR);
}

static uint64_t
bidi_row_hash(const BidiRows *src, int y, index_type cols) {
    const LineAttrs a = *bidi_row_attrs(src, y);
    // Without bidi_may_reorder, which follows from the cells
    const uint64_t seed = (a.bidi_stamp != BIDI_STAMP_NONE) | a.bidi_rtl << 1 | a.bidi_auto << 2;
    return XXH3_64bits_withSeed(bidi_row_cells(src, y), cols * sizeof(CPUCell), seed);
}

static bool
bidi_row_changed(const BidiMaps *b, const BidiRows *src, int y, int end) {
    if (!bidi_row_attrs(src, y)->has_dirty_text) return false;
    if (y < end) return true;
    if (y < 0) return y >= src->pushed;
    return !b->below_valid[y] || bidi_row_hash(src, y, b->cols) != b->below_hash[y];
}

// Whether a row of [first, last] holds an image placeholder. The line flag is set when one is written and outlives it.
static bool
bidi_rows_hold_placeholder(const BidiRows *src, int first, int last, const CPUCell *const *rows, index_type cols, const TextCache *tc) {
    for (int y = first; y <= last; y++) {
        if (!bidi_row_attrs(src, y)->has_image_placeholders) continue;
        for (index_type x = 0; x < cols; x++) {
            if (cell_first_char(rows[y - first] + x, tc) == IMAGE_PLACEHOLDER_CHAR) return true;
        }
    }
    return false;
}

// The fixed columns and span edges of each row of [first, last], NULL when no row has any
static const BidiFixedColumns *
bidi_paragraph_fixed_columns(BidiMaps *b, const BidiRows *src, int first, int last) {
    const unsigned num_rows = last - first + 1;
    ensure_space_for(b, para_fixed, BidiFixedColumns, num_rows, para_fixed_cap, num_rows, false);
    bool any = false;
    for (int y = first; y <= last; y++) {
        BidiFixedColumns *f = b->para_fixed + (y - first);
        if (y >= 0) screen_bidi_fixed_columns(src->screen, y, f);
        else f->count = f->num_edges = 0;
        any |= f->count || f->num_edges;
    }
    return any ? b->para_fixed : NULL;
}

// Puts in b->para_levels the levels of the paragraph [first, last] laid out from its text and records
static void
bidi_resolve_rows(BidiMaps *b, const BidiRows *src, int first, int last) {
    const index_type cols = src->screen->columns;
    const TextCache *tc = src->screen->text_cache;
    const unsigned num_rows = last - first + 1;
    const size_t num_cells = (size_t)num_rows * cols;
    ensure_space_for(b, para_rows, const CPUCell *, num_rows, para_rows_cap, num_rows, false);
    ensure_space_for(b, para_levels, uint8_t, num_cells, para_levels_cap, num_cells, false);
    bool rtl = false;
    // The base comes from the first row with a record. A row without one may hold the direction a leading mark set for its
    // first text written in bidi mode.
    LineAttrs lead = {0};
    for (int y = first; y <= last; y++) {
        LineAttrs *a = bidi_row_attrs(src, y);
        const CPUCell *cells = bidi_row_cells(src, y);
        b->para_rows[y - first] = cells;
        // A row left without text while no walk ran, under force_ltr, is clean and may still hold its record. The record test
        // comes first: it drops a record left on a row without text, which the reads below must not see.
        bidi_row_has_record(src, y, cols);
        // A row whose right-to-left text was overwritten drops its bit
        if (a->bidi_may_reorder && a->has_dirty_text) a->bidi_may_reorder = bidi_cells_may_reorder(cells, cols, tc);
        rtl |= a->bidi_may_reorder;
        if (lead.bidi_stamp == BIDI_STAMP_NONE) lead = *a;
    }
    if (lead.bidi_stamp == BIDI_STAMP_NONE) lead.bidi_rtl = lead.bidi_auto = false;
    if (lead.bidi_stamp == BIDI_STAMP_NONE || !(rtl || lead.bidi_rtl)) memset(b->para_levels, 0, num_cells);
    else if (bidi_rows_hold_placeholder(src, first, last, b->para_rows, cols, tc)) {
        // Not laid out, its text shaped as with bidi mode off, in the direction guessed from it: at BIDI_LEVEL_FIXED on a row
        // with a record, without levels on the others
        for (int y = first; y <= last; y++) {
            const bool recorded = bidi_row_attrs(src, y)->bidi_stamp != BIDI_STAMP_NONE;
            memset(b->para_levels + (size_t)(y - first) * cols, recorded ? BIDI_LEVEL_FIXED : 0, cols);
        }
    } else {
        const BidiFixedColumns *fixed = src->screen->smooth_scroll.count ? bidi_paragraph_fixed_columns(b, src, first, last) : NULL;
        if (!bidi_resolve_paragraph(&b->scratch, b->para_rows, num_rows, cols, tc, bidi_record_base(lead), fixed, b->para_levels))
            memset(b->para_levels, 0, num_cells);
    }
}

// Sets the levels of the rows on view of the paragraph [first, last]. Clean rows, and the row above the first one for its soft
// wrap, keep the levels they were rendered at; otherwise the paragraph is resolved again, as a dirty row's stored levels are
// stale, and so are those of a paragraph cut by a window edge that moved. Rows above the view are not checked: a push leaves
// them dirty and an edit before it dirtied the row below. Nor are history rows below the view pushed before the last walk of a
// view of history rows only, which evicted the others from the history render cache, nor screen rows below the view unchanged
// since the last shown resolve read them.
static void
bidi_map_paragraph(BidiMaps *b, const BidiRows *src, int first, int last, bool cut_by_moved_edge, bool shown, bool reuse) {
    const index_type cols = b->cols;
    const int top = src->top, end = top + (int)b->rows;
    bool dirty = cut_by_moved_edge;
    for (int y = MAX(first > src->lowest ? first - 1 : first, top); y <= last && !dirty; y++) dirty = bidi_row_changed(b, src, y, end);
    // The maps of its rows on view are those the last walk left, for the same rows and text
    if (!dirty && reuse) {
        for (int y = MAX(first, top); y <= last && y < end; y++) b->relevel[y - top] = false;
        return;
    }
    // Without a stamp the paragraph has no levels, and the bits of its rows may be stale. With one but no row holding a cell
    // that may reorder, nor a right-to-left base, its levels are zero too.
    bool stamped = false, reorders = false;
    for (int y = first; y <= last; y++) {
        const LineAttrs a = *bidi_row_attrs(src, y);
        stamped |= a.bidi_stamp != BIDI_STAMP_NONE;
        reorders |= a.bidi_may_reorder || (a.bidi_stamp != BIDI_STAMP_NONE && a.bidi_rtl);
    }
    reorders &= stamped;
#ifdef DEBUG
    for (int y = first; stamped && !reorders && y <= last; y++) {
        if (bidi_cells_may_reorder(bidi_row_cells(src, y), cols, src->screen->text_cache))
            fatal("bidi: row %d of a paragraph without bidi_may_reorder holds a cell that may reorder", y);
    }
#endif
    if (!dirty) {
        // Its stored levels came from the same text, so they are zero too
        if (!reorders) {
            for (int y = MAX(first, top); y <= last && y < end; y++) {
                bidi_set_row_no_levels(b, y - top);
                b->relevel[y - top] = false;
            }
            return;
        }
        for (int y = MAX(first, top); y <= last && y < end; y++) {
            const RenderCell *rc = bidi_row_render_cells(src, y);
            for (index_type x = 0; x < cols; x++) b->row_levels[x] = rc[x].level;
            bidi_set_row_levels(b, y - top, b->row_levels);
            b->relevel[y - top] = false;
        }
        return;
    }
    b->resolved++;
    if (reorders) bidi_resolve_rows(b, src, first, last);
    else {
        const size_t num_cells = (size_t)(last - first + 1) * cols;
        ensure_space_for(b, para_levels, uint8_t, num_cells, para_levels_cap, num_cells, false);
        memset(b->para_levels, 0, num_cells);
    }
    for (int y = first; y <= last; y++) {
        const uint8_t *levels = b->para_levels + (size_t)(y - first) * cols;
        if (top <= y && y < end) {
            b->relevel[y - top] = bidi_levels_differ(bidi_row_render_cells(src, y), levels, cols);
            bidi_set_row_levels(b, y - top, levels);
        } else if (!bidi_row_attrs(src, y)->has_dirty_text) {
            // A history row off view has its stored levels in the history render cache, if anywhere
            if (y < 0) historybuf_mark_line_dirty(src->screen->historybuf, -(y + 1));
            else if (bidi_levels_differ(bidi_row_render_cells(src, y), levels, cols)) linebuf_mark_line_dirty(src->screen->linebuf, y);
        }
    }
    if (!shown) return;
    for (int y = MAX(first, MAX(end, 0)); y <= last; y++) {
        b->below_hash[y] = bidi_row_hash(src, y, cols);
        b->below_valid[y] = true;
    }
}

// The window [lo, hi) a paragraph of the rows on view, [src->top, end), is resolved over: those rows and a screen height above
// and below them, so a longer one is laid out from its part in the window
static void
bidi_window(const BidiRows *src, int end, int *lo, int *hi) {
    const int margin = (int)src->screen->lines;
    *lo = MAX(src->lowest, src->top - margin);
    *hi = MIN(src->end, end + margin);
}

// The paragraph [first, last] of row y within the window [lo, hi)
static void
bidi_paragraph_of(const BidiRows *src, int y, int lo, int hi, int *first, int *last) {
    int f = y, l = y;
    while (f > lo && range_line_is_continued(src->screen, f)) f--;
    while (l + 1 < hi && range_line_is_continued(src->screen, l + 1)) l++;
    *first = f;
    *last = l;
}

// Whether a row of [first, last) has text not rendered yet
static bool
bidi_rows_dirty(const BidiRows *src, int first, int last) {
    int y = first;
    for (; y < MIN(last, 0); y++) {
        if (bidi_row_attrs(src, y)->has_dirty_text) return true;
    }
    const LineAttrs *a = src->screen->linebuf->line_attrs;
    for (; y < last; y++) {
        if (a[y].has_dirty_text) return true;
    }
    return false;
}

// Sets the levels of every render row, each paragraph bounded by bidi_window(). A walk not shown leaves the window of the last
// shown one, which the rendered levels are for. With reuse, the walk the maps are from showed the same rows, which cannot have
// moved, so only the dirty paragraphs are mapped again.
static void
bidi_map_rows(BidiMaps *b, const BidiRows *src, bool shown, bool reuse) {
    const int top = src->top, end = top + (int)b->rows;
    int lo, hi;
    bidi_window(src, end, &lo, &hi);
    const int64_t origin = (int64_t)src->screen->historybuf->num_pushed;
    const bool lo_moved = !reuse && origin + lo != b->window_lo, hi_moved = !reuse && origin + hi != b->window_hi;
    if (shown) {
        b->window_lo = origin + lo;
        b->window_hi = origin + hi;
    }
    b->resolved = 0;
    b->walk = src;
    // The order of a row depends on the edges of the regions on the screen row it shows, and a memo kept for a render row on
    // the levels alone would keep the spans of the row shown there before
    if (top != b->walk_top && src->screen->smooth_scroll.count) b->edges_changed = true;
    b->walk_top = top;
    if (!reuse) {
        // A row on view is read and rendered without its hash being kept
        const int on_view = src->screen->linebuf == b->below_source ? MIN(end, src->end) : src->end;
        if (on_view > 0) memset(b->below_valid, 0, on_view * sizeof(b->below_valid[0]));
        b->below_source = src->screen->linebuf;
        memset(b->row_levels, 0, b->cols);
        for (int y = top; y < end; y++) {
            if (src->lowest <= y && y < src->end) continue;
            bidi_set_row_levels(b, y - top, b->row_levels);
            b->relevel[y - top] = false;
        }
    }
    // No paragraph of the rows on view can have a dirty row: rows above the view are not checked, and the rows below it in the
    // window are those down to hi
    if (reuse && !bidi_rows_dirty(src, MAX(top, src->lowest), hi)) {
        memset(b->relevel, 0, b->rows * sizeof(b->relevel[0]));
    } else {
        for (int y = MAX(top, src->lowest); y < MIN(end, src->end);) {
            int first, last;
            bidi_paragraph_of(src, y, lo, hi, &first, &last);
            const bool cut = (lo_moved && first == lo && range_line_is_continued(src->screen, first)) ||
                             (hi_moved && last + 1 == hi && range_line_is_continued(src->screen, hi));
            bidi_map_paragraph(b, src, first, last, cut, shown, reuse);
            y = last + 1;
        }
    }
    // A dirty row's soft wrap can change the paragraph of the row below it, which is checked only once shown
    const int below = MIN(end, src->end);
    if (below < src->end && bidi_row_attrs(src, below - 1)->has_dirty_text) {
        if (below < 0) historybuf_mark_line_dirty(src->screen->historybuf, -(below + 1));
        else linebuf_mark_line_dirty(src->screen->linebuf, below);
    }
    bidi_scratch_trim(&b->scratch);
    b->walk = NULL;
    b->edges_changed = false;
    b->valid = true;
}

// The state of the maps a walk reads or writes
typedef struct BidiMapsSnapshot {
    uint8_t *levels;
    uint16_t *v2l;
    bool *active, *has_levels, *relevel, *below_valid;
    uint64_t *below_hash;
    int64_t window_lo, window_hi;
    int walk_top;
    const LineBuf *below_source;
    unsigned resolved;
    bool valid, changed, edges_changed;
} BidiMapsSnapshot;

static void *
bidi_copy(const void *src, size_t sz) {
    void *ans = malloc(sz);
    if (!ans) fatal("Out of memory copying bidi maps");
    return memcpy(ans, src, sz);
}

static void
bidi_maps_snapshot(const BidiMaps *b, BidiMapsSnapshot *s) {
    const size_t rows = b->rows, cells = rows * b->cols;
    *s = (BidiMapsSnapshot){
        .levels = bidi_copy(b->levels, cells * sizeof(b->levels[0])),
        .v2l = bidi_copy(b->v2l, cells * sizeof(b->v2l[0])),
        .active = bidi_copy(b->active, rows * sizeof(b->active[0])),
        .has_levels = bidi_copy(b->has_levels, rows * sizeof(b->has_levels[0])),
        .relevel = bidi_copy(b->relevel, rows * sizeof(b->relevel[0])),
        .below_valid = bidi_copy(b->below_valid, rows * sizeof(b->below_valid[0])),
        .below_hash = bidi_copy(b->below_hash, rows * sizeof(b->below_hash[0])),
        .window_lo = b->window_lo,
        .window_hi = b->window_hi,
        .walk_top = b->walk_top,
        .below_source = b->below_source,
        .resolved = b->resolved,
        .valid = b->valid,
        .changed = b->changed,
        .edges_changed = b->edges_changed};
}

static void
bidi_maps_restore(BidiMaps *b, const BidiMapsSnapshot *s) {
    const size_t rows = b->rows, cells = rows * b->cols;
    memcpy(b->levels, s->levels, cells * sizeof(b->levels[0]));
    memcpy(b->v2l, s->v2l, cells * sizeof(b->v2l[0]));
    memcpy(b->active, s->active, rows * sizeof(b->active[0]));
    memcpy(b->has_levels, s->has_levels, rows * sizeof(b->has_levels[0]));
    memcpy(b->relevel, s->relevel, rows * sizeof(b->relevel[0]));
    memcpy(b->below_valid, s->below_valid, rows * sizeof(b->below_valid[0]));
    memcpy(b->below_hash, s->below_hash, rows * sizeof(b->below_hash[0]));
    b->window_lo = s->window_lo;
    b->window_hi = s->window_hi;
    b->walk_top = s->walk_top;
    b->below_source = s->below_source;
    b->resolved = s->resolved;
    b->valid = s->valid;
    b->changed = s->changed;
    b->edges_changed = s->edges_changed;
}

static void
bidi_maps_snapshot_free(BidiMapsSnapshot *s) {
    free(s->levels);
    free(s->v2l);
    free(s->active);
    free(s->has_levels);
    free(s->relevel);
    free(s->below_valid);
    free(s->below_hash);
}

static bool
bidi_maps_match(const BidiMaps *b, const BidiMapsSnapshot *s, bool with_relevel) {
    const size_t rows = b->rows, cols = b->cols;
    if (memcmp(b->levels, s->levels, rows * cols) || memcmp(b->active, s->active, rows * sizeof(b->active[0])) ||
        memcmp(b->has_levels, s->has_levels, rows * sizeof(b->has_levels[0])))
        return false;
    if (with_relevel && memcmp(b->relevel, s->relevel, rows * sizeof(b->relevel[0]))) return false;
    for (size_t r = 0; r < rows; r++) {
        if (b->active[r] && memcmp(b->v2l + r * cols, s->v2l + r * cols, cols * sizeof(b->v2l[0]))) return false;
    }
    return true;
}

// Whether a full walk from the state before, the current one when NULL, leaves the maps the walk that ran left. The maps are left
// as that walk left them. A full walk run again marks dirty only rows of the paragraphs that walk resolved, which it marked.
static bool
bidi_walk_matches(BidiMaps *b, const BidiRows *src, bool shown, const BidiMapsSnapshot *before, bool with_relevel) {
    BidiMapsSnapshot after;
    bidi_maps_snapshot(b, &after);
    if (before) bidi_maps_restore(b, before);
    bidi_map_rows(b, src, shown, false);
    const bool ans = bidi_maps_match(b, &after, with_relevel);
    bidi_maps_restore(b, &after);
    bidi_maps_snapshot_free(&after);
    return ans;
}

static BidiRows
bidi_live_rows(Screen *self) {
    const HistoryBuf *hb = self->historybuf;
    return (BidiRows){
        .screen = self,
        .lowest = -(int)hb->count,
        .end = (int)self->lines,
        .top = -(int)(self->scrolled_by + pixel_scroll_enabled(self)),
        .pushed = -(int)MIN(hb->num_pushed - hb->bidi_walked, (uint64_t)hb->count)};
}

static bool
bidi_walk_reusable(const BidiMaps *b, const BidiRows *src) {
    const HistoryBuf *hb = src->screen->historybuf;
    return b->reusable && b->walk_generation == src->screen->bidi_layout_generation && b->walk_top == src->top && b->walk_pushed == hb->num_pushed &&
           b->walk_count == hb->count && !b->edges_changed;
}

bool
bidi_walk_matches_full(Screen *self) {
    BidiMaps *b = self->bidi_maps;
    if (!b || !b->reusable || b->rows != render_lines_for_screen(self)) return true;
    const BidiRows src = bidi_live_rows(self);
    return !bidi_walk_reusable(b, &src) || bidi_walk_matches(b, &src, true, NULL, false);
}

// Levels left in the render cells would be trusted if the buffer were stamped again, so its rows holding any are rendered again
static void
bidi_unstamp(LineBuf *lb) {
    lb->bidi_stamped = false;
    Line line;
    for (index_type y = 0; y < lb->ynum; y++) {
        linebuf_init_line_at(lb, y, &line);
        bool any = false;
        for (index_type x = 0; x < lb->xnum; x++) {
            any |= line.render_cells[x].level != 0;
            line.render_cells[x].level = 0;
        }
        if (any) linebuf_mark_line_dirty(lb, y);
    }
}

bool
bidi_live_frame_reorders_unstamped(const Screen *self) {
    // A row drawn only in the strip of a region, kept or in the scrollback, may hold the only record
    if (self->smooth_scroll.count && (bidi_kept_rows_stamped(self) || screen_bidi_strip_shows_recorded_history(self))) return true;
    if (self->scrolled_by) return self->historybuf->bidi_stamped || self->main_linebuf->bidi_stamped;
    return pixel_scroll_enabled(self) && self->historybuf->bidi_stamped && bidi_history_line0_recorded(self);
}

// NULL for a frame shown in logical order. The buffer drops its flag once none of its rows has a record or a leading mark's
// direction, unless the main one continues a history line while the history holds a record. A frame not shown (paused) does
// not mark its rows on view as rendered with the history rows below them.
BidiMaps *
bidi_prepare_live(Screen *self, bool shown) {
    if (OPT(force_ltr)) return NULL;
    LineBuf *lb = self->linebuf;
    HistoryBuf *hb = self->historybuf;
    if (UNLIKELY(self->bidi_history_bits_stale)) screen_bidi_recompute_history_may_reorder(self);
    if (lb->bidi_stamped && lb->bidi_maybe_unstamp && !(lb == self->main_linebuf && hb->bidi_stamped && hb->count && history_buf_endswith_wrap(hb))) {
        lb->bidi_maybe_unstamp = false;
        bool stamped = bidi_kept_rows_stamped(self);
        Line line;
        for (index_type y = 0; y < lb->ynum && !stamped; y++) {
            LineAttrs *a = lb->line_attrs + y;
            if (a->bidi_stamp == BIDI_STAMP_NONE) stamped = line_has_bidi_bits(*a);
            else {
                linebuf_init_line_at(lb, y, &line);
                stamped = line_has_bidi_record(a, &line);
            }
        }
        if (!stamped) {
            bidi_unstamp(lb);
            screen_bidi_records_writes_changed(self);
        }
    }
    // The history is the main screen's, shown above the alternate screen too when scrolled back
    if (!bidi_live_frame_reorders(self)) return NULL;
    const index_type rows = render_lines_for_screen(self);
    BidiMaps *b = bidi_maps_for_upload(self, lb, rows);
    if (!b) return NULL;
    // History rows rendered without the walk hold stale levels, which it would trust
    if (!b->live) historybuf_invalidate_render_cache(hb);
    b->live = true;
    const BidiRows src = bidi_live_rows(self);
    Line line;
    for (int y = MAX(src.top, src.lowest); y < MIN(src.top + (int)rows, 0); y++) {
        if (historybuf_init_line_for_render(hb, -(y + 1), &line, rows)) historybuf_mark_line_dirty(hb, -(y + 1));
    }
    const bool reuse = bidi_walk_reusable(b, &src);
#ifdef DEBUG
    BidiMapsSnapshot before;
    if (reuse) bidi_maps_snapshot(b, &before);
#endif
    bidi_map_rows(b, &src, shown, reuse);
#ifdef DEBUG
    if (reuse) {
        if (!bidi_walk_matches(b, &src, shown, &before, true)) fatal("bidi: the maps of a walk reusing them differ from a full walk");
        bidi_maps_snapshot_free(&before);
    }
#endif
    b->last_walk_reused = reuse;
    b->mapped = memchr(b->has_levels, true, rows) || memchr(b->relevel, true, rows);
    b->reusable = shown;
    b->walk_generation = self->bidi_layout_generation;
    b->walk_pushed = hb->num_pushed;
    b->walk_count = hb->count;
    if (shown && src.top >= src.lowest && src.top + (int)rows <= 0) hb->bidi_walked = hb->num_pushed;
    return b;
}

void
bidi_store_levels(const BidiMaps *b, index_type r, Line *line) {
    const uint8_t *levels = b->levels + (size_t)r * b->cols;
    for (index_type x = 0; x < b->cols; x++) line->render_cells[x].level = levels[x];
}

const uint16_t *
bidi_span_order(BidiMaps *b, const RenderCell *rc, index_type n) {
    for (index_type x = 0; x < n; x++) b->row_levels[x] = rc[x].level;
    return bidi_visual_order(b->row_levels, n, b->row_v2l) ? b->row_v2l : NULL;
}

const uint8_t *
bidi_strip_line_levels(BidiMaps *b, Line *line, bool fixed) {
    uint8_t *levels = b->row_levels;
    if (fixed) {
        if (!line_has_bidi_record(&line->attrs, line)) return NULL;
        memset(levels, BIDI_LEVEL_FIXED, line->xnum);
        return levels;
    }
    bool any = false;
    for (index_type x = 0; x < line->xnum; x++) any |= (levels[x] = line->render_cells[x].level) != 0;
    return any ? levels : NULL;
}

// The paragraph of row y is bounded by bidi_window() and its rows checked as in bidi_map_paragraph(), but by dirty text
// alone: no walk keeps a window edge that moved or the hash of a row below the view here.
void __attribute__((noinline, cold))
bidi_store_kept_row_levels(Screen *self, index_type y, index_type left, index_type width, RenderCell *rc) {
    if (UNLIKELY(self->bidi_history_bits_stale)) screen_bidi_recompute_history_may_reorder(self);
    const int top = -(int)(self->scrolled_by + pixel_scroll_enabled(self));
    const BidiRows src = {.screen = self, .lowest = -(int)self->historybuf->count, .end = (int)self->lines, .top = top};
    int lo, hi, first, last;
    bidi_window(&src, top + (int)render_lines_for_screen(self), &lo, &hi);
    bidi_paragraph_of(&src, (int)y, lo, hi, &first, &last);
    bool dirty = false;
    for (int r = MAX(first > src.lowest ? first - 1 : first, top); r <= last && !dirty; r++) dirty = bidi_row_attrs(&src, r)->has_dirty_text;
    if (!dirty) return;
    if (!self->bidi_maps && !(self->bidi_maps = calloc(1, sizeof(BidiMaps)))) fatal("Out of memory allocating bidi maps");
    BidiMaps *b = self->bidi_maps;
    bidi_resolve_rows(b, &src, first, last);
    const uint8_t *levels = b->para_levels + (size_t)((int)y - first) * self->columns + left;
    for (index_type x = 0; x < width; x++) rc[x].level = levels[x];
}

void
bidi_store_line_levels(Line *line, const uint8_t *levels) {
    for (index_type x = 0; x < line->xnum; x++) line->render_cells[x].level = levels ? levels[x] : 0;
}

index_type
bidi_visual_x(const BidiMaps *b, index_type r, index_type x, index_type span) {
    if (r >= b->rows || x >= b->cols || !b->active[r]) return x;
    const uint16_t *v2l = b->v2l + (size_t)r * b->cols;
    const index_type end = x + MAX(span, 1u);
    for (index_type v = 0; v < b->cols; v++) {
        if (x <= v2l[v] && v2l[v] < end) return v;
    }
    return x;
}

index_type
bidi_logical_x(const BidiMaps *b, index_type r, index_type visual_x) {
    if (r >= b->rows || visual_x >= b->cols || !b->active[r]) return visual_x;
    return b->v2l[(size_t)r * b->cols + visual_x];
}

bool
bidi_cell_is_rtl(const BidiMaps *b, index_type r, index_type x) {
    return r < b->rows && x < b->cols && (b->levels[(size_t)r * b->cols + x] & 1);
}

// Blank the cell shown at visual column col of render row r if it is a half of a character whose other half is shown at the adjacent
// column inner, which the pre-edit block covers
void
bidi_blank_cut_half(const BidiMaps *b, const CPUCell *cells, index_type r, CellGPUData *row, index_type col, index_type inner) {
    const index_type l = bidi_logical_x(b, r, col), m = bidi_logical_x(b, r, inner);
    const CPUCell *c = cells + l, *d = cells + m;
    if (!c->is_multicell || !d->is_multicell || c->y != d->y || l - c->x != m - d->x) return;
    const RenderCell blank = {0};
    cells_for_gpu(c, &blank, 1, row + col);
}
