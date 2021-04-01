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
#include "unicode-data.h"
#include "wcwidth-std.h"
#include "wcswidth.h"
#include FT_BITMAP_H

typedef struct FamilyInformation {
    char *name;
    bool bold, italic;
} FamilyInformation;

typedef struct Face {
    FT_Face freetype;
    hb_font_t *hb;
    FT_UInt pixel_size;
    int hinting, hintstyle;
    struct Face *fallbacks;
    size_t count, capacity;
} Face;

typedef struct {
    unsigned char* buf;
    size_t start_x, width, stride;
    size_t rows;
    FT_Pixel_Mode pixel_mode;
    unsigned int factor, right_edge;
    int bitmap_left, bitmap_top;
} ProcessedBitmap;


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
    free(face->fallbacks);
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

static inline int
get_load_flags(int hinting, int hintstyle, int base) {
    int flags = base;
    if (hinting) {
        if (hintstyle >= 3) flags |= FT_LOAD_TARGET_NORMAL;
        else if (0 < hintstyle  && hintstyle < 3) flags |= FT_LOAD_TARGET_LIGHT;
    } else flags |= FT_LOAD_NO_HINTING;
    return flags;
}


static bool
load_font(FontConfigFace *info, Face *ans) {
    ans->freetype = native_face_from_path(info->path, info->index);
    if (!ans->freetype) return false;
    ans->hb = hb_ft_font_create(ans->freetype, NULL);
    if (!ans->hb) { PyErr_NoMemory(); return false; }
    ans->hinting = info->hinting; ans->hintstyle = info->hintstyle;
    hb_ft_font_set_load_flags(ans->hb, get_load_flags(ans->hinting, ans->hintstyle, FT_LOAD_DEFAULT));
    return true;
}

static bool
ensure_state(void) {
    if (main_face.freetype && main_face.hb) return true;
    if (!information_for_font_family(main_face_family.name, main_face_family.bold, main_face_family.italic, &main_face_information)) return false;
    if (!load_font(&main_face_information, &main_face)) return false;
    hb_buffer = hb_buffer_create();
    if (!hb_buffer) { PyErr_NoMemory(); return false; }
    return true;
}

static int
font_units_to_pixels_y(FT_Face face, int x) {
    return (int)ceil((double)FT_MulFix(x, face->size->metrics.y_scale) / 64.0);
}

static FT_UInt
choose_bitmap_size(FT_Face face, FT_UInt desired_height) {
    unsigned short best = 0, diff = USHRT_MAX;
    const short limit = face->num_fixed_sizes;
    for (short i = 0; i < limit; i++) {
        unsigned short h = face->available_sizes[i].height;
        unsigned short d = h > (unsigned short)desired_height ? h - (unsigned short)desired_height : (unsigned short)desired_height - h;
        if (d < diff) {
            diff = d;
            best = i;
        }
    }
    FT_Select_Size(face, best);
    return best;
}

static void
set_pixel_size(Face *face, FT_UInt sz, bool has_color) {
    if (sz != face->pixel_size) {
        if (has_color) sz = choose_bitmap_size(face->freetype, font_units_to_pixels_y(main_face.freetype, main_face.freetype->height));
        else FT_Set_Pixel_Sizes(face->freetype, sz, sz);
        hb_ft_font_changed(face->hb);
        hb_ft_font_set_load_flags(face->hb, get_load_flags(face->hinting, face->hintstyle, FT_LOAD_DEFAULT));
        face->pixel_size = sz;
    }
}


typedef struct RenderState {
    uint32_t pending_in_buffer, fg, bg;
    pixel *output;
    size_t output_width, output_height;
    Face *current_face;
    float x, y;
    Region src, dest;
    unsigned sz_px;
} RenderState;

static void
setup_regions(ProcessedBitmap *bm, RenderState *rs, int baseline) {
    rs->src = (Region){ .left = bm->start_x, .bottom = bm->rows, .right = bm->width + bm->start_x };
    rs->dest = (Region){ .bottom = rs->output_height, .right = rs->output_width };
    int xoff = (int)(rs->x + bm->bitmap_left);
    if (xoff < 0) rs->src.left += -xoff;
    else rs->dest.left = xoff;
    int yoff = (int)(rs->y + bm->bitmap_top);
    if ((yoff > 0 && yoff > baseline)) {
        rs->dest.top = 0;
    } else {
        rs->dest.top = baseline - yoff;
    }
}

