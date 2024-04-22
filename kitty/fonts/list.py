#!/usr/bin/env python
# License: GPL v3 Copyright: 2017, Kovid Goyal <kovid at kovidgoyal.net>

import sys
from typing import Dict, List, Sequence

from kittens.tui.operations import styled
from kitty.constants import is_macos
from kitty.types import run_once

from . import ListedFont

if is_macos:
    from .core_text import get_variable_data_for_descriptor, list_fonts, prune_family_group
else:
    from .fontconfig import get_variable_data_for_descriptor, list_fonts, prune_family_group


@run_once
def isatty() -> bool:
    return sys.stdout.isatty()


def title(x: str) -> str:
    if isatty():
        return styled(x, fg='green', bold=True)
    return x


def italic(x: str) -> str:
    if isatty():
        return styled(x, italic=True)
    return x


def variable_font_label(x: str) -> str:
    if isatty():
        return styled(x, fg='yellow')
    return x


def variable_font_tag(x: str) -> str:
    if isatty():
        return styled(x, fg='cyan')
    return x


def indented(x: str, level: int = 1) -> str:
    return '  ' * level + x


def create_family_groups(monospaced: bool = True) -> Dict[str, List[ListedFont]]:
    g: Dict[str, List[ListedFont]] = {}
    for f in list_fonts():
        if not monospaced or f['is_monospace']:
            g.setdefault(f['family'], []).append(f)
    return {k: prune_family_group(v) for k, v in g.items()}


def show_variable(f: ListedFont, psnames: bool) -> None:
    vd = get_variable_data_for_descriptor(f)
    p = italic(f['family'])
    p = f"{p} {variable_font_label('Variable font')}"
    print(indented(p))
    print(indented(variable_font_label('Axes of variation'), level=2))
    for a in vd['axes']:
        t = variable_font_tag(a['tag'])
        n = a['strid'] or ''
        if n:
            t += f' ({n})'
        print(indented(t, level=3) + ':', f'minimum={a["minimum"]:g}', f'maximum={a["maximum"]:g}', f'default={a["default"]:g}')

    if vd['named_styles']:
        print(indented(variable_font_label('Named styles'), level=2))
        for ns in vd['named_styles']:
            name = ns['name'] or ''
            if psnames:
                name += f' ({ns["psname"] or ""})'
            axes = []
            for axis_tag, val in ns['axis_values'].items():
                axes.append(f'{axis_tag}={val:g}')
            p = name + ': ' + ' '.join(axes)
            print(indented(p, level=3))


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
            print(indented(p))
        print()
