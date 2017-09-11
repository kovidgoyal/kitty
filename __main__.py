#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2015, Kovid Goyal <kovid at kovidgoyal.net>

import sys
sys.debug_gl = '--debug-kitty-gl' in sys.argv

from kitty.main import main  # noqa
main()
