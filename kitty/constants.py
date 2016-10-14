#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2016, Kovid Goyal <kovid at kovidgoyal.net>

import os
from PyQt5.QtCore import QStandardPaths

appname = 'kitty'
version = (0, 1, 0)
str_version = '.'.join(map(str, version))


def _get_config_dir():
    # This must be called before calling setApplicationName
    if 'KITTY_CONFIG_DIRECTORY' in os.environ:
        return os.path.abspath(os.path.expanduser(os.environ['VISE_CONFIG_DIRECTORY']))

    candidate = QStandardPaths.writableLocation(QStandardPaths.ConfigLocation)
    if not candidate:
        raise RuntimeError(
            'Failed to find path for application config directory')
    ans = os.path.join(candidate, appname)
    try:
        os.makedirs(ans)
    except FileExistsError:
        pass
    return ans
config_dir = _get_config_dir()
del _get_config_dir
