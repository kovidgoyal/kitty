#!/usr/bin/env python
# License: GPLv3 Copyright: 2022, Kovid Goyal <kovid at kovidgoyal.net>


import os
import subprocess
from typing import Any, Dict, List

from kitty.types import run_once


@run_once
def ssh_options() -> Dict[str, str]:
    try:
        p = subprocess.run(['ssh'], stderr=subprocess.PIPE, encoding='utf-8')
        raw = p.stderr or ''
    except FileNotFoundError:
        return {
            '4': '', '6': '', 'A': '', 'a': '', 'C': '', 'f': '', 'G': '', 'g': '', 'K': '', 'k': '',
            'M': '', 'N': '', 'n': '', 'q': '', 's': '', 'T': '', 't': '', 'V': '', 'v': '', 'X': '',
            'x': '', 'Y': '', 'y': '', 'B': 'bind_interface', 'b': 'bind_address', 'c': 'cipher_spec',
            'D': '[bind_address:]port', 'E': 'log_file', 'e': 'escape_char', 'F': 'configfile', 'I': 'pkcs11',
            'i': 'identity_file', 'J': '[user@]host[:port]', 'L': 'address', 'l': 'login_name', 'm': 'mac_spec',
            'O': 'ctl_cmd', 'o': 'option', 'p': 'port', 'Q': 'query_option', 'R': 'address',
            'S': 'ctl_path', 'W': 'host:port', 'w': 'local_tun[:remote_tun]'
        }

    ans: Dict[str, str] = {}
    pos = 0
    while True:
        pos = raw.find('[', pos)
        if pos < 0:
            break
        num = 1
        epos = pos
        while num > 0:
            epos += 1
            if raw[epos] not in '[]':
                continue
            num += 1 if raw[epos] == '[' else -1
        q = raw[pos+1:epos]
        pos = epos
        if len(q) < 2 or q[0] != '-':
            continue
        if ' ' in q:
            opt, desc = q.split(' ', 1)
            ans[opt[1:]] = desc
        else:
            ans.update(dict.fromkeys(q[1:], ''))
    return ans


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
