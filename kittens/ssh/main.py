#!/usr/bin/env python3
# License: GPL v3 Copyright: 2018, Kovid Goyal <kovid at kovidgoyal.net>

import atexit
import fnmatch
import glob
import io
import json
import os
import re
import secrets
import shlex
import stat
import subprocess
import sys
import tarfile
import tempfile
import termios
import time
import traceback
from base64 import standard_b64decode, standard_b64encode
from contextlib import contextmanager, suppress
from getpass import getuser
from select import select
from typing import (
    Callable, Dict, Iterator, List, NoReturn, Optional, Sequence, Set, Tuple,
    Union
)

from kitty.constants import (
    runtime_dir, shell_integration_dir, ssh_control_master_template,
    terminfo_dir
)
from kitty.options.types import Options
from kitty.shm import SharedMemory
from kitty.types import run_once
from kitty.utils import SSHConnectionData, set_echo as turn_off_echo

from .completion import complete, ssh_options
from .config import init_config
from .copy import CopyInstruction
from .options.types import Options as SSHOptions
from .options.utils import DELETE_ENV_VAR

# See https://www.gnu.org/software/bash/manual/html_node/Double-Quotes.html
quote_pat = re.compile('([\\`"\n])')


def quote_env_val(x: str) -> str:
    x = quote_pat.sub(r'\\\1', x)
    x = x.replace('$(', r'\$(')  # prevent execution with $()
    return f'"{x}"'


def serialize_env(env: Dict[str, str], base_env: Dict[str, str]) -> bytes:
    lines = []

    def a(k: str, val: str) -> None:
        lines.append(f'export {shlex.quote(k)}={quote_env_val(val)}')

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


@run_once
def kitty_opts() -> Options:
    from kitty.cli import create_default_opts
    return create_default_opts()


