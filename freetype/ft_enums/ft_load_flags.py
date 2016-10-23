# -*- coding: utf-8 -*-
# -----------------------------------------------------------------------------
#
#  FreeType high-level python API - Copyright 2011-2015 Nicolas P. Rougier
#  Distributed under the terms of the new BSD license.
#
# -----------------------------------------------------------------------------
"""
A list of bit-field constants used with FT_Load_Glyph to indicate what kind
of operations to perform during glyph loading.


FT_LOAD_DEFAULT

  Corresponding to 0, this value is used as the default glyph load
  operation. In this case, the following happens:

  1. FreeType looks for a bitmap for the glyph corresponding to the face's
     current size. If one is found, the function returns. The bitmap data can
     be accessed from the glyph slot (see note below).

  2. If no embedded bitmap is searched or found, FreeType looks for a scalable
     outline. If one is found, it is loaded from the font file, scaled to
     device pixels, then 'hinted' to the pixel grid in order to optimize
     it. The outline data can be accessed from the glyph slot (see note below).

  Note that by default, the glyph loader doesn't render outlines into
  bitmaps. The following flags are used to modify this default behaviour to
  more specific and useful cases.


FT_LOAD_NO_SCALE

  Don't scale the outline glyph loaded, but keep it in font units.

  This flag implies FT_LOAD_NO_HINTING and FT_LOAD_NO_BITMAP, and unsets
  FT_LOAD_RENDER.


FT_LOAD_NO_HINTING

  Disable hinting. This generally generates 'blurrier' bitmap glyph when the
  glyph is rendered in any of the anti-aliased modes. See also the note below.

  This flag is implied by FT_LOAD_NO_SCALE.


FT_LOAD_RENDER

  Call FT_Render_Glyph after the glyph is loaded. By default, the glyph is
  rendered in FT_RENDER_MODE_NORMAL mode. This can be overridden by
  FT_LOAD_TARGET_XXX or FT_LOAD_MONOCHROME.

  This flag is unset by FT_LOAD_NO_SCALE.


FT_LOAD_NO_BITMAP

  Ignore bitmap strikes when loading. Bitmap-only fonts ignore this flag.

  FT_LOAD_NO_SCALE always sets this flag.


FT_LOAD_VERTICAL_LAYOUT

  Load the glyph for vertical text layout. Don't use it as it is problematic
  currently.


FT_LOAD_FORCE_AUTOHINT

  Indicates that the auto-hinter is preferred over the font's native
  hinter. See also the note below.


FT_LOAD_CROP_BITMAP

  Indicates that the font driver should crop the loaded bitmap glyph (i.e.,
  remove all space around its black bits). Not all drivers implement this.


FT_LOAD_PEDANTIC

  Indicates that the font driver should perform pedantic verifications during
  glyph loading. This is mostly used to detect broken glyphs in fonts. By
  default, FreeType tries to handle broken fonts also.


FT_LOAD_IGNORE_GLOBAL_ADVANCE_WIDTH

  Indicates that the font driver should ignore the global advance width defined
  in the font. By default, that value is used as the advance width for all
  glyphs when the face has FT_FACE_FLAG_FIXED_WIDTH set.

  This flag exists for historical reasons (to support buggy CJK fonts).


FT_LOAD_NO_RECURSE

  This flag is only used internally. It merely indicates that the font driver
  should not load composite glyphs recursively. Instead, it should set the
  'num_subglyph' and 'subglyphs' values of the glyph slot accordingly, and set
  'glyph->format' to FT_GLYPH_FORMAT_COMPOSITE.

  The description of sub-glyphs is not available to client applications for now.

  This flag implies FT_LOAD_NO_SCALE and FT_LOAD_IGNORE_TRANSFORM.


FT_LOAD_IGNORE_TRANSFORM

  Indicates that the transform matrix set by FT_Set_Transform should be ignored.


FT_LOAD_MONOCHROME

  This flag is used with FT_LOAD_RENDER to indicate that you want to render an
  outline glyph to a 1-bit monochrome bitmap glyph, with 8 pixels packed into
  each byte of the bitmap data.

  Note that this has no effect on the hinting algorithm used. You should rather
  use FT_LOAD_TARGET_MONO so that the monochrome-optimized hinting algorithm is
  used.


FT_LOAD_LINEAR_DESIGN

  Indicates that the 'linearHoriAdvance' and 'linearVertAdvance' fields of
  FT_GlyphSlotRec should be kept in font units. See FT_GlyphSlotRec for
  details.


FT_LOAD_NO_AUTOHINT

  Disable auto-hinter. See also the note below.
"""

FT_LOAD_FLAGS = { 'FT_LOAD_DEFAULT'                      : 0x0,
                  'FT_LOAD_NO_SCALE'                     : 0x1,
                  'FT_LOAD_NO_HINTING'                   : 0x2,
                  'FT_LOAD_RENDER'                       : 0x4,
                  'FT_LOAD_NO_BITMAP'                    : 0x8,
                  'FT_LOAD_VERTICAL_LAYOUT'              : 0x10,
                  'FT_LOAD_FORCE_AUTOHINT'               : 0x20,
                  'FT_LOAD_CROP_BITMAP'                  : 0x40,
                  'FT_LOAD_PEDANTIC'                     : 0x80,
                  'FT_LOAD_IGNORE_GLOBAL_ADVANCE_WIDTH'  : 0x200,
                  'FT_LOAD_NO_RECURSE'                   : 0x400,
                  'FT_LOAD_IGNORE_TRANSFORM'             : 0x800,
                  'FT_LOAD_MONOCHROME'                   : 0x1000,
                  'FT_LOAD_LINEAR_DESIGN'                : 0x2000,
                  'FT_LOAD_NO_AUTOHINT'                  : 0x8000 }
globals().update(FT_LOAD_FLAGS)
