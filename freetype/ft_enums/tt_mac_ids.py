# -*- coding: utf-8 -*-
# -----------------------------------------------------------------------------
#
#  FreeType high-level python API - Copyright 2011-2015 Nicolas P. Rougier
#  Distributed under the terms of the new BSD license.
#
# -----------------------------------------------------------------------------
"""
A list of valid values for the 'encoding_id' for TT_PLATFORM_MACINTOSH
charmaps and name entries.

TT_MAC_ID_ROMAN

TT_MAC_ID_TELUGU

TT_MAC_ID_GURMUKHI

TT_MAC_ID_TIBETAN

TT_MAC_ID_SIMPLIFIED_CHINESE

TT_MAC_ID_SINDHI

TT_MAC_ID_SINHALESE

TT_MAC_ID_RUSSIAN

TT_MAC_ID_KANNADA

TT_MAC_ID_VIETNAMESE

TT_MAC_ID_MONGOLIAN

TT_MAC_ID_DEVANAGARI

TT_MAC_ID_HEBREW

TT_MAC_ID_TAMIL

TT_MAC_ID_THAI

TT_MAC_ID_BURMESE

TT_MAC_ID_MALDIVIAN

TT_MAC_ID_TRADITIONAL_CHINESE

TT_MAC_ID_JAPANESE

TT_MAC_ID_GREEK

TT_MAC_ID_LAOTIAN

TT_MAC_ID_KHMER

TT_MAC_ID_UNINTERP

TT_MAC_ID_ORIYA

TT_MAC_ID_RSYMBOL

TT_MAC_ID_MALAYALAM

TT_MAC_ID_GEEZ

TT_MAC_ID_KOREAN

TT_MAC_ID_GUJARATI

TT_MAC_ID_BENGALI

TT_MAC_ID_ARABIC

TT_MAC_ID_GEORGIAN

TT_MAC_ID_ARMENIAN

TT_MAC_ID_SLAVIC
"""

TT_MAC_IDS = {
    'TT_MAC_ID_ROMAN'               :  0,
    'TT_MAC_ID_JAPANESE'            :  1,
    'TT_MAC_ID_TRADITIONAL_CHINESE' :  2,
    'TT_MAC_ID_KOREAN'              :  3,
    'TT_MAC_ID_ARABIC'              :  4,
    'TT_MAC_ID_HEBREW'              :  5,
    'TT_MAC_ID_GREEK'               :  6,
    'TT_MAC_ID_RUSSIAN'             :  7,
    'TT_MAC_ID_RSYMBOL'             :  8,
    'TT_MAC_ID_DEVANAGARI'          :  9,
    'TT_MAC_ID_GURMUKHI'            : 10,
    'TT_MAC_ID_GUJARATI'            : 11,
    'TT_MAC_ID_ORIYA'               : 12,
    'TT_MAC_ID_BENGALI'             : 13,
    'TT_MAC_ID_TAMIL'               : 14,
    'TT_MAC_ID_TELUGU'              : 15,
    'TT_MAC_ID_KANNADA'             : 16,
    'TT_MAC_ID_MALAYALAM'           : 17,
    'TT_MAC_ID_SINHALESE'           : 18,
    'TT_MAC_ID_BURMESE'             : 19,
    'TT_MAC_ID_KHMER'               : 20,
    'TT_MAC_ID_THAI'                : 21,
    'TT_MAC_ID_LAOTIAN'             : 22,
    'TT_MAC_ID_GEORGIAN'            : 23,
    'TT_MAC_ID_ARMENIAN'            : 24,
    'TT_MAC_ID_MALDIVIAN'           : 25,
    'TT_MAC_ID_SIMPLIFIED_CHINESE'  : 25,
    'TT_MAC_ID_TIBETAN'             : 26,
    'TT_MAC_ID_MONGOLIAN'           : 27,
    'TT_MAC_ID_GEEZ'                : 28,
    'TT_MAC_ID_SLAVIC'              : 29,
    'TT_MAC_ID_VIETNAMESE'          : 30,
    'TT_MAC_ID_SINDHI'              : 31,
    'TT_MAC_ID_UNINTERP'            : 32}
globals().update(TT_MAC_IDS)
