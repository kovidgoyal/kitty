# -*- coding: utf-8 -*-
# -----------------------------------------------------------------------------
#
#  FreeType high-level python API - Copyright 2011-2015 Nicolas P. Rougier
#  Distributed under the terms of the new BSD license.
#
# -----------------------------------------------------------------------------
"""
A list of valid values for the 'encoding_id' for TT_PLATFORM_APPLE_UNICODE
charmaps and name entries.


TT_APPLE_ID_DEFAULT

  Unicode version 1.0.


TT_APPLE_ID_UNICODE_1_1

  Unicode 1.1; specifies Hangul characters starting at U+34xx.


TT_APPLE_ID_ISO_10646

  Deprecated (identical to preceding).


TT_APPLE_ID_UNICODE_2_0

  Unicode 2.0 and beyond (UTF-16 BMP only).


TT_APPLE_ID_UNICODE_32

  Unicode 3.1 and beyond, using UTF-32.


TT_APPLE_ID_VARIANT_SELECTOR

  From Adobe, not Apple. Not a normal cmap. Specifies variations on a real
  cmap.
"""
TT_APPLE_IDS = {
    'TT_APPLE_ID_DEFAULT'          : 0,
    'TT_APPLE_ID_UNICODE_1_1'      : 1,
    'TT_APPLE_ID_ISO_10646'        : 2,
    'TT_APPLE_ID_UNICODE_2_0'      : 3,
    'TT_APPLE_ID_UNICODE_32'       : 4,
    'TT_APPLE_ID_VARIANT_SELECTOR' : 5 }
globals().update(TT_APPLE_IDS)
