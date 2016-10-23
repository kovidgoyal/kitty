# -*- coding: utf-8 -*-
# -----------------------------------------------------------------------------
#
#  FreeType high-level python API - Copyright 2011-2015 Nicolas P. Rougier
#  Distributed under the terms of the new BSD license.
#
# -----------------------------------------------------------------------------
"""
A list of bit-flags used to indicate the style of a given face. These are
used in the 'style_flags' field of FT_FaceRec.


FT_STYLE_FLAG_ITALIC

  Indicates that a given face style is italic or oblique.


FT_STYLE_FLAG_BOLD

  Indicates that a given face is bold.
"""
FT_STYLE_FLAGS = {'FT_STYLE_FLAG_ITALIC' : 1,
                   'FT_STYLE_FLAG_BOLD'   : 2 }
globals().update(FT_STYLE_FLAGS)
