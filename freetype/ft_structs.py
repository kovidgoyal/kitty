#!/usr/bin/env python
# -*- coding: utf-8 -*-
# -----------------------------------------------------------------------------
#
#  FreeType high-level python API - Copyright 2011-2015 Nicolas P. Rougier
#  Distributed under the terms of the new BSD license.
#
# -----------------------------------------------------------------------------
'''
Freetype structured types
-------------------------

FT_Library: A handle to a FreeType library instance.

FT_Vector: A simple structure used to store a 2D vector.

FT_BBox: A structure used to hold an outline's bounding box.

FT_Matrix: A simple structure used to store a 2x2 matrix.

FT_UnitVector: A simple structure used to store a 2D vector unit vector.

FT_Bitmap: A structure used to describe a bitmap or pixmap to the raster.

FT_Data: Read-only binary data represented as a pointer and a length.

FT_Generic: Client applications generic data.

FT_Bitmap_Size: Metrics of a bitmap strike.

FT_Charmap: The base charmap structure.

FT_Glyph_Metrics:A structure used to model the metrics of a single glyph.

FT_Outline: This structure is used to describe an outline to the scan-line
            converter.

FT_GlyphSlot: FreeType root glyph slot class structure.

FT_Glyph: The root glyph structure contains a given glyph image plus its
           advance width in 16.16 fixed float format.

FT_Size_Metrics: The size metrics structure gives the metrics of a size object.

FT_Size: FreeType root size class structure.

FT_Face: FreeType root face class structure.

FT_Parameter: A simple structure used to pass more or less generic parameters
              to FT_Open_Face.

FT_Open_Args: A structure used to indicate how to open a new font file or
              stream.

FT_SfntName: A structure used to model an SFNT 'name' table entry.

FT_Stroker: Opaque handler to a path stroker object.

FT_BitmapGlyph: A structure used for bitmap glyph images.
'''
from freetype.ft_types import *


# -----------------------------------------------------------------------------
# A handle to a FreeType library instance. Each 'library' is completely
# independent from the others; it is the 'root' of a set of objects like fonts,
# faces, sizes, etc.
class FT_LibraryRec(Structure):
    '''
    A handle to a FreeType library instance. Each 'library' is completely
    independent from the others; it is the 'root' of a set of objects like
    fonts, faces, sizes, etc.
    '''
    _fields_ = [ ]
FT_Library = POINTER(FT_LibraryRec)



# -----------------------------------------------------------------------------
# A simple structure used to store a 2D vector; coordinates are of the FT_Pos
# type.
class FT_Vector(Structure):
    '''
    A simple structure used to store a 2D vector; coordinates are of the FT_Pos
    type.

    x: The horizontal coordinate.
    y: The vertical coordinate.
    '''
    _fields_ = [('x', FT_Pos),
                ('y', FT_Pos)]



# -----------------------------------------------------------------------------
# A structure used to hold an outline's bounding box, i.e., the coordinates of
# its extrema in the horizontal and vertical directions.
#
# The bounding box is specified with the coordinates of the lower left and the
# upper right corner. In PostScript, those values are often called (llx,lly)
# and (urx,ury), respectively.
#
# If 'yMin' is negative, this value gives the glyph's descender. Otherwise, the
# glyph doesn't descend below the baseline. Similarly, if 'ymax' is positive,
# this value gives the glyph's ascender.
#
# 'xMin' gives the horizontal distance from the glyph's origin to the left edge
# of the glyph's bounding box. If 'xMin' is negative, the glyph extends to the
# left of the origin.
class FT_BBox(Structure):
    '''
    A structure used to hold an outline's bounding box, i.e., the coordinates
    of its extrema in the horizontal and vertical directions.

    The bounding box is specified with the coordinates of the lower left and
    the upper right corner. In PostScript, those values are often called
    (llx,lly) and (urx,ury), respectively.

    If 'yMin' is negative, this value gives the glyph's descender. Otherwise,
    the glyph doesn't descend below the baseline. Similarly, if 'ymax' is
    positive, this value gives the glyph's ascender.

    'xMin' gives the horizontal distance from the glyph's origin to the left
    edge of the glyph's bounding box. If 'xMin' is negative, the glyph extends
    to the left of the origin.

    xMin: The horizontal minimum (left-most).
    yMin: The vertical minimum (bottom-most).
    xMax: The horizontal maximum (right-most).
    yMax: The vertical maximum (top-most).
    '''
    _fields_ = [('xMin', FT_Pos),
                ('yMin', FT_Pos),
                ('xMax', FT_Pos),
                ('yMax', FT_Pos)]



