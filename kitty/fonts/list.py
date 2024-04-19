#!/usr/bin/env python
# License: GPL v3 Copyright: 2017, Kovid Goyal <kovid at kovidgoyal.net>

import sys
from typing import Dict, List, Sequence

from kittens.tui.operations import styled
from kitty.constants import is_macos

from . import ListedFont

if is_macos:
    from .core_text import list_fonts
else:
    from .fontconfig import get_variable_data_for_descriptor, list_fonts


def title(x: str) -> str:
    if sys.stdout.isatty():
        return styled(x, fg='green', bold=True)
    return x


def italic(x: str) -> str:
    if sys.stdout.isatty():
        return styled(x, italic=True)
    return x


def create_family_groups(monospaced: bool = True) -> Dict[str, List[ListedFont]]:
    g: Dict[str, List[ListedFont]] = {}
    for f in list_fonts():
        if not monospaced or f['is_monospace']:
            g.setdefault(f['family'], []).append(f)
    return g


def show_variable(f: ListedFont, psnames: bool) -> None:
    get_variable_data_for_descriptor(f['descriptor'])


def main(argv: Sequence[str]) -> None:
    psnames = '--psnames' in argv
    groups = create_family_groups()
    for k in sorted(groups, key=lambda x: x.lower()):
        print(title(k))
        for f in sorted(groups[k], key=lambda x: x['full_name'].lower()):
            if f['is_variable']:
                show_variable(f, psnames)
                continue
            p = italic(f['full_name'])
            if psnames:
                p += ' ({})'.format(f['postscript_name'])
            print('   ', p)
        print()
