#!/usr/bin/env python3
# License: GPL v3 Copyright: 2018, Kovid Goyal <kovid at kovidgoyal.net>

import atexit
import io
import json
import os
import re
import shlex
import sys
import tarfile
import tempfile
import time
import traceback
from base64 import standard_b64decode
from contextlib import suppress
from typing import (
    Any, Dict, Iterator, List, NoReturn, Optional, Set, Tuple, Union
)

from kitty.constants import cache_dir, shell_integration_dir, terminfo_dir
from kitty.fast_data_types import get_options
from kitty.short_uuid import uuid4
from kitty.types import run_once
from kitty.utils import SSHConnectionData

from .completion import complete, ssh_options
from .options.types import Options as SSHOptions
from .options.utils import DELETE_ENV_VAR


def serialize_env(env: Dict[str, str], base_env: Dict[str, str]) -> bytes:
    lines = []

    def a(k: str, val: str) -> None:
        lines.append(f'export {k}={shlex.quote(val)}')

    for k in sorted(env):
        v = env[k]
        if v is DELETE_ENV_VAR:
            lines.append(f'unset {shlex.quote(k)}')
        elif v == '_kitty_copy_env_var_':
            q = base_env.get(k)
            if q is not None:
                a(k, q)
        else:
            a(k, v)
    return '\n'.join(lines).encode('utf-8')


def make_tarfile(ssh_opts: SSHOptions, base_env: Dict[str, str]) -> bytes:

    def normalize_tarinfo(tarinfo: tarfile.TarInfo) -> tarfile.TarInfo:
        tarinfo.uname = tarinfo.gname = 'kitty'
        tarinfo.uid = tarinfo.gid = 0
        return tarinfo

    def add_data_as_file(tf: tarfile.TarFile, arcname: str, data: Union[str, bytes]) -> tarfile.TarInfo:
        ans = tarfile.TarInfo(arcname)
        ans.mtime = int(time.time())
        ans.type = tarfile.REGTYPE
        if isinstance(data, str):
            data = data.encode('utf-8')
        ans.size = len(data)
        normalize_tarinfo(ans)
        tf.addfile(ans, io.BytesIO(data))
        return ans

    def filter_files(tarinfo: tarfile.TarInfo) -> Optional[tarfile.TarInfo]:
        if tarinfo.name.endswith('ssh/bootstrap.sh'):
            return None
        return normalize_tarinfo(tarinfo)

    from kitty.shell_integration import get_effective_ksi_env_var
    if ssh_opts.shell_integration == 'inherit':
        ksi = get_effective_ksi_env_var()
    else:
        from kitty.options.types import Options
        from kitty.options.utils import shell_integration
        ksi = get_effective_ksi_env_var(Options({'shell_integration': shell_integration(ssh_opts.shell_integration)}))

    env = {
        'TERM': get_options().term,
        'COLORTERM': 'truecolor',
    }
    for q in ('KITTY_WINDOW_ID', 'WINDOWID'):
        val = os.environ.get(q)
        if val is not None:
            env[q] = val
    env.update(ssh_opts.env)
    env['KITTY_SHELL_INTEGRATION'] = ksi or DELETE_ENV_VAR
    env['KITTY_SSH_KITTEN_DATA_DIR'] = ssh_opts.remote_dir
    env_script = serialize_env(env, base_env)
    buf = io.BytesIO()
    with tarfile.open(mode='w:bz2', fileobj=buf, encoding='utf-8') as tf:
        rd = ssh_opts.remote_dir.rstrip('/')
        add_data_as_file(tf, 'kitty-ssh-kitten-data.sh', env_script)
        if ksi:
            tf.add(shell_integration_dir, arcname=rd + '/shell-integration', filter=filter_files)
        tf.add(terminfo_dir, arcname='.terminfo', filter=filter_files)
    return buf.getvalue()


@run_once
def load_ssh_options() -> Dict[str, SSHOptions]:
    from .config import init_config
    return init_config()


def get_ssh_data(msg: str, ssh_opts: Optional[Dict[str, SSHOptions]] = None) -> Iterator[bytes]:
    from .config import options_for_host
    record_sep = b'\036'

    if ssh_opts is None:
        ssh_opts = load_ssh_options()

    def fmt_prefix(msg: Any) -> bytes:
        return str(msg).encode('ascii') + record_sep

    yield record_sep  # to discard leading data
    try:
        msg = standard_b64decode(msg).decode('utf-8')
        md = dict(x.split('=', 1) for x in msg.split(':'))
        hostname = md['hostname']
        pw = md['pw']
        pwfilename = md['pwfile']
    except Exception:
        traceback.print_exc()
        yield fmt_prefix('!invalid ssh data request message')
    else:
        try:
            with open(os.path.join(cache_dir(), pwfilename), 'rb') as f:
                os.unlink(f.name)
                env_data = json.load(f)
                if pw != env_data['pw']:
                    raise ValueError('Incorrect password')
        except Exception:
            traceback.print_exc()
            yield fmt_prefix('!incorrect ssh data password')
        else:
            resolved_ssh_opts = options_for_host(hostname, ssh_opts)
            try:
                data = make_tarfile(resolved_ssh_opts, env_data['env'])
            except Exception:
                traceback.print_exc()
                yield fmt_prefix('!error while gathering ssh data')
            else:
                from base64 import standard_b64encode
                encoded_data = standard_b64encode(data)
                yield fmt_prefix(len(encoded_data))
                yield encoded_data


