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
#include "char-props.h"
#include "wcswidth.h"
#include FT_BITMAP_H
#define ELLIPSIS 0x2026

typedef struct FamilyInformation {
    char *name;
    bool bold, italic;
} FamilyInformation;

typedef struct Face {
    FT_Face freetype;
    hb_font_t *hb;
    FT_UInt pixel_size;
    int hinting, hintstyle;
    struct Face **fallbacks;
    size_t count, capacity;
} Face;

typedef struct {
    unsigned char* buf;
    size_t start_x, width, stride;
    size_t rows;
    FT_Pixel_Mode pixel_mode;
    unsigned int left_edge, top_edge, bottom_edge, right_edge;
    float factor;
    int bitmap_left, bitmap_top;
} ProcessedBitmap;

typedef struct RenderCtx {
    bool created;
    Face main_face;
    FontConfigFace main_face_information;
    FamilyInformation main_face_family;
    hb_buffer_t *hb_buffer;
} RenderCtx;

#define main_face ctx->main_face
#define main_face_information ctx->main_face_information
#define main_face_family ctx->main_face_family
#define hb_buffer ctx->hb_buffer

static FT_UInt
glyph_id_for_codepoint(Face *face, char_type cp) {
    return FT_Get_Char_Index(face->freetype, cp);
}

static void
free_face(Face *face) {
    if (face->freetype) FT_Done_Face(face->freetype);
    if (face->hb) hb_font_destroy(face->hb);
    for (size_t i = 0; i < face->count; i++) { free_face(face->fallbacks[i]); free(face->fallbacks[i]); }
    free(face->fallbacks);
    memset(face, 0, sizeof(Face));
}

static void
cleanup(RenderCtx *ctx) {
    free_face(&main_face);
    free(main_face_information.path); main_face_information.path = NULL;
    free(main_face_family.name);
    memset(&main_face_family, 0, sizeof(FamilyInformation));
    if (hb_buffer) hb_buffer_destroy(hb_buffer);
    hb_buffer = NULL;
}

void
set_main_face_family(FreeTypeRenderCtx ctx_, const char *family, bool bold, bool italic) {
    RenderCtx *ctx = (RenderCtx*)ctx_;
    if (
        (family == main_face_family.name || (main_face_family.name && strcmp(family, main_face_family.name) == 0)) &&
        main_face_family.bold == bold && main_face_family.italic == italic
    ) return;
    cleanup(ctx);
    main_face_family.name = family ? strdup(family) : NULL;
    main_face_family.bold = bold; main_face_family.italic = italic;
}

static int
get_load_flags(int hinting, int hintstyle, int base) {
    int flags = base;
    if (hinting) {
        if (hintstyle >= 3) flags |= FT_LOAD_TARGET_NORMAL;
        else if (0 < hintstyle) flags |= FT_LOAD_TARGET_LIGHT;
    } else flags |= FT_LOAD_NO_HINTING;
    return flags;
}

