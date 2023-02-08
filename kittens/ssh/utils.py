#!/usr/bin/env python
# License: GPLv3 Copyright: 2022, Kovid Goyal <kovid at kovidgoyal.net>


import os
import subprocess
from typing import Any, Dict, List, Sequence, Set, Tuple

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


def is_kitten_cmdline(q: Sequence[str]) -> bool:
    if not q:
        return False
    exe_name = os.path.basename(q[0]).lower()
    if exe_name == 'kitten' and q[1:2] == ['ssh']:
        return True
    if len(q) < 4:
        return False
    if exe_name != 'kitty':
        return False
    if q[1:3] == ['+kitten', 'ssh'] or q[1:4] == ['+', 'kitten', 'ssh']:
        return True
    return q[1:3] == ['+runpy', 'from kittens.runner import main; main()'] and len(q) >= 6 and q[5] == 'ssh'


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

    from kitty.shm import SharedMemory
    db = json.dumps(data).encode('utf-8')
    with SharedMemory(size=len(db) + SharedMemory.num_bytes_for_size, prefix=prefix) as shm:
        shm.write_data_with_size(db)
        shm.flush()
        atexit.register(shm.unlink)
    return shm.name


def set_env_in_cmdline(env: Dict[str, str], argv: List[str]) -> None:
    patch_cmdline('clone_env', create_shared_memory(env, 'ksse-'), argv)



def get_ssh_cli() -> Tuple[Set[str], Set[str]]:
    other_ssh_args: Set[str] = set()
    boolean_ssh_args: Set[str] = set()
    for k, v in ssh_options().items():
        k = f'-{k}'
        if v:
            other_ssh_args.add(k)
        else:
            boolean_ssh_args.add(k)
    return boolean_ssh_args, other_ssh_args


def is_extra_arg(arg: str, extra_args: Tuple[str, ...]) -> str:
    for x in extra_args:
        if arg == x or arg.startswith(f'{x}='):
            return x
    return ''


passthrough_args = {f'-{x}' for x in 'NnfGT'}


def set_server_args_in_cmdline(
    server_args: List[str], argv: List[str],
    extra_args: Tuple[str, ...] = ('--kitten',),
    allocate_tty: bool = False
) -> None:
    boolean_ssh_args, other_ssh_args = get_ssh_cli()
    ssh_args = []
    expecting_option_val = False
    found_extra_args: List[str] = []
    expecting_extra_val = ''
    ans = list(argv)
    found_ssh = False
    for i, argument in enumerate(argv):
        if not found_ssh:
            found_ssh = argument == 'ssh'
            continue
        if argument.startswith('-') and not expecting_option_val:
            if argument == '--':
                del ans[i+2:]
                if allocate_tty and ans[i-1] != '-t':
                    ans.insert(i, '-t')
                break
            if extra_args:
                matching_ex = is_extra_arg(argument, extra_args)
                if matching_ex:
                    if '=' in argument:
                        exval = argument.partition('=')[-1]
                        found_extra_args.extend((matching_ex, exval))
                    else:
                        expecting_extra_val = matching_ex
                        expecting_option_val = True
                    continue
            # could be a multi-character option
            all_args = argument[1:]
            for i, arg in enumerate(all_args):
                arg = f'-{arg}'
                if arg in boolean_ssh_args:
                    ssh_args.append(arg)
                    continue
                if arg in other_ssh_args:
                    ssh_args.append(arg)
                    rest = all_args[i+1:]
                    if rest:
                        ssh_args.append(rest)
                    else:
                        expecting_option_val = True
                    break
                raise KeyError(f'unknown option -- {arg[1:]}')
            continue
        if expecting_option_val:
            if expecting_extra_val:
                found_extra_args.extend((expecting_extra_val, argument))
                expecting_extra_val = ''
            else:
                ssh_args.append(argument)
            expecting_option_val = False
            continue
        del ans[i+1:]
        if allocate_tty and ans[i] != '-t':
            ans.insert(i, '-t')
        break
    argv[:] = ans + server_args
