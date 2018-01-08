/*
 * freetype.c
 * Copyright (C) 2016 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#include "fonts.h"
#include "state.h"
#include <math.h>
#include <structmember.h>
#include <ft2build.h>
#include <hb-ft.h>

#if HB_VERSION_MAJOR > 1 || (HB_VERSION_MAJOR == 1 && (HB_VERSION_MINOR > 6 || (HB_VERSION_MINOR == 6 && HB_VERSION_MICRO >= 3)))
#define HARFBUZZ_HAS_CHANGE_FONT
#endif

#include FT_FREETYPE_H
typedef struct {
    PyObject_HEAD

    FT_Face face;
    unsigned int units_per_EM;
    int ascender, descender, height, max_advance_width, max_advance_height, underline_position, underline_thickness;
    int hinting, hintstyle, index;
    bool is_scalable, has_color;
    float size_in_pts;
    FT_F26Dot6 char_width, char_height;
    FT_UInt xdpi, ydpi;
    PyObject *path;
    hb_font_t *harfbuzz_font;
    void *extra_data;
    free_extra_data_func free_extra_data;
    float apple_leading;
} Face;
PyTypeObject Face_Type;

static PyObject* FreeType_Exception = NULL;

void
set_freetype_error(const char* prefix, int err_code) {
    int i = 0;
#undef FTERRORS_H_
#undef __FTERRORS_H__
#define FT_ERRORDEF( e, v, s )  { e, s },
#define FT_ERROR_START_LIST     {
#define FT_ERROR_END_LIST       { 0, NULL } };

    static const struct {
        int          err_code;
        const char*  err_msg;
    } ft_errors[] =

#ifdef FT_ERRORS_H
#include FT_ERRORS_H
#else
    FT_ERROR_START_LIST FT_ERROR_END_LIST
#endif

    while(ft_errors[i].err_msg != NULL) {
        if (ft_errors[i].err_code == err_code) {
            PyErr_Format(FreeType_Exception, "%s %s", prefix, ft_errors[i].err_msg);
            return;
        }
        i++;
    }
    PyErr_Format(FreeType_Exception, "%s (error code: %d)", prefix, err_code);
}

static FT_Library  library;

#define CALC_CELL_HEIGHT(self) font_units_to_pixels(self, self->height)

static inline int
font_units_to_pixels(Face *self, int x) {
    return ceil((double)FT_MulFix(x, self->face->size->metrics.y_scale) / 64.0);
}

static inline bool
set_font_size(Face *self, FT_F26Dot6 char_width, FT_F26Dot6 char_height, FT_UInt xdpi, FT_UInt ydpi, unsigned int desired_height) {
    int error = FT_Set_Char_Size(self->face, 0, char_height, xdpi, ydpi);
    if (!error) {
        unsigned int ch = CALC_CELL_HEIGHT(self);
        if (desired_height && ch != desired_height) {
            FT_F26Dot6 h = floor((double)char_height * (double)desired_height / (double) ch);
            return set_font_size(self, 0, h, xdpi, ydpi, 0);
        }
        self->char_width = char_width; self->char_height = char_height; self->xdpi = xdpi; self->ydpi = ydpi;
        if (self->harfbuzz_font != NULL) {
#ifdef HARFBUZZ_HAS_CHANGE_FONT
            hb_ft_font_changed(self->harfbuzz_font);
#else
            hb_font_set_scale(
                self->harfbuzz_font,
                (int) (((uint64_t) self->face->size->metrics.x_scale * (uint64_t) self->face->units_per_EM + (1u<<15)) >> 16),
                (int) (((uint64_t) self->face->size->metrics.y_scale * (uint64_t) self->face->units_per_EM + (1u<<15)) >> 16)
            );
#endif
        }
    } else {
        if (!self->is_scalable && self->face->num_fixed_sizes > 0) {
            int32_t min_diff = INT32_MAX;
            if (desired_height == 0) desired_height = global_state.cell_height;
            if (desired_height == 0) {
                desired_height = ceil(((double)char_height / 64.) * (double)ydpi / 72.);
                desired_height += ceil(0.2 * desired_height);
            }
            FT_Int strike_index = -1;
            for (FT_Int i = 0; i < self->face->num_fixed_sizes; i++) {
                int h = self->face->available_sizes[i].height;
                int32_t diff = h < (int32_t)desired_height ? (int32_t)desired_height - h : h - (int32_t)desired_height;
                if (diff < min_diff) {
                    min_diff = diff;
                    strike_index = i;
                }
            }
            if (strike_index > -1) {
                error = FT_Select_Size(self->face, strike_index);
                if (error) { set_freetype_error("Failed to set char size for non-scalable font, with error:", error); return false; }
                return true;
            }
        }
        set_freetype_error("Failed to set char size, with error:", error);
        return false;
    }
    return !error;
}

bool
set_size_for_face(PyObject *s, unsigned int desired_height, bool force) {
    Face *self = (Face*)s;
    FT_F26Dot6 w = (FT_F26Dot6)(ceil(global_state.font_sz_in_pts * 64.0));
    FT_UInt xdpi = (FT_UInt)global_state.logical_dpi_x, ydpi = (FT_UInt)global_state.logical_dpi_y;
    if (!force && (self->char_width == w && self->char_height == w && self->xdpi == xdpi && self->ydpi == ydpi)) return true;
    ((Face*)self)->size_in_pts = global_state.font_sz_in_pts;
    return set_font_size(self, w, w, xdpi, ydpi, desired_height);
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


static inline bool
init_ft_face(Face *self, PyObject *path, int hinting, int hintstyle) {
#define CPY(n) self->n = self->face->n;
    CPY(units_per_EM); CPY(ascender); CPY(descender); CPY(height); CPY(max_advance_width); CPY(max_advance_height); CPY(underline_position); CPY(underline_thickness);
#undef CPY
    self->is_scalable = FT_IS_SCALABLE(self->face);
    self->has_color = FT_HAS_COLOR(self->face);
    self->hinting = hinting; self->hintstyle = hintstyle;
    if (!set_size_for_face((PyObject*)self, 0, false)) return false;
    self->harfbuzz_font = hb_ft_font_create(self->face, NULL);
    if (self->harfbuzz_font == NULL) { PyErr_NoMemory(); return false; }
    hb_ft_font_set_load_flags(self->harfbuzz_font, get_load_flags(self->hinting, self->hintstyle, FT_LOAD_DEFAULT));

    self->path = path;
    Py_INCREF(self->path);
    self->index = self->face->face_index & 0xFFFF;
    return true;
}

PyObject*
ft_face_from_data(const uint8_t* data, size_t sz, void *extra_data, free_extra_data_func fed, PyObject *path, int hinting, int hintstyle, float apple_leading) {
    Face *ans = (Face*)Face_Type.tp_alloc(&Face_Type, 0);
    if (ans == NULL) return NULL;
    int error = FT_New_Memory_Face(library, data, sz, 0, &ans->face);
    if(error) { set_freetype_error("Failed to load memory face, with error:", error); Py_CLEAR(ans); return NULL; }
    if (!init_ft_face(ans, path, hinting, hintstyle)) { Py_CLEAR(ans); return NULL; }
    ans->extra_data = extra_data;
    ans->free_extra_data = fed;
    ans->apple_leading = apple_leading;
    return (PyObject*)ans;
}

static inline bool
load_from_path_and_psname(const char *path, const char* psname, Face *ans) {
    int error, num_faces, index = 0;
    error = FT_New_Face(library, path, index, &ans->face);
    if (error) { set_freetype_error("Failed to load face, with error:", error); ans->face = NULL; return false; }
    num_faces = ans->face->num_faces;
    if (num_faces < 2) return true;
    do {
        if (ans->face) {
            if (!psname || strcmp(FT_Get_Postscript_Name(ans->face), psname) == 0) return true;
            FT_Done_Face(ans->face); ans->face = NULL;
        }
        error = FT_New_Face(library, path, ++index, &ans->face);
        if (error) ans->face = NULL;
    } while(index < num_faces);
    PyErr_Format(PyExc_ValueError, "No face matching the postscript name: %s found in: %s", psname, path);
    return false;
}

PyObject*
ft_face_from_path_and_psname(PyObject* path, const char* psname, void *extra_data, free_extra_data_func fed, int hinting, int hintstyle, float apple_leading) {
    if (PyUnicode_READY(path) != 0) return NULL;
    Face *ans = (Face*)Face_Type.tp_alloc(&Face_Type, 0);
    if (!ans) return NULL;
    if (!load_from_path_and_psname(PyUnicode_AsUTF8(path), psname, ans)) { Py_CLEAR(ans); return NULL; }
    if (!init_ft_face(ans, path, hinting, hintstyle)) { Py_CLEAR(ans); return NULL; }
    ans->extra_data = extra_data;
    ans->free_extra_data = fed;
    ans->apple_leading = apple_leading;
    return (PyObject*)ans;
}

PyObject*
face_from_descriptor(PyObject *descriptor) {
#define D(key, conv) { PyObject *t = PyDict_GetItemString(descriptor, #key); if (t == NULL) return NULL; key = conv(t); t = NULL; }
    char *path;
    long index;
    bool hinting;
    long hint_style;
    D(path, PyUnicode_AsUTF8);
    D(index, PyLong_AsLong);
    D(hinting, PyObject_IsTrue);
    D(hint_style, PyLong_AsLong);
#undef D
    Face *self = (Face *)Face_Type.tp_alloc(&Face_Type, 0);
    if (self != NULL) {
        int error = FT_New_Face(library, path, index, &(self->face));
        if(error) { set_freetype_error("Failed to load face, with error:", error); Py_CLEAR(self); return NULL; }
        if (!init_ft_face(self, PyDict_GetItemString(descriptor, "path"), hinting, hint_style)) { Py_CLEAR(self); return NULL; }
    }
    return (PyObject*)self;
}

PyObject*
face_from_path(const char *path, int index) {
    Face *ans = (Face*)Face_Type.tp_alloc(&Face_Type, 0);
    if (ans == NULL) return NULL;
    int error;
    error = FT_New_Face(library, path, index, &ans->face);
    if (error) { set_freetype_error("Failed to load face, with error:", error); ans->face = NULL; return NULL; }
    if (!init_ft_face(ans, Py_None, true, 3)) { Py_CLEAR(ans); return NULL; }
    return (PyObject*)ans;
}

static void
dealloc(Face* self) {
    if (self->harfbuzz_font) hb_font_destroy(self->harfbuzz_font);
    if (self->face) FT_Done_Face(self->face);
    if (self->extra_data && self->free_extra_data) self->free_extra_data(self->extra_data);
    Py_CLEAR(self->path);
    Py_TYPE(self)->tp_free((PyObject*)self);
}

static PyObject *
repr(Face *self) {
    return PyUnicode_FromFormat(
        "Face(family=%s, style=%s, ps_name=%s, path=%S, index=%d, is_scalable=%S, has_color=%S, ascender=%i, descender=%i, height=%i, underline_position=%i, underline_thickness=%i)",
        self->face->family_name ? self->face->family_name : "", self->face->style_name ? self->face->style_name : "",
        FT_Get_Postscript_Name(self->face),
        self->path, self->index, self->is_scalable ? Py_True : Py_False, self->has_color ? Py_True : Py_False,
        self->ascender, self->descender, self->height, self->underline_position, self->underline_thickness
    );
}


static inline bool
load_glyph(Face *self, int glyph_index, int load_type) {
    int flags = get_load_flags(self->hinting, self->hintstyle, load_type);
    int error = FT_Load_Glyph(self->face, glyph_index, flags);
    if (error) { set_freetype_error("Failed to load glyph, with error:", error); return false; }
    return true;
}

static inline unsigned int
calc_cell_width(Face *self) {
    unsigned int ans = 0;
    for (char_type i = 32; i < 128; i++) {
        int glyph_index = FT_Get_Char_Index(self->face, i);
        if (load_glyph(self, glyph_index, FT_LOAD_DEFAULT)) {
            ans = MAX(ans, (unsigned long)ceilf((float)self->face->glyph->metrics.horiAdvance / 64.f));
        }
    }
    return ans;
}

void
cell_metrics(PyObject *s, unsigned int* cell_width, unsigned int* cell_height, unsigned int* baseline, unsigned int* underline_position, unsigned int* underline_thickness) {
    Face *self = (Face*)s;
    *cell_width = calc_cell_width(self);
    *cell_height = CALC_CELL_HEIGHT(self);
    *baseline = font_units_to_pixels(self, self->ascender);
    *underline_position = MIN(*cell_height - 1, (unsigned int)font_units_to_pixels(self, MAX(0, self->ascender - self->underline_position)));
    *underline_thickness = MAX(1, font_units_to_pixels(self, self->underline_thickness));
}

unsigned int
glyph_id_for_codepoint(PyObject *s, char_type cp) {
    return FT_Get_Char_Index(((Face*)s)->face, cp);
}

hb_font_t*
harfbuzz_font_for_face(PyObject *self) { return ((Face*)self)->harfbuzz_font; }


typedef struct {
    unsigned char* buf;
    size_t start_x, width, stride;
    size_t rows;
    FT_Pixel_Mode pixel_mode;
    bool needs_free;
    unsigned int factor, right_edge;
} ProcessedBitmap;


static inline void
trim_borders(ProcessedBitmap *ans, size_t extra) {
    bool column_has_text = false;

    // Trim empty columns from the right side of the bitmap
    for (ssize_t x = ans->width - 1; !column_has_text && x > -1 && extra > 0; x--) {
        for (size_t y = 0; y < ans->rows && !column_has_text; y++) {
            if (ans->buf[x + y * ans->stride] > 200) column_has_text = true;
        }
        if (!column_has_text) { ans->width--; extra--; }
    }

    ans->start_x = extra;
    ans->width -= extra;
}


static inline bool
render_bitmap(Face *self, int glyph_id, ProcessedBitmap *ans, unsigned int cell_width, unsigned int cell_height, unsigned int num_cells, bool bold, bool italic, bool rescale) {
    if (!load_glyph(self, glyph_id, FT_LOAD_RENDER)) return false;
    unsigned int max_width = cell_width * num_cells;
    FT_Bitmap *bitmap = &self->face->glyph->bitmap;
    ans->buf = bitmap->buffer;
    ans->start_x = 0; ans->width = bitmap->width;
    ans->stride = bitmap->pitch < 0 ? -bitmap->pitch : bitmap->pitch;
    ans->rows = bitmap->rows;
    ans->pixel_mode = bitmap->pixel_mode;
    if (ans->width > max_width) {
        size_t extra = bitmap->width - max_width;
        if (italic && extra < cell_width / 2) {
            trim_borders(ans, extra);
        } else if (rescale && self->is_scalable && extra > MAX(2, cell_width / 4)) {
            FT_F26Dot6 char_width = self->char_width, char_height = self->char_height;
            float ar = (float)max_width / (float)bitmap->width;
            if (set_font_size(self, (FT_F26Dot6)((float)self->char_width * ar), (FT_F26Dot6)((float)self->char_height * ar), self->xdpi, self->ydpi, 0)) {
                if (!render_bitmap(self, glyph_id, ans, cell_width, cell_height, num_cells, bold, italic, false)) return false;
                if (!set_font_size(self, char_width, char_height, self->xdpi, self->ydpi, 0)) return false;
            } else return false;
        }
    }
    return true;
}

static void
downsample_bitmap(ProcessedBitmap *bm, unsigned int width, unsigned int cell_height) {
    // Downsample using a simple area averaging algorithm. Could probably do
    // better with bi-cubic or lanczos, but at these small sizes I dont think
    // it matters
    float ratio = MAX((float)bm->width / width, (float)bm->rows / cell_height);
    int factor = ceilf(ratio);
    uint8_t *dest = calloc(4, width * cell_height);
    if (dest == NULL) fatal("Out of memory");
    uint8_t *d = dest;

    for (unsigned int i = 0, sr = 0; i < cell_height; i++, sr += factor) {
        for (unsigned int j = 0, sc = 0; j < width; j++, sc += factor, d += 4) {

            // calculate area average
            unsigned int r=0, g=0, b=0, a=0, count=0;
            for (unsigned int y=sr; y < MIN(sr + factor, bm->rows); y++) {
                uint8_t *p = bm->buf + (y * bm->stride) + sc * 4;
                for (unsigned int x=sc; x < MIN(sc + factor, bm->width); x++, count++) {
                    b += *(p++); g += *(p++); r += *(p++); a += *(p++);
                }
            }
            if (count) {
                d[0] = b / count; d[1] = g / count; d[2] = r / count; d[3] = a / count;
            }

        }
    }
    bm->buf = dest; bm->needs_free = true; bm->stride = 4 * width; bm->width = width; bm->rows = cell_height;
    bm->factor = factor;
}

static inline void
detect_right_edge(ProcessedBitmap *ans) {
    ans->right_edge = 0;
    for (ssize_t x = ans->width - 1; !ans->right_edge && x > -1; x--) {
        for (size_t y = 0; y < ans->rows && !ans->right_edge; y++) {
            uint8_t *p = ans->buf + x * 4 + y * ans->stride;
            if (p[3] > 20) ans->right_edge = x;
        }
    }
}

static inline bool
render_color_bitmap(Face *self, int glyph_id, ProcessedBitmap *ans, unsigned int cell_width, unsigned int cell_height, unsigned int num_cells, unsigned int baseline) {
    (void)baseline;
    unsigned short best = 0, diff = USHRT_MAX;
    for (short i = 0; i < self->face->num_fixed_sizes; i++) {
        unsigned short w = self->face->available_sizes[i].width;
        unsigned short d = w > (unsigned short)cell_width ? w - (unsigned short)cell_width : (unsigned short)cell_width - w;
        if (d < diff) {
            diff = d;
            best = i;
        }
    }
    FT_Error error = FT_Select_Size(self->face, best);
    if (error) { set_freetype_error("Failed to set char size for non-scalable font, with error:", error); return false; }
    if (!load_glyph(self, glyph_id, FT_LOAD_COLOR)) return false;
    FT_Set_Char_Size(self->face, 0, self->char_height, self->xdpi, self->ydpi);
    FT_Bitmap *bitmap = &self->face->glyph->bitmap;
    if (bitmap->pixel_mode != FT_PIXEL_MODE_BGRA) return false;
    ans->buf = bitmap->buffer;
    ans->start_x = 0; ans->width = bitmap->width;
    ans->stride = bitmap->pitch < 0 ? -bitmap->pitch : bitmap->pitch;
    ans->rows = bitmap->rows;
    ans->pixel_mode = bitmap->pixel_mode;
    if (ans->width > num_cells * cell_width + 2) downsample_bitmap(ans, num_cells * cell_width, cell_height);
    detect_right_edge(ans);
    return true;
}


static inline void
copy_color_bitmap(uint8_t *src, pixel* dest, Region *src_rect, Region *dest_rect, size_t src_stride, size_t dest_stride) {
    for (size_t sr = src_rect->top, dr = dest_rect->top; sr < src_rect->bottom && dr < dest_rect->bottom; sr++, dr++) {
        pixel *d = dest + dest_stride * dr;
        uint8_t *s = src + src_stride * sr;
        for(size_t sc = src_rect->left, dc = dest_rect->left; sc < src_rect->right && dc < dest_rect->right; sc++, dc++) {
            uint8_t *bgra = s + 4 * sc;
            if (bgra[3]) {
#define C(idx, shift) ( (uint8_t)(((float)bgra[idx] / (float)bgra[3]) * 255) << shift)
                d[dc] = C(2, 24) | C(1, 16) | C(0, 8) | bgra[3];
#undef C
        } else d[dc] = 0;
        }
    }
}

static inline void
place_bitmap_in_canvas(pixel *cell, ProcessedBitmap *bm, size_t cell_width, size_t cell_height, float x_offset, float y_offset, FT_Glyph_Metrics *metrics, size_t baseline) {
    // We want the glyph to be positioned inside the cell based on the bearingX
    // and bearingY values, making sure that it does not overflow the cell.

    Region src = { .left = bm->start_x, .bottom = bm->rows, .right = bm->width }, dest = { .bottom = cell_height, .right = cell_width };

    // Calculate column bounds
    float bearing_x = (float)metrics->horiBearingX / 64.f;
    bearing_x /= bm->factor;
    int32_t xoff = (ssize_t)(x_offset + bearing_x);
    uint32_t extra;
    if (xoff < 0) src.left += -xoff;
    else dest.left = xoff;
    // Move the dest start column back if the width overflows because of it
    if (dest.left > 0 && dest.left + bm->width > cell_width) {
        extra = dest.left + bm->width - cell_width;
        dest.left = extra > dest.left ? 0 : dest.left - extra;
    }

    // Calculate row bounds
    float bearing_y = (float)metrics->horiBearingY / 64.f;
    bearing_y /= bm->factor;
    int32_t yoff = (ssize_t)(y_offset + bearing_y);
    if ((yoff > 0 && (size_t)yoff > baseline)) {
        dest.top = 0;
    } else {
        dest.top = baseline - yoff;
    }

    /* printf("x_offset: %d bearing_x: %f y_offset: %d bearing_y: %f src_start_row: %u src_start_column: %u dest_start_row: %u dest_start_column: %u bm_width: %lu bitmap_rows: %lu\n", xoff, bearing_x, yoff, bearing_y, src.top, src.left, dest.top, dest.left, bm->width, bm->rows); */

    if (bm->pixel_mode == FT_PIXEL_MODE_BGRA) {
        copy_color_bitmap(bm->buf, cell, &src, &dest, bm->stride, cell_width);
    } else render_alpha_mask(bm->buf, cell, &src, &dest, bm->stride, cell_width);
}

