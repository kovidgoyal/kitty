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

typedef struct {
    PyObject_HEAD

    unsigned int units_per_em;
    float ascent, descent, leading, underline_position, underline_thickness, point_sz, scaled_point_sz;
    CTFontRef ct_font;
    hb_font_t *hb_font;
    PyObject *family_name, *full_name, *postscript_name, *path;
} CTFace;
PyTypeObject CTFace_Type;

static inline char*
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

static inline void
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

static inline CTFace*
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

static inline unsigned int
glyph_id_for_codepoint_ctfont(CTFontRef ct_font, char_type ch) {
    unichar chars[2] = {0};
    CGGlyph glyphs[2] = {0};
    int count = CFStringGetSurrogatePairForLongCharacter(ch, chars) ? 2 : 1;
    CTFontGetGlyphsForCharacters(ct_font, chars, glyphs, count);
    return glyphs[0];
}

static inline bool
is_last_resort_font(CTFontRef new_font) {
    CFStringRef name = CTFontCopyPostScriptName(new_font);
    CFComparisonResult cr = CFStringCompare(name, CFSTR("LastResort"), 0);
    CFRelease(name);
    return cr == kCFCompareEqualTo;
}

static inline CTFontRef
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

static inline CTFontRef
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

static inline float
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
    *underline_position = (unsigned int)floor(self->ascent - self->underline_position + 0.5);
    *underline_thickness = (unsigned int)ceil(MAX(0.1, self->underline_thickness));
    *baseline = (unsigned int)self->ascent;
    *strikethrough_position = (unsigned int)floor(*baseline * 0.65);
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
    CFRelease(test_frame); CFRelease(path); CFRelease(framesetter);
    *cell_height = MAX(4u, (unsigned int)ceilf(line_height));
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

static uint8_t *render_buf = NULL;
static size_t render_buf_sz = 0;
static CGGlyph glyphs[128];
static CGRect boxes[128];
static CGPoint positions[128];
static CGSize advances[128];

static void
finalize(void) {
    free(render_buf);
    if (all_fonts_collection_data) CFRelease(all_fonts_collection_data);
}


static inline void
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
    CGContextSetTextPosition(ctx, -boxes[0].origin.x, MAX(2, height - baseline));
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

static inline void
ensure_render_space(size_t width, size_t height) {
    if (render_buf_sz >= width * height) return;
    free(render_buf);
    render_buf_sz = width * height;
    render_buf = malloc(render_buf_sz);
    if (render_buf == NULL) fatal("Out of memory");
}

static inline void
render_glyphs(CTFontRef font, unsigned int width, unsigned int height, unsigned int baseline, unsigned int num_glyphs) {
    memset(render_buf, 0, width * height);
    CGColorSpaceRef gray_color_space = CGColorSpaceCreateDeviceGray();
    if (gray_color_space == NULL) fatal("Out of memory");
    CGContextRef render_ctx = CGBitmapContextCreate(render_buf, width, height, 8, width, gray_color_space, (kCGBitmapAlphaInfoMask & kCGImageAlphaNone));
    if (render_ctx == NULL) fatal("Out of memory");
    CGContextSetShouldAntialias(render_ctx, true);
    CGContextSetShouldSmoothFonts(render_ctx, true);
    CGContextSetGrayFillColor(render_ctx, 1, 1); // white glyphs
    CGContextSetGrayStrokeColor(render_ctx, 1, 1);
    CGContextSetLineWidth(render_ctx, OPT(macos_thicken_font));
    CGContextSetTextDrawingMode(render_ctx, kCGTextFillStroke);
    CGContextSetTextMatrix(render_ctx, CGAffineTransformIdentity);
    CGContextSetTextPosition(render_ctx, 0, height - baseline);
    CTFontDrawGlyphs(font, glyphs, positions, num_glyphs, render_ctx);
    CGContextRelease(render_ctx);
    CGColorSpaceRelease(gray_color_space);
}

StringCanvas
render_simple_text_impl(PyObject *s, const char *text, unsigned int baseline) {
    CTFace *self = (CTFace*)s;
    CTFontRef font = self->ct_font;
    size_t num_chars = strnlen(text, 32);
    unichar chars[num_chars];
    CGSize local_advances[num_chars];
    for (size_t i = 0; i < num_chars; i++) chars[i] = text[i];
    CTFontGetGlyphsForCharacters(font, chars, glyphs, num_chars);
    CTFontGetAdvancesForGlyphs(font, kCTFontOrientationDefault, glyphs, local_advances, num_chars);
    CGRect bounding_box = CTFontGetBoundingRectsForGlyphs(font, kCTFontOrientationDefault, glyphs, boxes, num_chars);
    CGFloat x = 0, y = 0;
    for (size_t i = 0; i < num_chars; i++) {
        positions[i] = CGPointMake(x, y);
        x += local_advances[i].width; y += local_advances[i].height;
    }
    StringCanvas ans = { .width = (size_t)ceil(x), .height = (size_t)(2 * bounding_box.size.height) };
    ensure_render_space(ans.width, ans.height);
    render_glyphs(font, ans.width, ans.height, baseline, num_chars);
    ans.canvas = malloc(ans.width * ans.height);
    if (ans.canvas) memcpy(ans.canvas, render_buf, ans.width * ans.height);
    return ans;
}


static inline bool
do_render(CTFontRef ct_font, bool bold, bool italic, hb_glyph_info_t *info, hb_glyph_position_t *hb_positions, unsigned int num_glyphs, pixel *canvas, unsigned int cell_width, unsigned int cell_height, unsigned int num_cells, unsigned int baseline, bool *was_colored, bool allow_resize, FONTS_DATA_HANDLE fg, bool center_glyph) {
    unsigned int canvas_width = cell_width * num_cells;
    CGRect br = CTFontGetBoundingRectsForGlyphs(ct_font, kCTFontOrientationHorizontal, glyphs, boxes, num_glyphs);
    const bool debug_rendering = false;
    if (allow_resize) {
        // Resize glyphs that would bleed into neighboring cells, by scaling the font size
        float right = 0;
        for (unsigned i=0; i < num_glyphs; i++) right = MAX(right, boxes[i].origin.x + boxes[i].size.width);
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
    CTFontGetAdvancesForGlyphs(ct_font, kCTFontOrientationDefault, glyphs, advances, num_glyphs);
    for (unsigned i=0; i < num_glyphs; i++) {
        positions[i].x = x; positions[i].y = y;
        if (debug_rendering) printf("x=%f origin=%f width=%f advance=%f\n", x, boxes[i].origin.x, boxes[i].size.width, advances[i].width);
        x += advances[i].width; y += advances[i].height;
    }
    if (*was_colored) {
        render_color_glyph(ct_font, (uint8_t*)canvas, info[0].codepoint, cell_width * num_cells, cell_height, baseline);
    } else {
        ensure_render_space(canvas_width, cell_height);
        render_glyphs(ct_font, canvas_width, cell_height, baseline, num_glyphs);
        Region src = {.bottom=cell_height, .right=canvas_width}, dest = {.bottom=cell_height, .right=canvas_width};
        render_alpha_mask(render_buf, canvas, &src, &dest, canvas_width, canvas_width);
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
    for (unsigned i=0; i < num_glyphs; i++) glyphs[i] = info[i].codepoint;
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