# -----------------------------------------------------------------------------
# A simple structure used to store a 2x2 matrix. Coefficients are in 16.16
# fixed float format. The computation performed is:
#   x' = x*xx + y*xy
#   y' = x*yx + y*yy
class FT_Matrix(Structure):
    '''
    A simple structure used to store a 2x2 matrix. Coefficients are in 16.16
    fixed float format. The computation performed is:

    x' = x*xx + y*xy
    y' = x*yx + y*yy

    xx: Matrix coefficient.
    xy: Matrix coefficient.
    yx: Matrix coefficient.
    yy: Matrix coefficient.
    '''
    _fields_ = [('xx', FT_Fixed),
                ('xy', FT_Fixed),
                ('yx', FT_Fixed),
                ('yy', FT_Fixed)]



# -----------------------------------------------------------------------------
# A simple structure used to store a 2D vector unit vector. Uses FT_F2Dot14
# types.
class FT_UnitVector(Structure):
    '''
    A simple structure used to store a 2D vector unit vector. Uses FT_F2Dot14
    types.

    x: The horizontal coordinate.
    y: The vertical coordinate.
    '''
    _fields_ = [('x', FT_F2Dot14),
                ('y', FT_F2Dot14)]



# -----------------------------------------------------------------------------
# A structure used to describe a bitmap or pixmap to the raster. Note that we
# now manage pixmaps of various depths through the 'pixel_mode' field.
class FT_Bitmap(Structure):
    '''
    A structure used to describe a bitmap or pixmap to the raster. Note that we
    now manage pixmaps of various depths through the 'pixel_mode' field.

    rows: The number of bitmap rows.

    width: The number of pixels in bitmap row.

    pitch: The pitch's absolute value is the number of bytes taken by one
           bitmap row, including padding. However, the pitch is positive when
           the bitmap has a 'down' flow, and negative when it has an 'up'
           flow. In all cases, the pitch is an offset to add to a bitmap
           pointer in order to go down one row.

           Note that 'padding' means the alignment of a bitmap to a byte
           border, and FreeType functions normally align to the smallest
           possible integer value.

           For the B/W rasterizer, 'pitch' is always an even number.

           To change the pitch of a bitmap (say, to make it a multiple of 4),
           use FT_Bitmap_Convert. Alternatively, you might use callback
           functions to directly render to the application's surface; see the
           file 'example2.py' in the tutorial for a demonstration.

    buffer: A typeless pointer to the bitmap buffer. This value should be
            aligned on 32-bit boundaries in most cases.

    num_grays: This field is only used with FT_PIXEL_MODE_GRAY; it gives the
    number of gray levels used in the bitmap.

    pixel_mode: The pixel mode, i.e., how pixel bits are stored. See
    FT_Pixel_Mode for possible values.

    palette_mode: This field is intended for paletted pixel modes; it indicates
    how the palette is stored. Not used currently.

    palette: A typeless pointer to the bitmap palette; this field is intended
    for paletted pixel modes. Not used currently.
    '''
    _fields_ = [
        ('rows',         c_int),
        ('width',        c_int),
        ('pitch',        c_int),
        # declaring buffer as c_char_p confuses ctypes
        ('buffer',       POINTER(c_ubyte)),
        ('num_grays',    c_short),
        ('pixel_mode',   c_ubyte),
        ('palette_mode', c_char),
        ('palette',      c_void_p) ]



