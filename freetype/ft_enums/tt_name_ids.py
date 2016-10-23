# -*- coding: utf-8 -*-
# -----------------------------------------------------------------------------
#
#  FreeType high-level python API - Copyright 2011-2015 Nicolas P. Rougier
#  Distributed under the terms of the new BSD license.
#
# -----------------------------------------------------------------------------

"""
Possible values of the 'name' identifier field in the name records of the TTF
'name' table. These values are platform independent.

TT_NAME_ID_COPYRIGHT

TT_NAME_ID_FONT_FAMILY

TT_NAME_ID_FONT_SUBFAMILY

TT_NAME_ID_UNIQUE_ID

TT_NAME_ID_FULL_NAME

TT_NAME_ID_VERSION_STRING

TT_NAME_ID_PS_NAME

TT_NAME_ID_TRADEMARK

TT_NAME_ID_MANUFACTURER

TT_NAME_ID_DESIGNER

TT_NAME_ID_DESCRIPTION

TT_NAME_ID_VENDOR_URL

TT_NAME_ID_DESIGNER_URL

TT_NAME_ID_LICENSE

TT_NAME_ID_LICENSE_URL

TT_NAME_ID_PREFERRED_FAMILY

TT_NAME_ID_PREFERRED_SUBFAMILY

TT_NAME_ID_MAC_FULL_NAME

TT_NAME_ID_SAMPLE_TEXT

TT_NAME_ID_CID_FINDFONT_NAME

TT_NAME_ID_WWS_FAMILY

TT_NAME_ID_WWS_SUBFAMILY
"""


TT_NAME_IDS = {
    'TT_NAME_ID_COPYRIGHT'            :  0,
    'TT_NAME_ID_FONT_FAMILY'          :  1,
    'TT_NAME_ID_FONT_SUBFAMILY'       :  2,
    'TT_NAME_ID_UNIQUE_ID'            :  3,
    'TT_NAME_ID_FULL_NAME'            :  4,
    'TT_NAME_ID_VERSION_STRING'       :  5,
    'TT_NAME_ID_PS_NAME'              :  6,
    'TT_NAME_ID_TRADEMARK'            :  7,

    # the following values are from the OpenType spec
    'TT_NAME_ID_MANUFACTURER'         :  8,
    'TT_NAME_ID_DESIGNER'             :  9,
    'TT_NAME_ID_DESCRIPTION'          : 10,
    'TT_NAME_ID_VENDOR_URL'           : 11,
    'TT_NAME_ID_DESIGNER_URL'         : 12,
    'TT_NAME_ID_LICENSE'              : 13,
    'TT_NAME_ID_LICENSE_URL'          : 14,
    # number 15 is reserved
    'TT_NAME_ID_PREFERRED_FAMILY'     : 16,
    'TT_NAME_ID_PREFERRED_SUBFAMILY'  : 17,
    'TT_NAME_ID_MAC_FULL_NAME'        : 18,

    # The following code is new as of 2000-01-21
    'TT_NAME_ID_SAMPLE_TEXT'          : 19,

    # This is new in OpenType 1.3
    'TT_NAME_ID_CID_FINDFONT_NAME'    : 20,

    # This is new in OpenType 1.5
    'TT_NAME_ID_WWS_FAMILY'           : 21,
    'TT_NAME_ID_WWS_SUBFAMILY'        : 22 }
globals().update(TT_NAME_IDS)
