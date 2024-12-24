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

#define debug debug_fonts
static inline void cleanup_cfrelease(void *__p) { CFTypeRef *tp = (CFTypeRef *)__p; CFTypeRef cf = *tp; if (cf) { CFRelease(cf); } }
#define RAII_CoreFoundation(type, name, initializer) __attribute__((cleanup(cleanup_cfrelease))) type name = initializer

typedef struct {
    PyObject_HEAD

    unsigned int units_per_em;
    float ascent, descent, leading, underline_position, underline_thickness, point_sz, scaled_point_sz;
    CTFontRef ct_font;
    hb_font_t *hb_font;
    PyObject *family_name, *full_name, *postscript_name, *path, *name_lookup_table;
    FontFeatures font_features;
} CTFace;
PyTypeObject CTFace_Type;
static CTFontRef window_title_font = nil;

static PyObject*
convert_cfstring(CFStringRef src, int free_src) {
    RAII_CoreFoundation(CFStringRef, releaseme, free_src ? src : nil);
    (void)releaseme;
    if (!src) return PyUnicode_FromString("");
    const char *fast = CFStringGetCStringPtr(src, kCFStringEncodingUTF8);
    if (fast) return PyUnicode_FromString(fast);
#define SZ 4096
    char buf[SZ];
    if(!CFStringGetCString(src, buf, SZ, kCFStringEncodingUTF8)) { PyErr_SetString(PyExc_ValueError, "Failed to convert CFString"); return NULL; }
    return PyUnicode_FromString(buf);
#undef SZ
}

static void
init_face(CTFace *self, CTFontRef font) {
    if (self->hb_font) hb_font_destroy(self->hb_font);
    self->hb_font = NULL;
    if (self->ct_font) CFRelease(self->ct_font);
    self->ct_font = font; CFRetain(font);
    self->units_per_em = CTFontGetUnitsPerEm(self->ct_font);
    self->ascent = CTFontGetAscent(self->ct_font);
    self->descent = CTFontGetDescent(self->ct_font);
    self->leading = CTFontGetLeading(self->ct_font);
    self->underline_position = CTFontGetUnderlinePosition(self->ct_font);
    self->underline_thickness = CTFontGetUnderlineThickness(self->ct_font);
    self->scaled_point_sz = CTFontGetSize(self->ct_font);
}

static PyObject*
convert_url_to_filesystem_path(CFURLRef url) {
    uint8_t buf[4096];
    if (url && CFURLGetFileSystemRepresentation(url, true, buf, sizeof(buf))) return PyUnicode_FromString((const char*)buf);
    return PyUnicode_FromString("");
}

static PyObject*
get_path_for_font(CTFontRef font) {
    RAII_CoreFoundation(CFURLRef, url, CTFontCopyAttribute(font, kCTFontURLAttribute));
    return convert_url_to_filesystem_path(url);
}

static PyObject*
get_path_for_font_descriptor(CTFontDescriptorRef font) {
    RAII_CoreFoundation(CFURLRef, url, CTFontDescriptorCopyAttribute(font, kCTFontURLAttribute));
    return convert_url_to_filesystem_path(url);
}


static CTFace*
ct_face(CTFontRef font, PyObject *features) {
    CTFace *self = (CTFace *)CTFace_Type.tp_alloc(&CTFace_Type, 0);
    if (self) {
        init_face(self, font);
        self->family_name = convert_cfstring(CTFontCopyFamilyName(self->ct_font), true);
        self->full_name = convert_cfstring(CTFontCopyFullName(self->ct_font), true);
        self->postscript_name = convert_cfstring(CTFontCopyPostScriptName(self->ct_font), true);
        self->path = get_path_for_font(self->ct_font);
        if (self->family_name == NULL || self->full_name == NULL || self->postscript_name == NULL || self->path == NULL) { Py_CLEAR(self); }
        else {
            if (!create_features_for_face(postscript_name_for_face((PyObject*)self), features, &self->font_features)) { Py_CLEAR(self); }
        }
    }
    return self;
}

static void
dealloc(CTFace* self) {
    if (self->hb_font) hb_font_destroy(self->hb_font);
    if (self->ct_font) CFRelease(self->ct_font);
    self->hb_font = NULL;
    self->ct_font = NULL;
    free(self->font_features.features);
    Py_CLEAR(self->family_name); Py_CLEAR(self->full_name); Py_CLEAR(self->postscript_name); Py_CLEAR(self->path);
    Py_CLEAR(self->name_lookup_table);
    Py_TYPE(self)->tp_free((PyObject*)self);
}

static const char*
tag_to_string(uint32_t tag, uint8_t bytes[5]) {
    bytes[0] = (tag >> 24) & 0xff;
    bytes[1] = (tag >> 16) & 0xff;
    bytes[2] = (tag >> 8) & 0xff;
    bytes[3] = (tag) & 0xff;
    bytes[4] = 0;
    return (const char*)bytes;
}

static uint32_t
string_to_tag(const uint8_t *bytes) {
    return (((uint32_t)bytes[0]) << 24) | (((uint32_t)bytes[1]) << 16) | (((uint32_t)bytes[2]) << 8) | bytes[3];
}

FontFeatures*
features_for_face(PyObject *s) { return &((CTFace*)s)->font_features; }

static void
add_variation_pair(const void *key_, const void *value_, void *ctx) {
    PyObject *ans = ctx;
    CFNumberRef key = key_, value = value_;
    uint32_t tag; double val;
    if (!CFNumberGetValue(key, kCFNumberSInt32Type, &tag)) return;
    if (!CFNumberGetValue(value, kCFNumberDoubleType, &val)) return;
    uint8_t tag_string[5];
    tag_to_string(tag, tag_string);
    RAII_PyObject(pyval, PyFloat_FromDouble(val));
    if (pyval) PyDict_SetItemString(ans, (const char*)tag_string, pyval);
}

static PyObject*
variation_to_python(CFDictionaryRef v) {
    if (!v) { Py_RETURN_NONE; }
    RAII_PyObject(ans, PyDict_New());
    if (!ans) return NULL;
    CFDictionaryApplyFunction(v, add_variation_pair, ans);
    if (PyErr_Occurred()) return NULL;
    Py_INCREF(ans); return ans;
}

