/*
 * font-select.h
 * Copyright (C) 2026 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#pragma once

// Selection of the text fonts (and the symbol_map fonts) from the font
// specifications in kitty.conf. This is pure C code, it does not use Python,
// so that it can run in a thread while the rest of kitty starts up. The
// platform specific parts (listing fonts, matching fonts, reading font tables
// and converting the results to Python descriptors) are implemented by the
// backends in fontconfig.c and core_text.m.

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#define FS_MAX_AXES 64

typedef struct FSAxisValue {
    uint32_t tag;
    double value;
} FSAxisValue;

// A font as reported by the platform font database
typedef struct FSCandidate {
    void *handle; // FcPattern* or CTFontDescriptorRef, owned by the candidate
    char *path, *family, *style, *full_name, *postscript_name;
    int index;
    // fontconfig: FC_WEIGHT, FC_SLANT, FC_WIDTH. CoreText: the normalized traits
    double weight, slant, width;
    bool variable;                          // fontconfig: FC_VARIABLE. CoreText: has a variation dictionary
    bool monospace;                         // fontconfig: spacing is MONO or DUAL. CoreText: the monospace trait
    bool spacing_is_mono;                   // fontconfig: spacing is MONO
    bool expanded, condensed, bold, italic; // CoreText traits
    unsigned variation_count;               // CoreText: number of entries in the variation dictionary
    bool from_match;                        // fontconfig: created by FcFontMatch rather than FcFontList
    bool has_matrix;                        // fontconfig: has FC_MATRIX
    double matrix[4];
} FSCandidate;

// A candidate font specialized with variable font axis values
typedef struct FSFont {
    const FSCandidate *base;
    int named_style; // fontconfig: index of named style or -1
    // fontconfig: the "axes" values in the order of the fvar axes
    // CoreText: the "axis_map" dictionary
    bool has_axes;
    size_t num_axes;
    FSAxisValue axes[FS_MAX_AXES];
    bool has_matrix;
    double matrix[4];
} FSFont;

typedef struct FSCandidateList {
    const FSCandidate **items;
    size_t count, capacity;
} FSCandidateList;

typedef enum FSListKind { FS_LIST_FAMILY, FS_LIST_POSTSCRIPT_NAME, FS_LIST_FULL_NAME } FSListKind;

typedef struct FSFontSpec {
    char *family, *style, *postscript_name, *full_name, *system, *variable_name;
    bool has_variable_name; // variable_name can be specified as the empty string
    bool has_features;      // features are applied to the selected font by the Python code
    size_t num_axes;
    struct {
        char *name;
        double value;
    } *axes;
} FSFontSpec;

// Variable font data {{{
typedef struct FSVarAxis {
    double minimum, maximum, def;
    bool hidden;
    uint32_t tag;
    char *strid;
} FSVarAxis;

typedef struct FSNamedStyle {
    char *name, *psname;
    size_t num_values;
    FSAxisValue *values;
} FSNamedStyle;

typedef struct FSDesignValue {
    unsigned format, flags;
    char *name;
    double value, minimum, maximum, linked_value;
} FSDesignValue;

typedef struct FSDesignAxis {
    uint32_t tag;
    char *name;
    unsigned ordering;
    size_t num_values, capacity;
    FSDesignValue *values;
} FSDesignAxis;

typedef struct FSVariableData {
    char *variations_postscript_name_prefix, *elided_fallback_name;
    size_t num_axes, num_named_styles, num_design_axes;
    FSVarAxis *axes;
    FSNamedStyle *named_styles;
    FSDesignAxis *design_axes;
} FSVariableData;

// Raw font tables needed to compute variable font data, owned by the struct
typedef struct FSFontTables {
    uint8_t *fvar, *stat, *name;
    size_t fvar_len, stat_len, name_len;
} FSFontTables;

void fs_free_font_tables(FSFontTables *t);
void fs_free_variable_data(FSVariableData *vd);
bool fs_variable_data_from_tables(const FSFontTables *t, FSVariableData *vd);
// Read the tables for face index (the low 16 bits of index) from an sfnt font file
bool fs_read_font_tables_from_file(const char *path, int index, FSFontTables *t);
// }}}

typedef struct FSContext FSContext;

// Helpers for backends {{{
// The key used to compare font names: whitespace collapsed and stripped, lowercased. Caller must free.
char *fs_name_to_key(const char *name);
// Allocate a new candidate owned by the context
FSCandidate *fs_new_candidate(FSContext *ctx);
bool fs_list_append(FSCandidateList *l, const FSCandidate *c);
void fs_set_error(FSContext *ctx, const char *fmt, ...) __attribute__((format(printf, 2, 3)));
void fs_add_message(FSContext *ctx, const char *fmt, ...) __attribute__((format(printf, 2, 3)));
// Backend private data, freed with fs_backend_free_context_data()
void **fs_backend_data(FSContext *ctx);
// }}}

// Backend API {{{
// Initialize the font database, must be thread safe
bool fs_backend_init(FSContext *ctx);
void fs_backend_free_context_data(void *data);
void fs_backend_free_candidate(FSCandidate *c);
// Append the fonts whose name of the specified kind matches key (as returned by fs_name_to_key()).
// name is the name as specified by the user. For FS_LIST_FULL_NAME on
// CoreText the full name is the family name followed by the style name.
bool fs_backend_list(FSContext *ctx, FSListKind kind, const char *name, const char *key, bool monospaced, FSCandidateList *out);
bool fs_backend_font_tables(FSContext *ctx, const FSCandidate *c, FSFontTables *out);
#ifndef __APPLE__
// Equivalent to the Python fc_match(), returns NULL on failure
const FSCandidate *fs_backend_fc_match(FSContext *ctx, const char *family, bool bold, bool italic, int spacing);
// Whether two candidates created by fs_backend_fc_match() are equal
bool fs_backend_fc_match_equal(const FSCandidate *a, const FSCandidate *b);
#endif
// }}}

// Called by the backend finalize functions before the font database is
// finalized, waits for any selection running in a thread and frees it.
void fs_finalize_selection(void);
// Wait for any selection running in a thread to finish, call before modifying the font database
void fs_wait_for_selection_thread(void);