#define ARGB(a, r, g, b) ( (a & 0xff) << 24 ) | ( (r & 0xff) << 16) | ( (g & 0xff) << 8 ) | (b & 0xff)

static pixel
premult_pixel(pixel p, uint16_t alpha) {
#define s(x) (x * alpha / 255)
    uint16_t r = (p >> 16) & 0xff, g = (p >> 8) & 0xff, b = p & 0xff;
    return ARGB(alpha, s(r), s(g), s(b));
#undef s
}

static pixel
alpha_blend_premult(pixel over, pixel under) {
    const uint16_t over_r = (over >> 16) & 0xff, over_g = (over >> 8) & 0xff, over_b = over & 0xff;
    const uint16_t under_r = (under >> 16) & 0xff, under_g = (under >> 8) & 0xff, under_b = under & 0xff;
    const uint16_t factor = 255 - ((over >> 24) & 0xff);
#define ans(x) (over_##x + (factor * under_##x) / 255)
    return ARGB(under >> 24, ans(r), ans(g), ans(b));
#undef ans
}

static void
render_color_bitmap(ProcessedBitmap *src, RenderState *rs) {
    for (size_t sr = rs->src.top, dr = rs->dest.top; sr < rs->src.bottom && dr < rs->dest.bottom; sr++, dr++) {
        pixel *dest_row = rs->output + rs->output_width * dr;
        uint8_t *src_px = src->buf + src->stride * sr;
        for (size_t sc = rs->src.left, dc = rs->dest.left; sc < rs->src.right && dc < rs->dest.right; sc++, dc++, src_px += 4) {
            pixel fg = premult_pixel(ARGB(src_px[3], src_px[2], src_px[1], src_px[0]), src_px[3]);
            dest_row[dc] = alpha_blend_premult(fg, dest_row[dc]);
        }
    }
}

static void
render_gray_bitmap(ProcessedBitmap *src, RenderState *rs) {
    for (size_t sr = rs->src.top, dr = rs->dest.top; sr < rs->src.bottom && dr < rs->dest.bottom; sr++, dr++) {
        pixel *dest_row = rs->output + rs->output_width * dr;
        uint8_t *src_row = src->buf + src->stride * sr;
        for (size_t sc = rs->src.left, dc = rs->dest.left; sc < rs->src.right && dc < rs->dest.right; sc++, dc++) {
            pixel fg = premult_pixel(rs->fg, src_row[sc]);
            dest_row[dc] = alpha_blend_premult(fg, dest_row[dc]);
        }
    }
}

static inline void
populate_processed_bitmap(FT_GlyphSlotRec *slot, FT_Bitmap *bitmap, ProcessedBitmap *ans) {
    ans->stride = bitmap->pitch < 0 ? -bitmap->pitch : bitmap->pitch;
    ans->rows = bitmap->rows;
    ans->start_x = 0; ans->width = bitmap->width;
    ans->pixel_mode = bitmap->pixel_mode;
    ans->bitmap_top = slot->bitmap_top; ans->bitmap_left = slot->bitmap_left;
    ans->buf = bitmap->buffer;
}