static const ProcessedBitmap EMPTY_PBM = {.factor = 1};

bool
render_glyphs_in_cells(PyObject *f, bool bold, bool italic, hb_glyph_info_t *info, hb_glyph_position_t *positions, unsigned int num_glyphs, pixel *canvas, unsigned int cell_width, unsigned int cell_height, unsigned int num_cells, unsigned int baseline, bool *was_colored) {
    Face *self = (Face*)f;
    bool is_emoji = *was_colored; *was_colored = is_emoji && self->has_color;
    float x = 0.f, y = 0.f, x_offset = 0.f;
    ProcessedBitmap bm;
    unsigned int canvas_width = cell_width * num_cells;
    for (unsigned int i = 0; i < num_glyphs; i++) {
        bm = EMPTY_PBM;
        if (*was_colored) {
            if (!render_color_bitmap(self, info[i].codepoint, &bm, cell_width, cell_height, num_cells, baseline)) {
                if (PyErr_Occurred()) PyErr_Print();
                *was_colored = false;
                if (!render_bitmap(self, info[i].codepoint, &bm, cell_width, cell_height, num_cells, bold, italic, true)) return false;
            }
        } else {
            if (!render_bitmap(self, info[i].codepoint, &bm, cell_width, cell_height, num_cells, bold, italic, true)) return false;
        }
        x_offset = x + (float)positions[i].x_offset / 64.0f;
        y = (float)positions[i].y_offset / 64.0f;
        if ((*was_colored || self->face->glyph->metrics.width > 0) && bm.width > 0) place_bitmap_in_canvas(canvas, &bm, canvas_width, cell_height, x_offset, y, &self->face->glyph->metrics, baseline);
        x += (float)positions[i].x_advance / 64.0f;
        if (bm.needs_free) free(bm.buf);
    }

    // center the glyphs in the canvas
    unsigned int right_edge = (unsigned int)x, delta;
    // x_advance is wrong for colored bitmaps that have been downsampled
    if (*was_colored) right_edge = num_glyphs == 1 ? bm.right_edge : canvas_width;
    if (num_cells > 1 && right_edge < canvas_width && (delta = (canvas_width - right_edge) / 2) && delta > 1) {
        right_shift_canvas(canvas, canvas_width, cell_height, delta);
    }
    return true;
}

