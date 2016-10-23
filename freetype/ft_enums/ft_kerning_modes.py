# -*- coding: utf-8 -*-
# -----------------------------------------------------------------------------
#
#  FreeType high-level python API - Copyright 2011-2015 Nicolas P. Rougier
#  Distributed under the terms of the new BSD license.
#
# -----------------------------------------------------------------------------
"""
An enumeration used to specify which kerning values to return in
FT_Get_Kerning.


FT_KERNING_DEFAULT

  Return scaled and grid-fitted kerning distances (value is 0).


FT_KERNING_UNFITTED

  Return scaled but un-grid-fitted kerning distances.


FT_KERNING_UNSCALED

  Return the kerning vector in original font units.
"""
FT_KERNING_MODES = { 'FT_KERNING_DEFAULT'  : 0,
                     'FT_KERNING_UNFITTED' : 1,
                     'FT_KERNING_UNSCALED' : 2 }
globals().update(FT_KERNING_MODES)