# -----------------------------------------------------------------------------
# Read-only binary data represented as a pointer and a length.
class FT_Data(Structure):
    '''
    Read-only binary data represented as a pointer and a length.

    pointer: The data.
    length: The length of the data in bytes.
    '''
    _fields_ = [('pointer', POINTER(FT_Byte)),
                ('y',       FT_Int)]



# -----------------------------------------------------------------------------
# Client applications often need to associate their own data to a variety of
# FreeType core objects. For example, a text layout API might want to associate
# a glyph cache to a given size object.
#
# Most FreeType object contains a 'generic' field, of type FT_Generic, which
# usage is left to client applications and font servers.
#
# It can be used to store a pointer to client-specific data, as well as the
# address of a 'finalizer' function, which will be called by FreeType when the
# object is destroyed (for example, the previous client example would put the
# address of the glyph cache destructor in the 'finalizer' field).
class FT_Generic(Structure):
    '''
    Client applications often need to associate their own data to a variety of
    FreeType core objects. For example, a text layout API might want to
    associate a glyph cache to a given size object.

    Most FreeType object contains a 'generic' field, of type FT_Generic, which
    usage is left to client applications and font servers.

    It can be used to store a pointer to client-specific data, as well as the
    address of a 'finalizer' function, which will be called by FreeType when
    the object is destroyed (for example, the previous client example would put
    the address of the glyph cache destructor in the 'finalizer' field).

    data: A typeless pointer to any client-specified data. This field is
          completely ignored by the FreeType library.
    finalizer: A pointer to a 'generic finalizer' function, which will be
               called when the object is destroyed. If this field is set to
               NULL, no code will be called.
    '''
    _fields_ = [('data',      c_void_p),
                ('finalizer', FT_Generic_Finalizer)]




# -----------------------------------------------------------------------------
# This structure models the metrics of a bitmap strike (i.e., a set of glyphs
# for a given point size and resolution) in a bitmap font. It is used for the
# 'available_sizes' field of FT_Face.
class FT_Bitmap_Size(Structure):
    '''
    This structure models the metrics of a bitmap strike (i.e., a set of glyphs
    for a given point size and resolution) in a bitmap font. It is used for the
    'available_sizes' field of FT_Face.

    height: The vertical distance, in pixels, between two consecutive
            baselines. It is always positive.

    width: The average width, in pixels, of all glyphs in the strike.

    size: The nominal size of the strike in 26.6 fractional points. This field
          is not very useful.

    x_ppem: The horizontal ppem (nominal width) in 26.6 fractional pixels.

    y_ppem: The vertical ppem (nominal height) in 26.6 fractional pixels.
    '''
    _fields_ = [
        ('height', FT_Short),
        ('width',  FT_Short),
        ('size',   FT_Pos),
        ('x_ppem', FT_Pos),
        ('y_ppem', FT_Pos) ]



# -----------------------------------------------------------------------------
# The base charmap structure.
class FT_CharmapRec(Structure):
    '''
    The base charmap structure.

    face : A handle to the parent face object.

    encoding : An FT_Encoding tag identifying the charmap. Use this with
               FT_Select_Charmap.

    platform_id: An ID number describing the platform for the following
                 encoding ID. This comes directly from the TrueType
                 specification and should be emulated for other formats.

    encoding_id: A platform specific encoding number. This also comes from the
                 TrueType specification and should be emulated similarly.
    '''
    _fields_ = [
        ('face',        c_void_p),  # Shoudl be FT_Face
        ('encoding',    FT_Encoding),
        ('platform_id', FT_UShort),
        ('encoding_id', FT_UShort),
        ]
FT_Charmap = POINTER(FT_CharmapRec)



