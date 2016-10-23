# -*- coding: utf-8 -*-
# -----------------------------------------------------------------------------
#
#  FreeType high-level python API - Copyright 2011-2015 Nicolas P. Rougier
#  Distributed under the terms of the new BSD license.
#
# -----------------------------------------------------------------------------
"""
A list of valid values for the 'encoding_id' for TT_PLATFORM_ADOBE
charmaps. This is a FreeType-specific extension!

TT_ADOBE_ID_STANDARD

  Adobe standard encoding.


TT_ADOBE_ID_EXPERT

  Adobe expert encoding.


TT_ADOBE_ID_CUSTOM

  Adobe custom encoding.


TT_ADOBE_ID_LATIN_1

  Adobe Latin 1 encoding.
"""

TT_ADOBE_IDS = {
    'TT_ADOBE_ID_STANDARD' : 0,
    'TT_ADOBE_ID_EXPERT'   : 1,
    'TT_ADOBE_ID_CUSTOM'   : 2,
    'TT_ADOBE_ID_LATIN_1'  : 3 }
globals().update(TT_ADOBE_IDS)
