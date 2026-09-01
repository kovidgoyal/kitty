/*
 * bidi.c - Bidirectional text support using FriBidi
 */

#include "bidi.h"
#include "char-props.h"
#include "text-cache.h"
#include <stdlib.h>
#include <string.h>

bool
bidi_line_needs_bidi(Line *line) {
    if (!line || line->xnum == 0) return false;
    for (index_type i = 0; i < line->xnum; i++) {
        CPUCell *c = &line->cpu_cells[i];
        if (!c->ch_and_idx) continue;
        char_type ch = 0;
        if (c->ch_is_idx) {
            if (c->is_multicell && (c->x || c->y)) continue;
            // For bidi check we need first char of cell
            // Approximate via text_cache not available here without arg,
            // fallback to checking stored char for idx case via heuristic?
            // Most Arabic cells are single codepoint stored directly or via cache
            // We'll handle cache case in bidi_compute where we have access to TextCache
            // Here we do quick check on ch_and_idx low bits
            ch = c->ch_or_idx & 0x1fffff; // approx
            // If ch_or_idx is index, we can't know char, assume may need bidi
            // To avoid false negative, treat idx cells as potentially RTL
            return true; // conservative: if any idx cell, check via full compute
        } else {
            ch = c->ch_or_idx;
        }
        // Quick RTL range check: Hebrew, Arabic, Syriac, Thaana, etc.
        if ((ch >= 0x0590 && ch <= 0x08FF) ||
            (ch >= 0xFB1D && ch <= 0xFDFF) ||
            (ch >= 0xFE70 && ch <= 0xFEFF) ||
            (ch >= 0x200F && ch <= 0x200F) || // RLM
            (ch >= 0x202B && ch <= 0x202E) || // embedding overrides
            (ch >= 0x2066 && ch <= 0x2069)) return true;
    }
    return false;
}

bool
bidi_compute(Line *line, BidiInfo *info) {
    if (!line || !info || line->xnum == 0) return false;
    memset(info, 0, sizeof(BidiInfo));
    index_type n = line->xnum;
    // Use logical base LTR for terminal (like most terminals)
    // Alternatively could use FRIBIDI_PAR_ON to auto-detect per line
    // We use LTR base so "abc عربي" renders with arabic RTL inside LTR paragraph
    info->n = n;
    info->base_dir = FRIBIDI_PAR_LTR;
    // Allocate buffers
    FriBidiChar *logical = (FriBidiChar*)calloc(n, sizeof(FriBidiChar));
    FriBidiChar *visual = (FriBidiChar*)calloc(n, sizeof(FriBidiChar));
    info->levels = (FriBidiLevel*)calloc(n, sizeof(FriBidiLevel));
    info->visual_to_logical = (FriBidiStrIndex*)calloc(n, sizeof(FriBidiStrIndex));
    info->logical_to_visual = (FriBidiStrIndex*)calloc(n, sizeof(FriBidiStrIndex));
    if (!logical || !visual || !info->levels || !info->visual_to_logical || !info->logical_to_visual) {
        free(logical); free(visual);
        free(info->levels); free(info->visual_to_logical); free(info->logical_to_visual);
        memset(info, 0, sizeof(BidiInfo));
        return false;
    }
    // Fill logical array from line cells
    // For cells with ch_is_idx we need to resolve via text_cache
    // If text_cache is NULL (should not happen), fallback to ch_or_idx
    for (index_type i = 0; i < n; i++) {
        CPUCell *c = &line->cpu_cells[i];
        char_type ch = 0;
        if (!c->ch_and_idx) {
            ch = ' '; // treat empty cells as space (neutral) for bidi
            // Actually empty cells after xlimit should be ignored, but for bidi
            // we treat them as neutral to avoid affecting paragraph
        } else if (c->ch_is_idx) {
            if (line->text_cache) {
                // Get first char of cell
                // Use tc_first_char_at_index if available, else tc_chars_at_index
                // We need to handle multicell prefix cells where x!=0 -> skip
                if (c->is_multicell && (c->x || c->y)) {
                    ch = 0; // skip continuation cells for bidi? treat as same as base
                    // But for bidi we should skip zero-width continuation?
                    // For now map them to 0xFFFC object replacement?
                    ch = ' ';
                } else {
                    ch = tc_first_char_at_index(line->text_cache, c->ch_or_idx);
                    if (!ch) ch = ' ';
                }
            } else {
                ch = ' ';
            }
        } else {
            ch = c->ch_or_idx;
            if (!ch) ch = ' ';
        }
        logical[i] = (FriBidiChar)ch;

        // For continuation multicell cells (x>0), mark as same embedding as base?
        // FriBidi will handle but we duplicate char? Better to set same as start?
        // Keep as is; multicell split handling in render_line skips continuation.
    }

    // Perform bidi reorder
    // fribidi_log2vis handles one paragraph; we treat entire line as one paragraph
    FriBidiParType base = info->base_dir;
    // fribidi may modify base_dir to resolved direction, keep copy
    FriBidiLevel max_level = fribidi_log2vis(logical, n, &base, visual, info->logical_to_visual, info->visual_to_logical, info->levels);
    // max_level is max+1, 0 on error
    if (max_level == 0 && n > 0) {
        // Error, fallback to LTR
        for (index_type i=0;i<n;i++) {
            info->logical_to_visual[i]=i;
            info->visual_to_logical[i]=i;
            info->levels[i]=0;
        }
        info->max_level = 1;
        free(logical); free(visual);
        return true;
    }
    info->max_level = max_level;
    info->base_dir = base;
    free(logical); free(visual);

    // For empty trailing cells, force visual identity to avoid stray reorder
    // Find xlimit (last non-empty)
    index_type xlimit = n;
    while (xlimit > 0 && !line->cpu_cells[xlimit-1].ch_and_idx) xlimit--;
    for (index_type i = xlimit; i < n; i++) {
        info->levels[i] = 0;
        info->logical_to_visual[i] = i;
        info->visual_to_logical[i] = i;
    }
    return true;
}

void
bidi_free(BidiInfo *info) {
    if (!info) return;
    free(info->levels);
    free(info->visual_to_logical);
    free(info->logical_to_visual);
    memset(info, 0, sizeof(BidiInfo));
}