static bool
load_font(FontConfigFace *info, Face *ans) {
    ans->freetype = native_face_from_path(info->path, info->index);
    if (!ans->freetype || PyErr_Occurred()) return false;
    ans->hb = hb_ft_font_create(ans->freetype, NULL);
    if (!ans->hb) { PyErr_NoMemory(); return false; }
    ans->hinting = info->hinting; ans->hintstyle = info->hintstyle;
    hb_ft_font_set_load_flags(ans->hb, get_load_flags(ans->hinting, ans->hintstyle, FT_LOAD_DEFAULT));
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
set_pixel_size(RenderCtx *ctx, Face *face, FT_UInt sz, bool get_metrics UNUSED) {
    if (sz != face->pixel_size) {
        if (face->freetype->num_fixed_sizes > 0 && FT_HAS_COLOR(face->freetype)) choose_bitmap_size(face->freetype, font_units_to_pixels_y(main_face.freetype, main_face.freetype->height));
        else FT_Set_Pixel_Sizes(face->freetype, sz, sz);
        hb_ft_font_changed(face->hb);
        hb_ft_font_set_load_flags(face->hb, get_load_flags(face->hinting, face->hintstyle, FT_LOAD_DEFAULT));
        face->pixel_size = sz;
    }
}


typedef struct RenderState {
    uint32_t pending_in_buffer, fg, bg;
    pixel *output;
    size_t output_width, output_height, stride;
    Face *current_face;
    float x, y, start_pos_for_current_run;
    int y_offset;
    Region src, dest;
    unsigned sz_px;
    bool truncated;
    bool horizontally_center;
} RenderState;

static void
setup_regions(ProcessedBitmap *bm, RenderState *rs, int baseline) {
    rs->src = (Region){ .left = bm->start_x, .bottom = bm->rows, .right = bm->width + bm->start_x };
    rs->dest = (Region){ .bottom = rs->output_height, .right = rs->output_width };
    int xoff = (int)(rs->x + bm->bitmap_left);
    if (xoff < 0) rs->src.left += -xoff;
    else rs->dest.left = xoff;
    if (rs->horizontally_center) {
        int run_width = (int)(rs->output_width - rs->start_pos_for_current_run);
        rs->dest.left = (int)rs->start_pos_for_current_run + (run_width > (int)bm->width ? (run_width - bm->width)/2 : 0);
    }
    int yoff = (int)(rs->y + bm->bitmap_top);
    if ((yoff > 0 && yoff > baseline)) {
        rs->dest.top = 0;
    } else {
        rs->dest.top = baseline - yoff;
    }
    rs->dest.top += rs->y_offset;
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
        pixel *dest_row = rs->output + rs->stride * dr;
        uint8_t *src_px = src->buf + src->stride * sr + 4 * rs->src.left;
        for (size_t sc = rs->src.left, dc = rs->dest.left; sc < rs->src.right && dc < rs->dest.right; sc++, dc++, src_px += 4) {
            pixel fg = premult_pixel(ARGB(src_px[3], src_px[2], src_px[1], src_px[0]), src_px[3]);
            dest_row[dc] = alpha_blend_premult(fg, dest_row[dc]);
        }
    }
}

static void
render_gray_bitmap(ProcessedBitmap *src, RenderState *rs) {
    for (size_t sr = rs->src.top, dr = rs->dest.top; sr < rs->src.bottom && dr < rs->dest.bottom; sr++, dr++) {
        pixel *dest_row = rs->output + rs->stride * dr;
        uint8_t *src_row = src->buf + src->stride * sr;
        for (size_t sc = rs->src.left, dc = rs->dest.left; sc < rs->src.right && dc < rs->dest.right; sc++, dc++) {
            pixel fg = premult_pixel(rs->fg, src_row[sc]);
            dest_row[dc] = alpha_blend_premult(fg, dest_row[dc]);
        }
    }
}

static void
populate_processed_bitmap(FT_GlyphSlotRec *slot, FT_Bitmap *bitmap, ProcessedBitmap *ans) {
    ans->stride = bitmap->pitch < 0 ? -bitmap->pitch : bitmap->pitch;
    ans->rows = bitmap->rows;
    ans->start_x = 0; ans->width = bitmap->width;
    ans->pixel_mode = bitmap->pixel_mode;
    ans->bitmap_top = slot->bitmap_top; ans->bitmap_left = slot->bitmap_left;
    ans->buf = bitmap->buffer;
}

static void
detect_edges(ProcessedBitmap *ans) {
#define check const uint8_t *p = ans->buf + x * 4 + y * ans->stride; if (p[3] > 20)
    ans->right_edge = 0; ans->bottom_edge = 0;
    for (ssize_t x = ans->width - 1; !ans->right_edge && x > -1; x--) {
        for (size_t y = 0; y < ans->rows && !ans->right_edge; y++) {
            check ans->right_edge = x;
        }
    }
    for (ssize_t y = ans->rows - 1; !ans->bottom_edge && y > -1; y--) {
        for (size_t x = 0; x < ans->width && !ans->bottom_edge; x++) {
            check ans->bottom_edge = y;
        }
    }
    ans->left_edge = ans->width;
    for (size_t x = 0; ans->left_edge == ans->width && x < ans->width; x++) {
        for (size_t y = 0; y < ans->rows && ans->left_edge == ans->width; y++) {
            check ans->left_edge = x;
        }
    }
    ans->top_edge = ans->rows;
    for (size_t y = 0; ans->top_edge == ans->rows && y < ans->rows; y++) {
        for (size_t x = 0; x < ans->width && ans->top_edge == ans->rows; x++) {
            check ans->top_edge = y;
        }
    }
#undef check
}

