# -*- coding: utf-8 -*-
# -----------------------------------------------------------------------------
#
#  FreeType high-level python API - Copyright 2011-2015 Nicolas P. Rougier
#  Distributed under the terms of the new BSD license.
#
# -----------------------------------------------------------------------------
"""
An enumeration type that lists the render modes supported by FreeType 2. Each
mode corresponds to a specific type of scanline conversion performed on the
outline.


FT_PIXEL_MODE_NONE

  Value 0 is reserved.


FT_PIXEL_MODE_MONO

  A monochrome bitmap, using 1 bit per pixel. Note that pixels are stored in
  most-significant order (MSB), which means that the left-most pixel in a byte
  has value 128.


FT_PIXEL_MODE_GRAY

  An 8-bit bitmap, generally used to represent anti-aliased glyph images. Each
  pixel is stored in one byte. Note that the number of 'gray' levels is stored
  in the 'num_grays' field of the FT_Bitmap structure (it generally is 256).


FT_PIXEL_MODE_GRAY2

  A 2-bit per pixel bitmap, used to represent embedded anti-aliased bitmaps in
  font files according to the OpenType specification. We haven't found a single
  font using this format, however.


FT_PIXEL_MODE_GRAY4

  A 4-bit per pixel bitmap, representing embedded anti-aliased bitmaps in font
  files according to the OpenType specification. We haven't found a single font
  using this format, however.


FT_PIXEL_MODE_LCD

  An 8-bit bitmap, representing RGB or BGR decimated glyph images used for
  display on LCD displays; the bitmap is three times wider than the original
  glyph image. See also FT_RENDER_MODE_LCD.


FT_PIXEL_MODE_LCD_V

  An 8-bit bitmap, representing RGB or BGR decimated glyph images used for
  display on rotated LCD displays; the bitmap is three times taller than the
  original glyph image. See also FT_RENDER_MODE_LCD_V.

"""

FT_PIXEL_MODES = {'FT_PIXEL_MODE_NONE' : 0,
                  'FT_PIXEL_MODE_MONO' : 1,
                  'FT_PIXEL_MODE_GRAY' : 2,
                  'FT_PIXEL_MODE_GRAY2': 3,
                  'FT_PIXEL_MODE_GRAY4': 4,
                  'FT_PIXEL_MODE_LCD'  : 5,
                  'FT_PIXEL_MODE_LCD_V': 6,
                  'FT_PIXEL_MODE_MAX'  : 7}
globals().update(FT_PIXEL_MODES)
ft_pixel_mode_none  = FT_PIXEL_MODE_NONE
ft_pixel_mode_mono  = FT_PIXEL_MODE_MONO
ft_pixel_mode_grays = FT_PIXEL_MODE_GRAY
ft_pixel_mode_pal2  = FT_PIXEL_MODE_GRAY2
ft_pixel_mode_pal4  = FT_PIXEL_MODE_GRAY4
