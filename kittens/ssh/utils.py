#!/usr/bin/env python
# License: GPLv3 Copyright: 2022, Kovid Goyal <kovid at kovidgoyal.net>


import os
import subprocess
import traceback
from collections.abc import Iterator, Sequence
from contextlib import suppress
from typing import Any

from kitty.types import run_once
from kitty.utils import SSHConnectionData


@run_once
def ssh_options() -> dict[str, str]:
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

    ans: dict[str, str] = {}
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


def patch_cmdline(key: str, val: str, argv: list[str]) -> None:
    for i, arg in enumerate(tuple(argv)):
        if arg.startswith(f'--kitten={key}='):
            argv[i] = f'--kitten={key}={val}'
            return
        elif i > 0 and argv[i-1] == '--kitten' and (arg.startswith(f'{key}=') or arg.startswith(f'{key} ')):
            argv[i] = f'{key}={val}'
            return
    idx = argv.index('ssh')
    argv.insert(idx + 1, f'--kitten={key}={val}')


def set_cwd_in_cmdline(cwd: str, argv: list[str]) -> None:
    patch_cmdline('cwd', cwd, argv)


def create_shared_memory(data: Any, prefix: str) -> str:
    import atexit
    import json

    from kitty.fast_data_types import get_boss
    from kitty.shm import SharedMemory
    db = json.dumps(data).encode('utf-8')
    with SharedMemory(size=len(db) + SharedMemory.num_bytes_for_size, prefix=prefix) as shm:
        shm.write_data_with_size(db)
        shm.flush()
        atexit.register(shm.close)  # keeps shm alive till exit
        get_boss().atexit.shm_unlink(shm.name)
    return shm.name


def read_data_from_shared_memory(shm_name: str) -> Any:
    import json
    import stat

    from kitty.shm import SharedMemory
    with SharedMemory(shm_name, readonly=True) as shm:
        shm.unlink()
        if shm.stats.st_uid != os.geteuid() or shm.stats.st_gid != os.getegid():
            raise ValueError(f'Incorrect owner on pwfile: uid={shm.stats.st_uid} gid={shm.stats.st_gid}')
        mode = stat.S_IMODE(shm.stats.st_mode)
        if mode != stat.S_IREAD | stat.S_IWRITE:
            raise ValueError(f'Incorrect permissions on pwfile: 0o{mode:03o}')
        return json.loads(shm.read_data_with_size())


def get_ssh_data(msgb: memoryview, request_id: str) -> Iterator[bytes|memoryview]:
    from base64 import standard_b64decode
    yield b'\nKITTY_DATA_START\n'  # to discard leading data
    try:
        msg = standard_b64decode(msgb).decode('utf-8')
        md = dict(x.split('=', 1) for x in msg.split(':'))
        pw = md['pw']
        pwfilename = md['pwfile']
        rq_id = md['id']
    except Exception:
        traceback.print_exc()
        yield b'invalid ssh data request message\n'
    else:
        try:
            env_data = read_data_from_shared_memory(pwfilename)
            if pw != env_data['pw']:
                raise ValueError('Incorrect password')
            if rq_id != request_id:
                raise ValueError(f'Incorrect request id: {rq_id!r} expecting the KITTY_PID-KITTY_WINDOW_ID for the current kitty window')
        except Exception as e:
            traceback.print_exc()
            yield f'{e}\n'.encode()
        else:
            yield b'OK\n'
            encoded_data = memoryview(env_data['tarfile'].encode('ascii'))
            # macOS has a 255 byte limit on its input queue as per man stty.
            # Not clear if that applies to canonical mode input as well, but
            # better to be safe.
            line_sz = 254
            while encoded_data:
                yield encoded_data[:line_sz]
                yield b'\n'
                encoded_data = encoded_data[line_sz:]
            yield b'KITTY_DATA_END\n'


