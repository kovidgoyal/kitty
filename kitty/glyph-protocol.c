/*
 * glyph-protocol.c
 * Copyright (C) 2026 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

// Parsing of Glyph Protocol escape codes, see glyph-protocol.h

#include "glyph-protocol.h"
#include <float.h>
#include <math.h>

// Number parsing {{{
static inline bool
is_digit(uint8_t ch) {
    return '0' <= ch && ch <= '9';
}

bool
glyph_parse_number(const uint8_t *buf, size_t sz, size_t *pos, float *ans) {
    size_t i = *pos;
    bool negative = false;
    if (i < sz && (buf[i] == '+' || buf[i] == '-')) negative = buf[i++] == '-';
    // Up to 19 significant digits fit in a uint64_t, further digits only change the exponent
    uint64_t mantissa = 0;
    int significant_digits = 0;
    // The number of digits is bounded by the size of the buffer, which is far
    // smaller than INT_MAX, so this cannot overflow
    int64_t exponent = 0;
    bool has_int_digits = false, has_frac_digits = false;
    for (; i < sz && is_digit(buf[i]); i++) {
        has_int_digits = true;
        if (significant_digits < 19) {
            if (mantissa || buf[i] != '0') {
                mantissa = mantissa * 10 + (buf[i] - '0');
                significant_digits++;
            }
        } else exponent++;
    }
    if (i < sz && buf[i] == '.') {
        // A . must be followed by a digit, so 1. is not a number
        if (i + 1 >= sz || !is_digit(buf[i + 1])) return false;
        for (i++; i < sz && is_digit(buf[i]); i++) {
            has_frac_digits = true;
            if (significant_digits < 19) {
                if (mantissa || buf[i] != '0') {
                    mantissa = mantissa * 10 + (buf[i] - '0');
                    significant_digits++;
                }
                exponent--;
            }
        }
    }
    if (!has_int_digits && !has_frac_digits) return false;
    // An exponent is only consumed if it has at least one digit
    if (i < sz && (buf[i] == 'e' || buf[i] == 'E')) {
        size_t e = i + 1;
        bool exp_negative = false;
        if (e < sz && (buf[e] == '+' || buf[e] == '-')) exp_negative = buf[e++] == '-';
        if (e < sz && is_digit(buf[e])) {
            int64_t explicit_exponent = 0;
            for (; e < sz && is_digit(buf[e]); e++) {
                // Saturate at a value larger than any possible number of digits
                // in the buffer, so that the sum with the exponent from the
                // digits still overflows or underflows correctly
                if (explicit_exponent < INT32_MAX) explicit_exponent = explicit_exponent * 10 + (buf[e] - '0');
            }
            exponent += exp_negative ? -explicit_exponent : explicit_exponent;
            i = e;
        }
    }
    double val = 0;
    if (mantissa) {
        if (exponent > 400) return false;
        if (exponent < -400) val = 0;
        else val = (double)mantissa * pow(10.0, (double)exponent);
    }
    if (!isfinite(val) || val > FLT_MAX) return false;
    *ans = (float)(negative ? -val : val);
    *pos = i;
    return true;
}
// }}}

// Field parsing {{{
typedef struct Field {
    const uint8_t *data;
    size_t sz;
} Field;

static bool
field_eq(Field f, const char *s) {
    const size_t n = strlen(s);
    return f.sz == n && memcmp(f.data, s, n) == 0;
}

static bool
parse_hex_codepoint(Field f, char_type *ans) {
    if (!f.sz || f.sz > 8) return false;
    char_type val = 0;
    for (size_t i = 0; i < f.sz; i++) {
        const uint8_t ch = f.data[i];
        unsigned d;
        if (is_digit(ch)) d = ch - '0';
        else if ('a' <= ch && ch <= 'f') d = ch - 'a' + 10;
        else if ('A' <= ch && ch <= 'F') d = ch - 'A' + 10;
        else return false;
        val = (val << 4) | d;
    }
    // Must be a Unicode scalar value
    if (val > 0x10ffff || (0xd800 <= val && val <= 0xdfff)) return false;
    *ans = val;
    return true;
}

static void
parse_grapheme(Field f, GlyphCommand *cmd) {
    cmd->has_grapheme = true;
    cmd->grapheme_valid = false;
    cmd->grapheme_count = 0;
    size_t start = 0;
    for (size_t i = 0; i <= f.sz; i++) {
        if (i == f.sz || f.data[i] == ',') {
            if (cmd->grapheme_count >= GLYPH_MAX_GRAPHEME_CODEPOINTS) {
                cmd->grapheme_count = 0;
                return;
            }
            Field item = {.data = f.data + start, .sz = i - start};
            if (!parse_hex_codepoint(item, cmd->grapheme + cmd->grapheme_count)) {
                cmd->grapheme_count = 0;
                return;
            }
            cmd->grapheme_count++;
            start = i + 1;
        }
    }
    cmd->grapheme_valid = true;
}

static GlyphPayloadFormat
parse_format(Field f) {
    if (field_eq(f, "vg")) return GLYPH_FMT_VG;
    if (field_eq(f, "glyf")) return GLYPH_FMT_GLYF;
    if (field_eq(f, "colrv0")) return GLYPH_FMT_COLRV0;
    if (field_eq(f, "colrv1")) return GLYPH_FMT_COLRV1;
    return GLYPH_FMT_UNKNOWN;
}

const char *
glyph_format_name(GlyphPayloadFormat fmt) {
    switch (fmt) {
        case GLYPH_FMT_UNSPECIFIED: return "";
        case GLYPH_FMT_VG: return "vg";
        case GLYPH_FMT_GLYF: return "glyf";
        case GLYPH_FMT_COLRV0: return "colrv0";
        case GLYPH_FMT_COLRV1: return "colrv1";
        case GLYPH_FMT_UNKNOWN: return "unknown";
    }
    return "unknown";
}

static bool
parse_viewbox(Field f, float vb[4]) {
    size_t pos = 0;
    for (unsigned n = 0; n < 4; n++) {
        if (n) {
            // values are separated by commas or spaces
            const size_t before = pos;
            while (pos < f.sz && f.data[pos] == ' ') pos++;
            if (pos < f.sz && f.data[pos] == ',') {
                pos++;
                while (pos < f.sz && f.data[pos] == ' ') pos++;
            }
            if (pos == before) return false;
        }
        if (!glyph_parse_number(f.data, f.sz, &pos, vb + n)) return false;
        if (fabsf(vb[n]) > GLYPH_MAX_VIEWBOX_MAGNITUDE) return false;
    }
    if (pos != f.sz) return false;
    if (!(vb[2] > 0 && vb[3] > 0)) return false;
    // The limits on path data are relative to the larger side of the viewBox,
    // so with fit=cover or stretch and an extreme aspect ratio the path data
    // can be huge relative to the area the glyph is rendered into
    return MAX(vb[2], vb[3]) <= GLYPH_MAX_VIEWBOX_ASPECT_RATIO * MIN(vb[2], vb[3]);
}

static bool
parse_fit(Field f, GlyphFit *fit) {
    if (field_eq(f, "contain")) *fit = GLYPH_FIT_CONTAIN;
    else if (field_eq(f, "cover")) *fit = GLYPH_FIT_COVER;
    else if (field_eq(f, "stretch")) *fit = GLYPH_FIT_STRETCH;
    else return false;
    return true;
}

static bool
parse_align_value(Field f, GlyphAlign *a) {
    if (field_eq(f, "start")) *a = GLYPH_ALIGN_START;
    else if (field_eq(f, "center")) *a = GLYPH_ALIGN_CENTER;
    else if (field_eq(f, "end")) *a = GLYPH_ALIGN_END;
    else return false; // this includes baseline, which is invalid for a viewBox
    return true;
}

static bool
parse_align(Field f, GlyphAlign *h, GlyphAlign *v) {
    const uint8_t *comma = memchr(f.data, ',', f.sz);
    if (!comma) return false;
    Field hf = {.data = f.data, .sz = comma - f.data}, vf = {.data = comma + 1, .sz = f.sz - (hf.sz + 1)};
    return parse_align_value(hf, h) && parse_align_value(vf, v);
}

static void
parse_key_value(Field key, Field val, GlyphCommand *cmd) {
    if (field_eq(key, "cp")) {
        cmd->has_cp = true;
        cmd->cp_valid = parse_hex_codepoint(val, &cmd->cp);
        if (!cmd->cp_valid) cmd->cp = 0;
    } else if (field_eq(key, "grapheme")) {
        parse_grapheme(val, cmd);
    } else if (field_eq(key, "fmt")) {
        cmd->fmt = parse_format(val);
    } else if (field_eq(key, "reply")) {
        // Unknown values fall back to replying to everything
        if (field_eq(val, "0")) cmd->reply = GLYPH_REPLY_NONE;
        else if (field_eq(val, "2")) cmd->reply = GLYPH_REPLY_FAILURES;
        else cmd->reply = GLYPH_REPLY_ALL;
    } else if (field_eq(key, "vb")) {
        cmd->has_vb = true;
        if (!parse_viewbox(val, cmd->placement.vb)) cmd->placement_valid = false;
    } else if (field_eq(key, "fit")) {
        if (!parse_fit(val, &cmd->placement.fit)) cmd->placement_valid = false;
    } else if (field_eq(key, "align")) {
        if (!parse_align(val, &cmd->placement.align_h, &cmd->placement.align_v)) cmd->placement_valid = false;
    }
    // All other keys are ignored, as the spec requires for unrecognized
    // keys. This includes keys used only by the font based formats and
    // width, which kitty ignores as the width of a character is determined by
    // the text sizing protocol and its own rules.
}
// }}}

const char *
parse_glyph_command(const uint8_t *buf, size_t sz, GlyphCommand *cmd) {
    zero_at_ptr(cmd);
    cmd->reply = GLYPH_REPLY_ALL;
    cmd->placement_valid = true;
    cmd->placement.fit = GLYPH_FIT_CONTAIN;
    cmd->placement.align_h = GLYPH_ALIGN_CENTER;
    cmd->placement.align_v = GLYPH_ALIGN_CENTER;
    if (sz < GLYPH_PROTOCOL_PREFIX_LEN || memcmp(buf, GLYPH_PROTOCOL_PREFIX, GLYPH_PROTOCOL_PREFIX_LEN) != 0) return "not a glyph protocol message";
    size_t pos = GLYPH_PROTOCOL_PREFIX_LEN;
    // The verb is the first field
    const uint8_t *sep = memchr(buf + pos, ';', sz - pos);
    const size_t verb_end = sep ? (size_t)(sep - buf) : sz;
    if (verb_end - pos != 1) return "invalid verb";
    switch (buf[pos]) {
        case GLYPH_VERB_SUPPORT:
        case GLYPH_VERB_QUERY:
        case GLYPH_VERB_REGISTER:
        case GLYPH_VERB_CLEAR: cmd->verb = buf[pos]; break;
        default: return "unknown verb";
    }
    if (!sep) return NULL;
    pos = verb_end + 1;
    size_t end = sz;
    if (cmd->verb == GLYPH_VERB_REGISTER) {
        // The payload is the last field, identified by position not content,
        // as it can contain = characters
        const uint8_t *last_sep = buf + sz;
        while (last_sep > buf + pos && last_sep[-1] != ';') last_sep--;
        cmd->has_payload = true;
        cmd->payload_start = last_sep - buf;
        cmd->payload_sz = sz - cmd->payload_start;
        end = cmd->payload_start > pos ? cmd->payload_start - 1 : pos;
    }
    while (pos < end) {
        sep = memchr(buf + pos, ';', end - pos);
        const size_t field_end = sep ? (size_t)(sep - buf) : end;
        const uint8_t *eq = memchr(buf + pos, '=', field_end - pos);
        // Fields without = are not valid key=value pairs, ignore them
        if (eq) {
            Field key = {.data = buf + pos, .sz = eq - (buf + pos)};
            Field val = {.data = eq + 1, .sz = field_end - (eq + 1 - buf)};
            parse_key_value(key, val, cmd);
        }
        pos = field_end + 1;
    }
    return NULL;
}

// Python interface {{{
static PyObject *
align_name(GlyphAlign a) {
    switch (a) {
        case GLYPH_ALIGN_START: return PyUnicode_FromString("start");
        case GLYPH_ALIGN_CENTER: return PyUnicode_FromString("center");
        case GLYPH_ALIGN_END: return PyUnicode_FromString("end");
    }
    return PyUnicode_FromString("unknown");
}

static PyObject *
fit_name(GlyphFit f) {
    switch (f) {
        case GLYPH_FIT_CONTAIN: return PyUnicode_FromString("contain");
        case GLYPH_FIT_COVER: return PyUnicode_FromString("cover");
        case GLYPH_FIT_STRETCH: return PyUnicode_FromString("stretch");
    }
    return PyUnicode_FromString("unknown");
}

PyObject *
glyph_command_as_dict(const GlyphCommand *cmd, const uint8_t *buf) {
    RAII_PyObject(ans, PyDict_New());
    if (!ans) return NULL;
#define S(key, val)                                                    \
    {                                                                  \
        RAII_PyObject(v, val);                                         \
        if (!v || PyDict_SetItemString(ans, key, v) != 0) return NULL; \
    }
    S("verb", PyUnicode_FromFormat("%c", (int)cmd->verb));
    if (cmd->has_cp) S("cp", cmd->cp_valid ? PyLong_FromUnsignedLong(cmd->cp) : Py_NewRef(Py_None));
    if (cmd->has_grapheme) {
        if (cmd->grapheme_valid) {
            RAII_PyObject(g, PyTuple_New(cmd->grapheme_count));
            if (!g) return NULL;
            for (unsigned i = 0; i < cmd->grapheme_count; i++) {
                PyObject *c = PyLong_FromUnsignedLong(cmd->grapheme[i]);
                if (!c) return NULL;
                PyTuple_SET_ITEM(g, i, c);
            }
            S("grapheme", Py_NewRef(g));
        } else S("grapheme", Py_NewRef(Py_None));
    }
    S("fmt", PyUnicode_FromString(glyph_format_name(cmd->fmt)));
    S("reply", PyLong_FromUnsignedLong(cmd->reply));
    if (cmd->has_vb) {
        if (cmd->placement_valid) {
            const float *vb = cmd->placement.vb;
            S("vb", Py_BuildValue("(dddd)", (double)vb[0], (double)vb[1], (double)vb[2], (double)vb[3]));
        }
    }
    if (cmd->placement_valid) {
        S("fit", fit_name(cmd->placement.fit));
        S("align", Py_BuildValue("(NN)", align_name(cmd->placement.align_h), align_name(cmd->placement.align_v)));
    } else S("placement_invalid", Py_NewRef(Py_True));
    if (cmd->has_payload) S("payload", PyBytes_FromStringAndSize((const char *)buf + cmd->payload_start, cmd->payload_sz));
#undef S
    return Py_NewRef(ans);
}

static PyObject *
py_parse_glyph_command(PyObject *self UNUSED, PyObject *args) {
    const char *data;
    Py_ssize_t sz;
    if (!PyArg_ParseTuple(args, "y#", &data, &sz)) return NULL;
    GlyphCommand cmd;
    const char *err = parse_glyph_command((const uint8_t *)data, sz, &cmd);
    if (err) {
        PyErr_SetString(PyExc_ValueError, err);
        return NULL;
    }
    return glyph_command_as_dict(&cmd, (const uint8_t *)data);
}

static PyMethodDef methods[] = {
    {"parse_glyph_command", py_parse_glyph_command, METH_VARARGS, "Parse the body of a glyph protocol APC escape code, for testing"},
    {NULL, NULL, 0, NULL},
};

bool
init_glyph_protocol(PyObject *module) {
    if (PyModule_AddFunctions(module, methods) != 0) return false;
    return true;
}
// }}}
