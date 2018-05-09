#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2018, Kovid Goyal <kovid at kovidgoyal.net>

import warnings

from ..tui.images import can_display_images


class ImageSupportWarning(Warning):
    pass


def images_supported():
    ans = getattr(images_supported, 'ans', None)
    if ans is None:
        images_supported.ans = ans = can_display_images()
        if not ans:
            warnings.warn('ImageMagick not found images cannot be displayed', ImageSupportWarning)
    return ans
