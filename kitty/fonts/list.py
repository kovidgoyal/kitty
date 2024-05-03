#!/usr/bin/env python
# License: GPL v3 Copyright: 2017, Kovid Goyal <kovid at kovidgoyal.net>

from typing import Any, BinaryIO, Dict, List, Optional, Sequence

from kitty.constants import is_macos

from . import ListedFont
from .common import get_variable_data_for_descriptor

if is_macos:
    from .core_text import list_fonts, prune_family_group
else:
    from .fontconfig import list_fonts, prune_family_group


def create_family_groups(monospaced: bool = True, add_variable_data: bool = False) -> Dict[str, List[ListedFont]]:
    g: Dict[str, List[ListedFont]] = {}
    for f in list_fonts():
        if not monospaced or f['is_monospace']:
            g.setdefault(f['family'], []).append(f)
            if add_variable_data and f['is_variable']:
                f['variable_data'] = get_variable_data_for_descriptor(f['descriptor'])  # type: ignore
    return {k: prune_family_group(v) for k, v in g.items()}


def as_json(indent: Optional[int] = None) -> str:
    import json
    groups = create_family_groups(add_variable_data=True)
    return json.dumps(groups, indent=indent)


def handle_io(from_kitten: BinaryIO, to_kitten: BinaryIO) -> None:
    import json
    global exception_in_io_handler

    def send_to_kitten(x: Any) -> None:
        to_kitten.write(json.dumps(x).encode())
        to_kitten.write(b'\n')
        to_kitten.flush()

    send_to_kitten(create_family_groups(add_variable_data=True))
    for line in from_kitten:
        cmd = json.loads(line)
        action = cmd['action']
        if action == 'ping':
            send_to_kitten({'action': 'pong'})


def main(argv: Sequence[str]) -> None:
    import os
    import subprocess

    from kitty.constants import kitten_exe
    argv = list(argv)
    if '--psnames' in argv:
        argv.remove('--psnames')
    pass_fds = []
    if os.environ.get('KITTY_STDIO_FORWARDED'):
        pass_fds.append(int(os.environ['KITTY_STDIO_FORWARDED']))
    p = subprocess.Popen([kitten_exe(), '__list_fonts__'], stdin=subprocess.PIPE, stdout=subprocess.PIPE, pass_fds=pass_fds)
    try:
        handle_io(p.stdout, p.stdin)
    except Exception:
        ret = p.wait()
        import traceback
        traceback.print_exc()
    else:
        ret = p.wait()
    raise SystemExit(ret)