static bool
render_run(RenderState *rs) {
    hb_buffer_guess_segment_properties(hb_buffer);
    if (!HB_DIRECTION_IS_HORIZONTAL(hb_buffer_get_direction(hb_buffer))) {
        PyErr_SetString(PyExc_ValueError, "Vertical text is not supported");
        return false;
    }
    FT_Face face = rs->current_face->freetype;
    bool has_color = FT_HAS_COLOR(face);
    FT_UInt pixel_size = rs->sz_px;
    set_pixel_size(rs->current_face, pixel_size, has_color);
    hb_shape(rs->current_face->hb, hb_buffer, NULL, 0);
    unsigned int len = hb_buffer_get_length(hb_buffer);
    hb_glyph_info_t *info = hb_buffer_get_glyph_infos(hb_buffer, NULL);
    hb_glyph_position_t *positions = hb_buffer_get_glyph_positions(hb_buffer, NULL);
    int baseline = font_units_to_pixels_y(face, face->ascender);
    int load_flags = get_load_flags(rs->current_face->hinting, rs->current_face->hintstyle, has_color ? FT_LOAD_COLOR : FT_LOAD_RENDER);

    for (unsigned int i = 0; i < len; i++) {
        rs->x += (float)positions[i].x_offset / 64.0f;
        rs->y += (float)positions[i].y_offset / 64.0f;
        if (rs->x > rs->output_width) break;
        int error = FT_Load_Glyph(face, info[i].codepoint, load_flags);
        if (error) {
            set_freetype_error("Failed loading glyph", error);
            PyErr_Print();
            continue;
        };
        ProcessedBitmap pbm = {.factor=1};
        switch(face->glyph->bitmap.pixel_mode) {
            case FT_PIXEL_MODE_BGRA: {
                populate_processed_bitmap(face->glyph, &face->glyph->bitmap, &pbm);
                setup_regions(&pbm, rs, baseline);
                render_color_bitmap(&pbm, rs);
            }
                break;
            case FT_PIXEL_MODE_MONO: {
                FT_Bitmap bitmap;
                freetype_convert_mono_bitmap(&face->glyph->bitmap, &bitmap);
                populate_processed_bitmap(face->glyph, &bitmap, &pbm);
                setup_regions(&pbm, rs, baseline);
                render_gray_bitmap(&pbm, rs);
                FT_Bitmap_Done(freetype_library(), &bitmap);
            }
                break;
            case FT_PIXEL_MODE_GRAY:
                populate_processed_bitmap(face->glyph, &face->glyph->bitmap, &pbm);
                setup_regions(&pbm, rs, baseline);
                render_gray_bitmap(&pbm, rs);
                break;
            default:
                PyErr_Format(PyExc_TypeError, "Unknown FreeType bitmap type: %x", face->glyph->bitmap.pixel_mode);
                return false;
                break;
        }
        rs->x += (float)positions[i].x_advance / 64.0f;
    }

    return true;
}

static Face*
find_fallback_font_for(char_type codep, char_type next_codep) {
    if (glyph_id_for_codepoint(&main_face, codep) > 0) return &main_face;
    for (size_t i = 0; i < main_face.count; i++) {
        if (glyph_id_for_codepoint(main_face.fallbacks + i, codep) > 0) return main_face.fallbacks + i;
    }
    FontConfigFace q;
    bool prefer_color = false;
    char_type string[3] = {codep, next_codep, 0};
    if (wcswidth_string(string) >= 2 && is_emoji_presentation_base(codep)) prefer_color = true;
    if (!fallback_font(codep, main_face_family.name, main_face_family.bold, main_face_family.italic, prefer_color, &q)) return NULL;
    ensure_space_for(&main_face, fallbacks, Face, main_face.count + 1, capacity, 8, true);
    Face *ans = main_face.fallbacks + main_face.count;
    bool ok = load_font(&q, ans);
    free(q.path);
    if (!ok) return NULL;
    main_face.count++;
    return ans;
}

static bool
process_codepoint(RenderState *rs, char_type codep, char_type next_codep) {
    bool add_to_current_buffer = false;
    Face *fallback_font = NULL;
    if (is_combining_char(codep)) {
        add_to_current_buffer = true;
    } if (glyph_id_for_codepoint(&main_face, codep) > 0) {
        add_to_current_buffer = rs->current_face == &main_face;
        if (!add_to_current_buffer) fallback_font = &main_face;
    } else {
        if (glyph_id_for_codepoint(rs->current_face, codep) > 0) fallback_font = rs->current_face;
        else fallback_font = find_fallback_font_for(codep, next_codep);
        add_to_current_buffer = !fallback_font || rs->current_face == fallback_font;
    }
    if (!add_to_current_buffer) {
        if (rs->pending_in_buffer) {
            if (!render_run(rs)) return false;
            rs->pending_in_buffer = 0;
            hb_buffer_clear_contents(hb_buffer);
        }
        if (fallback_font) rs->current_face = fallback_font;
    }
    hb_buffer_add_utf32(hb_buffer, &codep, 1, 0, 1);
    rs->pending_in_buffer += 1;
    return true;
}