# -----------------------------------------------------------------------------
# A structure used to model the metrics of a single glyph. The values are
# expressed in 26.6 fractional pixel format; if the flag FT_LOAD_NO_SCALE has
# been used while loading the glyph, values are expressed in font units
# instead.
class FT_Glyph_Metrics(Structure):
    '''
    A structure used to model the metrics of a single glyph. The values are
    expressed in 26.6 fractional pixel format; if the flag FT_LOAD_NO_SCALE has
    been used while loading the glyph, values are expressed in font units
    instead.

    width: The glyph's width.

    height: The glyph's height.

    horiBearingX: Left side bearing for horizontal layout.

    horiBearingY: Top side bearing for horizontal layout.

    horiAdvance: Advance width for horizontal layout.

    vertBearingX: Left side bearing for vertical layout.

    vertBearingY: Top side bearing for vertical layout.

    vertAdvance: Advance height for vertical layout.
    '''
    _fields_ = [
        ('width',        FT_Pos),
        ('height',       FT_Pos),
        ('horiBearingX', FT_Pos),
        ('horiBearingY', FT_Pos),
        ('horiAdvance',  FT_Pos),
        ('vertBearingX', FT_Pos),
        ('vertBearingY', FT_Pos),
        ('vertAdvance',  FT_Pos),
    ]



# -----------------------------------------------------------------------------
# This structure is used to describe an outline to the scan-line converter.
class FT_Outline(Structure):
    '''
    This structure is used to describe an outline to the scan-line converter.

    n_contours: The number of contours in the outline.

    n_points: The number of points in the outline.

    points: A pointer to an array of 'n_points' FT_Vector elements, giving the
            outline's point coordinates.

    tags: A pointer to an array of 'n_points' chars, giving each outline
          point's type.

          If bit 0 is unset, the point is 'off' the curve, i.e., a Bezier
          control point, while it is 'on' if set.

          Bit 1 is meaningful for 'off' points only. If set, it indicates a
          third-order Bezier arc control point; and a second-order control
          point if unset.

          If bit 2 is set, bits 5-7 contain the drop-out mode (as defined in
          the OpenType specification; the value is the same as the argument to
          the SCANMODE instruction).

          Bits 3 and 4 are reserved for internal purposes.

    contours: An array of 'n_contours' shorts, giving the end point of each
              contour within the outline. For example, the first contour is
              defined by the points '0' to 'contours[0]', the second one is
              defined by the points 'contours[0]+1' to 'contours[1]', etc.

    flags: A set of bit flags used to characterize the outline and give hints
           to the scan-converter and hinter on how to convert/grid-fit it. See
           FT_OUTLINE_FLAGS.
    '''
    _fields_ = [
        ('n_contours', c_short),
        ('n_points',   c_short),
        ('points',     POINTER(FT_Vector)),
        # declaring buffer as c_char_p would prevent us to acces all tags
        ('tags',       POINTER(c_ubyte)),
        ('contours',   POINTER(c_short)),
        ('flags',      c_int),
    ]


# -----------------------------------------------------------------------------
# The root glyph structure contains a given glyph image plus its advance width
# in 16.16 fixed float format.

class FT_GlyphRec(Structure):
    '''
    The root glyph structure contains a given glyph image plus its advance
    width in 16.16 fixed float format.

    library:  A handle to the FreeType library object.

    clazz: A pointer to the glyph's class. Private.

    format: The format of the glyph's image.

    advance: A 16.16 vector that gives the glyph's advance width.
    '''
    _fields_ = [
        ('library',    FT_Library),
        ('clazz',      c_void_p),
        ('format',     FT_Glyph_Format),
        ('advance',    FT_Vector)
    ]
FT_Glyph = POINTER(FT_GlyphRec)



