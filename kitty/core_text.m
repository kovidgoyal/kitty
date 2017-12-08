/*
 * core_text.c
 * Copyright (C) 2017 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#include "state.h"
#include "fonts.h"
#include <structmember.h>
#include <stdint.h>
#include <math.h>
#import <CoreGraphics/CGBitmapContext.h>
#import <CoreText/CTFont.h>
#include <Foundation/Foundation.h>
#include <CoreText/CoreText.h>
#import <Foundation/NSString.h>
#import <Foundation/NSDictionary.h>


static inline char*
convert_cfstring(CFStringRef src, int free_src) {
#define SZ 2048
    static char buf[SZ+2] = {0};
    bool ok = false;
    if(!CFStringGetCString(src, buf, SZ, kCFStringEncodingUTF8)) PyErr_SetString(PyExc_ValueError, "Failed to convert CFString");
    else ok = true;
    if (free_src) CFRelease(src);
    return ok ? buf : NULL;
#undef SZ
}

static PyObject*
font_descriptor_to_python(CTFontDescriptorRef descriptor) {
    NSURL *url = (NSURL *) CTFontDescriptorCopyAttribute(descriptor, kCTFontURLAttribute);
    NSString *psName = (NSString *) CTFontDescriptorCopyAttribute(descriptor, kCTFontNameAttribute);  
    NSString *family = (NSString *) CTFontDescriptorCopyAttribute(descriptor, kCTFontFamilyNameAttribute);
    NSString *style = (NSString *) CTFontDescriptorCopyAttribute(descriptor, kCTFontStyleNameAttribute);
    NSDictionary *traits = (NSDictionary *) CTFontDescriptorCopyAttribute(descriptor, kCTFontTraitsAttribute);
    unsigned int straits = [traits[(id)kCTFontSymbolicTrait] unsignedIntValue];
    NSNumber *weightVal = traits[(id)kCTFontWeightTrait];
    NSNumber *widthVal = traits[(id)kCTFontWidthTrait];

    PyObject *ans = Py_BuildValue("{ssssssss sOsOsO sfsfsI}", 
            "path", [[url path] UTF8String], 
            "postscript_name", [psName UTF8String],
            "family", [family UTF8String],
            "style", [style UTF8String],

            "bold", (straits & kCTFontBoldTrait) != 0 ? Py_True : Py_False,
            "italic", (straits & kCTFontItalicTrait) != 0 ? Py_True : Py_False,
            "monospace", (straits & kCTFontMonoSpaceTrait) != 0 ? Py_True : Py_False,

            "weight", [weightVal floatValue],
            "width", [widthVal floatValue],
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
    if (t) attrs[(id)attr] = [NSString stringWithUTF8String:PyUnicode_AsUTF8(t)];

    SET(family, kCTFontFamilyNameAttribute);
    SET(style, kCTFontStyleNameAttribute);
    SET(postscript_name, kCTFontNameAttribute);
#undef SET

    return CTFontDescriptorCreateWithAttributes((CFDictionaryRef) attrs);
}

PyObject*
coretext_all_fonts(PyObject UNUSED *_self) {
    static CTFontCollectionRef collection = NULL;
    if (collection == NULL) collection = CTFontCollectionCreateFromAvailableFonts(NULL);
    NSArray *matches = (NSArray *) CTFontCollectionCreateMatchingFontDescriptors(collection);  
    PyObject *ans = PyTuple_New([matches count]), *temp;
    if (ans == NULL) return PyErr_NoMemory();
    for (unsigned int i = 0; i < [matches count]; i++) {
        temp = font_descriptor_to_python((CTFontDescriptorRef) matches[i]);
        if (temp == NULL) { Py_DECREF(ans); return NULL; }
        PyTuple_SET_ITEM(ans, i, temp); temp = NULL;
    }
    return ans;
}

static void
free_font(void *f) {
    CFRelease((CTFontRef)f);
}

static inline PyObject*
ft_face(CTFontRef font) {
    const char *psname = convert_cfstring(CTFontCopyPostScriptName(font), 1);
    NSURL *url = (NSURL*)CTFontCopyAttribute(font, kCTFontURLAttribute);
    PyObject *path = PyUnicode_FromString([[url path] UTF8String]);
    [url release];
    if (path == NULL) { CFRelease(font); return NULL; }
    PyObject *ans =  ft_face_from_path_and_psname(path, psname, (void*)font, free_font, true, 3, CTFontGetLeading(font));
    Py_DECREF(path);
    if (ans == NULL) { CFRelease(font); }
    return ans;
}

static inline CTFontRef
find_substitute_face(CFStringRef str, CTFontRef old_font) {
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
        return new_font;
    }
    PyErr_SetString(PyExc_ValueError, "CoreText returned the same font as a fallback font"); 
    return NULL;
}

PyObject*
create_fallback_face(PyObject *base_face, Cell* cell, bool UNUSED bold, bool UNUSED italic) {
    PyObject *lp = PyObject_CallMethod(base_face, "extra_data", NULL);
    if (lp == NULL) return NULL;
    CTFontRef font = PyLong_AsVoidPtr(lp);
    Py_CLEAR(lp);
    char text[128] = {0};
    cell_as_utf8(cell, true, text, ' ');
    CFStringRef str = CFStringCreateWithCString(NULL, text, kCFStringEncodingUTF8);
    if (str == NULL) return PyErr_NoMemory();
    CTFontRef new_font = find_substitute_face(str, font);
    CFRelease(str);
    if (new_font == NULL) return NULL;
    return ft_face(new_font);
}

uint8_t*
coretext_render_color_glyph(void *f, int glyph_id, unsigned int width, unsigned int height, unsigned int baseline) {
    CTFontRef font = f;
    CGColorSpaceRef color_space = CGColorSpaceCreateDeviceRGB();
    if (color_space == NULL) fatal("Out of memory");
    uint8_t* buf = calloc(4, width * height);
    if (buf == NULL) fatal("Out of memory");
    CGContextRef ctx = CGBitmapContextCreate(buf, width, height, 8, 4 * width, color_space, kCGImageAlphaPremultipliedLast | kCGBitmapByteOrderDefault);
    if (ctx == NULL) fatal("Out of memory");
    CGContextSetShouldAntialias(ctx, true);
    CGContextSetShouldSmoothFonts(ctx, true);  // sub-pixel antialias
    CGContextSetRGBFillColor(ctx, 1, 1, 1, 1); 
    CGAffineTransform transform = CGAffineTransformIdentity;
    CGContextSetTextDrawingMode(ctx, kCGTextFill);
    CGGlyph glyph = glyph_id;
    // TODO: Scale the glyph if its bbox is larger than the image by using a non-identity transform
    /* CGRect rect = CTFontGetBoundingRectsForGlyphs(font, kCTFontOrientationHorizontal, glyphs, 0, 1); */
    CGContextSetTextMatrix(ctx, transform);
    CGFloat pos_y = height - 1.2f * baseline;  // we want the emoji to be rendered a little below the baseline
    CGContextSetTextPosition(ctx, 0, MAX(2, pos_y)); 
    CTFontDrawGlyphs(font, &glyph, &CGPointZero, 1, ctx);
    CGContextRelease(ctx);
    CGColorSpaceRelease(color_space);
    return buf;
}

PyObject*
face_from_descriptor(PyObject *descriptor) {
    CTFontDescriptorRef desc = font_descriptor_from_python(descriptor);
    if (!desc) return NULL;
    float scaled_point_sz = ((global_state.logical_dpi_x + global_state.logical_dpi_y) / 144.0) * global_state.font_sz_in_pts;
    CTFontRef font = CTFontCreateWithFontDescriptor(desc, scaled_point_sz, NULL);
    CFRelease(desc); desc = NULL;
    if (!font) { PyErr_SetString(PyExc_ValueError, "Failed to create CTFont object"); return NULL; }
    return ft_face(font);
}

PyObject*
specialize_font_descriptor(PyObject *base_descriptor) {
    Py_INCREF(base_descriptor);
    return base_descriptor;
}

// Boilerplate {{{

static PyMethodDef module_methods[] = {
    METHODB(coretext_all_fonts, METH_NOARGS),
    {NULL, NULL, 0, NULL}        /* Sentinel */
};

int 
init_CoreText(PyObject *module) {
    if (PyModule_AddFunctions(module, module_methods) != 0) return 0;
    return 1;
}


// }}}