static Face*
find_fallback_font_for(RenderCtx *ctx, char_type codep, char_type next_codep) {
    if (glyph_id_for_codepoint(&main_face, codep) > 0) return &main_face;
    for (size_t i = 0; i < main_face.count; i++) {
        if (glyph_id_for_codepoint(main_face.fallbacks[i], codep) > 0) return main_face.fallbacks[i];
    }
    FontConfigFace q;
    bool prefer_color = false;
    char_type string[3] = {codep, next_codep, 0};
    if (wcswidth_string(string) >= 2 && char_props_for(codep).is_emoji_presentation_base) prefer_color = true;
    if (!fallback_font(codep, main_face_family.name, main_face_family.bold, main_face_family.italic, prefer_color, &q)) return NULL;
    ensure_space_for(&main_face, fallbacks, Face, main_face.count + 1, capacity, 8, true);
    Face *ans = calloc(1, sizeof(Face));
    if (!ans) fatal("Out of memory");
    bool ok = load_font(&q, ans);
    if (PyErr_Occurred()) PyErr_Print();
    free(q.path);
    if (!ok) { free(ans); return NULL; }
    main_face.fallbacks[main_face.count] = ans;
    main_face.count++;
    return ans;
}


static unsigned
calculate_ellipsis_width(RenderCtx *ctx) {
    Face *face = find_fallback_font_for(ctx, ELLIPSIS, 0);
    if (!face) return 0;
    set_pixel_size(ctx, face, main_face.pixel_size, false);
    int glyph_index = FT_Get_Char_Index(face->freetype, ELLIPSIS);
    if (!glyph_index) return 0;
    int error = FT_Load_Glyph(face->freetype, glyph_index, get_load_flags(face->hinting, face->hintstyle, FT_LOAD_DEFAULT));
    if (error) return 0;
    return (unsigned)ceilf((float)face->freetype->glyph->metrics.horiAdvance / 64.f);
}