static PyObject*
font_descriptor_to_python(CTFontDescriptorRef descriptor) {
    RAII_PyObject(path, get_path_for_font_descriptor(descriptor));
    RAII_PyObject(ps_name, convert_cfstring(CTFontDescriptorCopyAttribute(descriptor, kCTFontNameAttribute), true));
    RAII_PyObject(family, convert_cfstring(CTFontDescriptorCopyAttribute(descriptor, kCTFontFamilyNameAttribute), true));
    RAII_PyObject(style, convert_cfstring(CTFontDescriptorCopyAttribute(descriptor, kCTFontStyleNameAttribute), true));
    RAII_PyObject(display_name, convert_cfstring(CTFontDescriptorCopyAttribute(descriptor, kCTFontDisplayNameAttribute), true));
    RAII_CoreFoundation(CFDictionaryRef, traits, CTFontDescriptorCopyAttribute(descriptor, kCTFontTraitsAttribute));
    unsigned long symbolic_traits = 0; float weight = 0, width = 0, slant = 0;
#define get_number(d, key, output, type_) { \
            CFNumberRef value = (CFNumberRef)CFDictionaryGetValue(d, key); \
            if (value) CFNumberGetValue(value, type_, &output); }
    get_number(traits, kCTFontSymbolicTrait, symbolic_traits, kCFNumberLongType);
    get_number(traits, kCTFontWeightTrait, weight, kCFNumberFloatType);
    get_number(traits, kCTFontWidthTrait, width, kCFNumberFloatType);
    get_number(traits, kCTFontSlantTrait, slant, kCFNumberFloatType);
    RAII_CoreFoundation(CFDictionaryRef, cf_variation, CTFontDescriptorCopyAttribute(descriptor, kCTFontVariationAttribute));
    RAII_PyObject(variation, variation_to_python(cf_variation));
    if (!variation) return NULL;
#undef get_number


    PyObject *ans = Py_BuildValue("{ss sOsOsOsOsO sOsOsOsOsOsOsO sfsfsfsk}",
            "descriptor_type", "core_text",

            "path", path, "postscript_name", ps_name, "family", family, "style", style, "display_name", display_name,

            "bold", (symbolic_traits & kCTFontBoldTrait) != 0 ? Py_True : Py_False,
            "italic", (symbolic_traits & kCTFontItalicTrait) != 0 ? Py_True : Py_False,
            "monospace", (symbolic_traits & kCTFontTraitMonoSpace) != 0 ? Py_True : Py_False,
            "expanded", (symbolic_traits & kCTFontExpandedTrait) != 0 ? Py_True : Py_False,
            "condensed", (symbolic_traits & kCTFontCondensedTrait) != 0 ? Py_True : Py_False,
            "color_glyphs", (symbolic_traits & kCTFontColorGlyphsTrait) != 0 ? Py_True : Py_False,
            "variation", variation,

            "weight", weight, "width", width, "slant", slant, "traits", symbolic_traits
    );
    return ans;
}

static CTFontDescriptorRef
font_descriptor_from_python(PyObject *src) {
    CTFontSymbolicTraits symbolic_traits = 0;
    RAII_CoreFoundation(CFMutableDictionaryRef, ans, CFDictionaryCreateMutable(NULL, 0, &kCFTypeDictionaryKeyCallBacks, &kCFTypeDictionaryValueCallBacks));
    PyObject *t = PyDict_GetItemString(src, "traits");
    if (t == NULL) {
        symbolic_traits = (
            (PyDict_GetItemString(src, "bold") == Py_True ? kCTFontBoldTrait : 0) |
            (PyDict_GetItemString(src, "italic") == Py_True ? kCTFontItalicTrait : 0) |
            (PyDict_GetItemString(src, "monospace") == Py_True ? kCTFontMonoSpaceTrait : 0));
    } else {
        symbolic_traits = PyLong_AsUnsignedLong(t);
    }
    RAII_CoreFoundation(CFNumberRef, cf_symbolic_traits, CFNumberCreate(NULL, kCFNumberSInt32Type, &symbolic_traits));
    CFTypeRef keys[] = { kCTFontSymbolicTrait };
    CFTypeRef values[] = { cf_symbolic_traits };
    RAII_CoreFoundation(CFDictionaryRef, traits, CFDictionaryCreate(NULL, keys, values, 1, &kCFTypeDictionaryKeyCallBacks, &kCFTypeDictionaryValueCallBacks));
    CFDictionaryAddValue(ans, kCTFontTraitsAttribute, traits);

#define SET(x, attr) if ((t = PyDict_GetItemString(src, #x))) { \
    RAII_CoreFoundation(CFStringRef, cs, CFStringCreateWithCString(NULL, PyUnicode_AsUTF8(t), kCFStringEncodingUTF8)); \
    CFDictionaryAddValue(ans, attr, cs); }

    SET(family, kCTFontFamilyNameAttribute);
    SET(style, kCTFontStyleNameAttribute);
    SET(postscript_name, kCTFontNameAttribute);
#undef SET
    if ((t = PyDict_GetItemString(src, "axis_map"))) {
        RAII_CoreFoundation(CFMutableDictionaryRef, axis_map, CFDictionaryCreateMutable(NULL, 0, &kCFTypeDictionaryKeyCallBacks, &kCFTypeDictionaryValueCallBacks));
        PyObject *key, *value; Py_ssize_t pos = 0;
        while (PyDict_Next(t, &pos, &key, &value)) {
            double val = PyFloat_AS_DOUBLE(value);
            uint32_t tag = string_to_tag((const uint8_t*)PyUnicode_AsUTF8(key));
            RAII_CoreFoundation(CFNumberRef, cf_tag, CFNumberCreate(NULL, kCFNumberSInt32Type, &tag));
            RAII_CoreFoundation(CFNumberRef, cf_val, CFNumberCreate(NULL, kCFNumberDoubleType, &val));
            CFDictionaryAddValue(axis_map, cf_tag, cf_val);
        }
        CFDictionaryAddValue(ans, kCTFontVariationAttribute, axis_map);
    }
    return CTFontDescriptorCreateWithAttributes(ans);
}

