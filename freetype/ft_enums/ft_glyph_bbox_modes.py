# -*- coding: utf-8 -*-
# -----------------------------------------------------------------------------
#
#  FreeType high-level python API - Copyright 2011-2015 Nicolas P. Rougier
#  Distributed under the terms of the new BSD license.
#
# -----------------------------------------------------------------------------
"""
The mode how the values of FT_Glyph_Get_CBox are returned.

FT_GLYPH_BBOX_UNSCALED

  Return unscaled font units.

FT_GLYPH_BBOX_SUBPIXELS

  Return unfitted 26.6 coordinates.

FT_GLYPH_BBOX_GRIDFIT

  Return grid-fitted 26.6 coordinates.

FT_GLYPH_BBOX_TRUNCATE

  Return coordinates in integer pixels.

FT_GLYPH_BBOX_PIXELS

  Return grid-fitted pixel coordinates.
"""
FT_GLYPH_BBOX_MODES = {'FT_GLYPH_BBOX_UNSCALED'  : 0,
                       'FT_GLYPH_BBOX_SUBPIXELS' : 0,
                       'FT_GLYPH_BBOX_GRIDFIT'   : 1,
                       'FT_GLYPH_BBOX_TRUNCATE'  : 2,
                       'FT_GLYPH_BBOX_PIXELS'    : 3}
globals().update(FT_GLYPH_BBOX_MODES)
