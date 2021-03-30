/*
 * freetype_render_ui_text.c
 * Copyright (C) 2021 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#include "freetype_render_ui_text.h"
#include <hb.h>
#include <hb-ft.h>
#include "charsets.h"

typedef struct FamilyInformation {
    char *name;
    bool bold, italic;
} FamilyInformation;

typedef struct Face {
    FT_Face freetype;
    hb_font_t *hb;
    FT_UInt pixel_size;
    struct Face *fallbacks;
    size_t count, capacity;
} Face;

Face main_face = {0};
FontConfigFace main_face_information = {0};
FamilyInformation main_face_family = {0};
hb_buffer_t *hb_buffer = NULL;

static inline FT_UInt
glyph_id_for_codepoint(Face *face, char_type cp) {
    return FT_Get_Char_Index(face->freetype, cp);
}

static void
free_face(Face *face) {
    if (face->freetype) FT_Done_Face(face->freetype);
    if (face->hb) hb_font_destroy(face->hb);
    for (size_t i = 0; i < face->count; i++) free_face(face->fallbacks + i);
    memset(face, 0, sizeof(Face));
}

static void
cleanup(void) {
    free_face(&main_face);
    free(main_face_information.path); main_face_information.path = NULL;
    free(main_face_family.name);
    memset(&main_face_family, 0, sizeof(FamilyInformation));
    if (hb_buffer) hb_buffer_destroy(hb_buffer);
    hb_buffer = NULL;
}

void
set_main_face_family(const char *family, bool bold, bool italic) {
    if (family == main_face_family.name || (main_face_family.name && strcmp(family, main_face_family.name) == 0)) return;
    cleanup();
    main_face_family.name = strdup(family);
    main_face_family.bold = bold; main_face_family.italic = italic;
}

static bool
load_font(FontConfigFace *info, Face *ans) {
    ans->freetype = native_face_from_path(info->path, info->index);
    if (!ans->freetype) return false;
    ans->hb = hb_ft_font_create(ans->freetype, NULL);
    if (!ans->hb) { PyErr_NoMemory(); return false; }
    return true;
}

static bool
ensure_state(void) {
    if (main_face.freetype && main_face.hb) return false;
    if (!information_for_font_family(main_face_family.name, main_face_family.bold, main_face_family.italic, &main_face_information)) return false;
    if (!load_font(&main_face_information, &main_face)) return false;
    hb_buffer = hb_buffer_create();
    if (!hb_buffer) { PyErr_NoMemory(); return false; }
    return true;
}

static void
set_pixel_size(Face *face, FT_UInt sz) {
    if (sz != face->pixel_size) {
        FT_Set_Pixel_Sizes(face->freetype, sz, sz);  // TODO: check for and handle failures
        hb_ft_font_changed(face->hb);
        face->pixel_size = sz;
    }
}

typedef struct RenderState {
    uint32_t pending_in_buffer, fg, bg;
    uint8_t *output;
    bool alpha_first;
    size_t output_width, output_height;
    Face *current_face;
} RenderState;


bool
render_run(RenderState *rs) {
    hb_buffer_guess_segment_properties(hb_buffer);
    if (!HB_DIRECTION_IS_HORIZONTAL (hb_buffer_get_direction(hb_buffer))) {
        PyErr_SetString(PyExc_ValueError, "Vertical text is not supported");
        return false;
    }
    FT_UInt pixel_size = 2 * rs->output_height / 3;
    set_pixel_size(rs->current_face, pixel_size);
    hb_shape(rs->current_face->hb, hb_buffer, NULL, 0);
    unsigned int len = hb_buffer_get_length(hb_buffer);
    hb_glyph_info_t *info = hb_buffer_get_glyph_infos(hb_buffer, NULL);
    hb_glyph_position_t *pos = hb_buffer_get_glyph_positions(hb_buffer, NULL);

    (void)len; (void)info; (void)pos;

    return true;
}

static bool
current_font_has_codepoint(RenderState *rs, char_type codep) {
    if (rs->current_face != &main_face && glyph_id_for_codepoint(&main_face, codep) > 0) {
        rs->current_face = &main_face;
        return true;
    }
    return glyph_id_for_codepoint(rs->current_face, codep);
}

static bool
find_fallback_font_for(RenderState *rs, char_type codep) {
    if (glyph_id_for_codepoint(&main_face, codep) > 0) {
        rs->current_face = &main_face;
        return true;
    }
    for (size_t i = 0; i < main_face.count; i++) {
        if (glyph_id_for_codepoint(main_face.fallbacks + i, codep) > 0) {
            rs->current_face = main_face.fallbacks + i;
            return true;
        }
    }
    FontConfigFace q;
    if (!fallback_font(codep, main_face_family.name, main_face_family.bold, main_face_family.italic, &q)) return false;
    ensure_space_for(&main_face, fallbacks, Face, main_face.count + 1, capacity, 8, true);
    Face *ans = main_face.fallbacks + main_face.count;
    if (!load_font(&q, ans)) return false;
    main_face.count++;
    rs->current_face = ans;
    return true;
}


bool
render_single_line(const char *text, uint32_t fg, uint32_t bg, uint8_t *output_buf, size_t width, size_t height, bool alpha_first) {
    if (!ensure_state()) return false;
    for (uint32_t *px = (uint32_t*)output_buf, *end = ((uint32_t*)output_buf) + width * height; px < end; px++) *px = bg;
    if (!text || !text[0]) return true;
    (void)fg; (void)alpha_first;
    hb_buffer_clear_contents(hb_buffer);
    if (!hb_buffer_pre_allocate(hb_buffer, 512)) { PyErr_NoMemory(); return false; }
    RenderState rs = {
        .current_face = &main_face, .fg = fg, .bg = bg, .output_width = width, .output_height = height,
        .output = output_buf, .alpha_first = alpha_first
    };

    for (uint32_t i = 0, codep = 0, state = 0, prev = UTF8_ACCEPT; text[i] > 0; i++) {
        switch(decode_utf8(&state, &codep, text[i])) {
            case UTF8_ACCEPT:
                if (current_font_has_codepoint(&rs, codep)) {
                    hb_buffer_add_utf32(hb_buffer, &codep, 1, 0, 1);
                    rs.pending_in_buffer += 1;
                } else {
                    if (rs.pending_in_buffer) {
                        if (!render_run(&rs)) return false;
                        rs.pending_in_buffer = 0;
                        hb_buffer_clear_contents(hb_buffer);
                    }
                    if (!find_fallback_font_for(&rs, codep)) {
                        hb_buffer_add_utf32(hb_buffer, &codep, 1, 0, 1);
                        rs.pending_in_buffer += 1;
                    }
                }
                break;
            case UTF8_REJECT:
                state = UTF8_ACCEPT;
                if (prev != UTF8_ACCEPT && i > 0) i--;
                break;
        }
        prev = state;
    }
    if (rs.pending_in_buffer) {
        if (!render_run(&rs)) return false;
        rs.pending_in_buffer = 0;
        hb_buffer_clear_contents(hb_buffer);
    }
    return true;
}

static PyObject*
path_for_font(PyObject *self UNUSED, PyObject *args) {
    const char *family = NULL; int bold = 0, italic = 0;
    if (!PyArg_ParseTuple(args, "|zpp", &family, &bold, &italic)) return NULL;
    FontConfigFace f;
    if (!information_for_font_family(family, bold, italic, &f)) return NULL;
    PyObject *ret = Py_BuildValue("{ss si si si}", "path", f.path, "index", f.index, "hinting", f.hinting, "hintstyle", f.hintstyle);
    free(f.path);
    return ret;
}

static PyObject*
fallback_for_char(PyObject *self UNUSED, PyObject *args) {
    const char *family = NULL; int bold = 0, italic = 0;
    unsigned int ch;
    if (!PyArg_ParseTuple(args, "I|zpp", &ch, &family, &bold, &italic)) return NULL;
    FontConfigFace f;
    if (!fallback_font(ch, family, bold, italic, &f)) return NULL;
    PyObject *ret = Py_BuildValue("{ss si si si}", "path", f.path, "index", f.index, "hinting", f.hinting, "hintstyle", f.hintstyle);
    free(f.path);
    return ret;
}

static PyMethodDef module_methods[] = {
    METHODB(path_for_font, METH_VARARGS),
    METHODB(fallback_for_char, METH_VARARGS),

    {NULL, NULL, 0, NULL}        /* Sentinel */
};


bool
init_freetype_render_ui_text(PyObject *module) {
    if (PyModule_AddFunctions(module, module_methods) != 0) return false;
    if (Py_AtExit(cleanup) != 0) {
        PyErr_SetString(PyExc_RuntimeError, "Failed to register the fontconfig library at exit handler");
        return false;
    }
    return true;
}