# -----------------------------------------------------------------------------
# FreeType root glyph slot class structure. A glyph slot is a container where
# individual glyphs can be loaded, be they in outline or bitmap format.
class FT_GlyphSlotRec(Structure):
    '''
    FreeType root glyph slot class structure. A glyph slot is a container where
    individual glyphs can be loaded, be they in outline or bitmap format.

    library: A handle to the FreeType library instance this slot belongs to.

    face: A handle to the parent face object.

    next: In some cases (like some font tools), several glyph slots per face
          object can be a good thing. As this is rare, the glyph slots are
          listed through a direct, single-linked list using its 'next' field.

    generic: A typeless pointer which is unused by the FreeType library or any
             of its drivers. It can be used by client applications to link
             their own data to each glyph slot object.

    metrics: The metrics of the last loaded glyph in the slot. The returned
             values depend on the last load flags (see the FT_Load_Glyph API
             function) and can be expressed either in 26.6 fractional pixels or
             font units.

             Note that even when the glyph image is transformed, the metrics
             are not.

    linearHoriAdvance: The advance width of the unhinted glyph. Its value is
                       expressed in 16.16 fractional pixels, unless
                       FT_LOAD_LINEAR_DESIGN is set when loading the
                       glyph. This field can be important to perform correct
                       WYSIWYG layout. Only relevant for outline glyphs.

    linearVertAdvance: The advance height of the unhinted glyph. Its value is
                       expressed in 16.16 fractional pixels, unless
                       FT_LOAD_LINEAR_DESIGN is set when loading the
                       glyph. This field can be important to perform correct
                       WYSIWYG layout. Only relevant for outline glyphs.

    advance: This shorthand is, depending on FT_LOAD_IGNORE_TRANSFORM, the
             transformed advance width for the glyph (in 26.6 fractional pixel
             format). As specified with FT_LOAD_VERTICAL_LAYOUT, it uses either
             the 'horiAdvance' or the 'vertAdvance' value of 'metrics' field.

    format: This field indicates the format of the image contained in the glyph
            slot. Typically FT_GLYPH_FORMAT_BITMAP, FT_GLYPH_FORMAT_OUTLINE, or
            FT_GLYPH_FORMAT_COMPOSITE, but others are possible.

    bitmap: This field is used as a bitmap descriptor when the slot format is
            FT_GLYPH_FORMAT_BITMAP. Note that the address and content of the
            bitmap buffer can change between calls of FT_Load_Glyph and a few
            other functions.

    bitmap_left: This is the bitmap's left bearing expressed in integer
                 pixels. Of course, this is only valid if the format is
                 FT_GLYPH_FORMAT_BITMAP.

    bitmap_top: This is the bitmap's top bearing expressed in integer
                pixels. Remember that this is the distance from the baseline to
                the top-most glyph scanline, upwards y coordinates being
                positive.

    outline: The outline descriptor for the current glyph image if its format
             is FT_GLYPH_FORMAT_OUTLINE. Once a glyph is loaded, 'outline' can
             be transformed, distorted, embolded, etc. However, it must not be
             freed.

    num_subglyphs: The number of subglyphs in a composite glyph. This field is
                   only valid for the composite glyph format that should
                   normally only be loaded with the FT_LOAD_NO_RECURSE
                   flag. For now this is internal to FreeType.

    subglyphs: An array of subglyph descriptors for composite glyphs. There are
               'num_subglyphs' elements in there. Currently internal to
               FreeType.

    control_data: Certain font drivers can also return the control data for a
                  given glyph image (e.g. TrueType bytecode, Type 1
                  charstrings, etc.). This field is a pointer to such data.

    control_len: This is the length in bytes of the control data.

    other: Really wicked formats can use this pointer to present their own
           glyph image to client applications. Note that the application needs
           to know about the image format.

    lsb_delta: The difference between hinted and unhinted left side bearing
               while autohinting is active. Zero otherwise.

    rsb_delta: The difference between hinted and unhinted right side bearing
               while autohinting is active. Zero otherwise.
    '''
    _fields_ = [
        ('library',           FT_Library),
        ('face',              c_void_p),
        ('next',              c_void_p),
        ('reserved',          c_uint),
        ('generic',           FT_Generic),

        ('metrics',           FT_Glyph_Metrics),
        ('linearHoriAdvance', FT_Fixed),
        ('linearVertAdvance', FT_Fixed),
        ('advance',           FT_Vector),

        ('format',            FT_Glyph_Format),

        ('bitmap',            FT_Bitmap),
        ('bitmap_left',       FT_Int),
        ('bitmap_top',        FT_Int),

        ('outline',           FT_Outline),
        ('num_subglyphs',     FT_UInt),
        ('subglyphs',         c_void_p),

        ('control_data',      c_void_p),
        ('control_len',       c_long),

        ('lsb_delta',         FT_Pos),
        ('rsb_delta',         FT_Pos),
        ('other',             c_void_p),
        ('internal',          c_void_p),
    ]
