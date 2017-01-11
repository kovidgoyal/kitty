#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2016, Kovid Goyal <kovid at kovidgoyal.net>

from kitty.constants import isosx

if isosx:
    from .core_text import set_font_family, render_cell  # noqa
else:
    from .freetype import set_font_family, render_cell  # noqa
