# -*- coding: utf-8 -*-
# -----------------------------------------------------------------------------
#
#  FreeType high-level python API - Copyright 2011-2015 Nicolas P. Rougier
#  Distributed under the terms of the new BSD license.
#
# -----------------------------------------------------------------------------
"""
A list of bit flags that inform client applications of embedding and
subsetting restrictions associated with a font.

FT_FSTYPE_INSTALLABLE_EMBEDDING

  Fonts with no fsType bit set may be embedded and permanently installed on
  the remote system by an application.


FT_FSTYPE_RESTRICTED_LICENSE_EMBEDDING

  Fonts that have only this bit set must not be modified, embedded or exchanged
  in any manner without first obtaining permission of the font software
  copyright owner.


FT_FSTYPE_PREVIEW_AND_PRINT_EMBEDDING

  If this bit is set, the font may be embedded and temporarily loaded on the
  remote system. Documents containing Preview & Print fonts must be opened
  'read-only'; no edits can be applied to the document.


FT_FSTYPE_EDITABLE_EMBEDDING

  If this bit is set, the font may be embedded but must only be installed
  temporarily on other systems. In contrast to Preview & Print fonts,
  documents containing editable fonts may be opened for reading, editing is
  permitted, and changes may be saved.


FT_FSTYPE_NO_SUBSETTING

  If this bit is set, the font may not be subsetted prior to embedding.


FT_FSTYPE_BITMAP_EMBEDDING_ONLY

  If this bit is set, only bitmaps contained in the font may be embedded; no
  outline data may be embedded. If there are no bitmaps available in the font,
  then the font is unembeddable.
"""

FT_FSTYPES = {'FT_FSTYPE_INSTALLABLE_EMBEDDING'        : 0x0000,
              'FT_FSTYPE_RESTRICTED_LICENSE_EMBEDDING' : 0x0002,
              'FT_FSTYPE_PREVIEW_AND_PRINT_EMBEDDING'  : 0x0004,
              'FT_FSTYPE_EDITABLE_EMBEDDING'           : 0x0008,
              'FT_FSTYPE_NO_SUBSETTING'                : 0x0100,
              'FT_FSTYPE_BITMAP_EMBEDDING_ONLY'        : 0x0200,}
globals().update(FT_FSTYPES)
ft_fstype_installable_embedding  = FT_FSTYPE_INSTALLABLE_EMBEDDING
ft_fstype_restricted_license_embedding = FT_FSTYPE_RESTRICTED_LICENSE_EMBEDDING
ft_fstype_preview_and_print_embedding = FT_FSTYPE_PREVIEW_AND_PRINT_EMBEDDING
ft_fstype_editable_embedding = FT_FSTYPE_EDITABLE_EMBEDDING
ft_fstype_no_subsetting = FT_FSTYPE_NO_SUBSETTING
ft_fstype_bitmap_embedding_only = FT_FSTYPE_BITMAP_EMBEDDING_ONLY
