# -*- coding: utf-8 -*-
# -----------------------------------------------------------------------------
#
#  FreeType high-level python API - Copyright 2011-2015 Nicolas P. Rougier
#  Distributed under the terms of the new BSD license.
#
# -----------------------------------------------------------------------------
'''
Freetype enum types
-------------------

FT_PIXEL_MODES: An enumeration type used to describe the format of pixels in a
                given bitmap. Note that additional formats may be added in the
                future.

FT_GLYPH_BBOX_MODES: The mode how the values of FT_Glyph_Get_CBox are returned.

FT_GLYPH_FORMATS: An enumeration type used to describe the format of a given
                  glyph image. Note that this version of FreeType only supports
                  two image formats, even though future font drivers will be
                  able to register their own format.

FT_ENCODINGS: An enumeration used to specify character sets supported by
              charmaps. Used in the FT_Select_Charmap API function.

FT_RENDER_MODES: An enumeration type that lists the render modes supported by
                 FreeType 2. Each mode corresponds to a specific type of
                 scanline conversion performed on the outline.

FT_LOAD_TARGETS: A list of values that are used to select a specific hinting
                 algorithm to use by the hinter. You should OR one of these
                 values to your 'load_flags' when calling FT_Load_Glyph.

FT_LOAD_FLAGS: A list of bit-field constants used with FT_Load_Glyph to
               indicate what kind of operations to perform during glyph
               loading.

FT_STYLE_FLAGS: A list of bit-flags used to indicate the style of a given
                face. These are used in the 'style_flags' field of FT_FaceRec.

FT_FSTYPES: A list of bit flags that inform client applications of embedding
            and subsetting restrictions associated with a font.

FT_FACE_FLAGS: A list of bit flags used in the 'face_flags' field of the
               FT_FaceRec structure. They inform client applications of
               properties of the corresponding face.

FT_OUTLINE_FLAGS: A list of bit-field constants use for the flags in an
                  outline's 'flags' field.

FT_OPEN_MODES: A list of bit-field constants used within the 'flags' field of
               the FT_Open_Args structure.

FT_KERNING_MODES: An enumeration used to specify which kerning values to return
                  in FT_Get_Kerning.

FT_STROKER_LINEJOINS: These values determine how two joining lines are rendered
                      in a stroker.

FT_STROKER_LINECAPS: These values determine how the end of opened sub-paths are
                     rendered in a stroke.

FT_STROKER_BORDERS: These values are used to select a given stroke border in
                    FT_Stroker_GetBorderCounts and FT_Stroker_ExportBorder.

FT_LCD_FILTERS: A list of values to identify various types of LCD filters.

TT_PLATFORMS: A list of valid values for the 'platform_id' identifier code in
              FT_CharMapRec and FT_SfntName structures.

TT_APPLE_IDS: A list of valid values for the 'encoding_id' for
              TT_PLATFORM_APPLE_UNICODE charmaps and name entries.

TT_MAC_IDS: A list of valid values for the 'encoding_id' for
            TT_PLATFORM_MACINTOSH charmaps and name entries.

TT_MS_IDS: A list of valid values for the 'encoding_id' for
           TT_PLATFORM_MICROSOFT charmaps and name entries.

TT_ADOBE_IDS: A list of valid values for the 'encoding_id' for
              TT_PLATFORM_ADOBE charmaps. This is a FreeType-specific
              extension!

TT_MAC_LANGIDS: Possible values of the language identifier field in the name
                records of the TTF `name' table if the `platform' identifier
                code is TT_PLATFORM_MACINTOSH.

TT_MS_LANGIDS: Possible values of the language identifier field in the name
               records of the TTF `name' table if the `platform' identifier
               code is TT_PLATFORM_MICROSOFT.

TT_NAME_IDS: Possible values of the `name' identifier field in the name
             records of the TTF `name' table.  These values are platform
             independent.
'''
from freetype.ft_enums.ft_fstypes import *
from freetype.ft_enums.ft_face_flags import *
from freetype.ft_enums.ft_encodings import *
from freetype.ft_enums.ft_glyph_bbox_modes import *
from freetype.ft_enums.ft_glyph_formats import *
from freetype.ft_enums.ft_kerning_modes import *
from freetype.ft_enums.ft_lcd_filters import *
from freetype.ft_enums.ft_load_flags import *
from freetype.ft_enums.ft_load_targets import *
from freetype.ft_enums.ft_open_modes import *
from freetype.ft_enums.ft_outline_flags import *
from freetype.ft_enums.ft_pixel_modes import *
from freetype.ft_enums.ft_render_modes import *
from freetype.ft_enums.ft_stroker_borders import *
from freetype.ft_enums.ft_stroker_linecaps import *
from freetype.ft_enums.ft_stroker_linejoins import *
from freetype.ft_enums.ft_style_flags import *
from freetype.ft_enums.tt_adobe_ids import *
from freetype.ft_enums.tt_apple_ids import *
from freetype.ft_enums.tt_mac_ids import *
from freetype.ft_enums.tt_ms_ids import *
from freetype.ft_enums.tt_ms_langids import *
from freetype.ft_enums.tt_mac_langids import *
from freetype.ft_enums.tt_name_ids import *
from freetype.ft_enums.tt_platforms import *
