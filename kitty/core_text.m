/*
 * core_text.c
 * Copyright (C) 2017 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#include "data-types.h"
#include <structmember.h>
#include <stdint.h>
#include <math.h>
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
    CTFontRef font;
    PyObject *family_name, *full_name, *postscript_name, *path;
} Face;


static inline PyObject*
convert_cfstring(CFStringRef src, int free_src) {
#define SZ 2048
    static char buf[SZ+2] = {0};
    PyObject *ans = NULL;
    if(!CFStringGetCString(src, buf, SZ, kCFStringEncodingUTF8)) PyErr_SetString(PyExc_ValueError, "Failed to convert CFString");
    else ans = PyUnicode_FromString(buf);
    if (free_src) CFRelease(src);
    return ans;
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
            (PyDict_GetItemString(src, "bold") == Py_True) ? kCTFontBoldTrait : 0 |
            (PyDict_GetItemString(src, "italic") == Py_True) ? kCTFontItalicTrait : 0 |
            (PyDict_GetItemString(src, "monospace") == Py_True) ? kCTFontMonoSpaceTrait : 0);
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


static PyObject*
new(PyTypeObject *type, PyObject *args, PyObject UNUSED *kwds) {
    Face *self;
    PyObject *descriptor;
    float point_sz, dpi;
    if(!PyArg_ParseTuple(args, "Off", &descriptor, &point_sz, &dpi)) return NULL;
    self = (Face *)type->tp_alloc(type, 0);
    if (self) {
        CTFontDescriptorRef desc = font_descriptor_from_python(descriptor);
        if (desc) {
            self->point_sz = point_sz;
            self->scaled_point_sz = (dpi / 72.0) * point_sz;
            self->font = CTFontCreateWithFontDescriptor(desc, self->scaled_point_sz, NULL);
            CFRelease(desc);
            if (!self->font) { Py_CLEAR(self); PyErr_SetString(PyExc_ValueError, "Failed to create CTFont object"); }
            else {
                self->units_per_em = CTFontGetUnitsPerEm(self->font);
                self->ascent = CTFontGetAscent(self->font);
                self->descent = CTFontGetDescent(self->font);
                self->leading = CTFontGetLeading(self->font);
                self->underline_position = CTFontGetUnderlinePosition(self->font);
                self->underline_thickness = CTFontGetUnderlineThickness(self->font);
                self->scaled_point_sz = CTFontGetSize(self->font);
                self->family_name = convert_cfstring(CTFontCopyFamilyName(self->font), 1);
                self->full_name = convert_cfstring(CTFontCopyFullName(self->font), 1);
                self->postscript_name = convert_cfstring(CTFontCopyPostScriptName(self->font), 1);
                NSURL *url = (NSURL*)CTFontCopyAttribute(self->font, kCTFontURLAttribute);
                self->path = PyUnicode_FromString([[url path] UTF8String]);
                [url release];
                if (self->family_name == NULL || self->full_name == NULL || self->postscript_name == NULL || self->path == NULL) { Py_CLEAR(self); }
            }
        } else {
            Py_CLEAR(self);
            PyErr_NoMemory();
        }
    }
    return (PyObject*)self;
}


static void
dealloc(Face* self) {
    if (self->font) CFRelease(self->font);
    Py_CLEAR(self->family_name); Py_CLEAR(self->full_name); Py_CLEAR(self->postscript_name); Py_CLEAR(self->path);
    Py_TYPE(self)->tp_free((PyObject*)self);
}

static void
encode_utf16_pair(uint32_t character, unichar *units) {
    unsigned int code;
    assert(0x10000 <= character && character <= 0x10FFFF);
    code = (character - 0x10000);
    units[0] = 0xD800 | (code >> 10);
    units[1] = 0xDC00 | (code & 0x3FF);
}

static PyObject*
has_char(Face *self, PyObject *args) {
#define has_char_doc "True iff this font has glyphs for the specified character"
    int ch, count = 1;
    unichar chars[2] = {0};
    CGGlyph glyphs[2] = {0};
    if (!PyArg_ParseTuple(args, "C", &ch)) return NULL;
    if (ch <= 0xffff) chars[0] = (unichar)ch;
    else { encode_utf16_pair(ch, chars); count = 2; }
    PyObject *ret = (CTFontGetGlyphsForCharacters(self->font, chars, glyphs, count)) ? Py_True : Py_False;
    Py_INCREF(ret);
    return ret;
}

static PyObject*
font_units_to_pixels(Face *self, PyObject *args) {
#define font_units_to_pixels_doc "Convert the specified value from font units to pixels at the current font size"
    double x;
    if (!PyArg_ParseTuple(args, "d", &x)) return NULL;
    x *= self->scaled_point_sz / self->units_per_em;
    return Py_BuildValue("i", (int)ceil(x));
}

static PyObject*
cell_size(Face *self) {
#define cell_size_doc "Return the best cell size for this font based on the advances for the ASCII chars from 32 to 127"
#define count (128 - 32)
    unichar chars[count+1] = {0};
    CGGlyph glyphs[count+1] = {0};
    unsigned int width = 0, w, i;
    for (i = 0; i < count; i++) chars[i] = 32 + i;
    CTFontGetGlyphsForCharacters(self->font, chars, glyphs, count);
    for (i = 0; i < count; i++) {
        if (glyphs[i]) {
            w = (unsigned int)(ceilf(
                        CTFontGetAdvancesForGlyphs(self->font, kCTFontOrientationHorizontal, glyphs+i, NULL, 1)));
            if (w > width) width = w; 
        }
    }
    // See https://stackoverflow.com/questions/5511830/how-does-line-spacing-work-in-core-text-and-why-is-it-different-from-nslayoutm
    CGFloat leading = MAX(0, self->leading);
    leading = floor(leading + 0.5);
    CGFloat line_height = floor(self->ascent + 0.5) + floor(self->descent + 0.5) + leading;
    CGFloat ascender_delta = (leading > 0) ? 0 : floor(0.2 * line_height + 0.5);
    return Py_BuildValue("II", width, (unsigned int)(line_height + ascender_delta));  
#undef count
}

static PyObject*
render_char(Face *self, PyObject *args) {
#define render_char_doc "Render the specified character into the specified buffer. Combining unicode chars should be handled automatically (I hope)"
    char *s;
    unsigned int width, height;
    PyObject *pbuf;
    CGColorSpaceRef color_space = NULL;
    CGContextRef ctx = NULL;
    CTFontRef font = NULL;
    if (!PyArg_ParseTuple(args, "esIIO!", "UTF-8", &s, &width, &height, &PyLong_Type, &pbuf)) return NULL;
    uint8_t *buf = (uint8_t*)PyLong_AsVoidPtr(pbuf);
    CFStringRef str = CFStringCreateWithCString(NULL, s, kCFStringEncodingUTF8);
    if (!str) return PyErr_NoMemory();
    CGGlyph glyphs[10] = {0};
    unichar chars[10] = {0};
    CFRange range = CFRangeMake(0, CFStringGetLength(str));
    CFStringGetCharacters(str, range, chars);
    font = CTFontCreateForString(self->font, str, range);
    if (font == NULL) { PyErr_SetString(PyExc_ValueError, "Failed to find fallback font"); goto end; }
    CTFontGetGlyphsForCharacters(font, chars, glyphs, range.length);
    color_space = CGColorSpaceCreateDeviceGray();
    if (color_space == NULL) { PyErr_NoMemory(); goto end; }
    ctx = CGBitmapContextCreate(buf, width, height, 8, width, color_space, (kCGBitmapAlphaInfoMask & kCGImageAlphaNone));
    if (ctx == NULL) { PyErr_SetString(PyExc_ValueError, "Failed to create bitmap context"); goto end; }
    CGContextSetShouldAntialias(ctx, true);
    CGContextSetShouldSmoothFonts(ctx, true);  // sub-pixel antialias
    CGContextSetRGBFillColor(ctx, 1, 1, 1, 1); // white glyphs
    CGAffineTransform transform = CGAffineTransformIdentity;
    CGContextSetTextDrawingMode(ctx, kCGTextFill);
    CGGlyph glyph = glyphs[0];
    if (glyph) {
        // TODO: Scale the glyph if its bbox is larger than the image by using a non-identity transform
        /* CGRect rect = CTFontGetBoundingRectsForGlyphs(font, kCTFontOrientationHorizontal, glyphs, 0, 1); */
        CGContextSetTextMatrix(ctx, transform);
        CGFloat pos_y = height - self->ascent; 
        CGContextSetTextPosition(ctx, 0, pos_y); 
        CTFontDrawGlyphs(font, &glyph, &CGPointZero, 1, ctx);
    }

