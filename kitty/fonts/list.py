#!/usr/bin/env python3
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2017, Kovid Goyal <kovid at kovidgoyal.net>

import sys
from typing import Dict, List, Sequence

from kitty.constants import is_macos

from . import ListedFont

if is_macos:
    from .core_text import list_fonts
else:
    from .fontconfig import list_fonts


def create_family_groups(monospaced: bool = True) -> Dict[str, List[ListedFont]]:
    g: Dict[str, List[ListedFont]] = {}
    for f in list_fonts():
        if not monospaced or f['is_monospace']:
            g.setdefault(f['family'], []).append(f)
    return g


def main(argv: Sequence[str]) -> None:
    psnames = '--psnames' in argv
    isatty = sys.stdout.isatty()
    groups = create_family_groups()
    for k in sorted(groups, key=lambda x: x.lower()):
        if isatty:
            print('\033[1;32m' + k + '\033[m')
        else:
            print(k)
        for f in sorted(groups[k], key=lambda x: x['full_name'].lower()):
            p = f['full_name']
            if isatty:
                p = '\033[3m' + p + '\033[m'
            if psnames:
                p += ' ({})'.format(f['postscript_name'])
            print('   ', p)
        print()