def make_tarfile(ssh_opts: SSHOptions, base_env: Dict[str, str], compression: str = 'gz') -> bytes:

    def normalize_tarinfo(tarinfo: tarfile.TarInfo) -> tarfile.TarInfo:
        tarinfo.uname = tarinfo.gname = ''
        tarinfo.uid = tarinfo.gid = 0
        return tarinfo

    def add_data_as_file(tf: tarfile.TarFile, arcname: str, data: Union[str, bytes]) -> tarfile.TarInfo:
        ans = tarfile.TarInfo(arcname)
        ans.mtime = 0
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
                for pat in (f'*/{junk_dir}', f'*/{junk_dir}/*'):
                    if fnmatch.fnmatch(tarinfo.name, pat):
                        return None
            for pat in pats:
                if fnmatch.fnmatch(tarinfo.name, pat):
                    return None
            return normalize_tarinfo(tarinfo)
        return filter

    from kitty.shell_integration import get_effective_ksi_env_var
    if ssh_opts.shell_integration == 'inherited':
        ksi = get_effective_ksi_env_var(kitty_opts())
    else:
        from kitty.options.utils import shell_integration
        ksi = get_effective_ksi_env_var(Options({'shell_integration': shell_integration(ssh_opts.shell_integration)}))

    env = {
        'TERM': os.environ.get('TERM') or kitty_opts().term,
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
    if ssh_opts.cwd:
        env['KITTY_LOGIN_CWD'] = ssh_opts.cwd
    env_script = serialize_env(env, base_env)
    buf = io.BytesIO()
    with tarfile.open(mode=f'w:{compression}', fileobj=buf, encoding='utf-8') as tf:
        rd = ssh_opts.remote_dir.rstrip('/')
        for ci in ssh_opts.copy.values():
            tf.add(ci.local_path, arcname=ci.arcname, filter=filter_from_globs(*ci.exclude_patterns))
        add_data_as_file(tf, 'data.sh', env_script)
        if ksi:
            arcname = 'home/' + rd + '/shell-integration'
            tf.add(shell_integration_dir, arcname=arcname, filter=filter_from_globs(
                f'{arcname}/ssh/*',          # bootstrap files are sent as command line args
                f'{arcname}/zsh/kitty.zsh',  # present for legacy compat not needed by ssh kitten
            ))
        tf.add(f'{terminfo_dir}/kitty.terminfo', arcname='home/.terminfo/kitty.terminfo', filter=normalize_tarinfo)
        tf.add(glob.glob(f'{terminfo_dir}/*/xterm-kitty')[0], arcname='home/.terminfo/x/xterm-kitty', filter=normalize_tarinfo)
    return buf.getvalue()


def get_ssh_data(msg: str, request_id: str) -> Iterator[bytes]:
    yield b'\nKITTY_DATA_START\n'  # to discard leading data
    try:
        msg = standard_b64decode(msg).decode('utf-8')
        md = dict(x.split('=', 1) for x in msg.split(':'))
        pw = md['pw']
        pwfilename = md['pwfile']
        rq_id = md['id']
    except Exception:
        traceback.print_exc()
        yield b'invalid ssh data request message\n'
    else:
        try:
            with SharedMemory(pwfilename, readonly=True) as shm:
                shm.unlink()
                if shm.stats.st_uid != os.geteuid() or shm.stats.st_gid != os.getegid():
                    raise ValueError('Incorrect owner on pwfile')
                mode = stat.S_IMODE(shm.stats.st_mode)
                if mode != stat.S_IREAD:
                    raise ValueError('Incorrect permissions on pwfile')
                env_data = json.loads(shm.read_data_with_size())
                if pw != env_data['pw']:
                    raise ValueError('Incorrect password')
                if rq_id != request_id:
                    raise ValueError('Incorrect request id')
        except Exception as e:
            traceback.print_exc()
            yield f'{e}\n'.encode('utf-8')
        else:
            yield b'OK\n'
            ssh_opts = SSHOptions(env_data['opts'])
            ssh_opts.copy = {k: CopyInstruction(*v) for k, v in ssh_opts.copy.items()}
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
    ssh_opts: SSHOptions, script_type: str = 'sh', remote_args: Sequence[str] = (),
    test_script: str = '', request_id: Optional[str] = None, cli_hostname: str = '', cli_uname: str = '',
    request_data: bool = False, echo_on: bool = True
) -> Tuple[str, Dict[str, str], SharedMemory]:
    if request_id is None:
        request_id = os.environ['KITTY_PID'] + '-' + os.environ['KITTY_WINDOW_ID']
    exec_cmd = prepare_exec_cmd(remote_args, script_type == 'py') if remote_args else ''
    with open(os.path.join(shell_integration_dir, 'ssh', f'bootstrap.{script_type}')) as f:
        ans = f.read()
    pw = secrets.token_hex()
    tfd = standard_b64encode(make_tarfile(ssh_opts, dict(os.environ), 'gz' if script_type == 'sh' else 'bz2')).decode('ascii')
    data = {'pw': pw, 'opts': ssh_opts._asdict(), 'hostname': cli_hostname, 'uname': cli_uname, 'tarfile': tfd}
    db = json.dumps(data)
    with SharedMemory(size=len(db) + SharedMemory.num_bytes_for_size, mode=stat.S_IREAD, prefix=f'kssh-{os.getpid()}-') as shm:
        shm.write_data_with_size(db)
        shm.flush()
        atexit.register(shm.unlink)
    sensitive_data = {'REQUEST_ID': request_id, 'DATA_PASSWORD': pw, 'PASSWORD_FILENAME': shm.name}
    replacements = {
        'EXEC_CMD': exec_cmd, 'TEST_SCRIPT': test_script, 'REQUEST_DATA': '1' if request_data else '0', 'ECHO_ON': '1' if echo_on else '0',
    }
    sd = replacements.copy()
    if request_data:
        sd.update(sensitive_data)
    replacements.update(sensitive_data)
    return prepare_script(ans, sd), replacements, shm


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
                expecting_extra_val = ''
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
    passthrough_args = {f'-{x}' for x in 'NnfG'}
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
                expecting_extra_val = ''
            else:
                ssh_args.append(argument)
            expecting_option_val = False
            continue
        server_args.append(argument)
    if not server_args:
        raise InvalidSSHArgs()
    return ssh_args, server_args, passthrough, tuple(found_extra_args)