static bool
render_run(RenderCtx *ctx, RenderState *rs) {
    hb_buffer_guess_segment_properties(hb_buffer);
    if (!HB_DIRECTION_IS_HORIZONTAL(hb_buffer_get_direction(hb_buffer))) {
        PyErr_SetString(PyExc_ValueError, "Vertical text is not supported");
        return false;
    }
    FT_Face face = rs->current_face->freetype;
    bool has_color = FT_HAS_COLOR(face);
    FT_UInt pixel_size = rs->sz_px;
    set_pixel_size(ctx, rs->current_face, pixel_size, false);
    hb_shape(rs->current_face->hb, hb_buffer, NULL, 0);
    unsigned int len = hb_buffer_get_length(hb_buffer);
    hb_glyph_info_t *info = hb_buffer_get_glyph_infos(hb_buffer, NULL);
    hb_glyph_position_t *positions = hb_buffer_get_glyph_positions(hb_buffer, NULL);
    int baseline = font_units_to_pixels_y(face, face->ascender);
    int load_flags = get_load_flags(rs->current_face->hinting, rs->current_face->hintstyle, FT_LOAD_RENDER | (has_color ? FT_LOAD_COLOR : 0));
    float pos = rs->x;
    unsigned int limit = len;
    for (unsigned int i = 0; i < len; i++) {
        float delta = (float)positions[i].x_offset / 64.0f + (float)positions[i].x_advance / 64.0f;
        if (pos + delta >= rs->output_width) {
            limit = i;
            break;
        }
        pos += delta;
    }
    if (limit < len) {
        unsigned ellipsis_width = calculate_ellipsis_width(ctx);
        while (pos + ellipsis_width >= rs->output_width && limit) {
            limit--;
            pos -= (float)positions[limit].x_offset / 64.0f + (float)positions[limit].x_advance / 64.0f;
        }
        rs->truncated = true;
    }

    rs->start_pos_for_current_run = rs->x;
    for (unsigned int i = 0; i < limit; i++) {
        rs->x += (float)positions[i].x_offset / 64.0f;
        rs->y += (float)positions[i].y_offset / 64.0f;
        if (rs->x > rs->output_width) break;
        int error = FT_Load_Glyph(face, info[i].codepoint, load_flags);
        if (error) {
            set_freetype_error("Failed loading glyph", error);
            PyErr_Print();
            continue;
        };
        ProcessedBitmap pbm = {0};
        switch(face->glyph->bitmap.pixel_mode) {
            case FT_PIXEL_MODE_BGRA: {
                uint8_t *buf = NULL;
                unsigned text_height = font_units_to_pixels_y(main_face.freetype, main_face.freetype->height);
                populate_processed_bitmap(face->glyph, &face->glyph->bitmap, &pbm);
                unsigned bm_width = 0, bm_height = text_height;
                if (pbm.rows > bm_height) {
                    double ratio = pbm.width / (double)pbm.rows;
                    bm_width = (unsigned)(ratio * bm_height);
                    buf = calloc((size_t)bm_height * bm_width, sizeof(pixel));
                    if (!buf) break;
                    downsample_32bit_image(pbm.buf, pbm.width, pbm.rows, pbm.stride, buf, bm_width, bm_height);
                    pbm.buf = buf; pbm.stride = 4 * bm_width; pbm.width = bm_width; pbm.rows = bm_height;
                    detect_edges(&pbm);
                }
                setup_regions(&pbm, rs, baseline);
                if (bm_width) {
                    /* printf("bottom_edge: %u top_edge: %u left_edge: %u right_edge: %u\n", */
                    /*         pbm.bottom_edge, pbm.top_edge, pbm.left_edge, pbm.right_edge); */
                    rs->src.top = pbm.top_edge; rs->src.bottom = pbm.bottom_edge + 1;
                    rs->src.left = pbm.left_edge; rs->src.right = pbm.right_edge + 1;
                    rs->dest.left = (int)(rs->x + 2);
                    positions[i].x_advance = (pbm.right_edge - pbm.left_edge + 2) * 64;
                    unsigned main_baseline = font_units_to_pixels_y(main_face.freetype, main_face.freetype->ascender);
                    unsigned symbol_height = pbm.bottom_edge - pbm.top_edge;
                    unsigned baseline_y = main_baseline + rs->y_offset, text_bottom_y = text_height + rs->y_offset;
                    if (symbol_height <= baseline_y) {
                        rs->dest.top = baseline_y - symbol_height + 2;
                    } else {
                        if (symbol_height <= text_bottom_y) rs->dest.top = text_bottom_y - symbol_height;
                        else rs->dest.top = 0;
                    }
                    rs->dest.top += main_baseline > pbm.bottom_edge ? main_baseline - pbm.bottom_edge : 0;
                    /* printf("symbol_height: %u baseline_y: %u\n", symbol_height, baseline_y); */
                }
                render_color_bitmap(&pbm, rs);
                free(buf);
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
                PyErr_Format(PyExc_TypeError, "Unknown FreeType bitmap type: 0x%x", face->glyph->bitmap.pixel_mode);
                return false;
                break;
        }
        rs->x += (float)positions[i].x_advance / 64.0f;
    }
    return true;
}

static bool
process_codepoint(RenderCtx *ctx, RenderState *rs, char_type codep, char_type next_codep) {
    bool add_to_current_buffer = false;
    Face *fallback_font = NULL;
    if (char_props_for(codep).is_combining_char) {
        add_to_current_buffer = true;
    } else if (glyph_id_for_codepoint(&main_face, codep) > 0) {
        add_to_current_buffer = rs->current_face == &main_face;
        if (!add_to_current_buffer) fallback_font = &main_face;
    } else {
        if (glyph_id_for_codepoint(rs->current_face, codep) > 0) fallback_font = rs->current_face;
        else fallback_font = find_fallback_font_for(ctx, codep, next_codep);
        add_to_current_buffer = !fallback_font || rs->current_face == fallback_font;
    }
    if (!add_to_current_buffer) {
        if (rs->pending_in_buffer) {
            if (!render_run(ctx, rs)) return false;
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
render_single_line(FreeTypeRenderCtx ctx_, const char *text, unsigned sz_px, pixel fg, pixel bg, uint8_t *output_buf, size_t width, size_t height, float x_offset, float y_offset, size_t right_margin, bool horizontally_center_runs) {
    RenderCtx *ctx = (RenderCtx*)ctx_;
    if (!ctx->created) return false;
    size_t output_width = right_margin <= width ? width - right_margin : 0;
    bool has_text = text && text[0];
    pixel pbg = premult_pixel(bg, ((bg >> 24) & 0xff));
    for (size_t y = 0; y < height; y++) {
        pixel *px = (pixel*)(output_buf + 4 * y * width);
        for (size_t x = (size_t)x_offset; x < output_width; x++) px[x] = pbg;
    }
    if (!has_text) return true;
    hb_buffer_clear_contents(hb_buffer);
    if (!hb_buffer_pre_allocate(hb_buffer, 512)) { PyErr_NoMemory(); return false; }

    size_t text_len = strlen(text);
    char_type *unicode = calloc(text_len + 1, sizeof(char_type));
    if (!unicode) { PyErr_NoMemory(); return false; }
    bool ok = false;
    text_len = decode_utf8_string(text, text_len, unicode);
    set_pixel_size(ctx, &main_face, sz_px, true);
    unsigned text_height = font_units_to_pixels_y(main_face.freetype, main_face.freetype->height);
    RenderState rs = {
        .current_face = &main_face, .fg = fg, .bg = bg, .horizontally_center = horizontally_center_runs,
        .output_width = output_width, .output_height = height, .stride = width,
        .output = (pixel*)output_buf, .x = x_offset, .y = y_offset, .sz_px = sz_px
    };
    if (text_height < height) rs.y_offset = (height - text_height) / 2;

    for (size_t i = 0; i < text_len && rs.x < rs.output_width && !rs.truncated; i++) {
        if (!process_codepoint(ctx, &rs, unicode[i], unicode[i + 1])) goto end;
    }
    if (rs.pending_in_buffer && rs.x < rs.output_width && !rs.truncated) {
        if (!render_run(ctx, &rs)) goto end;
        rs.pending_in_buffer = 0;
        hb_buffer_clear_contents(hb_buffer);
    }
    if (rs.truncated) {
        hb_buffer_clear_contents(hb_buffer);
        rs.pending_in_buffer = 0;
        rs.current_face = &main_face;
        if (!process_codepoint(ctx, &rs, ELLIPSIS, 0)) goto end;
        if (!render_run(ctx, &rs)) goto end;
    }
    ok = true;
end:
    free(unicode);
    return ok;
}

static uint8_t*
render_single_char_bitmap(const FT_Bitmap *bm, size_t *result_width, size_t *result_height) {
    *result_width = bm->width; *result_height = bm->rows;
    uint8_t *rendered = malloc(*result_width * *result_height);
    if (!rendered) { PyErr_NoMemory(); return NULL; }
    for (size_t r = 0; r < bm->rows; r++) {
        uint8_t *src_row = bm->buffer + bm->pitch * r;
        uint8_t *dest_row = rendered + *result_width * r;
        memcpy(dest_row, src_row, *result_width);
    }
    return rendered;
}

typedef struct TempFontData {
    Face *face;
    FT_UInt orig_sz;
} TempFontData;

static void
cleanup_resize(TempFontData *f) {
    if (f->face && f->face->freetype) {
        f->face->pixel_size = f->orig_sz;
        FT_Set_Pixel_Sizes(f->face->freetype, f->orig_sz, f->orig_sz);
    }
}
#define RAII_TempFontData(name) __attribute__((cleanup(cleanup_resize))) TempFontData name = {0}

static void*
report_freetype_error_for_char(int error, char ch, const char *operation) {
    char buf[128];
    snprintf(buf, sizeof(buf), "Failed to %s glyph for character: %c, with error: ", operation, ch);
    set_freetype_error(buf, error);
    return NULL;
}

uint8_t*
render_single_ascii_char_as_mask(FreeTypeRenderCtx ctx_, const char ch, size_t *result_width, size_t *result_height) {
    RenderCtx *ctx = (RenderCtx*)ctx_;
    if (!ctx->created) { PyErr_SetString(PyExc_RuntimeError, "freetype render ctx not created"); return NULL; }
    RAII_TempFontData(temp);
    Face *face = &main_face;
    int glyph_index = FT_Get_Char_Index(face->freetype, ch);
    if (!glyph_index) { PyErr_Format(PyExc_KeyError, "character %c not found in font", ch); return NULL; }
    unsigned int height = font_units_to_pixels_y(face->freetype, face->freetype->height);
    size_t avail_height = *result_height;
    if (avail_height < 4) { PyErr_Format(PyExc_ValueError, "Invalid available height: %zu", avail_height); return NULL; }
    float ratio = ((float)height) / avail_height;
    temp.face = face; temp.orig_sz = face->pixel_size;
    face->pixel_size = (FT_UInt)(face->pixel_size / ratio);
    if (face->pixel_size != temp.orig_sz) FT_Set_Pixel_Sizes(face->freetype, avail_height, avail_height);
    int error = FT_Load_Glyph(face->freetype, glyph_index, get_load_flags(face->hinting, face->hintstyle, FT_LOAD_DEFAULT));
    if (error) return report_freetype_error_for_char(error, ch, "load");
    if (face->freetype->glyph->format != FT_GLYPH_FORMAT_BITMAP) {
        error = FT_Render_Glyph(face->freetype->glyph, FT_RENDER_MODE_NORMAL);
        if (error) return report_freetype_error_for_char(error, ch, "render");
    }
    uint8_t *rendered = NULL;
    switch(face->freetype->glyph->bitmap.pixel_mode) {
        case FT_PIXEL_MODE_MONO: {
            FT_Bitmap bitmap;
            if (!freetype_convert_mono_bitmap(&face->freetype->glyph->bitmap, &bitmap)) return NULL;
            rendered = render_single_char_bitmap(&bitmap, result_width, result_height);
            FT_Bitmap_Done(freetype_library(), &bitmap);
        }
            break;
        case FT_PIXEL_MODE_GRAY:
            rendered = render_single_char_bitmap(&face->freetype->glyph->bitmap, result_width, result_height);
            break;
        default:
            PyErr_Format(PyExc_TypeError, "Unknown FreeType bitmap type: 0x%x", face->freetype->glyph->bitmap.pixel_mode);
            return false;
            break;
    }
    return rendered;
}

FreeTypeRenderCtx
create_freetype_render_context(const char *family, bool bold, bool italic) {
    RenderCtx *ctx = calloc(1, sizeof(RenderCtx));
    main_face_family.name = family ? strdup(family) : NULL;
    main_face_family.bold = bold; main_face_family.italic = italic;
    if (!information_for_font_family(main_face_family.name, main_face_family.bold, main_face_family.italic, &main_face_information)) return NULL;
    if (!load_font(&main_face_information, &main_face)) return NULL;
    hb_buffer = hb_buffer_create();
    if (!hb_buffer) { PyErr_NoMemory(); return NULL; }
    ctx->created = true;
    return (FreeTypeRenderCtx)ctx;
}

void
release_freetype_render_context(FreeTypeRenderCtx ctx) { if (ctx) { cleanup((RenderCtx*)ctx); free(ctx); } }

static PyObject*
render_line(PyObject *self UNUSED, PyObject *args, PyObject *kw) {
    // use for testing as below
    // kitty +runpy "from kitty.fast_data_types import *; open('/tmp/test.rgba', 'wb').write(freetype_render_line())" && convert -size 800x60 -depth 8 /tmp/test.rgba /tmp/test.png && icat /tmp/test.png
    const char *text = "Test 猫 H🐱🚀b rendering with ellipsis for cut off text", *family = NULL;
    unsigned int width = 800, height = 60, right_margin = 0;
    int bold = 0, italic = 0;
    unsigned long fg = 0, bg = 0xfffefefe;
    float x_offset = 0, y_offset = 0;
    static const char* kwlist[] = {"text", "width", "height", "font_family", "bold", "italic", "fg", "bg", "x_offset", "y_offset", "right_margin", NULL};
    if (!PyArg_ParseTupleAndKeywords(args, kw, "|sIIzppkkffI", (char**)kwlist, &text, &width, &height, &family, &bold, &italic, &fg, &bg, &x_offset, &y_offset, &right_margin)) return NULL;
    PyObject *ans = PyBytes_FromStringAndSize(NULL, (Py_ssize_t)width * height * 4);
    if (!ans) return NULL;
    uint8_t *buffer = (uint8_t*) PyBytes_AS_STRING(ans);
    RenderCtx *ctx = (RenderCtx*)create_freetype_render_context(family, bold, italic);
    if (!ctx) return NULL;
    if (!render_single_line((FreeTypeRenderCtx)ctx, text, 3 * height / 4, 0, 0xffffffff, buffer, width, height, x_offset, y_offset, right_margin, false)) {
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
    release_freetype_render_context((FreeTypeRenderCtx)ctx);
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
    return true;
}
