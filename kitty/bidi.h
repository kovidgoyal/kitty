/*
 * bidi.h - Bidirectional text support using FriBidi
 * Copyright (C) 2026 Kovid Goyal
 */

#pragma once
#include "data-types.h"
#include "line.h"
#include <fribidi.h>
#include <stdbool.h>

typedef struct {
    FriBidiLevel *levels;
    FriBidiStrIndex *visual_to_logical; // v -> l
    FriBidiStrIndex *logical_to_visual; // l -> v
    FriBidiStrIndex n;
    FriBidiLevel max_level;
    FriBidiParType base_dir;
} BidiInfo;

// Compute bidi info for a line. Returns false on failure (falls back to LTR).
// Caller must call bidi_free after use.
bool bidi_compute(Line *line, BidiInfo *info);
void bidi_free(BidiInfo *info);

// Check if bidi is needed (contains RTL characters)
bool bidi_line_needs_bidi(Line *line);

// Helper to get visual position for logical index
static inline FriBidiStrIndex bidi_logical_to_visual(BidiInfo *info, FriBidiStrIndex logical) {
    if (!info || !info->logical_to_visual || logical >= info->n) return logical;
    return info->logical_to_visual[logical];
}
static inline FriBidiStrIndex bidi_visual_to_logical(BidiInfo *info, FriBidiStrIndex visual) {
    if (!info || !info->visual_to_logical || visual >= info->n) return visual;
    return info->visual_to_logical[visual];
}
