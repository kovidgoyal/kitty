#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2015, Kovid Goyal <kovid at kovidgoyal.net>

import sys

if len(sys.argv) > 1 and sys.argv[1] == 'icat':
    from kitty.icat import main
    main(sys.argv[1:])
else:
    from kitty.main import main
    main()
