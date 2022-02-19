/*
 * core_text.c
 * Copyright (C) 2017 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#include "state.h"
#include "cleanup.h"
#include "fonts.h"
#include "unicode-data.h"
#include <structmember.h>
#include <stdint.h>
#include <math.h>
#include <hb-coretext.h>
#include <hb-ot.h>
#import <CoreGraphics/CGBitmapContext.h>
#import <CoreText/CTFont.h>
#include <Foundation/Foundation.h>
#include <CoreText/CoreText.h>
#import <Foundation/NSString.h>
#import <Foundation/NSDictionary.h>

#define debug(...) if (global_state.debug_rendering) { fprintf(stderr, __VA_ARGS__); fflush(stderr); }

typedef struct {
    PyObject_HEAD

    unsigned int units_per_em;
    float ascent, descent, leading, underline_position, underline_thickness, point_sz, scaled_point_sz;
    CTFontRef ct_font;
    hb_font_t *hb_font;
    PyObject *family_name, *full_name, *postscript_name, *path;
} CTFace;
PyTypeObject CTFace_Type;
static CTFontRef window_title_font = nil;

static char*
convert_cfstring(CFStringRef src, int free_src) {
#define SZ 4094
    static char buf[SZ+2] = {0};
    bool ok = false;
    if(!CFStringGetCString(src, buf, SZ, kCFStringEncodingUTF8)) PyErr_SetString(PyExc_ValueError, "Failed to convert CFString");
    else ok = true;
    if (free_src) CFRelease(src);
    return ok ? buf : NULL;
#undef SZ
}

static void
init_face(CTFace *self, CTFontRef font, FONTS_DATA_HANDLE fg UNUSED) {
    if (self->hb_font) hb_font_destroy(self->hb_font);
    self->hb_font = NULL;
    if (self->ct_font) CFRelease(self->ct_font);
    self->ct_font = font;
    self->units_per_em = CTFontGetUnitsPerEm(self->ct_font);
    self->ascent = CTFontGetAscent(self->ct_font);
    self->descent = CTFontGetDescent(self->ct_font);
    self->leading = CTFontGetLeading(self->ct_font);
    self->underline_position = CTFontGetUnderlinePosition(self->ct_font);
    self->underline_thickness = CTFontGetUnderlineThickness(self->ct_font);
    self->scaled_point_sz = CTFontGetSize(self->ct_font);
}

static CTFace*
ct_face(CTFontRef font, FONTS_DATA_HANDLE fg) {
    CTFace *self = (CTFace *)CTFace_Type.tp_alloc(&CTFace_Type, 0);
    if (self) {
        init_face(self, font, fg);
        self->family_name = Py_BuildValue("s", convert_cfstring(CTFontCopyFamilyName(self->ct_font), true));
        self->full_name = Py_BuildValue("s", convert_cfstring(CTFontCopyFullName(self->ct_font), true));
        self->postscript_name = Py_BuildValue("s", convert_cfstring(CTFontCopyPostScriptName(self->ct_font), true));
        NSURL *url = (NSURL*)CTFontCopyAttribute(self->ct_font, kCTFontURLAttribute);
        self->path = Py_BuildValue("s", [[url path] UTF8String]);
        [url release];
        if (self->family_name == NULL || self->full_name == NULL || self->postscript_name == NULL || self->path == NULL) { Py_CLEAR(self); }
    }
    return self;
}

static void
dealloc(CTFace* self) {
    if (self->hb_font) hb_font_destroy(self->hb_font);
    if (self->ct_font) CFRelease(self->ct_font);
    self->hb_font = NULL;
    self->ct_font = NULL;
    Py_CLEAR(self->family_name); Py_CLEAR(self->full_name); Py_CLEAR(self->postscript_name); Py_CLEAR(self->path);
    Py_TYPE(self)->tp_free((PyObject*)self);
}

static PyObject*
font_descriptor_to_python(CTFontDescriptorRef descriptor) {
    NSURL *url = (NSURL *) CTFontDescriptorCopyAttribute(descriptor, kCTFontURLAttribute);
    NSString *psName = (NSString *) CTFontDescriptorCopyAttribute(descriptor, kCTFontNameAttribute);
    NSString *family = (NSString *) CTFontDescriptorCopyAttribute(descriptor, kCTFontFamilyNameAttribute);
    NSString *style = (NSString *) CTFontDescriptorCopyAttribute(descriptor, kCTFontStyleNameAttribute);
    NSDictionary *traits = (NSDictionary *) CTFontDescriptorCopyAttribute(descriptor, kCTFontTraitsAttribute);
    unsigned int straits = [traits[(id)kCTFontSymbolicTrait] unsignedIntValue];
    float weightVal = [traits[(id)kCTFontWeightTrait] floatValue];
    float widthVal = [traits[(id)kCTFontWidthTrait] floatValue];

    PyObject *ans = Py_BuildValue("{ssssssss sOsOsOsOsOsO sfsfsI}",
            "path", [[url path] UTF8String],
            "postscript_name", [psName UTF8String],
            "family", [family UTF8String],
            "style", [style UTF8String],

            "bold", (straits & kCTFontBoldTrait) != 0 ? Py_True : Py_False,
            "italic", (straits & kCTFontItalicTrait) != 0 ? Py_True : Py_False,
            "monospace", (straits & kCTFontMonoSpaceTrait) != 0 ? Py_True : Py_False,
            "expanded", (straits & kCTFontExpandedTrait) != 0 ? Py_True : Py_False,
            "condensed", (straits & kCTFontCondensedTrait) != 0 ? Py_True : Py_False,
            "color_glyphs", (straits & kCTFontColorGlyphsTrait) != 0 ? Py_True : Py_False,

            "weight", weightVal,
            "width", widthVal,
            "traits", straits
    );
    [url release];
    [psName release];
    [family release];
    [style release];
    [traits release];
    return ans;
}

static CTFontDescriptorRef
font_descriptor_from_python(PyObject *src) {
    CTFontSymbolicTraits symbolic_traits = 0;
    NSMutableDictionary *attrs = [NSMutableDictionary dictionary];
    PyObject *t = PyDict_GetItemString(src, "traits");
    if (t == NULL) {
        symbolic_traits = (
            (PyDict_GetItemString(src, "bold") == Py_True ? kCTFontBoldTrait : 0) |
            (PyDict_GetItemString(src, "italic") == Py_True ? kCTFontItalicTrait : 0) |
            (PyDict_GetItemString(src, "monospace") == Py_True ? kCTFontMonoSpaceTrait : 0));
    } else {
        symbolic_traits = PyLong_AsUnsignedLong(t);
    }
    NSDictionary *traits = @{(id)kCTFontSymbolicTrait:[NSNumber numberWithUnsignedInt:symbolic_traits]};
    attrs[(id)kCTFontTraitsAttribute] = traits;

#define SET(x, attr) \
    t = PyDict_GetItemString(src, #x); \
    if (t) attrs[(id)attr] = @(PyUnicode_AsUTF8(t));

    SET(family, kCTFontFamilyNameAttribute);
    SET(style, kCTFontStyleNameAttribute);
    SET(postscript_name, kCTFontNameAttribute);
#undef SET

    return CTFontDescriptorCreateWithAttributes((CFDictionaryRef) attrs);
}

static CTFontCollectionRef all_fonts_collection_data = NULL;

static CTFontCollectionRef
all_fonts_collection() {
    if (all_fonts_collection_data == NULL) all_fonts_collection_data = CTFontCollectionCreateFromAvailableFonts(NULL);
    return all_fonts_collection_data;
}

static PyObject*
coretext_all_fonts(PyObject UNUSED *_self) {
    CFArrayRef matches = CTFontCollectionCreateMatchingFontDescriptors(all_fonts_collection());
    const CFIndex count = CFArrayGetCount(matches);
    PyObject *ans = PyTuple_New(count), *temp;
    if (ans == NULL) { CFRelease(matches); return PyErr_NoMemory(); }
    for (CFIndex i = 0; i < count; i++) {
        temp = font_descriptor_to_python((CTFontDescriptorRef) CFArrayGetValueAtIndex(matches, i));
        if (temp == NULL) { CFRelease(matches); Py_DECREF(ans); return NULL; }
        PyTuple_SET_ITEM(ans, i, temp); temp = NULL;
    }
    CFRelease(matches);
    return ans;
}

static unsigned int
glyph_id_for_codepoint_ctfont(CTFontRef ct_font, char_type ch) {
    unichar chars[2] = {0};
    CGGlyph glyphs[2] = {0};
    int count = CFStringGetSurrogatePairForLongCharacter(ch, chars) ? 2 : 1;
    CTFontGetGlyphsForCharacters(ct_font, chars, glyphs, count);
    return glyphs[0];
}

static bool
is_last_resort_font(CTFontRef new_font) {
    CFStringRef name = CTFontCopyPostScriptName(new_font);
    CFComparisonResult cr = CFStringCompare(name, CFSTR("LastResort"), 0);
    CFRelease(name);
    return cr == kCFCompareEqualTo;
}

static CTFontRef
manually_search_fallback_fonts(CTFontRef current_font, CPUCell *cell) {
    CFArrayRef fonts = CTFontCollectionCreateMatchingFontDescriptors(all_fonts_collection());
    CTFontRef ans = NULL;
    const CFIndex count = CFArrayGetCount(fonts);
    for (CFIndex i = 0; i < count; i++) {
        CTFontDescriptorRef descriptor = (CTFontDescriptorRef)CFArrayGetValueAtIndex(fonts, i);
        CTFontRef new_font = CTFontCreateWithFontDescriptor(descriptor, CTFontGetSize(current_font), NULL);
        if (new_font) {
            if (!is_last_resort_font(new_font)) {
                char_type ch = cell->ch ? cell->ch : ' ';
                bool found = true;
                if (!glyph_id_for_codepoint_ctfont(new_font, ch)) found = false;
                for (unsigned i = 0; i < arraysz(cell->cc_idx) && cell->cc_idx[i] && found; i++) {
                    ch = codepoint_for_mark(cell->cc_idx[i]);
                    if (!glyph_id_for_codepoint_ctfont(new_font, ch)) found = false;
                }
                if (found) {
                    ans = new_font;
                    break;
                }
            }
            CFRelease(new_font);
        }
    }
    CFRelease(fonts);
    return ans;
}

static CTFontRef
find_substitute_face(CFStringRef str, CTFontRef old_font, CPUCell *cpu_cell) {
    // CTFontCreateForString returns the original font when there are combining
    // diacritics in the font and the base character is in the original font,
    // so we have to check each character individually
    CFIndex len = CFStringGetLength(str), start = 0, amt = len;
    while (start < len) {
        CTFontRef new_font = CTFontCreateForString(old_font, str, CFRangeMake(start, amt));
        if (amt == len && len != 1) amt = 1;
        else start++;
        if (new_font == NULL) { PyErr_SetString(PyExc_ValueError, "Failed to find fallback CTFont"); return NULL; }
        if (new_font == old_font) { CFRelease(new_font); continue; }
        if (is_last_resort_font(new_font)) {
            CFRelease(new_font);
            if (is_private_use(cpu_cell->ch)) {
                // CoreTexts fallback font mechanism does not work for private use characters
                new_font = manually_search_fallback_fonts(old_font, cpu_cell);
                if (new_font) return new_font;
            }
            PyErr_SetString(PyExc_ValueError, "Failed to find fallback CTFont other than the LastResort font");
            return NULL;
        }
        return new_font;
    }
    PyErr_SetString(PyExc_ValueError, "CoreText returned the same font as a fallback font");
    return NULL;
}

PyObject*
create_fallback_face(PyObject *base_face, CPUCell* cell, bool UNUSED bold, bool UNUSED italic, bool emoji_presentation, FONTS_DATA_HANDLE fg) {
    CTFace *self = (CTFace*)base_face;
    CTFontRef new_font;
#define search_for_fallback() \
        char text[64] = {0}; \
        cell_as_utf8_for_fallback(cell, text); \
        CFStringRef str = CFStringCreateWithCString(NULL, text, kCFStringEncodingUTF8); \
        if (str == NULL) return PyErr_NoMemory(); \
        new_font = find_substitute_face(str, self->ct_font, cell); \
        CFRelease(str);

    if (emoji_presentation) {
        new_font = CTFontCreateWithName((CFStringRef)@"AppleColorEmoji", self->scaled_point_sz, NULL);
        if (!new_font || !glyph_id_for_codepoint_ctfont(new_font, cell->ch)) {
            if (new_font) CFRelease(new_font);
            search_for_fallback();
        }
    }
    else { search_for_fallback(); }
    if (new_font == NULL) return NULL;
    return (PyObject*)ct_face(new_font, fg);
}

unsigned int
glyph_id_for_codepoint(PyObject *s, char_type ch) {
    CTFace *self = (CTFace*)s;
    return glyph_id_for_codepoint_ctfont(self->ct_font, ch);
}

bool
is_glyph_empty(PyObject *s, glyph_index g) {
    CTFace *self = (CTFace*)s;
    CGGlyph gg = g;
    CGRect bounds;
    CTFontGetBoundingRectsForGlyphs(self->ct_font, kCTFontOrientationHorizontal, &gg, &bounds, 1);
    return bounds.size.width <= 0;
}

int
get_glyph_width(PyObject *s, glyph_index g) {
    CTFace *self = (CTFace*)s;
    CGGlyph gg = g;
    CGRect bounds;
    CTFontGetBoundingRectsForGlyphs(self->ct_font, kCTFontOrientationHorizontal, &gg, &bounds, 1);
    return (int)ceil(bounds.size.width);
}

static float
scaled_point_sz(FONTS_DATA_HANDLE fg) {
    return ((fg->logical_dpi_x + fg->logical_dpi_y) / 144.0) * fg->font_sz_in_pts;
}

bool
set_size_for_face(PyObject *s, unsigned int UNUSED desired_height, bool force, FONTS_DATA_HANDLE fg) {
    CTFace *self = (CTFace*)s;
    float sz = scaled_point_sz(fg);
    if (!force && self->scaled_point_sz == sz) return true;
    CTFontRef new_font = CTFontCreateCopyWithAttributes(self->ct_font, sz, NULL, NULL);
    if (new_font == NULL) fatal("Out of memory");
    init_face(self, new_font, fg);
    return true;
}

hb_font_t*
harfbuzz_font_for_face(PyObject* s) {
    CTFace *self = (CTFace*)s;
    if (!self->hb_font) {
        self->hb_font = hb_coretext_font_create(self->ct_font);
        if (!self->hb_font) fatal("Failed to create hb_font");
        hb_ot_font_set_funcs(self->hb_font);
    }
    return self->hb_font;
}

static unsigned int
adjust_ypos(unsigned int pos, unsigned int cell_height, int adjustment) {
    if (adjustment >= 0) adjustment = MIN(adjustment, (int)pos - 1);
    else adjustment = MAX(adjustment, (int)pos - (int)cell_height + 1);
    return pos - adjustment;
}

void
cell_metrics(PyObject *s, unsigned int* cell_width, unsigned int* cell_height, unsigned int* baseline, unsigned int* underline_position, unsigned int* underline_thickness, unsigned int* strikethrough_position, unsigned int* strikethrough_thickness) {
    // See https://developer.apple.com/library/content/documentation/StringsTextFonts/Conceptual/TextAndWebiPhoneOS/TypoFeatures/TextSystemFeatures.html
    CTFace *self = (CTFace*)s;
#define count (128 - 32)
    unichar chars[count+1] = {0};
    CGGlyph glyphs[count+1] = {0};
    unsigned int width = 0, w, i;
    for (i = 0; i < count; i++) chars[i] = 32 + i;
    CTFontGetGlyphsForCharacters(self->ct_font, chars, glyphs, count);
    for (i = 0; i < count; i++) {
        if (glyphs[i]) {
            w = (unsigned int)(ceilf(
                        CTFontGetAdvancesForGlyphs(self->ct_font, kCTFontOrientationHorizontal, glyphs+i, NULL, 1)));
            if (w > width) width = w;
        }
    }
    *cell_width = MAX(1u, width);
    *underline_thickness = (unsigned int)ceil(MAX(0.1, self->underline_thickness));
    *strikethrough_thickness = *underline_thickness;
    // float line_height = MAX(1, floor(self->ascent + self->descent + MAX(0, self->leading) + 0.5));
    // Let CoreText's layout engine calculate the line height. Slower, but hopefully more accurate.
#define W "AQWMH_gyl "
    CFStringRef ts = CFSTR(W W W W W W W W W W W W W W W W W W W W W W W W W W W W W W W W W W W W W W W W W W W W W W W W W W W W W W W W W W W W W W W W W W W W W W W W W W W W W W W W W W W W W W W W W W W W W W W W W W);
#undef W
    CFMutableAttributedStringRef test_string = CFAttributedStringCreateMutable(kCFAllocatorDefault, CFStringGetLength(ts));
    CFAttributedStringReplaceString(test_string, CFRangeMake(0, 0), ts);
    CFAttributedStringSetAttribute(test_string, CFRangeMake(0, CFStringGetLength(ts)), kCTFontAttributeName, self->ct_font);
    CGMutablePathRef path = CGPathCreateMutable();
    CGPathAddRect(path, NULL, CGRectMake(10, 10, 200, 200));
    CTFramesetterRef framesetter = CTFramesetterCreateWithAttributedString(test_string);
    CFRelease(test_string);
    CTFrameRef test_frame = CTFramesetterCreateFrame(framesetter, CFRangeMake(0, 0), path, NULL);
    CGPoint origin1, origin2;
    CTFrameGetLineOrigins(test_frame, CFRangeMake(0, 1), &origin1);
    CTFrameGetLineOrigins(test_frame, CFRangeMake(1, 1), &origin2);
    CGFloat line_height = origin1.y - origin2.y;
    CFArrayRef lines = CTFrameGetLines(test_frame);
    CTLineRef line = CFArrayGetValueAtIndex(lines, 0);
    CGRect bounds = CTLineGetBoundsWithOptions(line, 0);
    CGRect bounds_without_leading = CTLineGetBoundsWithOptions(line, kCTLineBoundsExcludeTypographicLeading);
    CGFloat typographic_ascent, typographic_descent, typographic_leading;
    CTLineGetTypographicBounds(line, &typographic_ascent, &typographic_descent, &typographic_leading);
    *cell_height = MAX(4u, (unsigned int)ceilf(line_height));
    CGFloat bounds_ascent = bounds_without_leading.size.height + bounds_without_leading.origin.y;
    int baseline_offset = 0;
    if (OPT(adjust_baseline_px) != 0) baseline_offset = OPT(adjust_baseline_px);
    else if (OPT(adjust_baseline_frac) != 0) baseline_offset = (int)(*cell_height * OPT(adjust_baseline_frac));
    int underline_offset = OPT(underline_offset);
    *baseline = (unsigned int)floor(bounds_ascent + 0.5);
    // Not sure if we should add this to bounds ascent and then round it or add
    // it to already rounded baseline and round again.
    *underline_position = (unsigned int)floor(bounds_ascent - self->underline_position + 0.5);
    *strikethrough_position = (unsigned int)floor(*baseline * 0.65);

    debug("Cell height calculation:\n");
    debug("\tline height from line origins: %f\n", line_height);
    debug("\tline bounds: origin-y: %f height: %f\n", bounds.origin.y, bounds.size.height);
    debug("\tline bounds-no-leading: origin-y: %f height: %f\n", bounds.origin.y, bounds.size.height);
    debug("\tbounds metrics: ascent: %f\n", bounds_ascent);
    debug("\tline metrics: ascent: %f descent: %f leading: %f\n", typographic_ascent, typographic_descent, typographic_leading);
    debug("\tfont metrics: ascent: %f descent: %f leading: %f underline_position: %f\n", self->ascent, self->descent, self->leading, self->underline_position);
    debug("\tcell_height: %u baseline: %u underline_position: %u strikethrough_position: %u\n", *cell_height, *baseline, *underline_position, *strikethrough_position);
    if (baseline_offset) {
        *baseline = adjust_ypos(*baseline, *cell_height, baseline_offset);
        *underline_position = adjust_ypos(*underline_position, *cell_height, baseline_offset);
        *strikethrough_position = adjust_ypos(*strikethrough_position, *cell_height, baseline_offset);
    }
    if (underline_offset){
        *underline_position = adjust_ypos(*underline_position, *cell_height, underline_offset);
    }

    CFRelease(test_frame); CFRelease(path); CFRelease(framesetter);

#undef count
}

PyObject*
face_from_descriptor(PyObject *descriptor, FONTS_DATA_HANDLE fg) {
    CTFontDescriptorRef desc = font_descriptor_from_python(descriptor);
    if (!desc) return NULL;
    CTFontRef font = CTFontCreateWithFontDescriptor(desc, scaled_point_sz(fg), NULL);
    CFRelease(desc); desc = NULL;
    if (!font) { PyErr_SetString(PyExc_ValueError, "Failed to create CTFont object"); return NULL; }
    return (PyObject*) ct_face(font, fg);
}

PyObject*
face_from_path(const char *path, int UNUSED index, FONTS_DATA_HANDLE fg) {
    CFStringRef s = CFStringCreateWithCString(NULL, path, kCFStringEncodingUTF8);
    CFURLRef url = CFURLCreateWithFileSystemPath(kCFAllocatorDefault, s, kCFURLPOSIXPathStyle, false);
    CGDataProviderRef dp = CGDataProviderCreateWithURL(url);
    CGFontRef cg_font = CGFontCreateWithDataProvider(dp);
    CTFontRef ct_font = CTFontCreateWithGraphicsFont(cg_font, 0.0, NULL, NULL);
    CFRelease(cg_font); CFRelease(dp); CFRelease(url); CFRelease(s);
    return (PyObject*) ct_face(ct_font, fg);
}

PyObject*
specialize_font_descriptor(PyObject *base_descriptor, FONTS_DATA_HANDLE fg UNUSED) {
    Py_INCREF(base_descriptor);
    return base_descriptor;
}

struct RenderBuffers {
    uint8_t *render_buf;
    size_t render_buf_sz, sz;
    CGGlyph *glyphs;
    CGRect *boxes;
    CGPoint *positions;
    CGSize *advances;
};
static struct RenderBuffers buffers = {0};

static void
finalize(void) {
    free(buffers.render_buf); free(buffers.glyphs); free(buffers.boxes); free(buffers.positions); free(buffers.advances);
    memset(&buffers, 0, sizeof(struct RenderBuffers));
    if (all_fonts_collection_data) CFRelease(all_fonts_collection_data);
    if (window_title_font) CFRelease(window_title_font);
    window_title_font = nil;
}


static void
render_color_glyph(CTFontRef font, uint8_t *buf, int glyph_id, unsigned int width, unsigned int height, unsigned int baseline) {
    CGColorSpaceRef color_space = CGColorSpaceCreateDeviceRGB();
    if (color_space == NULL) fatal("Out of memory");
    CGContextRef ctx = CGBitmapContextCreate(buf, width, height, 8, 4 * width, color_space, kCGImageAlphaPremultipliedLast | kCGBitmapByteOrderDefault);
    if (ctx == NULL) fatal("Out of memory");
    CGContextSetShouldAntialias(ctx, true);
    CGContextSetShouldSmoothFonts(ctx, true);  // sub-pixel antialias
    CGContextSetRGBFillColor(ctx, 1, 1, 1, 1);
    CGAffineTransform transform = CGAffineTransformIdentity;
    CGContextSetTextDrawingMode(ctx, kCGTextFill);
    CGGlyph glyph = glyph_id;
    CGContextSetTextMatrix(ctx, transform);
    CGContextSetTextPosition(ctx, -buffers.boxes[0].origin.x, MAX(2, height - baseline));
    CGPoint p = CGPointMake(0, 0);
    CTFontDrawGlyphs(font, &glyph, &p, 1, ctx);
    CGContextRelease(ctx);
    CGColorSpaceRelease(color_space);
    for (size_t r = 0; r < width; r++) {
        for (size_t c = 0; c < height; c++, buf += 4) {
            uint32_t px = (buf[0] << 24) | (buf[1] << 16) | (buf[2] << 8) | buf[3];
            *((pixel*)buf) = px;
        }
    }
}

static void
ensure_render_space(size_t width, size_t height, size_t num_glyphs) {
    if (buffers.render_buf_sz < width * height) {
        free(buffers.render_buf); buffers.render_buf = NULL;
        buffers.render_buf_sz = width * height;
        buffers.render_buf = malloc(buffers.render_buf_sz);
        if (buffers.render_buf == NULL) fatal("Out of memory");
    }
    if (buffers.sz < num_glyphs) {
        buffers.sz = MAX(128, num_glyphs * 2);
        buffers.advances = calloc(sizeof(buffers.advances[0]), buffers.sz);
        buffers.boxes = calloc(sizeof(buffers.boxes[0]), buffers.sz);
        buffers.glyphs = calloc(sizeof(buffers.glyphs[0]), buffers.sz);
        buffers.positions = calloc(sizeof(buffers.positions[0]), buffers.sz);
        if (!buffers.advances || !buffers.boxes || !buffers.glyphs || !buffers.positions) fatal("Out of memory");
    }
}

static void
setup_ctx_for_alpha_mask(CGContextRef render_ctx) {
    CGContextSetShouldAntialias(render_ctx, true);
    CGContextSetShouldSmoothFonts(render_ctx, true);
    CGContextSetGrayFillColor(render_ctx, 1, 1); // white glyphs
    CGContextSetGrayStrokeColor(render_ctx, 1, 1);
    CGContextSetLineWidth(render_ctx, OPT(macos_thicken_font));
    CGContextSetTextDrawingMode(render_ctx, kCGTextFillStroke);
    CGContextSetTextMatrix(render_ctx, CGAffineTransformIdentity);
}

static void
render_glyphs(CTFontRef font, unsigned int width, unsigned int height, unsigned int baseline, unsigned int num_glyphs) {
    memset(buffers.render_buf, 0, width * height);
    CGColorSpaceRef gray_color_space = CGColorSpaceCreateDeviceGray();
    if (gray_color_space == NULL) fatal("Out of memory");
    CGContextRef render_ctx = CGBitmapContextCreate(buffers.render_buf, width, height, 8, width, gray_color_space, (kCGBitmapAlphaInfoMask & kCGImageAlphaNone));
    CGColorSpaceRelease(gray_color_space);
    if (render_ctx == NULL) fatal("Out of memory");
    setup_ctx_for_alpha_mask(render_ctx);
    CGContextSetTextPosition(render_ctx, 0, height - baseline);
    CTFontDrawGlyphs(font, buffers.glyphs, buffers.positions, num_glyphs, render_ctx);
    CGContextRelease(render_ctx);
}

StringCanvas
render_simple_text_impl(PyObject *s, const char *text, unsigned int baseline) {
    CTFace *self = (CTFace*)s;
    CTFontRef font = self->ct_font;
    size_t num_chars = strnlen(text, 32);
    unichar chars[num_chars];
    CGSize local_advances[num_chars];
    for (size_t i = 0; i < num_chars; i++) chars[i] = text[i];
    ensure_render_space(0, 0, num_chars);
    CTFontGetGlyphsForCharacters(font, chars, buffers.glyphs, num_chars);
    CTFontGetAdvancesForGlyphs(font, kCTFontOrientationDefault, buffers.glyphs, local_advances, num_chars);
    CGRect bounding_box = CTFontGetBoundingRectsForGlyphs(font, kCTFontOrientationDefault, buffers.glyphs, buffers.boxes, num_chars);
    CGFloat x = 0, y = 0;
    for (size_t i = 0; i < num_chars; i++) {
        buffers.positions[i] = CGPointMake(x, y);
        x += local_advances[i].width; y += local_advances[i].height;
    }
    StringCanvas ans = { .width = (size_t)ceil(x), .height = (size_t)(2 * bounding_box.size.height) };
    ensure_render_space(ans.width, ans.height, num_chars);
    render_glyphs(font, ans.width, ans.height, baseline, num_chars);
    ans.canvas = malloc(ans.width * ans.height);
    if (ans.canvas) memcpy(ans.canvas, buffers.render_buf, ans.width * ans.height);
    return ans;
}

static bool
ensure_ui_font(size_t in_height) {
    static size_t for_height = 0;
    if (window_title_font) {
        if (for_height == in_height) return true;
        CFRelease(window_title_font);
    }
    window_title_font = CTFontCreateUIFontForLanguage(kCTFontUIFontWindowTitle, 0.f, NULL);
    if (!window_title_font) return false;
    CGFloat line_height = MAX(1, floor(CTFontGetAscent(window_title_font) + CTFontGetDescent(window_title_font) + MAX(0, CTFontGetLeading(window_title_font)) + 0.5));
    CGFloat pts_per_px = CTFontGetSize(window_title_font) / line_height;
    CGFloat desired_size = in_height * pts_per_px;
    if (desired_size != CTFontGetSize(window_title_font)) {
        CTFontRef sized = CTFontCreateCopyWithAttributes(window_title_font, desired_size, NULL, NULL);
        CFRelease(window_title_font);
        window_title_font = sized;
        if (!window_title_font) return false;
    }
    for_height = in_height;
    return true;
}

bool
cocoa_render_line_of_text(const char *text, const color_type fg, const color_type bg, uint8_t *rgba_output, const size_t width, const size_t height) {
    CGColorSpaceRef color_space = CGColorSpaceCreateDeviceRGB();
    if (color_space == NULL) return false;
    CGContextRef ctx = CGBitmapContextCreate(rgba_output, width, height, 8, 4 * width, color_space, kCGImageAlphaPremultipliedLast | kCGBitmapByteOrderDefault);
    CGColorSpaceRelease(color_space);
    if (ctx == NULL) return false;
    if (!ensure_ui_font(height)) return false;

    CGContextSetShouldAntialias(ctx, true);
    CGContextSetShouldSmoothFonts(ctx, true);  // sub-pixel antialias
    CGContextSetRGBFillColor(ctx, ((bg >> 16) & 0xff) / 255.f, ((bg >> 8) & 0xff) / 255.f, (bg & 0xff) / 255.f, 1.f);
    CGContextFillRect(ctx, CGRectMake(0.0, 0.0, width, height));
    CGContextSetTextDrawingMode(ctx, kCGTextFill);
    CGContextSetTextMatrix(ctx, CGAffineTransformIdentity);
    CGContextSetRGBFillColor(ctx, ((fg >> 16) & 0xff) / 255.f, ((fg >> 8) & 0xff) / 255.f, (fg & 0xff) / 255.f, 1.f);
    CGContextSetRGBStrokeColor(ctx, ((fg >> 16) & 0xff) / 255.f, ((fg >> 8) & 0xff) / 255.f, (fg & 0xff) / 255.f, 1.f);

    NSAttributedString *str = [[NSAttributedString alloc] initWithString:@(text) attributes:@{(NSString *)kCTFontAttributeName: (__bridge id)window_title_font}];
    if (!str) { CGContextRelease(ctx); return false; }
    CTLineRef line = CTLineCreateWithAttributedString((CFAttributedStringRef)str);
    [str release];
    if (!line) { CGContextRelease(ctx); return false; }
    CGFloat ascent, descent, leading;
    CTLineGetTypographicBounds(line, &ascent, &descent, &leading);
    CGContextSetTextPosition(ctx, 0, descent);
    CTLineDraw(line, ctx);
    CFRelease(line);
    CGContextRelease(ctx);
    return true;
}

uint8_t*
render_single_ascii_char_as_mask(const char ch, size_t *result_width, size_t *result_height) {
    if (!ensure_ui_font(*result_height)) { PyErr_SetString(PyExc_RuntimeError, "failed to create UI font"); return NULL; }
    unichar chars = ch;
    CGSize local_advances[1];
    CTFontGetGlyphsForCharacters(window_title_font, &chars, buffers.glyphs, 1);
    CTFontGetAdvancesForGlyphs(window_title_font, kCTFontOrientationDefault, buffers.glyphs, local_advances, 1);
    CGRect bounding_box = CTFontGetBoundingRectsForGlyphs(window_title_font, kCTFontOrientationDefault, buffers.glyphs, buffers.boxes, 1);

    size_t width = (size_t)ceilf(bounding_box.size.width);
    size_t height = (size_t)ceilf(bounding_box.size.height);
    uint8_t *canvas = calloc(width, height);
    if (!canvas) { PyErr_NoMemory(); return NULL; }
    CGColorSpaceRef gray_color_space = CGColorSpaceCreateDeviceGray();
    if (gray_color_space == NULL) { PyErr_NoMemory(); free(canvas); return NULL; }
    CGContextRef render_ctx = CGBitmapContextCreate(canvas, width, height, 8, width, gray_color_space, (kCGBitmapAlphaInfoMask & kCGImageAlphaNone));
    CGColorSpaceRelease(gray_color_space);
    if (render_ctx == NULL) { PyErr_NoMemory(); free(canvas); return NULL; }
    setup_ctx_for_alpha_mask(render_ctx);
    /* printf("origin.y: %f descent: %f ascent: %f height: %zu size.height: %f\n", bounding_box.origin.y, CTFontGetDescent(window_title_font), CTFontGetAscent(window_title_font), height, bounding_box.size.height); */
    CGContextSetTextPosition(render_ctx, -bounding_box.origin.x, -bounding_box.origin.y);
    CTFontDrawGlyphs(window_title_font, buffers.glyphs, buffers.positions, 1, render_ctx);
    CGContextRelease(render_ctx);
    *result_width = width; *result_height = height;
    return canvas;
}


