#!/usr/bin/env python3
# License: GPL v3 Copyright: 2018, Kovid Goyal <kovid at kovidgoyal.net>

import atexit
import fnmatch
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
from base64 import standard_b64decode, standard_b64encode
from contextlib import suppress
from getpass import getuser
from typing import (
    Any, Callable, Dict, Iterator, List, NoReturn, Optional, Sequence, Set,
    Tuple, Union
)

from kitty.constants import cache_dir, shell_integration_dir, terminfo_dir
from kitty.fast_data_types import get_options
from kitty.short_uuid import uuid4
from kitty.utils import SSHConnectionData

from .completion import complete, ssh_options
from .config import init_config, options_for_host
from .copy import CopyInstruction
from .options.types import Options as SSHOptions
from .options.utils import DELETE_ENV_VAR


def serialize_env(env: Dict[str, str], base_env: Dict[str, str]) -> bytes:
    lines = []

    def a(k: str, val: str) -> None:
        lines.append(f'export {k}={shlex.quote(val)}')

    for k in sorted(env):
        v = env[k]
        if v == DELETE_ENV_VAR:
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

    def filter_from_globs(*pats: str) -> Callable[[tarfile.TarInfo], Optional[tarfile.TarInfo]]:
        def filter(tarinfo: tarfile.TarInfo) -> Optional[tarfile.TarInfo]:
            for junk_dir in ('.DS_Store', '__pycache__'):
                for pat in (f'*/{junk_dir}', '*/{junk_dir}/*'):
                    if fnmatch.fnmatch(tarinfo.name, pat):
                        return None
            for pat in pats:
                if fnmatch.fnmatch(tarinfo.name, pat):
                    return None
            return normalize_tarinfo(tarinfo)
        return filter

    from kitty.shell_integration import get_effective_ksi_env_var
    if ssh_opts.shell_integration == 'inherited':
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
    if ssh_opts.login_shell:
        env['KITTY_LOGIN_SHELL'] = ssh_opts.login_shell
    env_script = serialize_env(env, base_env)
    buf = io.BytesIO()
    with tarfile.open(mode='w:bz2', fileobj=buf, encoding='utf-8') as tf:
        rd = ssh_opts.remote_dir.rstrip('/')
        for ci in ssh_opts.copy.values():
            tf.add(ci.local_path, arcname=ci.arcname, filter=filter_from_globs(*ci.exclude_patterns))
        add_data_as_file(tf, 'data.sh', env_script)
        if ksi:
            arcname = 'home/' + rd + '/shell-integration'
            tf.add(shell_integration_dir, arcname=arcname, filter=filter_from_globs(
                f'{arcname}/ssh/bootstrap.*',  # bootstrap files are sent as command line args
                f'{arcname}/zsh/kitty.zsh',  # present for legacy compat not needed by ssh kitten
            ))
        tf.add(terminfo_dir, arcname='home/.terminfo', filter=normalize_tarinfo)
    return buf.getvalue()


def get_ssh_data(msg: str, request_id: str) -> Iterator[bytes]:
    record_sep = b'\036'

    def fmt_prefix(msg: Any) -> bytes:
        return str(msg).encode('ascii') + record_sep

    yield record_sep  # to discard leading data
    try:
        msg = standard_b64decode(msg).decode('utf-8')
        md = dict(x.split('=', 1) for x in msg.split(':'))
        hostname = md['hostname']
        pw = md['pw']
        pwfilename = md['pwfile']
        username = md['user']
        rq_id = md['id']
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
                if rq_id != request_id:
                    raise ValueError('Incorrect request id')
        except Exception as e:
            traceback.print_exc()
            yield fmt_prefix(f'!{e}')
        else:
            ssh_opts = {k: SSHOptions(v) for k, v in env_data['opts'].items()}
            resolved_ssh_opts = options_for_host(hostname, username, ssh_opts)
            resolved_ssh_opts.copy = {k: CopyInstruction(*v) for k, v in resolved_ssh_opts.copy.items()}
            try:
                data = make_tarfile(resolved_ssh_opts, env_data['env'])
            except Exception:
                traceback.print_exc()
                yield fmt_prefix('!error while gathering ssh data')
            else:
                encoded_data = standard_b64encode(data)
                yield fmt_prefix(len(encoded_data))
                yield encoded_data


def safe_remove(x: str) -> None:
    with suppress(OSError):
        os.remove(x)


def prepare_script(ans: str, replacements: Dict[str, str]) -> str:
    for k in ('EXEC_CMD',):
        replacements[k] = replacements.get(k, '')

    def sub(m: 're.Match[str]') -> str:
        return replacements[m.group()]

    return re.sub('|'.join(fr'\b{k}\b' for k in replacements), sub, ans)


def prepare_exec_cmd(remote_args: Sequence[str], is_python: bool) -> str:
    # ssh simply concatenates multiple commands using a space see
    # line 1129 of ssh.c and on the remote side sshd.c runs the
    # concatenated command as shell -c cmd
    if is_python:
        return standard_b64encode(' '.join(remote_args).encode('utf-8')).decode('ascii')
    args = ' '.join(c.replace("'", """'"'"'""") for c in remote_args)
    return f"""exec "$login_shell" -c '{args}'"""


