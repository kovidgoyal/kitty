#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2018, Kovid Goyal <kovid at kovidgoyal.net>

import shutil
import warnings


class ImageSupportWarning(Warning):
    pass


def images_supported():
    ans = getattr(images_supported, 'ans', None)
    if ans is None:
        ans = shutil.which('convert') is not None
        images_supported.ans = ans
        if not ans:
            warnings.warn('ImageMagick not found images cannot be displayed', ImageSupportWarning)
    return ans
