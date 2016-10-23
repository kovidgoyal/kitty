# -*- coding: utf-8 -*-
# -----------------------------------------------------------------------------
#
#  FreeType high-level python API - Copyright 2011-2015 Nicolas P. Rougier
#  Distributed under the terms of the new BSD license.
#
# -----------------------------------------------------------------------------
"""
These values determine how the end of opened sub-paths are rendered in a
stroke.


FT_STROKER_LINECAP_BUTT

  The end of lines is rendered as a full stop on the last point itself.


FT_STROKER_LINECAP_ROUND

  The end of lines is rendered as a half-circle around the last point.


FT_STROKER_LINECAP_SQUARE

  The end of lines is rendered as a square around the last point.
"""

FT_STROKER_LINECAPS = { 'FT_STROKER_LINECAP_BUTT'   : 0,
                        'FT_STROKER_LINECAP_ROUND'  : 1,
                        'FT_STROKER_LINECAP_SQUARE' : 2}
globals().update(FT_STROKER_LINECAPS)
