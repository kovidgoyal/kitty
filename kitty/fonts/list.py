#!/usr/bin/env python
# License: GPL v3 Copyright: 2017, Kovid Goyal <kovid at kovidgoyal.net>

from typing import Dict, List, Sequence

from kitty.constants import is_macos

from . import ListedFont
from .common import get_variable_data_for_descriptor

if is_macos:
    from .core_text import list_fonts, prune_family_group
else:
    from .fontconfig import list_fonts, prune_family_group


def create_family_groups(monospaced: bool = True) -> Dict[str, List[ListedFont]]:
    g: Dict[str, List[ListedFont]] = {}
    for f in list_fonts():
        if not monospaced or f['is_monospace']:
            g.setdefault(f['family'], []).append(f)
    return {k: prune_family_group(v) for k, v in g.items()}


def as_json() -> str:
    import json
    groups = create_family_groups()
    for g in groups.values():
        for f in g:
            if f['is_variable']:
                f['variable_data'] = get_variable_data_for_descriptor(f['descriptor'])
    return json.dumps(groups, indent=2)


def main(argv: Sequence[str]) -> None:
    import subprocess

    from kitty.constants import kitten_exe
    argv = list(argv)
    if '--psnames' in argv:
        argv.remove('--psnames')
    cp = subprocess.run([kitten_exe(), '__list_fonts__'], input=as_json().encode())
    raise SystemExit(cp.returncode)