FT_GlyphSlot = POINTER(FT_GlyphSlotRec)



# -----------------------------------------------------------------------------
# The size metrics structure gives the metrics of a size object.
class FT_Size_Metrics(Structure):
    '''
    The size metrics structure gives the metrics of a size object.

    x_ppem: The width of the scaled EM square in pixels, hence the term 'ppem'
            (pixels per EM). It is also referred to as 'nominal width'.

    y_ppem: The height of the scaled EM square in pixels, hence the term 'ppem'
            (pixels per EM). It is also referred to as 'nominal height'.

    x_scale: A 16.16 fractional scaling value used to convert horizontal
             metrics from font units to 26.6 fractional pixels. Only relevant
             for scalable font formats.

    y_scale: A 16.16 fractional scaling value used to convert vertical metrics
             from font units to 26.6 fractional pixels. Only relevant for
             scalable font formats.

    ascender: The ascender in 26.6 fractional pixels. See FT_FaceRec for the
              details.

    descender: The descender in 26.6 fractional pixels. See FT_FaceRec for the
               details.

    height: The height in 26.6 fractional pixels. See FT_FaceRec for the
            details.

    max_advance: The maximal advance width in 26.6 fractional pixels. See
                 FT_FaceRec for the details.
    '''
    _fields_ = [
        ('x_ppem',      FT_UShort),
        ('y_ppem',      FT_UShort),

        ('x_scale',     FT_Fixed),
        ('y_scale',     FT_Fixed),

        ('ascender',    FT_Pos),
        ('descender',   FT_Pos),
        ('height',      FT_Pos),
        ('max_advance', FT_Pos),
    ]



# -----------------------------------------------------------------------------
# FreeType root size class structure. A size object models a face object at a
# given size.
class FT_SizeRec(Structure):
    '''
    FreeType root size class structure. A size object models a face object at a
    given size.

    face: Handle to the parent face object.

    generic: A typeless pointer, which is unused by the FreeType library or any
             of its drivers. It can be used by client applications to link
             their own data to each size object.

    metrics: Metrics for this size object. This field is read-only.
    '''
    _fields_ = [
        ('face',     c_void_p),
        ('generic',  FT_Generic),
        ('metrics',  FT_Size_Metrics),
        ('internal', c_void_p),
    ]
FT_Size = POINTER(FT_SizeRec)