static PyObject*
display_name(Face *self) {
    const char *psname = FT_Get_Postscript_Name(self->face);
    if (psname) return Py_BuildValue("s", psname);
    Py_INCREF(self->path);
    return self->path;
}

static PyObject*
extra_data(Face *self) {
    return PyLong_FromVoidPtr(self->extra_data);
}

// Boilerplate {{{

static PyMemberDef members[] = {
#define MEM(name, type) {#name, type, offsetof(Face, name), READONLY, #name}
    MEM(units_per_EM, T_UINT),
    MEM(ascender, T_INT),
    MEM(descender, T_INT),
    MEM(height, T_INT),
    MEM(max_advance_width, T_INT),
    MEM(max_advance_height, T_INT),
    MEM(underline_position, T_INT),
    MEM(underline_thickness, T_INT),
    MEM(is_scalable, T_BOOL),
    MEM(path, T_OBJECT_EX),
    {NULL}  /* Sentinel */
};

static PyMethodDef methods[] = {
    METHODB(display_name, METH_NOARGS),
    METHODB(extra_data, METH_NOARGS),
    {NULL}  /* Sentinel */
};


PyTypeObject Face_Type = {
    PyVarObject_HEAD_INIT(NULL, 0)
    .tp_name = "fast_data_types.Face",
    .tp_basicsize = sizeof(Face),
    .tp_dealloc = (destructor)dealloc,
    .tp_flags = Py_TPFLAGS_DEFAULT,
    .tp_doc = "FreeType Font face",
    .tp_methods = methods,
    .tp_members = members,
    .tp_repr = (reprfunc)repr,
};

static void
free_freetype() {
    FT_Done_FreeType(library);
}

bool
init_freetype_library(PyObject *m) {
    if (PyType_Ready(&Face_Type) < 0) return 0;
    if (PyModule_AddObject(m, "Face", (PyObject *)&Face_Type) != 0) return 0;
    Py_INCREF(&Face_Type);
    FreeType_Exception = PyErr_NewException("fast_data_types.FreeTypeError", NULL, NULL);
    if (FreeType_Exception == NULL) return false;
    if (PyModule_AddObject(m, "FreeTypeError", FreeType_Exception) != 0) return false;
    int error = FT_Init_FreeType(&library);
    if (error) {
        set_freetype_error("Failed to initialize FreeType library, with error:", error);
        return false;
    }
    if (Py_AtExit(free_freetype) != 0) {
        PyErr_SetString(FreeType_Exception, "Failed to register the freetype library at exit handler");
        return false;
    }
    return true;
}

// }}}
