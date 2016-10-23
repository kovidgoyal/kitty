# -*- coding: utf-8 -*-
# -----------------------------------------------------------------------------
#
#  FreeType high-level python API - Copyright 2011-2015 Nicolas P. Rougier
#  Distributed under the terms of the new BSD license.
#
# -----------------------------------------------------------------------------
"""
A list of valid values for the 'encoding_id' for TT_PLATFORM_MICROSOFT
charmaps and name entries.


TT_MS_ID_SYMBOL_CS

  Corresponds to Microsoft symbol encoding. See FT_ENCODING_MS_SYMBOL.


TT_MS_ID_UNICODE_CS

  Corresponds to a Microsoft WGL4 charmap, matching Unicode. See
  FT_ENCODING_UNICODE.


TT_MS_ID_SJIS

  Corresponds to SJIS Japanese encoding. See FT_ENCODING_SJIS.


TT_MS_ID_GB2312

  Corresponds to Simplified Chinese as used in Mainland China. See
  FT_ENCODING_GB2312.


TT_MS_ID_BIG_5

  Corresponds to Traditional Chinese as used in Taiwan and Hong Kong. See
  FT_ENCODING_BIG5.


TT_MS_ID_WANSUNG

  Corresponds to Korean Wansung encoding. See FT_ENCODING_WANSUNG.

TT_MS_ID_JOHAB

  Corresponds to Johab encoding. See FT_ENCODING_JOHAB.


TT_MS_ID_UCS_4

  Corresponds to UCS-4 or UTF-32 charmaps. This has been added to the OpenType
  specification version 1.4 (mid-2001.)
"""

TT_MS_IDS = {
    'TT_MS_ID_SYMBOL_CS'  :  0,
    'TT_MS_ID_UNICODE_CS' :  1,
    'TT_MS_ID_SJIS'       :  2,
    'TT_MS_ID_GB2312'     :  3,
    'TT_MS_ID_BIG_5'      :  4,
    'TT_MS_ID_WANSUNG'    :  5,
    'TT_MS_ID_JOHAB'      :  6,
    'TT_MS_ID_UCS_4'      : 10 }
globals().update(TT_MS_IDS)