# -----------------------------------------------------------------------------
# FreeType root face class structure. A face object models a typeface in a font
# file.
class FT_FaceRec(Structure):
    '''
    FreeType root face class structure. A face object models a typeface in a
    font file.

    num_faces: The number of faces in the font file. Some font formats can have
               multiple faces in a font file.

    face_index: The index of the face in the font file. It is set to 0 if there
                is only one face in the font file.

    face_flags: A set of bit flags that give important information about the
                face; see FT_FACE_FLAG_XXX for the details.

    style_flags: A set of bit flags indicating the style of the face; see
                 FT_STYLE_FLAG_XXX for the details.

    num_glyphs: The number of glyphs in the face. If the face is scalable and
                has sbits (see 'num_fixed_sizes'), it is set to the number of
                outline glyphs.

                For CID-keyed fonts, this value gives the highest CID used in
                the font.

    family_name: The face's family name. This is an ASCII string, usually in
                 English, which describes the typeface's family (like 'Times
                 New Roman', 'Bodoni', 'Garamond', etc). This is a least common
                 denominator used to list fonts. Some formats (TrueType &
                 OpenType) provide localized and Unicode versions of this
                 string. Applications should use the format specific interface
                 to access them. Can be NULL (e.g., in fonts embedded in a PDF
                 file).

    style_name: The face's style name. This is an ASCII string, usually in
                English, which describes the typeface's style (like 'Italic',
                'Bold', 'Condensed', etc). Not all font formats provide a style
                name, so this field is optional, and can be set to NULL. As for
                'family_name', some formats provide localized and Unicode
                versions of this string. Applications should use the format
                specific interface to access them.

    num_fixed_sizes: The number of bitmap strikes in the face. Even if the face
                     is scalable, there might still be bitmap strikes, which
                     are called 'sbits' in that case.

    available_sizes: An array of FT_Bitmap_Size for all bitmap strikes in the
                     face. It is set to NULL if there is no bitmap strike.

    num_charmaps: The number of charmaps in the face.

    charmaps: An array of the charmaps of the face.

    generic: A field reserved for client uses. See the FT_Generic type
            description.

    bbox: The font bounding box. Coordinates are expressed in font units (see
          'units_per_EM'). The box is large enough to contain any glyph from
          the font. Thus, 'bbox.yMax' can be seen as the 'maximal ascender',
          and 'bbox.yMin' as the 'minimal descender'. Only relevant for
          scalable formats.

          Note that the bounding box might be off by (at least) one pixel for
          hinted fonts. See FT_Size_Metrics for further discussion.

    units_per_EM: The number of font units per EM square for this face. This is
                  typically 2048 for TrueType fonts, and 1000 for Type 1
                  fonts. Only relevant for scalable formats.

    ascender: The typographic ascender of the face, expressed in font
              units. For font formats not having this information, it is set to
              'bbox.yMax'. Only relevant for scalable formats.

    descender: The typographic descender of the face, expressed in font
               units. For font formats not having this information, it is set
               to 'bbox.yMin'. Note that this field is usually negative. Only
               relevant for scalable formats.

    height: The height is the vertical distance between two consecutive
            baselines, expressed in font units. It is always positive. Only
            relevant for scalable formats.

    max_advance_width: The maximal advance width, in font units, for all glyphs
                       in this face. This can be used to make word wrapping
                       computations faster. Only relevant for scalable formats.

    max_advance_height: The maximal advance height, in font units, for all
                        glyphs in this face. This is only relevant for vertical
                        layouts, and is set to 'height' for fonts that do not
                        provide vertical metrics. Only relevant for scalable
                        formats.

    underline_position: The position, in font units, of the underline line for
                        this face. It is the center of the underlining
                        stem. Only relevant for scalable formats.

    underline_thickness: The thickness, in font units, of the underline for
                         this face. Only relevant for scalable formats.

    glyph: The face's associated glyph slot(s).

    size: The current active size for this face.

    charmap: The current active charmap for this face.
    '''
    _fields_ = [
          ('num_faces',  FT_Long),
          ('face_index', FT_Long),

          ('face_flags',  FT_Long),
          ('style_flags', FT_Long),

          ('num_glyphs',  FT_Long),

          ('family_name', FT_String_p),
          ('style_name',  FT_String_p),

          ('num_fixed_sizes', FT_Int),
          ('available_sizes', POINTER(FT_Bitmap_Size)),

          ('num_charmaps', c_int),
          ('charmaps',     POINTER(FT_Charmap)),

          ('generic', FT_Generic),

          # The following member variables (down to `underline_thickness')
          # are only relevant to scalable outlines; cf. @FT_Bitmap_Size
          # for bitmap fonts.
          ('bbox', FT_BBox),

          ('units_per_EM', FT_UShort),
          ('ascender',     FT_Short),
          ('descender',    FT_Short),
          ('height',       FT_Short),

          ('max_advance_width',  FT_Short),
          ('max_advance_height', FT_Short),

          ('underline_position',  FT_Short),
          ('underline_thickness', FT_Short),

          ('glyph',   FT_GlyphSlot),
          ('size',    FT_Size),
          ('charmap', FT_Charmap),

          # private
          ('driver',          c_void_p),
          ('memory',          c_void_p),
          ('stream',          c_void_p),
          ('sizes_list_head', c_void_p),
          ('sizes_list_tail', c_void_p),
          ('autohint',        FT_Generic),
          ('extensions',      c_void_p),
          ('internal',        c_void_p),
    ]