def wrap_bootstrap_script(sh_script: str, interpreter: str) -> List[str]:
    # sshd will execute the command we pass it by join all command line
    # arguments with a space and passing it as a single argument to the users
    # login shell with -c. If the user has a non POSIX login shell it might
    # have different escaping semantics and syntax, so the command it should
    # execute has to be as simple as possible, basically of the form
    # interpreter -c unwrap_script escaped_bootstrap_script
    # The unwrap_script is responsible for unescaping the bootstrap script and
    # executing it.
    q = os.path.basename(interpreter).lower()
    is_python = 'python' in q
    if is_python:
        es = standard_b64encode(sh_script.encode('utf-8')).decode('ascii')
        unwrap_script = '''"import base64, sys; eval(compile(base64.standard_b64decode(sys.argv[-1]), 'bootstrap.py', 'exec'))"'''
    else:
        # We cant rely on base64 being available on the remote system, so instead
        # we quote the bootstrap script by replacing ' and \ with \v and \f
        # also replacing \n and ! with \r and \b for tcsh
        # finally surrounding with '
        es = "'" + sh_script.replace("'", '\v').replace('\\', '\f').replace('\n', '\r').replace('!', '\b') + "'"
        unwrap_script = r"""'eval "$(echo "$0" | tr \\\v\\\f\\\r\\\b \\\047\\\134\\\n\\\041)"' """
    # exec is supported by all sh like shells, and fish and csh
    return ['exec', interpreter, '-c', unwrap_script, es]


def get_remote_command(
    remote_args: List[str], ssh_opts: SSHOptions, hostname: str = 'localhost', cli_hostname: str = '', cli_uname: str = '',
    echo_on: bool = True, request_data: bool = False
) -> Tuple[List[str], Dict[str, str], str]:
    interpreter = ssh_opts.interpreter
    q = os.path.basename(interpreter).lower()
    is_python = 'python' in q
    sh_script, replacements, shm = bootstrap_script(
        ssh_opts, script_type='py' if is_python else 'sh', remote_args=remote_args,
        cli_hostname=cli_hostname, cli_uname=cli_uname, echo_on=echo_on, request_data=request_data)
    return wrap_bootstrap_script(sh_script, interpreter), replacements, shm.name


def connection_sharing_args(opts: SSHOptions, kitty_pid: int) -> List[str]:
    rd = runtime_dir()
    # Bloody OpenSSH generates a 40 char hash and in creating the socket
    # appends a 27 char temp suffix to it. Socket max path length is approx
    # ~104 chars. macOS has no system runtime dir so we use a cache dir in
    # /Users/WHY_DOES_ANYONE_USE_MACOS/Library/Caches/APPLE_ARE_IDIOTIC
    if len(rd) > 35 and os.path.isdir('/tmp'):
        idiotic_design = f'/tmp/kssh-rdir-{os.getuid()}'
        try:
            os.symlink(rd, idiotic_design)
        except FileExistsError:
            try:
                dest = os.readlink(idiotic_design)
            except OSError as e:
                raise ValueError(f'The {idiotic_design} symlink could not be created as something with that name exists already') from e
            else:
                if dest != rd:
                    with tempfile.TemporaryDirectory(dir='/tmp') as tdir:
                        tlink = os.path.join(tdir, 'sigh')
                        os.symlink(rd, tlink)
                        os.rename(tlink, idiotic_design)
        rd = idiotic_design

    cp = os.path.join(rd, ssh_control_master_template.format(kitty_pid=kitty_pid, ssh_placeholder='%C'))
    ans: List[str] = [
        '-o', 'ControlMaster=auto',
        '-o', f'ControlPath={cp}',
        '-o', 'ControlPersist=yes',
        '-o', 'ServerAliveInterval=60',
        '-o', 'ServerAliveCountMax=5',
        '-o', 'TCPKeepAlive=no',
    ]
    return ans


@contextmanager
def restore_terminal_state() -> Iterator[bool]:
    with open(os.ctermid()) as f:
        val = termios.tcgetattr(f.fileno())
        try:
            yield bool(val[3] & termios.ECHO)
        finally:
            termios.tcsetattr(f.fileno(), termios.TCSAFLUSH, val)


def dcs_to_kitty(payload: Union[bytes, str], type: str = 'ssh') -> bytes:
    if isinstance(payload, str):
        payload = payload.encode('utf-8')
    payload = standard_b64encode(payload)
    return b'\033P@kitty-' + type.encode('ascii') + b'|' + payload + b'\033\\'


@run_once
def ssh_version() -> Tuple[int, int]:
    o = subprocess.check_output(['ssh', '-V'], stderr=subprocess.STDOUT).decode()
    m = re.match(r'OpenSSH_(\d+).(\d+)', o)
    if m is None:
        raise ValueError(f'Invalid version string for OpenSSH: {o}')
    return int(m.group(1)), int(m.group(2))


