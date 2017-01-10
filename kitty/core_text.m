/*
 * core_text.c
 * Copyright (C) 2017 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#include "data-types.h"
#include <structmember.h>
#import <CoreText/CTFont.h>
#import <Foundation/NSString.h>
#import <Foundation/NSDictionary.h>

typedef struct {
    PyObject_HEAD

    unsigned int units_per_em;
    float ascent, descent, leading, underline_position, underline_thickness;
    CTFontRef font;
} Face;


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
    Py_TYPE(self)->tp_free((PyObject*)self);
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
    {NULL}  /* Sentinel */
};

static PyMethodDef methods[] = {
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
