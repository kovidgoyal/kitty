# -*- coding: utf-8 -*-
"""
    pyte.compat
    ~~~~~~~~~~~

    Python version specific compatibility fixes.

    :copyright: (c) 2015-2016 by pyte authors and contributors,
                see AUTHORS for details.
    :license: LGPL, see LICENSE for more details.
"""

import sys

if sys.version_info[0] == 2:
    from future_builtins import map

    range = xrange
    str = unicode
    chr = unichr

    from functools import partial
    iter_bytes = partial(map, ord)
else:
    from builtins import map, range, str, chr
    iter_bytes = iter