@contextmanager
def drain_potential_tty_garbage(p: 'subprocess.Popen[bytes]', data_request: str) -> Iterator[None]:
    ssh_started_at = time.monotonic()
    with open(os.open(os.ctermid(), os.O_CLOEXEC | os.O_RDWR | os.O_NOCTTY), 'wb') as tty:
        if data_request:
            turn_off_echo(tty.fileno())
            tty.write(dcs_to_kitty(data_request))
            tty.flush()
        try:
            yield
        finally:
            if p.returncode and time.monotonic() - ssh_started_at < 30:
                # discard queued input data on tty in case data transmission was
                # interrupted due to SSH failure, avoids spewing garbage to
                # screen
                data = b''
                give_up_at = time.monotonic() + 1
                tty_fd = tty.fileno()
                while time.monotonic() < give_up_at and b'KITTY_DATA_END' not in data:
                    rd, wr, err = select([tty_fd], [], [tty_fd], max(0, give_up_at - time.monotonic()))
                    if err or not rd:
                        break
                    q = os.read(tty_fd, io.DEFAULT_BUFFER_SIZE)
                    if not q:
                        break
                    data += q


def run_ssh(ssh_args: List[str], server_args: List[str], found_extra_args: Tuple[str, ...]) -> NoReturn:
    cmd = ['ssh'] + ssh_args
    hostname, remote_args = server_args[0], server_args[1:]
    if not remote_args:
        cmd.append('-t')
    insertion_point = len(cmd)
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
            aq = pat.sub(r'\1 ', a.lstrip())
            if aq.split(maxsplit=1)[0] != 'hostname':
                overrides.append(aq)
    if overrides:
        overrides.insert(0, f'hostname {uname}@{hostname_for_match}')
    host_opts = init_config(hostname_for_match, uname, overrides)
    use_control_master = host_opts.share_connections
    if use_control_master:
        cmd[insertion_point:insertion_point] = connection_sharing_args(host_opts, int(os.environ['KITTY_PID']))
    use_kitty_askpass = host_opts.askpass == 'native' or (host_opts.askpass == 'unless-set' and 'SSH_ASKPASS' not in os.environ)
    need_to_request_data = True
    if use_kitty_askpass:
        if ssh_version() >= (8, 4):
            # SSH_ASKPASS_REQUIRE was introduced in 8.4 release on 2020-09-27
            need_to_request_data = False
            os.environ['SSH_ASKPASS_REQUIRE'] = 'force'
        os.environ['SSH_ASKPASS'] = os.path.join(shell_integration_dir, 'ssh', 'askpass.py')
    with restore_terminal_state() as echo_on:
        rcmd, replacements, shm_name = get_remote_command(
            remote_args, host_opts, hostname, hostname_for_match, uname, echo_on, request_data=need_to_request_data)
        cmd += rcmd
        try:
            p = subprocess.Popen(cmd)
        except FileNotFoundError:
            raise SystemExit('Could not find the ssh executable, is it in your PATH?')
        else:
            rq = '' if need_to_request_data else 'id={REQUEST_ID}:pwfile={PASSWORD_FILENAME}:pw={DATA_PASSWORD}'.format(**replacements)
            with drain_potential_tty_garbage(p, rq):
                try:
                    raise SystemExit(p.wait())
                except KeyboardInterrupt:
                    raise SystemExit(1)


def main(args: List[str]) -> NoReturn:
    args = args[1:]
    if args and args[0] == 'use-python':
        args = args[1:]  # backwards compat from when we had a python implementation
    try:
        ssh_args, server_args, passthrough, found_extra_args = parse_ssh_args(args, extra_args=('--kitten',))
    except InvalidSSHArgs as e:
        e.system_exit()
    if not os.environ.get('KITTY_WINDOW_ID') or not os.environ.get('KITTY_PID'):
        raise SystemExit('The SSH kitten is meant to run inside a kitty window')
    if passthrough:
        raise SystemExit('The SSH kitten is meant for interactive use via SSH only')
    if not sys.stdin.isatty():
        raise SystemExit('The SSH kitten is meant for interactive use only, STDIN must be a terminal')
    run_ssh(ssh_args, server_args, found_extra_args)


if __name__ == '__main__':
    main(sys.argv)
elif __name__ == '__completer__':
    setattr(sys, 'kitten_completer', complete)
elif __name__ == '__conf__':
    from .options.definition import definition
    sys.options_definition = definition  # type: ignore
