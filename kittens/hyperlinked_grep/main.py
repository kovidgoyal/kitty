#!/usr/bin/env python
# License: GPLv3 Copyright: 2020, Kovid Goyal <kovid at kovidgoyal.net>

import sys

if __name__ == '__main__':
    raise SystemExit('This should be run as kitten hyperlinked_grep')
elif __name__ == '__wrapper_of__':
    cd = sys.cli_docs  # type: ignore
    cd['wrapper_of'] = 'rg'
