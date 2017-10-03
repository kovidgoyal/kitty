#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2015, Kovid Goyal <kovid at kovidgoyal.net>

import sys
sys.debug_gl = '--debug-kitty-gl' in sys.argv

if len(sys.argv) > 1 and sys.argv[1] == 'icat':
    from kitty.icat import main
    main()
else:
    from kitty.main import main
    main()
