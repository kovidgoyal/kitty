/*
 * core_text.c
 * Copyright (C) 2017 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#include "data-types.h"
#include <structmember.h>
#include <stdint.h>
#import <CoreText/CTFont.h>
#import <Foundation/NSString.h>
#import <Foundation/NSDictionary.h>

typedef struct {
    PyObject_HEAD

    unsigned int units_per_em;
    float ascent, descent, leading, underline_position, underline_thickness;
    CTFontRef font;
    PyObject *family_name, *full_name;
} Face;


static PyObject*
convert_cfstring(CFStringRef src) {
#define SZ 2048
    static char buf[SZ+2] = {0};
    if(!CFStringGetCString(src, buf, SZ, kCFStringEncodingUTF8)) { PyErr_SetString(PyExc_ValueError, "Failed to convert CFString"); return NULL; }
    return PyUnicode_FromString(buf);
#undef SZ
}


static PyObject*
new(PyTypeObject *type, PyObject *args, PyObject UNUSED *kwds) {
    Face *self;
    int bold, italic;
    char *cfamily;
    float point_sz;
    if(!PyArg_ParseTuple(args, "sppf", &cfamily, &bold, &italic, &point_sz)) return NULL;
    NSString *family = [[NSString alloc] initWithCString:cfamily encoding:NSUTF8StringEncoding];
    if (family == NULL) return PyErr_NoMemory();
    self = (Face *)type->tp_alloc(type, 0);
    if (self) {
        CTFontSymbolicTraits symbolic_traits = (bold ? kCTFontBoldTrait : 0) | (italic ? kCTFontItalicTrait : 0);
        NSDictionary *font_traits = [NSDictionary dictionaryWithObject:[NSNumber numberWithInt:symbolic_traits] forKey:(NSString *)kCTFontSymbolicTrait];
        NSDictionary *font_attributes = [NSDictionary dictionaryWithObjectsAndKeys:family, kCTFontFamilyNameAttribute, font_traits, kCTFontTraitsAttribute, nil];
        CTFontDescriptorRef descriptor = CTFontDescriptorCreateWithAttributes((CFDictionaryRef)font_attributes);
        if (descriptor) {
            self->font = CTFontCreateWithFontDescriptor(descriptor, point_sz, NULL);
            CFRelease(descriptor);
            if (!self->font) { Py_CLEAR(self); PyErr_SetString(PyExc_ValueError, "Failed to create CTFont object"); }
            else {
                self->units_per_em = CTFontGetUnitsPerEm(self->font);
                self->ascent = CTFontGetAscent(self->font);
                self->descent = CTFontGetDescent(self->font);
                self->leading = CTFontGetLeading(self->font);
                self->underline_position = CTFontGetUnderlinePosition(self->font);
                self->underline_thickness = CTFontGetUnderlineThickness(self->font);
                self->family_name = convert_cfstring(CTFontCopyFamilyName(self->font));
                self->full_name = convert_cfstring(CTFontCopyFullName(self->font));
                if (self->family_name == NULL || self->full_name == NULL) { Py_CLEAR(self); }
            }
        } else {
            Py_CLEAR(self);
            PyErr_NoMemory();
        }
    }
    [ family release ];
    return (PyObject*)self;
}


static void
dealloc(Face* self) {
    if (self->font) CFRelease(self->font);
    Py_CLEAR(self->family_name); Py_CLEAR(self->full_name);
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

// Boilerplate {{{

static PyMemberDef members[] = {
#define MEM(name, type) {#name, type, offsetof(Face, name), READONLY, #name}
    MEM(units_per_em, T_UINT),
    MEM(ascent, T_FLOAT),
    MEM(descent, T_FLOAT),
    MEM(leading, T_FLOAT),
    MEM(underline_position, T_FLOAT),
    MEM(underline_thickness, T_FLOAT),
    MEM(family_name, T_OBJECT),
    MEM(full_name, T_OBJECT),
    {NULL}  /* Sentinel */
};

static PyMethodDef methods[] = {
    METHOD(has_char, METH_VARARGS)
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
};


int 
init_CoreText(PyObject *module) {
    if (PyType_Ready(&Face_Type) < 0) return 0;
    if (PyModule_AddObject(module, "CTFace", (PyObject *)&Face_Type) != 0) return 0;
    return 1;
}


// }}}
