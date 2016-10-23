# -*- coding: utf-8 -*-
# -----------------------------------------------------------------------------
#
#  FreeType high-level python API - Copyright 2011-2015 Nicolas P. Rougier
#  Distributed under the terms of the new BSD license.
#
# -----------------------------------------------------------------------------
"""
A list of bit-field constants used within the 'flags' field of the
FT_Open_Args structure.


FT_OPEN_MEMORY

  This is a memory-based stream.


FT_OPEN_STREAM

  Copy the stream from the 'stream' field.


FT_OPEN_PATHNAME

  Create a new input stream from a C path name.


FT_OPEN_DRIVER

  Use the 'driver' field.


FT_OPEN_PARAMS

  Use the 'num_params' and 'params' fields.
"""
FT_OPEN_MODES = {'FT_OPEN_MEMORY':   0x1,
                 'FT_OPEN_STREAM':   0x2,
                 'FT_OPEN_PATHNAME': 0x4,
                 'FT_OPEN_DRIVER':   0x8,
                 'FT_OPEN_PARAMS':   0x10 }
globals().update(FT_OPEN_MODES)