static bool
do_render(CTFontRef ct_font, bool bold, bool italic, hb_glyph_info_t *info, hb_glyph_position_t *hb_positions, unsigned int num_glyphs, pixel *canvas, unsigned int cell_width, unsigned int cell_height, unsigned int num_cells, unsigned int baseline, bool *was_colored, bool allow_resize, FONTS_DATA_HANDLE fg, bool center_glyph) {
    unsigned int canvas_width = cell_width * num_cells;
    ensure_render_space(canvas_width, cell_height, num_glyphs);
    CGRect br = CTFontGetBoundingRectsForGlyphs(ct_font, kCTFontOrientationHorizontal, buffers.glyphs, buffers.boxes, num_glyphs);
    const bool debug_rendering = false;
    if (allow_resize) {
        // Resize glyphs that would bleed into neighboring cells, by scaling the font size
        float right = 0;
        for (unsigned i=0; i < num_glyphs; i++) right = MAX(right, buffers.boxes[i].origin.x + buffers.boxes[i].size.width);
        if (!bold && !italic && right > canvas_width + 1) {
            if (debug_rendering) printf("resizing glyphs, right: %f canvas_width: %u\n", right, canvas_width);
            CGFloat sz = CTFontGetSize(ct_font);
            sz *= canvas_width / right;
            CTFontRef new_font = CTFontCreateCopyWithAttributes(ct_font, sz, NULL, NULL);
            bool ret = do_render(new_font, bold, italic, info, hb_positions, num_glyphs, canvas, cell_width, cell_height, num_cells, baseline, was_colored, false, fg, center_glyph);
            CFRelease(new_font);
            return ret;
        }
    }
    CGFloat x = 0, y = 0;
    CTFontGetAdvancesForGlyphs(ct_font, kCTFontOrientationDefault, buffers.glyphs, buffers.advances, num_glyphs);
    for (unsigned i=0; i < num_glyphs; i++) {
        buffers.positions[i].x = x; buffers.positions[i].y = y;
        if (debug_rendering) printf("x=%f origin=%f width=%f advance=%f\n", x, buffers.boxes[i].origin.x, buffers.boxes[i].size.width, buffers.advances[i].width);
        x += buffers.advances[i].width; y += buffers.advances[i].height;
    }
    if (*was_colored) {
        render_color_glyph(ct_font, (uint8_t*)canvas, info[0].codepoint, cell_width * num_cells, cell_height, baseline);
    } else {
        render_glyphs(ct_font, canvas_width, cell_height, baseline, num_glyphs);
        Region src = {.bottom=cell_height, .right=canvas_width}, dest = {.bottom=cell_height, .right=canvas_width};
        render_alpha_mask(buffers.render_buf, canvas, &src, &dest, canvas_width, canvas_width);
    }
    if (num_cells && (center_glyph || (num_cells == 2 && *was_colored))) {
        if (debug_rendering) printf("centering glyphs: center_glyph: %d\n", center_glyph);
        // center glyphs (two cell emoji, PUA glyphs, ligatures, etc)
        CGFloat delta = (((CGFloat)canvas_width - br.size.width) / 2.f);
        // FiraCode ligatures result in negative origins
        if (br.origin.x > 0) delta -= br.origin.x;
        if (delta >= 1.f) right_shift_canvas(canvas, canvas_width, cell_height, (unsigned)(delta));
    }
    return true;
}

