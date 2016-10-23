# -*- coding: utf-8 -*-
# -----------------------------------------------------------------------------
#
#  FreeType high-level python API - Copyright 2011-2015 Nicolas P. Rougier
#  Distributed under the terms of the new BSD license.
#
# -----------------------------------------------------------------------------
'''
Internal exception with freetype error message
'''
class FT_Exception(Exception):
    def __init__(self, errcode, message=''):
        self.message = message
        self.errcode = errcode

    def __str__(self):
        return '%s: %s (%s)'%(self.__class__.__name__, self.message,
            self._errors.get(self.errcode, 'unknown error'))

    _errors = {
        0x00: "no error" ,
        0x01: "cannot open resource" ,
        0x02: "unknown file format" ,
        0x03: "broken file" ,
        0x04: "invalid FreeType version" ,
        0x05: "module version is too low" ,
        0x06: "invalid argument" ,
        0x07: "unimplemented feature" ,
        0x08: "broken table" ,
        0x09: "broken offset within table" ,
        0x10: "invalid glyph index" ,
        0x11: "invalid character code" ,
        0x12: "unsupported glyph image format" ,
        0x13: "cannot render this glyph format" ,
        0x14: "invalid outline" ,
        0x15: "invalid composite glyph" ,
        0x16: "too many hints" ,
        0x17: "invalid pixel size" ,
        0x20: "invalid object handle" ,
        0x21: "invalid library handle" ,
        0x22: "invalid module handle" ,
        0x23: "invalid face handle" ,
        0x24: "invalid size handle" ,
        0x25: "invalid glyph slot handle" ,
        0x26: "invalid charmap handle" ,
        0x27: "invalid cache manager handle" ,
        0x28: "invalid stream handle" ,
        0x30: "too many modules" ,
        0x31: "too many extensions" ,
        0x40: "out of memory" ,
        0x41: "unlisted object" ,
        0x51: "cannot open stream" ,
        0x52: "invalid stream seek" ,
        0x53: "invalid stream skip" ,
        0x54: "invalid stream read" ,
        0x55: "invalid stream operation" ,
        0x56: "invalid frame operation" ,
        0x57: "nested frame access" ,
        0x58: "invalid frame read" ,
        0x60: "raster uninitialized" ,
        0x61: "raster corrupted" ,
        0x62: "raster overflow" ,
        0x63: "negative height while rastering" ,
        0x70: "too many registered caches" ,
        0x80: "invalid opcode" ,
        0x81: "too few arguments" ,
        0x82: "stack overflow" ,
        0x83: "code overflow" ,
        0x84: "bad argument" ,
        0x85: "division by zero" ,
        0x86: "invalid reference" ,
        0x87: "found debug opcode" ,
        0x88: "found ENDF opcode in execution stream" ,
        0x89: "nested DEFS" ,
        0x8A: "invalid code range" ,
        0x8B: "execution context too long" ,
        0x8C: "too many function definitions" ,
        0x8D: "too many instruction definitions" ,
        0x8E: "SFNT font table missing" ,
        0x8F: "horizontal header (hhea, table missing" ,
        0x90: "locations (loca, table missing" ,
        0x91: "name table missing" ,
        0x92: "character map (cmap, table missing" ,
        0x93: "horizontal metrics (hmtx, table missing" ,
        0x94: "PostScript (post, table missing" ,
        0x95: "invalid horizontal metrics" ,
        0x96: "invalid character map (cmap, format" ,
        0x97: "invalid ppem value" ,
        0x98: "invalid vertical metrics" ,
        0x99: "could not find context" ,
        0x9A: "invalid PostScript (post, table format" ,
        0x9B: "invalid PostScript (post, table" ,
        0xA0: "opcode syntax error" ,
        0xA1: "argument stack underflow" ,
        0xA2: "ignore" ,
        0xB0: "`STARTFONT' field missing" ,
        0xB1: "`FONT' field missing" ,
        0xB2: "`SIZE' field missing" ,
        0xB3: "`CHARS' field missing" ,
        0xB4: "`STARTCHAR' field missing" ,
        0xB5: "`ENCODING' field missing" ,
        0xB6: "`BBX' field missing" ,
        0xB7: "`BBX' too big" ,
    }