static CTFontCollectionRef all_fonts_collection_data = NULL;

static CTFontCollectionRef
all_fonts_collection(void) {
    if (all_fonts_collection_data == NULL) all_fonts_collection_data = CTFontCollectionCreateFromAvailableFonts(NULL);
    return all_fonts_collection_data;
}

static PyObject*
coretext_all_fonts(PyObject UNUSED *_self, PyObject *monospaced_only_) {
    int monospaced_only = PyObject_IsTrue(monospaced_only_);
    RAII_CoreFoundation(CFArrayRef, matches, CTFontCollectionCreateMatchingFontDescriptors(all_fonts_collection()));
    const CFIndex count = CFArrayGetCount(matches);
    RAII_PyObject(ans, PyTuple_New(count));
    if (ans == NULL) return NULL;
    PyObject *temp;
    Py_ssize_t num = 0;
    for (CFIndex i = 0; i < count; i++) {
        CTFontDescriptorRef desc = (CTFontDescriptorRef) CFArrayGetValueAtIndex(matches, i);
        if (monospaced_only) {
            RAII_CoreFoundation(CFDictionaryRef, traits, CTFontDescriptorCopyAttribute(desc, kCTFontTraitsAttribute));
            if (traits) {
                unsigned long symbolic_traits;
                CFNumberRef value = (CFNumberRef)CFDictionaryGetValue(traits, kCTFontSymbolicTrait);
                if (value) {
                    CFNumberGetValue(value, kCFNumberLongType, &symbolic_traits);
                    if (!(symbolic_traits & kCTFontTraitMonoSpace)) continue;
                }
            }
        }
        temp = font_descriptor_to_python(desc);
        if (temp == NULL) return NULL;
        PyTuple_SET_ITEM(ans, num++, temp); temp = NULL;
    }
    if (_PyTuple_Resize(&ans, num) == -1) return NULL;
    Py_INCREF(ans);
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
cf_string_equals(CFStringRef a, CFStringRef b) { return CFStringCompare(a, b, 0) == kCFCompareEqualTo; }

#define LAST_RESORT_FONT_NAME "LastResort"

static bool
is_last_resort_font(CTFontRef new_font) {
    CFStringRef name = CTFontCopyPostScriptName(new_font);
    bool ans = cf_string_equals(name, CFSTR(LAST_RESORT_FONT_NAME));
    CFRelease(name);
    return ans;
}

static CTFontDescriptorRef _nerd_font_descriptor = NULL, builtin_nerd_font_descriptor = NULL;

static CTFontRef nerd_font(CGFloat sz) {
    static bool searched = false;
    if (!searched) {
        searched = true;
        CFArrayRef fonts = CTFontCollectionCreateMatchingFontDescriptors(all_fonts_collection());
        const CFIndex count = CFArrayGetCount(fonts);
        for (CFIndex i = 0; i < count; i++) {
            CTFontDescriptorRef descriptor = (CTFontDescriptorRef)CFArrayGetValueAtIndex(fonts, i);
            CFStringRef name = CTFontDescriptorCopyAttribute(descriptor, kCTFontNameAttribute);
            bool is_nerd_font = cf_string_equals(name, CFSTR("SymbolsNFM"));
            CFRelease(name);
            if (is_nerd_font) {
                _nerd_font_descriptor = CTFontDescriptorCreateCopyWithAttributes(descriptor, CTFontDescriptorCopyAttributes(descriptor));
                break;
            }
        }
        CFRelease(fonts);
    }
    if (_nerd_font_descriptor) return CTFontCreateWithFontDescriptor(_nerd_font_descriptor, sz, NULL);
    if (builtin_nerd_font_descriptor) return CTFontCreateWithFontDescriptor(builtin_nerd_font_descriptor, sz, NULL);
    return NULL;
}

static bool ctfont_has_codepoint(const void *ctfont, char_type cp) { return glyph_id_for_codepoint_ctfont(ctfont, cp) > 0; }
static bool font_can_render_cell(CTFontRef font, const ListOfChars *lc) { return has_cell_text(ctfont_has_codepoint, font, false, lc); }

static CTFontRef
manually_search_fallback_fonts(CTFontRef current_font, const ListOfChars *lc) {
    char_type ch = lc->chars[0] ? lc->chars[0] : ' ';
    const bool in_first_pua = 0xe000 <= ch && ch <= 0xf8ff;
    // preferentially load from NERD fonts
    if (in_first_pua) {
        CTFontRef nf = nerd_font(CTFontGetSize(current_font));
        if (nf) {
            if (font_can_render_cell(nf, lc)) return nf;
            CFRelease(nf);
        }
    }
    CFArrayRef fonts = CTFontCollectionCreateMatchingFontDescriptors(all_fonts_collection());
    CTFontRef ans = NULL;
    const CFIndex count = CFArrayGetCount(fonts);
    for (CFIndex i = 0; i < count; i++) {
        CTFontDescriptorRef descriptor = (CTFontDescriptorRef)CFArrayGetValueAtIndex(fonts, i);
        CTFontRef new_font = CTFontCreateWithFontDescriptor(descriptor, CTFontGetSize(current_font), NULL);
        if (!is_last_resort_font(new_font)) {
            if (font_can_render_cell(new_font, lc)) {
                ans = new_font;
                break;
            }
        }
        CFRelease(new_font);
    }
    CFRelease(fonts);
    if (!ans) {
        CTFontRef nf = nerd_font(CTFontGetSize(current_font));
        if (nf) {
            if (font_can_render_cell(nf, lc)) ans = nf;
            else CFRelease(nf);
        }
    }
    return ans;
}

static CTFontRef
find_substitute_face(CFStringRef str, CTFontRef old_font, const ListOfChars *lc) {
    // CTFontCreateForString returns the original font when there are combining
    // diacritics in the font and the base character is in the original font,
    // so we have to check each character individually
    CFIndex len = CFStringGetLength(str), start = 0, amt = len;
    while (start < len) {
        CTFontRef new_font = CTFontCreateForString(old_font, str, CFRangeMake(start, amt));
        if (amt == len && len != 1) amt = 1;
        else start++;
        if (new_font == old_font) { CFRelease(new_font); continue; }
        if (!new_font || is_last_resort_font(new_font)) {
            if (new_font) CFRelease(new_font);
            if (is_private_use(lc->chars[0])) {
                // CoreTexts fallback font mechanism does not work for private use characters
                new_font = manually_search_fallback_fonts(old_font, lc);
                if (new_font) return new_font;
            }
            return NULL;
        }
        return new_font;
    }
    return NULL;
}

static CTFontRef
apply_styles_to_fallback_font(CTFontRef original_fallback_font, bool bold, bool italic) {
    if (!original_fallback_font || (!bold && !italic) || is_last_resort_font(original_fallback_font)) return original_fallback_font;
    CTFontDescriptorRef original_descriptor = CTFontCopyFontDescriptor(original_fallback_font);
    // We cannot set kCTFontTraitMonoSpace in traits as if the original
    // fallback font is Zapf Dingbats we get .AppleSystemUIFontMonospaced as
    // the new fallback
    CTFontSymbolicTraits traits = 0;
    if (bold) traits |= kCTFontTraitBold;
    if (italic) traits |= kCTFontTraitItalic;
    CTFontDescriptorRef descriptor = CTFontDescriptorCreateCopyWithSymbolicTraits(original_descriptor, traits, traits);
    CFRelease(original_descriptor);
    if (descriptor) {
        CTFontRef ans = CTFontCreateWithFontDescriptor(descriptor, CTFontGetSize(original_fallback_font), NULL);
        CFRelease(descriptor);
        if (!ans) return original_fallback_font;
        CFStringRef new_name = CTFontCopyFamilyName(ans);
        CFStringRef old_name = CTFontCopyFamilyName(original_fallback_font);
        bool same_family = cf_string_equals(new_name, old_name);
        /* NSLog(@"old: %@ new: %@", old_name, new_name); */
        CFRelease(new_name); CFRelease(old_name);
        if (same_family) { CFRelease(original_fallback_font); return ans; }
        CFRelease(ans);
    }
    return original_fallback_font;
}

static bool face_has_codepoint(const void *face, char_type ch) { return glyph_id_for_codepoint(face, ch) > 0; }
static struct { char *buf; size_t capacity; } ft_buffer;

static CFStringRef
lc_as_fallback(const ListOfChars *lc) {
    ensure_space_for((&ft_buffer), buf, ft_buffer.buf[0], lc->count * 4 + 128, capacity, 256, false);
    cell_as_utf8_for_fallback(lc, ft_buffer.buf);
    return CFStringCreateWithCString(NULL, ft_buffer.buf, kCFStringEncodingUTF8);
}

PyObject*
create_fallback_face(PyObject *base_face, const ListOfChars *lc, bool bold, bool italic, bool emoji_presentation, FONTS_DATA_HANDLE fg) {
    CTFace *self = (CTFace*)base_face;
    RAII_CoreFoundation(CTFontRef, new_font, NULL);
#define search_for_fallback() \
        CFStringRef str = lc_as_fallback(lc); \
        if (str == NULL) return PyErr_NoMemory(); \
        new_font = find_substitute_face(str, self->ct_font, lc); \
        CFRelease(str);

    if (emoji_presentation) {
        new_font = CTFontCreateWithName((CFStringRef)@"AppleColorEmoji", self->scaled_point_sz, NULL);
        if (!new_font || !glyph_id_for_codepoint_ctfont(new_font, lc->chars[0])) {
            if (new_font) CFRelease(new_font);
            search_for_fallback();
        }
    }
    else { search_for_fallback(); new_font = apply_styles_to_fallback_font(new_font, bold, italic); }
    if (new_font == NULL) Py_RETURN_NONE;
    RAII_PyObject(postscript_name, convert_cfstring(CTFontCopyPostScriptName(new_font), true));
    if (!postscript_name) return NULL;
    ssize_t idx = -1;
    PyObject *q, *ans = NULL;
    while ((q = iter_fallback_faces(fg, &idx))) {
        CTFace *qf = (CTFace*)q;
        if (PyObject_RichCompareBool(postscript_name, qf->postscript_name, Py_EQ) == 1) {
            ans = PyLong_FromSsize_t(idx);
            break;
        }
    }
    if (!ans) {
        ans = (PyObject*)ct_face(new_font, NULL);
        if (ans && !has_cell_text(face_has_codepoint, ans, global_state.debug_font_fallback, lc)) {
            Py_CLEAR(ans);
            Py_RETURN_NONE;
        }
    }
    return ans;
}

unsigned int
glyph_id_for_codepoint(const PyObject *s, char_type ch) {
    const CTFace *self = (CTFace*)s;
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
_scaled_point_sz(double font_sz_in_pts, double dpi_x, double dpi_y) {
    return ((dpi_x + dpi_y) / 144.0) * font_sz_in_pts;
}

static float
scaled_point_sz(FONTS_DATA_HANDLE fg) {
    return _scaled_point_sz(fg->font_sz_in_pts, fg->logical_dpi_x, fg->logical_dpi_y);
}

static bool
_set_size_for_face(CTFace *self, bool force, double font_sz_in_pts, double dpi_x, double dpi_y) {
    float sz = _scaled_point_sz(font_sz_in_pts, dpi_x, dpi_y);
    if (!force && self->scaled_point_sz == sz) return true;
    RAII_CoreFoundation(CTFontRef, new_font, CTFontCreateCopyWithAttributes(self->ct_font, sz, NULL, NULL));
    if (new_font == NULL) fatal("Out of memory");
    init_face(self, new_font);
    return true;
}

bool
set_size_for_face(PyObject *s, unsigned int UNUSED desired_height, bool force, FONTS_DATA_HANDLE fg) {
    CTFace *self = (CTFace*)s;
    return _set_size_for_face(self, force, fg->font_sz_in_pts, fg->logical_dpi_x, fg->logical_dpi_y);
}

static PyObject*
set_size(CTFace *self, PyObject *args) {
    double font_sz_in_pts, dpi_x, dpi_y;
    if (!PyArg_ParseTuple(args, "ddd", &font_sz_in_pts, &dpi_x, &dpi_y)) return NULL;
    if (!_set_size_for_face(self, false, font_sz_in_pts, dpi_x, dpi_y)) return NULL;
    Py_RETURN_NONE;
}

// CoreText delegates U+2010 to U+00AD if the font is missing U+2010. Example
// of such a font is Fira Code. So we specialize HarfBuzz glyph lookup to take
// this into account.
static hb_bool_t
get_nominal_glyph(hb_font_t *font, void *font_data, hb_codepoint_t unicode, hb_codepoint_t *glyph, void *user_data) {
    hb_font_t *parent_font = font_data; (void)user_data; (void)font;
    hb_bool_t ans = hb_font_get_nominal_glyph(parent_font, unicode, glyph);
    if (!ans && unicode == 0x2010) {
        CTFontRef ct_font = hb_coretext_font_get_ct_font(parent_font);
        unsigned int gid = glyph_id_for_codepoint_ctfont(ct_font, unicode);
        if (gid > 0) {
            ans = true; *glyph = gid;
        }
    }
    return ans;
}

static hb_bool_t
get_variation_glyph(hb_font_t *font, void *font_data, hb_codepoint_t unicode, hb_codepoint_t variation, hb_codepoint_t *glyph, void *user_data) {
    hb_font_t *parent_font = font_data; (void)user_data; (void)font;
    hb_bool_t ans = hb_font_get_variation_glyph(parent_font, unicode, variation, glyph);
    if (!ans && unicode == 0x2010) {
        CTFontRef ct_font = hb_coretext_font_get_ct_font(parent_font);
        unsigned int gid = glyph_id_for_codepoint_ctfont(ct_font, unicode);
        if (gid > 0) {
            ans = true; *glyph = gid;
        }
    }
    return ans;
}


hb_font_t*
harfbuzz_font_for_face(PyObject* s) {
    CTFace *self = (CTFace*)s;
    if (!self->hb_font) {
        hb_font_t *hb = hb_coretext_font_create(self->ct_font);
        if (!hb) fatal("Failed to create hb_font_t");
        // dunno if we need this, harfbuzz docs say it is used by CoreText
        // for optical sizing which changes the look of glyphs at small and large sizes
        hb_font_set_ptem(hb, self->scaled_point_sz);
        // Setup CoreText compatible glyph lookup functions
        self->hb_font = hb_font_create_sub_font(hb);
        if (!self->hb_font) fatal("Failed to create sub hb_font_t");
        hb_font_funcs_t *ffunctions = hb_font_funcs_create();
        hb_font_set_funcs(self->hb_font, ffunctions, hb, NULL);
        hb_font_funcs_set_nominal_glyph_func(ffunctions, get_nominal_glyph, NULL, NULL);
        hb_font_funcs_set_variation_glyph_func(ffunctions, get_variation_glyph, NULL, NULL);
        hb_font_funcs_destroy(ffunctions); // sub font retains a reference to this
        hb_font_destroy(hb);  // the sub font retains a reference to the parent font
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
    CGPathAddRect(path, NULL, CGRectMake(10, 10, 200, 8000));
    CTFramesetterRef framesetter = CTFramesetterCreateWithAttributedString(test_string);
    CFRelease(test_string);
    CTFrameRef test_frame = CTFramesetterCreateFrame(framesetter, CFRangeMake(0, 0), path, NULL);
    CGPoint origin1, origin2;
    CTFrameGetLineOrigins(test_frame, CFRangeMake(0, 1), &origin1);
    CTFrameGetLineOrigins(test_frame, CFRangeMake(1, 1), &origin2);
    CGFloat line_height = origin1.y - origin2.y;
    CFArrayRef lines = CTFrameGetLines(test_frame);
    if (!CFArrayGetCount(lines)) fatal("Failed to typeset test line to calculate cell metrics");
    CTLineRef line = CFArrayGetValueAtIndex(lines, 0);
    CGRect bounds = CTLineGetBoundsWithOptions(line, 0);
    CGRect bounds_without_leading = CTLineGetBoundsWithOptions(line, kCTLineBoundsExcludeTypographicLeading);
    CGFloat typographic_ascent, typographic_descent, typographic_leading;
    CTLineGetTypographicBounds(line, &typographic_ascent, &typographic_descent, &typographic_leading);
    *cell_height = MAX(4u, (unsigned int)ceilf(line_height));
    CGFloat bounds_ascent = bounds_without_leading.size.height + bounds_without_leading.origin.y;
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
    CFRelease(test_frame); CFRelease(path); CFRelease(framesetter);

#undef count
}

PyObject*
face_from_descriptor(PyObject *descriptor, FONTS_DATA_HANDLE fg) {
    RAII_CoreFoundation(CTFontDescriptorRef, desc, NULL);
    if (builtin_nerd_font_descriptor) {
        PyObject *psname = PyDict_GetItemString(descriptor, "postscript_name");
        if (psname && PyUnicode_CompareWithASCIIString(psname, "SymbolsNFM") == 0) {
            RAII_PyObject(path, get_path_for_font_descriptor(builtin_nerd_font_descriptor));
            PyObject *dpath = PyDict_GetItemString(descriptor, "path");
            if (dpath && PyUnicode_Compare(path, dpath) == 0) {
                desc = builtin_nerd_font_descriptor; CFRetain(desc);
            }
        }
    }
    if (!desc) desc = font_descriptor_from_python(descriptor);
    if (!desc) return NULL;
    RAII_CoreFoundation(CTFontRef, font, CTFontCreateWithFontDescriptor(desc, fg ? scaled_point_sz(fg) : 12, NULL));
    if (!font) { PyErr_SetString(PyExc_ValueError, "Failed to create CTFont object"); return NULL; }
    return (PyObject*) ct_face(font, PyDict_GetItemString(descriptor, "features"));
}

PyObject*
face_from_path(const char *path, int UNUSED index, FONTS_DATA_HANDLE fg UNUSED) {
    RAII_CoreFoundation(CFStringRef, s, CFStringCreateWithCString(NULL, path, kCFStringEncodingUTF8));
    RAII_CoreFoundation(CFURLRef, url, CFURLCreateWithFileSystemPath(kCFAllocatorDefault, s, kCFURLPOSIXPathStyle, false));
    RAII_CoreFoundation(CGDataProviderRef, dp, CGDataProviderCreateWithURL(url));
    RAII_CoreFoundation(CGFontRef, cg_font, CGFontCreateWithDataProvider(dp));
    RAII_CoreFoundation(CTFontRef, ct_font, CTFontCreateWithGraphicsFont(cg_font, 0.0, NULL, NULL));
    return (PyObject*) ct_face(ct_font, NULL);
}

static PyObject*
new(PyTypeObject *type UNUSED, PyObject *args, PyObject *kw) {
    const char *path = NULL;
    PyObject *descriptor = NULL;

    static char *kwds[] = {"descriptor", "path", NULL};
    if (!PyArg_ParseTupleAndKeywords(args, kw, "|Os", kwds, &descriptor, &path)) return NULL;
    if (descriptor) return face_from_descriptor(descriptor, NULL);
    if (path) return face_from_path(path, 0, NULL);
    PyErr_SetString(PyExc_TypeError, "Must specify either path or descriptor");
    return NULL;
}

PyObject*
specialize_font_descriptor(PyObject *base_descriptor, double font_sz_in_pts UNUSED, double dpi_x UNUSED, double dpi_y UNUSED) {
    return PyDict_Copy(base_descriptor);
}

struct RenderBuffers {
    uint8_t *render_buf;
    size_t render_buf_sz, sz;
    CGGlyph *glyphs;
    CGRect *boxes;
    CGPoint *positions;
};
static struct RenderBuffers buffers = {0};

static void
finalize(void) {
    free(ft_buffer.buf); ft_buffer.buf = NULL; ft_buffer.capacity = 0;
    free(buffers.render_buf); free(buffers.glyphs); free(buffers.boxes); free(buffers.positions);
    memset(&buffers, 0, sizeof(struct RenderBuffers));
    if (all_fonts_collection_data) CFRelease(all_fonts_collection_data);
    if (window_title_font) CFRelease(window_title_font);
    window_title_font = nil;
    if (_nerd_font_descriptor) CFRelease(_nerd_font_descriptor);
    if (builtin_nerd_font_descriptor) CFRelease(builtin_nerd_font_descriptor);
    _nerd_font_descriptor = NULL; builtin_nerd_font_descriptor = NULL;
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
        free(buffers.boxes); free(buffers.glyphs); free(buffers.positions);
        buffers.boxes = calloc(sizeof(buffers.boxes[0]), buffers.sz);
        buffers.glyphs = calloc(sizeof(buffers.glyphs[0]), buffers.sz);
        buffers.positions = calloc(sizeof(buffers.positions[0]), buffers.sz);
        if (!buffers.boxes || !buffers.glyphs || !buffers.positions) fatal("Out of memory");
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

static void destroy_hb_buffer(hb_buffer_t **x) { if (*x) hb_buffer_destroy(*x); }

static PyObject*
render_sample_text(CTFace *self, PyObject *args) {
    unsigned long canvas_width, canvas_height;
    unsigned long fg = 0xffffff;
    CTFontRef font = self->ct_font;
    PyObject *ptext;
    if (!PyArg_ParseTuple(args, "Ukk|k", &ptext, &canvas_width, &canvas_height, &fg)) return NULL;
    unsigned int cell_width, cell_height, baseline, underline_position, underline_thickness, strikethrough_position, strikethrough_thickness;
    cell_metrics((PyObject*)self, &cell_width, &cell_height, &baseline, &underline_position, &underline_thickness, &strikethrough_position, &strikethrough_thickness);
    if (!cell_width || !cell_height) return Py_BuildValue("yII", "", cell_width, cell_height);
    size_t num_chars = PyUnicode_GET_LENGTH(ptext);
    int num_chars_per_line = canvas_width / cell_width, num_of_lines = (int)ceil((float)num_chars / (float)num_chars_per_line);
    canvas_height = MIN(canvas_height, num_of_lines * cell_height);
    RAII_PyObject(pbuf, PyBytes_FromStringAndSize(NULL, sizeof(pixel) * canvas_width * canvas_height));
    if (!pbuf) return NULL;
    memset(PyBytes_AS_STRING(pbuf), 0, PyBytes_GET_SIZE(pbuf));

    __attribute__((cleanup(destroy_hb_buffer))) hb_buffer_t *hb_buffer = hb_buffer_create();
    if (!hb_buffer_pre_allocate(hb_buffer, 4*num_chars)) { PyErr_NoMemory(); return NULL; }
    for (size_t n = 0; n < num_chars; n++) {
        Py_UCS4 codep = PyUnicode_READ_CHAR(ptext, n);
        hb_buffer_add_utf32(hb_buffer, &codep, 1, 0, 1);
    }
    hb_buffer_guess_segment_properties(hb_buffer);
    if (!HB_DIRECTION_IS_HORIZONTAL(hb_buffer_get_direction(hb_buffer))) goto end;
    hb_shape(harfbuzz_font_for_face((PyObject*)self), hb_buffer, self->font_features.features, self->font_features.count);
    unsigned int len = hb_buffer_get_length(hb_buffer);
    hb_glyph_info_t *info = hb_buffer_get_glyph_infos(hb_buffer, NULL);
    hb_glyph_position_t *positions = hb_buffer_get_glyph_positions(hb_buffer, NULL);

    memset(PyBytes_AS_STRING(pbuf), 0, PyBytes_GET_SIZE(pbuf));
    if (cell_width > canvas_width) goto end;

    ensure_render_space(canvas_width, canvas_height, len);
    float pen_x = 0, pen_y = 0;
    unsigned num_glyphs = 0;
    CGFloat scale = CTFontGetSize(self->ct_font) / CTFontGetUnitsPerEm(self->ct_font);
    for (unsigned int i = 0; i < len; i++) {
        float advance = (float)positions[i].x_advance * scale;
        if (pen_x + advance > canvas_width) {
            pen_y += cell_height;
            pen_x = 0;
            if (pen_y >= canvas_height) break;
        }
        double x = pen_x + (double)positions[i].x_offset * scale;
        double y = pen_y + (double)positions[i].y_offset * scale;
        pen_x += advance;
        buffers.positions[i] = CGPointMake(x, -y);
        buffers.glyphs[i] = info[i].codepoint;
        num_glyphs++;
    }
    render_glyphs(font, canvas_width, canvas_height, baseline, num_glyphs);
    uint8_t r = (fg >> 16) & 0xff, g = (fg >> 8) & 0xff, b = fg & 0xff;
    const uint8_t *last_pixel = (uint8_t*)PyBytes_AS_STRING(pbuf) + PyBytes_GET_SIZE(pbuf) - sizeof(pixel);
    const uint8_t *s_limit = buffers.render_buf + canvas_width * canvas_height;
    for (
        uint8_t *p = (uint8_t*)PyBytes_AS_STRING(pbuf), *s = buffers.render_buf;
        p <= last_pixel && s < s_limit;
        p += sizeof(pixel), s++
    ) {
        p[0] = r; p[1] = g; p[2] = b; p[3] = s[0];
    }
end:
    return Py_BuildValue("OII", pbuf, cell_width, cell_height);

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
do_render(CTFontRef ct_font, unsigned int units_per_em, bool bold, bool italic, hb_glyph_info_t *info, hb_glyph_position_t *hb_positions, unsigned int num_glyphs, pixel *canvas, unsigned int cell_width, unsigned int cell_height, unsigned int num_cells, unsigned int baseline, bool *was_colored, bool allow_resize, FONTS_DATA_HANDLE fg, bool center_glyph) {
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
            bool ret = do_render(new_font, CTFontGetUnitsPerEm(new_font), bold, italic, info, hb_positions, num_glyphs, canvas, cell_width, cell_height, num_cells, baseline, was_colored, false, fg, center_glyph);
            CFRelease(new_font);
            return ret;
        }
    }
    CGFloat x = 0, y = 0;
    CGFloat scale = CTFontGetSize(ct_font) / units_per_em;
    for (unsigned i=0; i < num_glyphs; i++) {
        buffers.positions[i].x = x + hb_positions[i].x_offset * scale; buffers.positions[i].y = y + hb_positions[i].y_offset * scale;
        if (debug_rendering) printf("x=%f y=%f origin=%f width=%f x_advance=%f x_offset=%f y_advance=%f y_offset=%f\n",
                buffers.positions[i].x, buffers.positions[i].y, buffers.boxes[i].origin.x, buffers.boxes[i].size.width,
                hb_positions[i].x_advance * scale, hb_positions[i].x_offset * scale,
                hb_positions[i].y_advance * scale, hb_positions[i].y_offset * scale);
        x += hb_positions[i].x_advance * scale; y += hb_positions[i].y_advance * scale;
    }
    if (*was_colored) {
        render_color_glyph(ct_font, (uint8_t*)canvas, info[0].codepoint, cell_width * num_cells, cell_height, baseline);
    } else {
        render_glyphs(ct_font, canvas_width, cell_height, baseline, num_glyphs);
        Region src = {.bottom=cell_height, .right=canvas_width}, dest = {.bottom=cell_height, .right=canvas_width};
        render_alpha_mask(buffers.render_buf, canvas, &src, &dest, canvas_width, canvas_width, 0xffffff);
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
    return do_render(self->ct_font, self->units_per_em, bold, italic, info, hb_positions, num_glyphs, canvas, cell_width, cell_height, num_cells, baseline, was_colored, true, fg, center_glyph);
}

// Font tables {{{

static bool
ensure_name_table(CTFace *self) {
    if (self->name_lookup_table) return true;
    RAII_CoreFoundation(CFDataRef, cftable, CTFontCopyTable(self->ct_font, kCTFontTableName, kCTFontTableOptionNoOptions));
    const uint8_t *table = cftable ? CFDataGetBytePtr(cftable) : NULL;
    size_t table_len = cftable ? CFDataGetLength(cftable) : 0;
    self->name_lookup_table = read_name_font_table(table, table_len);
    return !!self->name_lookup_table;
}

static PyObject*
get_best_name(CTFace *self, PyObject *nameid) {
    if (!ensure_name_table(self)) return NULL;
    return get_best_name_from_name_table(self->name_lookup_table, nameid);
}

static PyObject*
get_variation(CTFace *self, PyObject *args UNUSED) {
    RAII_CoreFoundation(CFDictionaryRef, src, CTFontCopyVariation(self->ct_font));
    return variation_to_python(src);
}

static PyObject*
applied_features(CTFace *self, PyObject *a UNUSED) {
    return font_features_as_dict(&self->font_features);
}

static PyObject*
get_features(CTFace *self, PyObject *a UNUSED) {
    if (!ensure_name_table(self)) return NULL;
    RAII_PyObject(output, PyDict_New()); if (!output) return NULL;
    RAII_CoreFoundation(CFDataRef, cftable, CTFontCopyTable(self->ct_font, kCTFontTableGSUB, kCTFontTableOptionNoOptions));
    const uint8_t *table = cftable ? CFDataGetBytePtr(cftable) : NULL;
    size_t table_len = cftable ? CFDataGetLength(cftable) : 0;
    if (!read_features_from_font_table(table, table_len, self->name_lookup_table, output)) return NULL;
    RAII_CoreFoundation(CFDataRef, cfpostable, CTFontCopyTable(self->ct_font, kCTFontTableGPOS, kCTFontTableOptionNoOptions));
    table = cfpostable ? CFDataGetBytePtr(cfpostable) : NULL;
    table_len = cfpostable ? CFDataGetLength(cfpostable) : 0;
    if (!read_features_from_font_table(table, table_len, self->name_lookup_table, output)) return NULL;
    Py_INCREF(output); return output;
}


static PyObject*
get_variable_data(CTFace *self, PyObject *args UNUSED) {
    if (!ensure_name_table(self)) return NULL;
    RAII_PyObject(output, PyDict_New());
    if (!output) return NULL;
    RAII_CoreFoundation(CFDataRef, cftable, CTFontCopyTable(self->ct_font, kCTFontTableFvar, kCTFontTableOptionNoOptions));
    const uint8_t *table = cftable ? CFDataGetBytePtr(cftable) : NULL;
    size_t table_len = cftable ? CFDataGetLength(cftable) : 0;
    if (!read_fvar_font_table(table, table_len, self->name_lookup_table, output)) return NULL;
    RAII_CoreFoundation(CFDataRef, stable, CTFontCopyTable(self->ct_font, kCTFontTableSTAT, kCTFontTableOptionNoOptions));
    table = stable ? CFDataGetBytePtr(stable) : NULL;
    table_len = stable ? CFDataGetLength(stable) : 0;
    if (!read_STAT_font_table(table, table_len, self->name_lookup_table, output)) return NULL;
    Py_INCREF(output); return output;
}

static PyObject*
identify_for_debug(CTFace *self, PyObject *args UNUSED) {
    RAII_PyObject(features, PyTuple_New(self->font_features.count)); if (!features) return NULL;
    char buf[128];
    for (unsigned i = 0; i < self->font_features.count; i++) {
        hb_feature_to_string(self->font_features.features + i, buf, sizeof(buf));
        PyObject *f = PyUnicode_FromString(buf); if (!f) return NULL;
        PyTuple_SET_ITEM(features, i, f);
    }
    return PyUnicode_FromFormat("%V: %V\nFeatures: %S", self->postscript_name, "[psname]", self->path, "[path]", features);
}

// }}}


// Boilerplate {{{

static PyObject*
display_name(CTFace *self, PyObject *args UNUSED) {
    CFStringRef dn = CTFontCopyDisplayName(self->ct_font);
    return convert_cfstring(dn, true);
}

static PyObject*
postscript_name(CTFace *self, PyObject *args UNUSED) {
    return self->postscript_name ? Py_BuildValue("O", self->postscript_name) : PyUnicode_FromString("");
}


static PyMethodDef methods[] = {
    METHODB(display_name, METH_NOARGS),
    METHODB(postscript_name, METH_NOARGS),
    METHODB(get_variable_data, METH_NOARGS),
    METHODB(applied_features, METH_NOARGS),
    METHODB(get_features, METH_NOARGS),
    METHODB(get_variation, METH_NOARGS),
    METHODB(identify_for_debug, METH_NOARGS),
    METHODB(set_size, METH_VARARGS),
    METHODB(render_sample_text, METH_VARARGS),
    METHODB(get_best_name, METH_O),
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
    snprintf(buf, sizeof(buf)/sizeof(buf[0]), "ascent=%.1f, descent=%.1f, leading=%.1f, scaled_point_sz=%.1f, underline_position=%.1f underline_thickness=%.1f",
        (self->ascent), (self->descent), (self->leading), (self->scaled_point_sz), (self->underline_position), (self->underline_thickness));
    return PyUnicode_FromFormat(
        "Face(family=%U, full_name=%U, postscript_name=%U, path=%U, units_per_em=%u, %s)",
        self->family_name, self->full_name, self->postscript_name, self->path, self->units_per_em, buf
    );
}


static PyObject*
add_font_file(PyObject UNUSED *_self, PyObject *args) {
    const unsigned char *path = NULL; Py_ssize_t sz;
    if (!PyArg_ParseTuple(args, "s#", &path, &sz)) return NULL;
    RAII_CoreFoundation(CFURLRef, url, CFURLCreateFromFileSystemRepresentation(kCFAllocatorDefault, path, sz, false));
    if (CTFontManagerRegisterFontsForURL(url, kCTFontManagerScopeProcess, NULL)) Py_RETURN_TRUE;
    Py_RETURN_FALSE;
}

static PyObject*
set_builtin_nerd_font(PyObject UNUSED *self, PyObject *pypath) {
    if (!PyUnicode_Check(pypath)) { PyErr_SetString(PyExc_TypeError, "path must be a string"); return NULL; }
    const char *path = NULL; Py_ssize_t sz;
    path = PyUnicode_AsUTF8AndSize(pypath, &sz);
    RAII_CoreFoundation(CFURLRef, url, CFURLCreateFromFileSystemRepresentation(kCFAllocatorDefault, (const unsigned char*)path, sz, false));
    RAII_CoreFoundation(CFArrayRef, descriptors, CTFontManagerCreateFontDescriptorsFromURL(url));
    if (!descriptors || CFArrayGetCount(descriptors) == 0) {
        PyErr_SetString(PyExc_OSError, "Failed to create descriptor from nerd font path");
        return NULL;
    }
    if (builtin_nerd_font_descriptor) CFRelease(builtin_nerd_font_descriptor);
    builtin_nerd_font_descriptor = CFArrayGetValueAtIndex(descriptors, 0);
    CFRetain(builtin_nerd_font_descriptor);
    return font_descriptor_to_python(builtin_nerd_font_descriptor);
}

static PyMethodDef module_methods[] = {
    METHODB(coretext_all_fonts, METH_O),
    METHODB(add_font_file, METH_VARARGS),
    METHODB(set_builtin_nerd_font, METH_O),
    {NULL, NULL, 0, NULL}        /* Sentinel */
};

static PyMemberDef members[] = {
#define MEM(name, type) {#name, type, offsetof(CTFace, name), READONLY, #name}
    MEM(units_per_em, T_UINT),
    MEM(scaled_point_sz, T_FLOAT),
    MEM(ascent, T_FLOAT),
    MEM(descent, T_FLOAT),
    MEM(leading, T_FLOAT),
    MEM(underline_position, T_FLOAT),
    MEM(underline_thickness, T_FLOAT),
    MEM(family_name, T_OBJECT),
    MEM(path, T_OBJECT),
    MEM(full_name, T_OBJECT),
    {NULL}  /* Sentinel */
};

PyTypeObject CTFace_Type = {
    PyVarObject_HEAD_INIT(NULL, 0)
    .tp_name = "fast_data_types.CTFace",
    .tp_new = new,
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