bool
render_glyphs_in_cells(PyObject *s, bool bold, bool italic, hb_glyph_info_t *info, hb_glyph_position_t *hb_positions, unsigned int num_glyphs, pixel *canvas, unsigned int cell_width, unsigned int cell_height, unsigned int num_cells, unsigned int baseline, bool *was_colored, FONTS_DATA_HANDLE fg, bool center_glyph) {
    CTFace *self = (CTFace*)s;
    ensure_render_space(128, 128, num_glyphs);
    for (unsigned i=0; i < num_glyphs; i++) buffers.glyphs[i] = info[i].codepoint;
    return do_render(self->ct_font, bold, italic, info, hb_positions, num_glyphs, canvas, cell_width, cell_height, num_cells, baseline, was_colored, true, fg, center_glyph);
}



// Boilerplate {{{

static PyObject*
display_name(CTFace *self) {
    CFStringRef dn = CTFontCopyDisplayName(self->ct_font);
    const char *d = convert_cfstring(dn, true);
    return Py_BuildValue("s", d);
}

static PyMethodDef methods[] = {
    METHODB(display_name, METH_NOARGS),
    {NULL}  /* Sentinel */
};

const char*
postscript_name_for_face(const PyObject *face_) {
    const CTFace *self = (const CTFace*)face_;
    if (self->postscript_name) return PyUnicode_AsUTF8(self->postscript_name);
    return "";
}