def bootstrap_script(
    script_type: str = 'sh', remote_args: Sequence[str] = (),
    ssh_opts_dict: Dict[str, Dict[str, Any]] = {},
    test_script: str = '', request_id: Optional[str] = None
) -> str:
    if request_id is None:
        request_id = os.environ['KITTY_PID'] + '-' + os.environ['KITTY_WINDOW_ID']
    exec_cmd = prepare_exec_cmd(remote_args, script_type == 'py') if remote_args else ''
    with open(os.path.join(shell_integration_dir, 'ssh', f'bootstrap.{script_type}')) as f:
        ans = f.read()
    pw = uuid4()
    with tempfile.NamedTemporaryFile(prefix='ssh-kitten-pw-', suffix='.json', dir=cache_dir(), delete=False) as tf:
        data = {'pw': pw, 'env': dict(os.environ), 'opts': ssh_opts_dict}
        tf.write(json.dumps(data).encode('utf-8'))
    atexit.register(safe_remove, tf.name)
    replacements = {
        'DATA_PASSWORD': pw, 'PASSWORD_FILENAME': os.path.basename(tf.name), 'EXEC_CMD': exec_cmd, 'TEST_SCRIPT': test_script,
        'REQUEST_ID': request_id
    }
    return prepare_script(ans, replacements)


def load_script(script_type: str = 'sh', remote_args: Sequence[str] = (), ssh_opts_dict: Dict[str, Dict[str, Any]] = {}) -> str:
    return bootstrap_script(script_type, remote_args, ssh_opts_dict=ssh_opts_dict)


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


def get_connection_data(args: List[str], cwd: str = '', extra_args: Tuple[str, ...] = ()) -> Optional[SSHConnectionData]:
    boolean_ssh_args, other_ssh_args = get_ssh_cli()
    port: Optional[int] = None
    expecting_port = expecting_identity = False
    expecting_option_val = False
    expecting_hostname = False
    expecting_extra_val = ''
    host_name = identity_file = found_ssh = ''
    found_extra_args: List[Tuple[str, str]] = []

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

    return SSHConnectionData(found_ssh, host_name, port, identity_file, tuple(found_extra_args))


class InvalidSSHArgs(ValueError):

    def __init__(self, msg: str = ''):
        super().__init__(msg)
        self.err_msg = msg

    def system_exit(self) -> None:
        if self.err_msg:
            print(self.err_msg, file=sys.stderr)
        os.execlp('ssh', 'ssh')


def parse_ssh_args(args: List[str], extra_args: Tuple[str, ...] = ()) -> Tuple[List[str], List[str], bool, Tuple[str, ...]]:
    boolean_ssh_args, other_ssh_args = get_ssh_cli()
    passthrough_args = {f'-{x}' for x in 'Nnf'}
    ssh_args = []
    server_args: List[str] = []
    expecting_option_val = False
    passthrough = False
    stop_option_processing = False
    found_extra_args: List[str] = []
    expecting_extra_val = ''
    for argument in args:
        if len(server_args) > 1 or stop_option_processing:
            server_args.append(argument)
            continue
        if argument.startswith('-') and not expecting_option_val:
            if argument == '--':
                stop_option_processing = True
                continue
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
            if expecting_extra_val:
                found_extra_args.extend((expecting_extra_val, argument))
            else:
                ssh_args.append(argument)
            expecting_option_val = False
            continue
        server_args.append(argument)
    if not server_args:
        raise InvalidSSHArgs()
    return ssh_args, server_args, passthrough, tuple(found_extra_args)


def get_remote_command(
    remote_args: List[str], hostname: str = 'localhost', interpreter: str = 'sh',
    ssh_opts_dict: Dict[str, Dict[str, Any]] = {}
) -> List[str]:
    is_python = 'python' in interpreter.lower()
    sh_script = load_script(script_type='py' if is_python else 'sh', remote_args=remote_args, ssh_opts_dict=ssh_opts_dict)
    return [f'{interpreter} -c {shlex.quote(sh_script)}']


def main(args: List[str]) -> NoReturn:
    args = args[1:]
    if args and args[0] == 'use-python':
        args = args[1:]  # backwards compat from when we had a python implementation
    try:
        ssh_args, server_args, passthrough, found_extra_args = parse_ssh_args(args, extra_args=('--kitten',))
    except InvalidSSHArgs as e:
        e.system_exit()
    if not os.environ.get('KITTY_WINDOW_ID'):
        passthrough = True
    cmd = ['ssh'] + ssh_args
    if passthrough:
        cmd += server_args
    else:
        hostname, remote_args = server_args[0], server_args[1:]
        if not remote_args:
            cmd.append('-t')
        cmd.append('--')
        cmd.append(hostname)
        uname = getuser()
        if hostname.startswith('ssh://'):
            from urllib.parse import urlparse
            purl = urlparse(hostname)
            hostname_for_match = purl.hostname or hostname
            uname = purl.username or uname
        elif '@' in hostname and hostname[0] != '@':
            uname, hostname_for_match = hostname.split('@', 1)
        else:
            hostname_for_match = hostname
        hostname_for_match = hostname.split('@', 1)[-1].split(':', 1)[0]
        overrides = []
        pat = re.compile(r'^([a-zA-Z0-9_]+)[ \t]*=')
        for i, a in enumerate(found_extra_args):
            if i % 2 == 1:
                overrides.append(pat.sub(r'\1 ', a.lstrip()))
        so = init_config(overrides)
        sod = {k: v._asdict() for k, v in so.items()}
        cmd += get_remote_command(remote_args, hostname, options_for_host(hostname_for_match, uname, so).interpreter, sod)
    os.execvp('ssh', cmd)


if __name__ == '__main__':
    main(sys.argv)
elif __name__ == '__completer__':
    setattr(sys, 'kitten_completer', complete)
elif __name__ == '__conf__':
    from .options.definition import definition
    sys.options_definition = definition  # type: ignore
