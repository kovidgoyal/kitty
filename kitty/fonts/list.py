#!/usr/bin/env python
# License: GPL v3 Copyright: 2017, Kovid Goyal <kovid at kovidgoyal.net>

from typing import IO, Any, Dict, List, Optional, Sequence

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


def as_json(indent: Optional[int] = None) -> str:
    import json
    groups = create_family_groups()
    return json.dumps(groups, indent=indent)


def handle_io(from_kitten: IO[bytes], to_kitten: IO[bytes]) -> None:
    import json
    global exception_in_io_handler

    def send_to_kitten(x: Any) -> None:
        to_kitten.write(json.dumps(x).encode())
        to_kitten.write(b'\n')
        to_kitten.flush()

    send_to_kitten(create_family_groups())
    for line in from_kitten:
        cmd = json.loads(line)
        action = cmd['action']
        if action == 'read_variable_data':
            ans = []
            for descriptor in cmd['descriptors']:
                ans.append(get_variable_data_for_descriptor(descriptor))
            send_to_kitten(ans)


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
    assert p.stdout is not None and p.stdin is not None
    try:
        handle_io(p.stdout, p.stdin)
    except Exception:
        ret = p.wait()
        import traceback
        traceback.print_exc()
    else:
        ret = p.wait()
    raise SystemExit(ret)
