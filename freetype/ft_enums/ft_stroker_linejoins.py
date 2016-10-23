# -*- coding: utf-8 -*-
# -----------------------------------------------------------------------------
#
#  FreeType high-level python API - Copyright 2011-2015 Nicolas P. Rougier
#  Distributed under the terms of the new BSD license.
#
# -----------------------------------------------------------------------------
"""
These values determine how two joining lines are rendered in a stroker.


FT_STROKER_LINEJOIN_ROUND

  Used to render rounded line joins. Circular arcs are used to join two lines
  smoothly.


FT_STROKER_LINEJOIN_BEVEL

  Used to render beveled line joins; i.e., the two joining lines are extended
  until they intersect.


FT_STROKER_LINEJOIN_MITER

  Same as beveled rendering, except that an additional line break is added if
  the angle between the two joining lines is too closed (this is useful to
  avoid unpleasant spikes in beveled rendering).
"""
FT_STROKER_LINEJOINS = { 'FT_STROKER_LINEJOIN_ROUND' : 0,
                         'FT_STROKER_LINEJOIN_BEVEL' : 1,
                         'FT_STROKER_LINEJOIN_MITER' : 2}
globals().update(FT_STROKER_LINEJOINS)