def set_env_in_cmdline(env: dict[str, str], argv: list[str], clone: bool = True) -> None:
    from kitty.options.utils import DELETE_ENV_VAR
    if clone:
        patch_cmdline('clone_env', create_shared_memory(env, 'ksse-'), argv)
        return
    idx = argv.index('ssh')
    for i in range(idx, len(argv)):
        if argv[i] == '--kitten':
            idx = i + 1
        elif argv[i].startswith('--kitten='):
            idx = i
    env_dirs = []
    for k, v in env.items():
        if v is DELETE_ENV_VAR:
            x = f'--kitten=env={k}'
        else:
            x = f'--kitten=env={k}={v}'
        env_dirs.append(x)
    argv[idx+1:idx+1] = env_dirs


def get_ssh_cli() -> tuple[set[str], set[str]]:
    other_ssh_args: set[str] = set()
    boolean_ssh_args: set[str] = set()
    for k, v in ssh_options().items():
        k = f'-{k}'
        if v:
            other_ssh_args.add(k)
        else:
            boolean_ssh_args.add(k)
    return boolean_ssh_args, other_ssh_args


def is_extra_arg(arg: str, extra_args: tuple[str, ...]) -> str:
    for x in extra_args:
        if arg == x or arg.startswith(f'{x}='):
            return x
    return ''


passthrough_args = {f'-{x}' for x in 'NnfGT'}


def set_server_args_in_cmdline(
    server_args: list[str], argv: list[str],
    extra_args: tuple[str, ...] = ('--kitten',),
    allocate_tty: bool = False
) -> None:
    boolean_ssh_args, other_ssh_args = get_ssh_cli()
    ssh_args = []
    expecting_option_val = False
    found_extra_args: list[str] = []
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


def get_connection_data(args: list[str], cwd: str = '', extra_args: tuple[str, ...] = ()) -> SSHConnectionData | None:
    boolean_ssh_args, other_ssh_args = get_ssh_cli()
    port: int | None = None
    expecting_port = expecting_identity = False
    expecting_option_val = False
    expecting_hostname = False
    expecting_extra_val = ''
    host_name = identity_file = found_ssh = ''
    found_extra_args: list[tuple[str, str]] = []

    for i, arg in enumerate(args):
        if not found_ssh:
            if os.path.basename(arg).lower() in ('ssh', 'ssh.exe'):
                found_ssh = arg
            continue
        if expecting_hostname:
            host_name = arg
            continue
        if arg.startswith('-') and not expecting_option_val:
            if arg in boolean_ssh_args:
                continue
            if arg == '--':
                expecting_hostname = True
            if arg.startswith('-p'):
                if arg[2:].isdigit():
                    with suppress(Exception):
                        port = int(arg[2:])
                    continue
                elif arg == '-p':
                    expecting_port = True
            elif arg.startswith('-i'):
                if arg == '-i':
                    expecting_identity = True
                else:
                    identity_file = arg[2:]
                    continue
            if arg.startswith('--') and extra_args:
                matching_ex = is_extra_arg(arg, extra_args)
                if matching_ex:
                    if '=' in arg:
                        exval = arg.partition('=')[-1]
                        found_extra_args.append((matching_ex, exval))
                        continue
                    expecting_extra_val = matching_ex

            expecting_option_val = True
            continue

        if expecting_option_val:
            if expecting_port:
                with suppress(Exception):
                    port = int(arg)
                expecting_port = False
            elif expecting_identity:
                identity_file = arg
            elif expecting_extra_val:
                found_extra_args.append((expecting_extra_val, arg))
                expecting_extra_val = ''
            expecting_option_val = False
            continue

        if not host_name:
            host_name = arg
    if not host_name:
        return None
    if host_name.startswith('ssh://'):
        from urllib.parse import urlparse
        purl = urlparse(host_name)
        if purl.hostname:
            host_name = purl.hostname
        if purl.username:
            host_name = f'{purl.username}@{host_name}'
        if port is None and purl.port:
            port = purl.port
    if identity_file:
        if not os.path.isabs(identity_file):
            identity_file = os.path.expanduser(identity_file)
        if not os.path.isabs(identity_file):
            identity_file = os.path.normpath(os.path.join(cwd or os.getcwd(), identity_file))

    return SSHConnectionData(found_ssh, host_name, port, identity_file, tuple(found_extra_args))
