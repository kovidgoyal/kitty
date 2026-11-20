/*
 * bidi.c
 *
 * Distributed under terms of the GPL3 license.
 */

#include "bidi.h"

// Isolates fed to FriBidi as isolates per paragraph; later ones are neutrals. FriBidi's NEWS lists quadratic time in FSIs
// before 1.0.17 and in back-to-back isolates before 1.0.18.
#define BIDI_MAX_ISOLATES 32
#define BIDI_N0_MAX_WALK 32

// False for codepoints outside the blocks with right-to-left or Arabic letters
static inline bool
bidi_codepoint_may_reorder(char_type ch) {
    if (ch < 0x590) return false;
    if (ch < 0xfb1d) return ch <= 0x8ff;
    if (ch >= 0x1f000) return false;
    return ch <= 0xfdff || ch - 0xfe70 <= 0xfefe - 0xfe70 || ch - 0x10800 <= 0x10fff - 0x10800 || ch - 0x1e800 <= 0x1efff - 0x1e800;
}

void
bidi_scratch_free(BidiScratch *s) {
    free(s->text);
    free(s->types);
    free(s->brackets);
    free(s->levels);
    free(s->cell_of_char);
    free(s->row_start);
    free(s->row_bytes);
    zero_at_ptr(s);
}

void
bidi_scratch_trim(BidiScratch *s) {
    if (s->peak && s->levels_cap > MAX(8 * s->peak, (size_t)1 << 16)) bidi_scratch_free(s);
    s->peak = 0;
}

bool
bidi_cells_may_reorder(const CPUCell *cells, index_type num, const TextCache *tc) {
    for (const CPUCell *c = cells, *end = cells + num; c < end; c++) {
        char_type ch = c->ch_or_idx;
        if (c->ch_is_idx) {
            if (c->is_multicell && (c->x || c->y)) continue;
            ch = tc_first_char_at_index(tc, ch);
        }
        if (bidi_codepoint_may_reorder(ch)) return true;
    }
    return false;
}

// Appends the row's chars to s->text and returns the new length, or UINT32_MAX for a row with a cell spanning several rows,
// which cannot be reordered
static inline uint32_t
feed_row(BidiScratch *s, const CPUCell *cells, index_type cols, const TextCache *tc, uint32_t n) {
    FriBidiChar *restrict text = s->text + n, *const text_start = text;
    uint32_t *restrict cell_of_char = s->cell_of_char + n;
    for (index_type col = 0; col < cols; col++) {
        const CPUCell *c = cells + col;
        if (c->is_multicell) {
            if (c->scale > 1) return UINT32_MAX;
            if (col && c->x) continue;
        }
        const char_type ch = cell_first_char(c, tc);
        *text++ = ch ? ch : ' ';
        *cell_of_char++ = col;
    }
    return n + (uint32_t)(text - text_start);
}

// Embeddings, overrides and isolates are never honoured: a cell can start with such a control only through OSC 66, which can
// start any number of cells with one
static void
retype_controls(BidiScratch *s, uint32_t n) {
    for (uint32_t i = 0; i < n; i++) {
        if (s->types[i] & (FRIBIDI_MASK_EXPLICIT | FRIBIDI_MASK_ISOLATE)) s->types[i] = FRIBIDI_TYPE_ON;
    }
}

// FriBidi before 1.0.17 walks back from the opening bracket of every pair (N0) to the previous strong char, so a pair whose
// walk is longer than BIDI_N0_MAX_WALK chars is fed as two neutrals, as are brackets that pair with nothing
static void
limit_bracket_pairs(BidiScratch *s, uint32_t n) {
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
                open[top++].near = (int64_t)i - last_strong[depth] <= BIDI_N0_MAX_WALK;
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

bool
bidi_resolve_paragraph(
    BidiScratch *s, const CPUCell *const *rows, unsigned num_rows, index_type cols, const TextCache *tc, FriBidiParType base, uint8_t *levels) {
    ensure_space_for(s, row_start, uint32_t, num_rows + 1, row_start_cap, num_rows + 1, false);
    uint32_t n = 0;
    for (unsigned r = 0; r < num_rows; r++) {
        // A cell holding only leading controls still feeds a blank
        const size_t cap = n + (size_t)cols * (MAX_NUM_CODEPOINTS_PER_CELL + 1);
        ensure_space_for(s, text, FriBidiChar, cap, text_cap, cap, false);
        ensure_space_for(s, cell_of_char, uint32_t, cap, cell_of_char_cap, cap, false);
        s->row_start[r] = n;
        if ((n = feed_row(s, rows[r], cols, tc, n)) == UINT32_MAX) return false;
    }
    s->row_start[num_rows] = n;
    s->peak = MAX(s->peak, (size_t)n);
    ensure_space_for(s, types, FriBidiCharType, n, types_cap, n, false);
    ensure_space_for(s, brackets, FriBidiBracketType, n, brackets_cap, n, false);
    ensure_space_for(s, levels, FriBidiLevel, n, levels_cap, n, false);
    fribidi_get_bidi_types(s->text, (FriBidiStrIndex)n, s->types);
    retype_controls(s, n);
    fribidi_get_bracket_types(s->text, (FriBidiStrIndex)n, s->types, s->brackets);
    limit_bracket_pairs(s, n);
    FriBidiParType dir = base;
    // Returns the highest level plus one, 0 on failure; 1 means every level is 0, so nothing to reorder
    if (fribidi_get_par_embedding_levels_ex(s->types, s->brackets, (FriBidiStrIndex)n, &dir, s->levels) <= 1) return false;
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
            for (const index_type c = s->cell_of_char[i]; col < c; col++) row[col] = level;
            level = (uint8_t)s->levels[i];
        }
        for (; col < cols; col++) row[col] = level;
    }
    return true;
}

bool
bidi_visual_order(const uint8_t *levels, index_type cols, uint16_t *v2l) {
    uint8_t max_level = 0, min_level = UINT8_MAX;
    for (index_type x = 0; x < cols; x++) {
        max_level = MAX(max_level, levels[x]);
        min_level = MIN(min_level, levels[x]);
    }
    const unsigned min_odd = min_level | 1u;
    if (max_level < min_odd) return false;
    for (index_type x = 0; x < cols; x++) v2l[x] = (uint16_t)x;
    for (unsigned level = max_level; level >= min_odd; level--) {
        for (index_type x = 0; x < cols;) {
            if (levels[x] < level) {
                x++;
                continue;
            }
            index_type end = x + 1;
            while (end < cols && levels[end] >= level) end++;
            for (index_type a = x, b = end - 1; a < b; a++, b--) {
                const uint16_t t = v2l[a];
                v2l[a] = v2l[b];
                v2l[b] = t;
            }
            x = end;
        }
    }
    for (index_type x = 0; x < cols; x++) {
        if (v2l[x] != x) return true;
    }
    return false;
}

void
bidi_permute_row_bytes(BidiScratch *s, const uint16_t *v2l, index_type cols, uint8_t *row, size_t stride) {
    const size_t sz = (size_t)cols * stride;
    ensure_space_for(s, row_bytes, uint8_t, sz, row_bytes_cap, sz, false);
    memcpy(s->row_bytes, row, sz);
    for (index_type v = 0; v < cols; v++) memcpy(row + v * stride, s->row_bytes + v2l[v] * stride, stride);
}
