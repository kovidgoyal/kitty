#!/usr/bin/env python
# License: GPLv3 Copyright: 2022, Kovid Goyal <kovid at kovidgoyal.net>


import os
from typing import Any, Dict, List


def is_kitten_cmdline(q: List[str]) -> bool:
    if len(q) < 4:
        return False
    if os.path.basename(q[0]).lower() != 'kitty':
        return False
    return q[1:3] == ['+kitten', 'ssh'] or q[1:4] == ['+', 'kitten', 'ssh']


def patch_cmdline(key: str, val: str, argv: List[str]) -> None:
    for i, arg in enumerate(tuple(argv)):
        if arg.startswith(f'--kitten={key}='):
            argv[i] = f'--kitten={key}={val}'
            return
        elif i > 0 and argv[i-1] == '--kitten' and (arg.startswith(f'{key}=') or arg.startswith(f'{key} ')):
            argv[i] = val
            return
    idx = argv.index('ssh')
    argv.insert(idx + 1, f'--kitten={key}={val}')


def set_cwd_in_cmdline(cwd: str, argv: List[str]) -> None:
    patch_cmdline('cwd', cwd, argv)


def create_shared_memory(data: Any, prefix: str) -> str:
    import atexit
    import json
    import stat

    from kitty.shm import SharedMemory
    db = json.dumps(data).encode('utf-8')
    with SharedMemory(size=len(db) + SharedMemory.num_bytes_for_size, mode=stat.S_IREAD, prefix=prefix) as shm:
        shm.write_data_with_size(db)
        shm.flush()
        atexit.register(shm.unlink)
    return shm.name


def set_env_in_cmdline(env: Dict[str, str], argv: List[str]) -> None:
    patch_cmdline('clone_env', create_shared_memory(env, 'ksse-'), argv)