FT_Face = POINTER(FT_FaceRec)



# -----------------------------------------------------------------------------
# A simple structure used to pass more or less generic parameters to
# FT_Open_Face.
class FT_Parameter(Structure):
    '''
    A simple structure used to pass more or less generic parameters to
    FT_Open_Face.

    tag: A four-byte identification tag.

    data: A pointer to the parameter data
    '''
    _fields_ = [
        ('tag',  FT_ULong),
        ('data', FT_Pointer) ]
FT_Parameter_p = POINTER(FT_Parameter)



# -----------------------------------------------------------------------------
# A structure used to indicate how to open a new font file or stream. A pointer
# to such a structure can be used as a parameter for the functions FT_Open_Face
# and FT_Attach_Stream.
class FT_Open_Args(Structure):
    '''
    A structure used to indicate how to open a new font file or stream. A pointer
    to such a structure can be used as a parameter for the functions FT_Open_Face
    and FT_Attach_Stream.

    flags: A set of bit flags indicating how to use the structure.

    memory_base: The first byte of the file in memory.

    memory_size: The size in bytes of the file in memory.

    pathname: A pointer to an 8-bit file pathname.

    stream: A handle to a source stream object.

    driver: This field is exclusively used by FT_Open_Face; it simply specifies
            the font driver to use to open the face. If set to 0, FreeType
            tries to load the face with each one of the drivers in its list.

    num_params: The number of extra parameters.

    params: Extra parameters passed to the font driver when opening a new face.
    '''
    _fields_ = [
        ('flags',        FT_UInt),
        ('memory_base',  POINTER(FT_Byte)),
        ('memory_size',  FT_Long),
        ('pathname',     FT_String_p),
        ('stream',       c_void_p),
        ('driver',       c_void_p),
        ('num_params',   FT_Int),
        ('params',       FT_Parameter_p) ]



# -----------------------------------------------------------------------------
# A structure used to model an SFNT 'name' table entry.

class FT_SfntName(Structure):
    '''
    platform_id: The platform ID for 'string'.

    encoding_id: The encoding ID for 'string'.

    language_id: The language ID for 'string'

    name_id: An identifier for 'string'

    string: The 'name' string. Note that its format differs depending on the
            (platform,encoding) pair. It can be a Pascal String, a UTF-16 one,
            etc.

            Generally speaking, the string is not zero-terminated. Please refer
            to the TrueType specification for details.

    string_len: The length of 'string' in bytes.
    '''

    _fields_ = [
        ('platform_id', FT_UShort),
        ('encoding_id', FT_UShort),
        ('language_id', FT_UShort),
        ('name_id',     FT_UShort),
        # this string is *not* null-terminated!
        ('string',      POINTER(FT_Byte)),
        ('string_len',  FT_UInt) ]



# -----------------------------------------------------------------------------
# Opaque handler to a path stroker object.
class FT_StrokerRec(Structure):
    '''
    Opaque handler to a path stroker object.
    '''
    _fields_ = [ ]
FT_Stroker = POINTER(FT_StrokerRec)


# -----------------------------------------------------------------------------
# A structure used for bitmap glyph images. This really is a 'sub-class' of
# FT_GlyphRec.
#
class FT_BitmapGlyphRec(Structure):
    '''
    A structure used for bitmap glyph images. This really is a 'sub-class' of
    FT_GlyphRec.
    '''
    _fields_ = [
        ('root' , FT_GlyphRec),
        ('left', FT_Int),
        ('top', FT_Int),
        ('bitmap', FT_Bitmap)
    ]
FT_BitmapGlyph = POINTER(FT_BitmapGlyphRec)
