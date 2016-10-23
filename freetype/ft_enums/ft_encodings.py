# -*- coding: utf-8 -*-
# -----------------------------------------------------------------------------
#
#  FreeType high-level python API - Copyright 2011-2015 Nicolas P. Rougier
#  Distributed under the terms of the new BSD license.
#
# -----------------------------------------------------------------------------
"""
An enumeration used to specify character sets supported by charmaps. Used in
the FT_Select_Charmap API function.

FT_ENCODING_NONE

  The encoding value 0 is reserved.

FT_ENCODING_UNICODE

  Corresponds to the Unicode character set. This value covers all versions of
  the Unicode repertoire, including ASCII and Latin-1. Most fonts include a
  Unicode charmap, but not all of them.

  For example, if you want to access Unicode value U+1F028 (and the font
  contains it), use value 0x1F028 as the input value for FT_Get_Char_Index.

FT_ENCODING_MS_SYMBOL

  Corresponds to the Microsoft Symbol encoding, used to encode mathematical
  symbols in the 32..255 character code range. For more information, see
  'http://www.ceviz.net/symbol.htm'.

FT_ENCODING_SJIS

  Corresponds to Japanese SJIS encoding. More info at at
  'http://langsupport.japanreference.com/encoding.shtml'. See note on
  multi-byte encodings below.

FT_ENCODING_GB2312

  Corresponds to an encoding system for Simplified Chinese as used used in
  mainland China.

FT_ENCODING_BIG5

  Corresponds to an encoding system for Traditional Chinese as used in Taiwan
  and Hong Kong.

FT_ENCODING_WANSUNG

  Corresponds to the Korean encoding system known as Wansung. For more
  information see 'http://www.microsoft.com/typography/unicode/949.txt'.

FT_ENCODING_JOHAB

  The Korean standard character set (KS C 5601-1992), which corresponds to MS
  Windows code page 1361. This character set includes all possible Hangeul
  character combinations.

FT_ENCODING_ADOBE_LATIN_1

  Corresponds to a Latin-1 encoding as defined in a Type 1 PostScript font. It
  is limited to 256 character codes.

FT_ENCODING_ADOBE_STANDARD

  Corresponds to the Adobe Standard encoding, as found in Type 1, CFF, and
  OpenType/CFF fonts. It is limited to 256 character codes.

FT_ENCODING_ADOBE_EXPERT

  Corresponds to the Adobe Expert encoding, as found in Type 1, CFF, and
  OpenType/CFF fonts. It is limited to 256 character codes.

FT_ENCODING_ADOBE_CUSTOM

  Corresponds to a custom encoding, as found in Type 1, CFF, and OpenType/CFF
  fonts. It is limited to 256 character codes.

FT_ENCODING_APPLE_ROMAN

  Corresponds to the 8-bit Apple roman encoding. Many TrueType and OpenType
  fonts contain a charmap for this encoding, since older versions of Mac OS are
  able to use it.

FT_ENCODING_OLD_LATIN_2

  This value is deprecated and was never used nor reported by FreeType. Don't
  use or test for it.
"""

def _FT_ENC_TAG(a,b,c,d):
    return ( ord(a) << 24 | ord(b) << 16 | ord(c) << 8 | ord(d) )

FT_ENCODINGS = {'FT_ENCODING_NONE'           : _FT_ENC_TAG('\0','\0','\0','\0'),
                'FT_ENCODING_MS_SYMBOL'      : _FT_ENC_TAG( 's','y','m','b' ),
                'FT_ENCODING_UNICODE'        : _FT_ENC_TAG( 'u','n','i','c' ),
                'FT_ENCODING_SJIS'           : _FT_ENC_TAG( 's','j','i','s' ),
                'FT_ENCODING_GB2312'         : _FT_ENC_TAG( 'g','b',' ',' ' ),
                'FT_ENCODING_BIG5'           : _FT_ENC_TAG( 'b','i','g','5' ),
                'FT_ENCODING_WANSUNG'        : _FT_ENC_TAG( 'w','a','n','s' ),
                'FT_ENCODING_JOHAB'          : _FT_ENC_TAG( 'j','o','h','a' ),
                'FT_ENCODING_ADOBE_STANDARD' : _FT_ENC_TAG( 'A','D','O','B' ),
                'FT_ENCODING_ADOBE_EXPERT'   : _FT_ENC_TAG( 'A','D','B','E' ),
                'FT_ENCODING_ADOBE_CUSTOM'   : _FT_ENC_TAG( 'A','D','B','C' ),
                'FT_ENCODING_ADOBE_LATIN1'   : _FT_ENC_TAG( 'l','a','t','1' ),
                'FT_ENCODING_OLD_LATIN2'     : _FT_ENC_TAG( 'l','a','t','2' ),
                'FT_ENCODING_APPLE_ROMAN'    : _FT_ENC_TAG( 'a','r','m','n' ) }
globals().update(FT_ENCODINGS)