end:
    CFRelease(str);
    if (ctx) CGContextRelease(ctx);
    if (color_space) CGColorSpaceRelease(color_space);
    if (font && font != self->font) CFRelease(font);
    if (PyErr_Occurred()) return NULL;
    Py_RETURN_NONE;
}

static PyObject *
repr(Face *self) {
    char buf[400] = {0};
    snprintf(buf, sizeof(buf)/sizeof(buf[0]), "ascent=%.1f, descent=%.1f, leading=%.1f, point_sz=%.1f, scaled_point_sz=%.1f, underline_position=%.1f underline_thickness=%.1f", 
        (self->ascent), (self->descent), (self->leading), (self->point_sz), (self->scaled_point_sz), (self->underline_position), (self->underline_thickness));
    return PyUnicode_FromFormat(
        "Face(family=%U, full_name=%U, postscript_name=%U, path=%U, units_per_em=%u, %s)",
        self->family_name, self->full_name, self->postscript_name, self->path, self->units_per_em, buf
    );
}


// Boilerplate {{{

static PyMemberDef members[] = {
#define MEM(name, type) {#name, type, offsetof(Face, name), READONLY, #name}
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

static PyMethodDef methods[] = {
    METHOD(has_char, METH_VARARGS)
    METHOD(cell_size, METH_NOARGS)
    METHOD(font_units_to_pixels, METH_VARARGS)
    METHOD(render_char, METH_VARARGS)
    {NULL}  /* Sentinel */
};


PyTypeObject Face_Type = {
    PyVarObject_HEAD_INIT(NULL, 0)
    .tp_name = "fast_data_types.CTFace",
    .tp_basicsize = sizeof(Face),
    .tp_dealloc = (destructor)dealloc, 
    .tp_flags = Py_TPFLAGS_DEFAULT,        
    .tp_doc = "CoreText Font face",
    .tp_methods = methods,
    .tp_members = members,
    .tp_new = new,                
    .tp_repr = (reprfunc)repr,
};

static PyMethodDef module_methods[] = {
    {"coretext_all_fonts", (PyCFunction)coretext_all_fonts, METH_NOARGS, ""},
    {NULL, NULL, 0, NULL}        /* Sentinel */
};

int 
init_CoreText(PyObject *module) {
    if (PyType_Ready(&Face_Type) < 0) return 0;
    if (PyModule_AddObject(module, "CTFace", (PyObject *)&Face_Type) != 0) return 0;
    if (PyModule_AddFunctions(module, module_methods) != 0) return 0;
    return 1;
}


// }}}
