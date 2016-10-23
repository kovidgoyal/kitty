# -*- coding: utf-8 -*-
# -----------------------------------------------------------------------------
#
#  FreeType high-level python API - Copyright 2011-2015 Nicolas P. Rougier
#  Distributed under the terms of the new BSD license.
#
# -----------------------------------------------------------------------------
"""
These values are used to select a given stroke border in
FT_Stroker_GetBorderCounts and FT_Stroker_ExportBorder.


FT_STROKER_BORDER_LEFT

  Select the left border, relative to the drawing direction.


FT_STROKER_BORDER_RIGHT

  Select the right border, relative to the drawing direction.


Note

  Applications are generally interested in the 'inside' and 'outside'
  borders. However, there is no direct mapping between these and the 'left' and
  'right' ones, since this really depends on the glyph's drawing orientation,
  which varies between font formats.

  You can however use FT_Outline_GetInsideBorder and
  FT_Outline_GetOutsideBorder to get these.
"""
FT_STROKER_BORDERS = { 'FT_STROKER_BORDER_LEFT'  : 0,
                       'FT_STROKER_BORDER_RIGHT' : 1}
globals().update(FT_STROKER_BORDERS)
