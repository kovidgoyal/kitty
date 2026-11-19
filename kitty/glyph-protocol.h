/*
 * glyph-protocol.h
 * Copyright (C) 2026 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

// The Glyph Protocol lets programs register vector glyphs for codepoints in a
// reserved block of the Supplementary Private Use Area-B. Its messages are
// APC escape codes of the form: ESC _ 25a1 ; <verb> [; key=value]* [; payload] ST
// See https://github.com/raphamorim/rio/blob/main/specs/glyph-protocol.md

#pragma once

#include "data-types.h"

// The identifier that starts every glyph protocol APC message
#define GLYPH_PROTOCOL_PREFIX "25a1;"
#define GLYPH_PROTOCOL_PREFIX_LEN (sizeof(GLYPH_PROTOCOL_PREFIX) - 1)
// The registration block, the only codepoints that can be registered
#define GLYPH_BLOCK_FIRST 0x100000u
#define GLYPH_BLOCK_LAST 0x1003ffu
#define GLYPH_BLOCK_SIZE (GLYPH_BLOCK_LAST - GLYPH_BLOCK_FIRST + 1u)
// The maximum size of a payload in bytes
#define GLYPH_MAX_PAYLOAD_SIZE (32u * 1024u)
// The maximum number of codepoints in a grapheme query
#define GLYPH_MAX_GRAPHEME_CODEPOINTS 32u
// The maximum magnitude of a viewBox value
#define GLYPH_MAX_VIEWBOX_MAGNITUDE 1000000.f
// The maximum ratio of the sides of a viewBox
#define GLYPH_MAX_VIEWBOX_ASPECT_RATIO 4096.f

static inline bool
is_glyph_block_codepoint(char_type cp) {
    return GLYPH_BLOCK_FIRST <= cp && cp <= GLYPH_BLOCK_LAST;
}

typedef enum GlyphVerb {
    GLYPH_VERB_SUPPORT = 's',
    GLYPH_VERB_QUERY = 'q',
    GLYPH_VERB_REGISTER = 'r',
    GLYPH_VERB_CLEAR = 'c',
} GlyphVerb;

typedef enum GlyphPayloadFormat {
    // No fmt key, which the spec says means glyf
    GLYPH_FMT_UNSPECIFIED,
    GLYPH_FMT_VG,
    GLYPH_FMT_GLYF,
    GLYPH_FMT_COLRV0,
    GLYPH_FMT_COLRV1,
    // A format name this implementation does not know about
    GLYPH_FMT_UNKNOWN,
} GlyphPayloadFormat;

typedef enum GlyphReplyLevel {
    GLYPH_REPLY_NONE = 0,
    GLYPH_REPLY_ALL = 1,
    GLYPH_REPLY_FAILURES = 2,
} GlyphReplyLevel;

typedef enum GlyphFit {
    GLYPH_FIT_CONTAIN,
    GLYPH_FIT_COVER,
    GLYPH_FIT_STRETCH,
} GlyphFit;

typedef enum GlyphAlign {
    GLYPH_ALIGN_START,
    GLYPH_ALIGN_CENTER,
    GLYPH_ALIGN_END,
} GlyphAlign;

// How a registered glyph's viewBox is placed in the area its character is
// rendered into, as with SVG's preserveAspectRatio
typedef struct GlyphPlacement {
    // x, y, width, height of the viewBox
    float vb[4];
    GlyphFit fit;
    GlyphAlign align_h, align_v;
} GlyphPlacement;

typedef struct GlyphCommand {
    GlyphVerb verb;

    // cp key: has_cp is true if the key is present, cp_valid if its value is
    // a valid Unicode scalar value, in which case it is stored in cp
    bool has_cp, cp_valid;
    char_type cp;

    // grapheme key: as for cp, the codepoints are stored only if all of them are valid
    bool has_grapheme, grapheme_valid;
    unsigned grapheme_count;
    char_type grapheme[GLYPH_MAX_GRAPHEME_CODEPOINTS];

    GlyphPayloadFormat fmt;
    GlyphReplyLevel reply;

    // vb, fit and align keys. placement_valid is false if any of them has an
    // invalid value. has_vb is true if the vb key is present.
    bool has_vb, placement_valid;
    GlyphPlacement placement;

    // The payload, the last field of a register command, as offsets into the
    // buffer that was parsed
    bool has_payload;
    size_t payload_start, payload_sz;
} GlyphCommand;

// Parse the body of an APC escape code (everything between ESC _ and ESC \),
// which must start with GLYPH_PROTOCOL_PREFIX. Returns NULL on success, or a
// message describing why the escape code could not be parsed at all, in which
// case it must be ignored. Keys with invalid values do not cause failure, they
// are recorded in the command so that a reply describing the error can be
// sent.
const char *parse_glyph_command(const uint8_t *buf, size_t sz, GlyphCommand *cmd);

// Parse a number as defined for SVG path data: an optional sign, then digits,
// digits with a fraction or a fraction alone, then an optional exponent. A .
// must be followed by a digit. On success, *pos is advanced to just after the
// number. Fails if the number does not fit in a 32-bit float.
bool glyph_parse_number(const uint8_t *buf, size_t sz, size_t *pos, float *ans);

const char *glyph_format_name(GlyphPayloadFormat fmt);

// A dict representation of a parsed command, used for testing and dumping
// commands. buf must be the buffer the command was parsed from.
PyObject *glyph_command_as_dict(const GlyphCommand *cmd, const uint8_t *buf);