static PyObject *
repr(CTFace *self) {
    char buf[1024] = {0};
    snprintf(buf, sizeof(buf)/sizeof(buf[0]), "ascent=%.1f, descent=%.1f, leading=%.1f, point_sz=%.1f, scaled_point_sz=%.1f, underline_position=%.1f underline_thickness=%.1f",
        (self->ascent), (self->descent), (self->leading), (self->point_sz), (self->scaled_point_sz), (self->underline_position), (self->underline_thickness));
    return PyUnicode_FromFormat(
        "Face(family=%U, full_name=%U, postscript_name=%U, path=%U, units_per_em=%u, %s)",
        self->family_name, self->full_name, self->postscript_name, self->path, self->units_per_em, buf
    );
}


static PyMethodDef module_methods[] = {
    METHODB(coretext_all_fonts, METH_NOARGS),
    {NULL, NULL, 0, NULL}        /* Sentinel */
};

static PyMemberDef members[] = {
#define MEM(name, type) {#name, type, offsetof(CTFace, name), READONLY, #name}
    MEM(units_per_em, T_UINT),
    MEM(point_sz, T_FLOAT),
    MEM(scaled_point_sz, T_FLOAT),
    MEM(ascent, T_FLOAT),
    MEM(descent, T_FLOAT),
    MEM(leading, T_FLOAT),
    MEM(underline_position, T_FLOAT),
    MEM(underline_thickness, T_FLOAT),
    MEM(family_name, T_OBJECT),
    MEM(path, T_OBJECT),
    MEM(full_name, T_OBJECT),
    MEM(postscript_name, T_OBJECT),
    {NULL}  /* Sentinel */
};

PyTypeObject CTFace_Type = {
    PyVarObject_HEAD_INIT(NULL, 0)
    .tp_name = "fast_data_types.CTFace",
    .tp_basicsize = sizeof(CTFace),
    .tp_dealloc = (destructor)dealloc,
    .tp_flags = Py_TPFLAGS_DEFAULT,
    .tp_doc = "CoreText Font face",
    .tp_methods = methods,
    .tp_members = members,
    .tp_repr = (reprfunc)repr,
};



int
init_CoreText(PyObject *module) {
    if (PyType_Ready(&CTFace_Type) < 0) return 0;
    if (PyModule_AddObject(module, "CTFace", (PyObject *)&CTFace_Type) != 0) return 0;
    if (PyModule_AddFunctions(module, module_methods) != 0) return 0;
    register_at_exit_cleanup_func(CORE_TEXT_CLEANUP_FUNC, finalize);
    return 1;
}

// }}}
