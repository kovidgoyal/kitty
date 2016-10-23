# -*- coding: utf-8 -*-
# -----------------------------------------------------------------------------
#
#  FreeType high-level python API - Copyright 2011-2015 Nicolas P. Rougier
#  Distributed under the terms of the new BSD license.
#
# -----------------------------------------------------------------------------
"""
A list of values that are used to select a specific hinting algorithm to use
by the hinter. You should OR one of these values to your 'load_flags' when
calling FT_Load_Glyph.

Note that font's native hinters may ignore the hinting algorithm you have
specified (e.g., the TrueType bytecode interpreter). You can set
FT_LOAD_FORCE_AUTOHINT to ensure that the auto-hinter is used.

Also note that FT_LOAD_TARGET_LIGHT is an exception, in that it always
implies FT_LOAD_FORCE_AUTOHINT.


FT_LOAD_TARGET_NORMAL

  This corresponds to the default hinting algorithm, optimized for standard
  gray-level rendering. For monochrome output, use FT_LOAD_TARGET_MONO instead.


FT_LOAD_TARGET_LIGHT

  A lighter hinting algorithm for non-monochrome modes. Many generated glyphs
  are more fuzzy but better resemble its original shape. A bit like rendering
  on Mac OS X.

  As a special exception, this target implies FT_LOAD_FORCE_AUTOHINT.


FT_LOAD_TARGET_MONO

  Strong hinting algorithm that should only be used for monochrome output. The
  result is probably unpleasant if the glyph is rendered in non-monochrome
  modes.


FT_LOAD_TARGET_LCD

  A variant of FT_LOAD_TARGET_NORMAL optimized for horizontally decimated LCD
  displays.


FT_LOAD_TARGET_LCD_V

  A variant of FT_LOAD_TARGET_NORMAL optimized for vertically decimated LCD
  displays.
"""

from freetype.ft_enums.ft_render_modes import *


def _FT_LOAD_TARGET_(x):
    return (x & 15) << 16
FT_LOAD_TARGETS = {
    'FT_LOAD_TARGET_NORMAL' : _FT_LOAD_TARGET_(FT_RENDER_MODE_NORMAL),
    'FT_LOAD_TARGET_LIGHT'  : _FT_LOAD_TARGET_(FT_RENDER_MODE_LIGHT),
    'FT_LOAD_TARGET_MONO'   : _FT_LOAD_TARGET_(FT_RENDER_MODE_MONO),
    'FT_LOAD_TARGET_LCD'    : _FT_LOAD_TARGET_(FT_RENDER_MODE_LCD),
    'FT_LOAD_TARGET_LCD_V'  : _FT_LOAD_TARGET_(FT_RENDER_MODE_LCD_V) }
globals().update(FT_LOAD_TARGETS)
#def FT_LOAD_TARGET_MODE(x):
#    return (x >> 16) & 15