def safe_remove(x: str) -> None:
    with suppress(OSError):
        os.remove(x)


def prepare_script(ans: str, replacements: Dict[str, str]) -> str:
    pw = uuid4()
    with tempfile.NamedTemporaryFile(prefix='ssh-kitten-pw-', suffix='.json', dir=cache_dir(), delete=False) as tf:
        data = {'pw': pw, 'env': dict(os.environ)}
        tf.write(json.dumps(data).encode('utf-8'))
    atexit.register(safe_remove, tf.name)
    replacements['DATA_PASSWORD'] = pw
    replacements['PASSWORD_FILENAME'] = os.path.basename(tf.name)
    for k in ('EXEC_CMD', 'OVERRIDE_LOGIN_SHELL'):
        replacements[k] = replacements.get(k, '')

    def sub(m: 're.Match[str]') -> str:
        return replacements[m.group()]

    return re.sub('|'.join(fr'\b{k}\b' for k in replacements), sub, ans)


def bootstrap_script(script_type: str = 'sh', **replacements: str) -> str:
    with open(os.path.join(shell_integration_dir, 'ssh', f'bootstrap.{script_type}')) as f:
        ans = f.read()
    return prepare_script(ans, replacements)


def load_script(script_type: str = 'sh', exec_cmd: str = '') -> str:
    return bootstrap_script(script_type, EXEC_CMD=exec_cmd)


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


def get_connection_data(args: List[str], cwd: str = '') -> Optional[SSHConnectionData]:
    boolean_ssh_args, other_ssh_args = get_ssh_cli()
    port: Optional[int] = None
    expecting_port = expecting_identity = False
    expecting_option_val = False
    expecting_hostname = False
    host_name = identity_file = found_ssh = ''

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
            expecting_option_val = True
            continue

        if expecting_option_val:
            if expecting_port:
                with suppress(Exception):
                    port = int(arg)
                expecting_port = False
            elif expecting_identity:
                identity_file = arg
            expecting_option_val = False
            continue

        if not host_name:
            host_name = arg
    if not host_name:
        return None
    if identity_file:
        if not os.path.isabs(identity_file):
            identity_file = os.path.expanduser(identity_file)
        if not os.path.isabs(identity_file):
            identity_file = os.path.normpath(os.path.join(cwd or os.getcwd(), identity_file))

    return SSHConnectionData(found_ssh, host_name, port, identity_file)


class InvalidSSHArgs(ValueError):

    def __init__(self, msg: str = ''):
        super().__init__(msg)
        self.err_msg = msg

    def system_exit(self) -> None:
        if self.err_msg:
            print(self.err_msg, file=sys.stderr)
        os.execlp('ssh', 'ssh')


def parse_ssh_args(args: List[str]) -> Tuple[List[str], List[str], bool]:
    boolean_ssh_args, other_ssh_args = get_ssh_cli()
    passthrough_args = {f'-{x}' for x in 'Nnf'}
    ssh_args = []
    server_args: List[str] = []
    expecting_option_val = False
    passthrough = False
    stop_option_processing = False
    for argument in args:
        if len(server_args) > 1 or stop_option_processing:
            server_args.append(argument)
            continue
        if argument.startswith('-') and not expecting_option_val:
            if argument == '--':
                stop_option_processing = True
                continue
            # could be a multi-character option
            all_args = argument[1:]
            for i, arg in enumerate(all_args):
                arg = f'-{arg}'
                if arg in passthrough_args:
                    passthrough = True
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
                raise InvalidSSHArgs(f'unknown option -- {arg[1:]}')
            continue
        if expecting_option_val:
            ssh_args.append(argument)
            expecting_option_val = False
            continue
        server_args.append(argument)
    if not server_args:
        raise InvalidSSHArgs()
    return ssh_args, server_args, passthrough


def get_posix_cmd(remote_args: List[str]) -> List[str]:
    command_to_execute = ''
    if remote_args:
        # ssh simply concatenates multiple commands using a space see
        # line 1129 of ssh.c and on the remote side sshd.c runs the
        # concatenated command as shell -c cmd
        args = [c.replace("'", """'"'"'""") for c in remote_args]
        command_to_execute = "exec $login_shell -c '{}'".format(' '.join(args))
    sh_script = load_script(exec_cmd=command_to_execute)
    return [f'sh -c {shlex.quote(sh_script)}']


def main(args: List[str]) -> NoReturn:
    args = args[1:]
    if args and args[0] == 'use-python':
        args = args[1:]  # backwards compat from when we had a python implementation
    try:
        ssh_args, server_args, passthrough = parse_ssh_args(args)
    except InvalidSSHArgs as e:
        e.system_exit()
    cmd = ['ssh'] + ssh_args
    if passthrough:
        cmd += server_args
    else:
        hostname, remote_args = server_args[0], server_args[1:]
        if not remote_args:
            cmd.append('-t')
        cmd.append('--')
        cmd.append(hostname)
        f = get_posix_cmd
        cmd += f(remote_args)
    os.execvp('ssh', cmd)


if __name__ == '__main__':
    main(sys.argv)
elif __name__ == '__completer__':
    setattr(sys, 'kitten_completer', complete)
