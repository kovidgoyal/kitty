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
// Flag in cell_of_char: a char that takes no column, fed in its cell's column
#define BIDI_EXTRA_CHAR (1u << 31)

// False for codepoints outside the blocks with right-to-left or Arabic letters
static inline bool
bidi_codepoint_may_reorder(char_type ch) {
    if (ch < 0x590) return false;
    if (ch < 0xfb1d) return ch <= 0x8ff;
    if (ch >= 0x1f000) return false;
    return ch <= 0xfdff || ch - 0xfe70 <= 0xfefe - 0xfe70 || ch - 0x10800 <= 0x10fff - 0x10800 || ch - 0x1e800 <= 0x1efff - 0x1e800;
}

// Keeps of a run of marks its first and last and the first of each other mark in it, each mark being a strong type of its own.
// The resolution reads of the run only its first type (P2), the types at its ends (W rules, N1, N2) and which types it holds
// (N0), never the levels of its marks. Returns the new length.
static inline unsigned
collapse_marks(char_type *run, unsigned len) {
    if (len < 3) return len;
    const char_type first = run[0], last = run[len - 1];
    unsigned n = 1;
    for (unsigned i = 1; i < len - 1; i++) {
        bool kept = run[i] == first || run[i] == last;
        for (unsigned j = 1; j < n && !kept; j++) kept = run[j] == run[i];
        if (!kept) run[n++] = run[i];
    }
    run[n++] = last;
    return n;
}

// Stores in buf the isolate controls and marks among the chars after the cell's first char, each run of marks collapsed
static inline unsigned
cell_extra_chars(const CPUCell *c, const TextCache *tc, char_type buf[MAX_NUM_CODEPOINTS_PER_CELL]) {
    if (!c->ch_is_idx || (c->is_multicell && (c->x || c->y))) return 0;
    ListOfChars lc = {.chars = buf, .capacity = MAX_NUM_CODEPOINTS_PER_CELL};
    if (!tc_chars_at_index_without_alloc(tc, c->ch_or_idx, &lc)) return 0;
    unsigned n = 0, run = 0;
    for (size_t i = 1; i < lc.count; i++) {
        const char_type ch = lc.chars[i];
        if (ch - 0x2066u <= 0x2069u - 0x2066u) {
            n = run + collapse_marks(buf + run, n - run);
            buf[n++] = ch;
            run = n;
        } else if ((ch | 1) == 0x200f || ch == 0x61c) buf[n++] = ch;
    }
    return run + collapse_marks(buf + run, n - run);
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
    char_type buf[MAX_NUM_CODEPOINTS_PER_CELL];
    for (const CPUCell *c = cells, *end = cells + num; c < end; c++) {
        char_type ch = c->ch_or_idx;
        if (c->ch_is_idx) {
            if (c->is_multicell && (c->x || c->y)) continue;
            ch = tc_first_char_at_index(tc, ch);
        }
        if (bidi_codepoint_may_reorder(ch)) return true;
        if (!c->ch_is_idx) continue;
        // Likewise an RLI, RLM or ALM after the first char
        for (unsigned i = 0, k = cell_extra_chars(c, tc, buf); i < k; i++) {
            if (buf[i] == 0x2067 || buf[i] == 0x200f || buf[i] == 0x61c) return true;
        }
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
        if (!c->ch_is_idx) continue;
        char_type buf[MAX_NUM_CODEPOINTS_PER_CELL];
        // Within the scratch: bidi_resolve_paragraph() sized it for the chars cell_extra_chars() counted in these same cells
        for (unsigned i = 0, k = cell_extra_chars(c, tc, buf); i < k; i++) {
            *text++ = buf[i];
            *cell_of_char++ = col | BIDI_EXTRA_CHAR;
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
            if (s->cell_of_char[i] & BIDI_EXTRA_CHAR) continue;
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
