#!/usr/bin/env python
# -*- coding: utf-8 -*-
# -----------------------------------------------------------------------------
#
#  FreeType high-level python API - Copyright 2011 Nicolas P. Rougier
#  Distributed under the terms of the new BSD license.
#
# -----------------------------------------------------------------------------
'''
Freetype basic data types
-------------------------

FT_Byte : A simple typedef for the unsigned char type.

FT_Bytes : A typedef for constant memory areas.

FT_Char : A simple typedef for the signed char type.

FT_Int : A typedef for the int type.

FT_UInt : A typedef for the unsigned int type.

FT_Int16 : A typedef for a 16bit signed integer type.

FT_UInt16 : A typedef for a 16bit unsigned integer type.

FT_Int32 : A typedef for a 32bit signed integer type.

FT_UInt32 : A typedef for a 32bit unsigned integer type.

FT_Short : A typedef for signed short.

FT_UShort : A typedef for unsigned short.

FT_Long : A typedef for signed long.

FT_ULong : A typedef for unsigned long.

FT_Bool : A typedef of unsigned char, used for simple booleans. As usual,
          values 1 and 0 represent true and false, respectively.

FT_Offset : This is equivalent to the ANSI C 'size_t' type, i.e., the largest
            unsigned integer type used to express a file size or position, or
            a memory block size.

FT_PtrDist : This is equivalent to the ANSI C 'ptrdiff_t' type, i.e., the
             largest signed integer type used to express the distance between
             two pointers.

FT_String : A simple typedef for the char type, usually used for strings. 

FT_Tag  : A typedef for 32-bit tags (as used in the SFNT format).

FT_Error : The FreeType error code type. A value of 0 is always interpreted as
           a successful operation.

FT_Fixed : This type is used to store 16.16 fixed float values, like scaling
           values or matrix coefficients.

FT_Pointer : A simple typedef for a typeless pointer.

FT_Pos : The type FT_Pos is used to store vectorial coordinates. Depending on
         the context, these can represent distances in integer font units, or
         16.16, or 26.6 fixed float pixel coordinates.

FT_FWord : A signed 16-bit integer used to store a distance in original font
           units.

FT_UFWord : An unsigned 16-bit integer used to store a distance in original
            font units.

FT_F2Dot14 : A signed 2.14 fixed float type used for unit vectors.

FT_F26Dot6 : A signed 26.6 fixed float type used for vectorial pixel
             coordinates.
'''
from ctypes import *


FT_Byte    = c_ubyte  # A simple typedef for the unsigned char type.

FT_Bytes   = c_char_p # A typedef for constant memory areas.

FT_Char    = c_char   # A simple typedef for the signed char type.

FT_Int     = c_int    # A typedef for the int type.

FT_UInt    = c_uint   # A typedef for the unsigned int type.

FT_Int16   = c_short  # A typedef for a 16bit signed integer type.

FT_UInt16  = c_ushort # A typedef for a 16bit unsigned integer type.

FT_Int32   = c_int32  # A typedef for a 32bit signed integer type.

FT_UInt32  = c_uint32 # A typedef for a 32bit unsigned integer type.

FT_Short   = c_short  # A typedef for signed short.

FT_UShort  = c_ushort # A typedef for unsigned short.

FT_Long    = c_long   # A typedef for signed long.

FT_ULong   = c_ulong  # A typedef for unsigned long.

FT_Bool    = c_char   # A typedef of unsigned char, used for simple booleans. As
                      # usual, values 1 and 0 represent true and false,
                      # respectively.

FT_Offset  = c_size_t # This is equivalent to the ANSI C 'size_t' type, i.e.,
                      # the largest unsigned integer type used to express a file
                      # size or position, or a memory block size.

FT_PtrDist = c_longlong # This is equivalent to the ANSI C 'ptrdiff_t' type,
                        # i.e., the largest signed integer type used to express
                        # the distance between two pointers.

FT_String  = c_char   # A simple typedef for the char type, usually used for strings. 

FT_String_p= c_char_p

FT_Tag     = FT_UInt32 # A typedef for 32-bit tags (as used in the SFNT format).

FT_Error   = c_int    # The FreeType error code type. A value of 0 is always
                      # interpreted as a successful operation.

FT_Fixed   = c_long   # This type is used to store 16.16 fixed float values,
                      # like scaling values or matrix coefficients.

FT_Pointer = c_void_p # A simple typedef for a typeless pointer.

FT_Pos     = c_long   # The type FT_Pos is used to store vectorial
                      # coordinates. Depending on the context, these can
                      # represent distances in integer font units, or 16.16, or
                      # 26.6 fixed float pixel coordinates.

FT_FWord   = c_short  # A signed 16-bit integer used to store a distance in
                      # original font units.

FT_UFWord  = c_ushort # An unsigned 16-bit integer used to store a distance in
                      # original font units.

FT_F2Dot14 = c_short  # A signed 2.14 fixed float type used for unit vectors.

FT_F26Dot6 = c_long   # A signed 26.6 fixed float type used for vectorial pixel
                      # coordinates.

FT_Glyph_Format = c_int

FT_Encoding     = c_int


# Describe a function used to destroy the 'client' data of any FreeType
# object. See the description of the FT_Generic type for details of usage.
FT_Generic_Finalizer = CFUNCTYPE(None, c_void_p)