bool
render_single_line(const char *text, unsigned sz_px, pixel fg, pixel bg, uint8_t *output_buf, size_t width, size_t height, float x_offset, float y_offset) {
    if (!ensure_state()) return false;
    bool has_text = text && text[0];
    pixel pbg = premult_pixel(bg, ((bg >> 24) & 0xff));
    for (pixel *px = (pixel*)output_buf, *end = ((pixel*)output_buf) + width * height; px < end; px++) *px = pbg;
    if (!has_text) return true;
    hb_buffer_clear_contents(hb_buffer);
    if (!hb_buffer_pre_allocate(hb_buffer, 512)) { PyErr_NoMemory(); return false; }

    size_t text_len = strlen(text);
    char_type *unicode = calloc(sizeof(char_type), text_len + 1);
    if (!unicode) { PyErr_NoMemory(); return false; }
    bool ok = false;
    text_len = decode_utf8_string(text, text_len, unicode);
    RenderState rs = {
        .current_face = &main_face, .fg = fg, .bg = bg, .output_width = width, .output_height = height,
        .output = (pixel*)output_buf, .x = x_offset, .y = y_offset, .sz_px = sz_px
    };

    for (size_t i = 0; i < text_len && rs.x < rs.output_width; i++) {
        if (!process_codepoint(&rs, unicode[i], unicode[i + 1])) goto end;
    }
    if (rs.pending_in_buffer && rs.x < rs.output_width) {
        if (!render_run(&rs)) goto end;
        rs.pending_in_buffer = 0;
        hb_buffer_clear_contents(hb_buffer);
    }
    ok = true;
end:
    free(unicode);
    return ok;
}


static PyObject*
render_line(PyObject *self UNUSED, PyObject *args, PyObject *kw) {
    // use for testing as below
    // kitty +runpy "from kitty.fast_data_types import *; open('/tmp/test.rgba', 'wb').write(freetype_render_line())" && convert -size 800x120 -depth 8 /tmp/test.rgba /tmp/test.png && icat /tmp/test.png
    const char *text = "Test 猫 H🐱H rendering", *family = NULL;
    unsigned int width = 800, height = 120;
    int bold = 0, italic = 0;
    unsigned long fg = 0, bg = 0xfffefefe;
    float x_offset = 0, y_offset = 0;
    static const char* kwlist[] = {"text", "width", "height", "font_family", "bold", "italic", "fg", "bg", "x_offset", "y_offset", NULL};
    if (!PyArg_ParseTupleAndKeywords(args, kw, "|sIIzppkkff", (char**)kwlist, &text, &width, &height, &family, &bold, &italic, &fg, &bg, &x_offset, &y_offset)) return NULL;
    if (family) set_main_face_family(family, bold, italic);
    PyObject *ans = PyBytes_FromStringAndSize(NULL, width * height * 4);
    if (!ans) return NULL;
    uint8_t *buffer = (u_int8_t*) PyBytes_AS_STRING(ans);
    if (!render_single_line(text, 3 * height / 4, 0, 0xffffffff, buffer, width, height, x_offset, y_offset)) {
        Py_CLEAR(ans);
        if (!PyErr_Occurred()) PyErr_SetString(PyExc_RuntimeError, "Unknown error while rendering text");
        ans = NULL;
    } else {
        // remove pre-multiplication and convert to ABGR which is what the ImageMagick .rgba filetype wants
        for (pixel *p = (pixel*)buffer, *end = (pixel*)(buffer + PyBytes_GET_SIZE(ans)); p < end; p++) {
            const uint16_t a = (*p >> 24) & 0xff;
            if (!a) continue;
            uint16_t r = (*p >> 16) & 0xff, g = (*p >> 8) & 0xff, b = *p & 0xff;
#define c(x) (((x * 255) / a))
            *p = ARGB(a, c(b), c(g), c(r));
#undef c
        }
    }
    return ans;
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
    if (!fallback_font(ch, family, bold, italic, false, &f)) return NULL;
    PyObject *ret = Py_BuildValue("{ss si si si}", "path", f.path, "index", f.index, "hinting", f.hinting, "hintstyle", f.hintstyle);
    free(f.path);
    return ret;
}

static PyMethodDef module_methods[] = {
    {"fontconfig_path_for_font", (PyCFunction)(void (*) (void))(path_for_font), METH_VARARGS, NULL},
    {"fontconfig_fallback_for_char", (PyCFunction)(void (*) (void))(fallback_for_char), METH_VARARGS, NULL},
    {"freetype_render_line", (PyCFunction)(void (*) (void))(render_line), METH_VARARGS | METH_KEYWORDS, NULL},

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
