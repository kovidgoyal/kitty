#!/usr/bin/env python3
# License: GPL v3 Copyright: 2018, Kovid Goyal <kovid at kovidgoyal.net>

import fnmatch
import glob
import io
import json
import os
import re
import secrets
import shlex
import shutil
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
    Any, Callable, Dict, Iterator, List, NoReturn, Optional, Sequence, Set,
    Tuple, Union, cast
)

from kitty.constants import (
    cache_dir, runtime_dir, shell_integration_dir, ssh_control_master_template,
    str_version, terminfo_dir
)
from kitty.shell_integration import as_str_literal
from kitty.shm import SharedMemory
from kitty.types import run_once
from kitty.utils import (
    SSHConnectionData, expandvars, resolve_abs_or_config_path,
    set_echo as turn_off_echo
)

from ..tui.operations import (
    RESTORE_PRIVATE_MODE_VALUES, SAVE_PRIVATE_MODE_VALUES, Mode,
    restore_colors, save_colors, set_mode
)
from ..tui.utils import kitty_opts, running_in_tmux
from .config import init_config
from .copy import CopyInstruction
from .options.types import Options as SSHOptions
from .options.utils import DELETE_ENV_VAR
from .utils import create_shared_memory, ssh_options


@run_once
def ssh_exe() -> str:
    return shutil.which('ssh') or 'ssh'


def read_data_from_shared_memory(shm_name: str) -> Any:
    with SharedMemory(shm_name, readonly=True) as shm:
        shm.unlink()
        if shm.stats.st_uid != os.geteuid() or shm.stats.st_gid != os.getegid():
            raise ValueError('Incorrect owner on pwfile')
        mode = stat.S_IMODE(shm.stats.st_mode)
        if mode != stat.S_IREAD:
            raise ValueError('Incorrect permissions on pwfile')
        return json.loads(shm.read_data_with_size())


# See https://www.gnu.org/software/bash/manual/html_node/Double-Quotes.html
quote_pat = re.compile('([\\`"])')


def quote_env_val(x: str, literal_quote: bool = False) -> str:
    if literal_quote:
        return as_str_literal(x)
    x = quote_pat.sub(r'\\\1', x)
    x = x.replace('$(', r'\$(')  # prevent execution with $()
    return f'"{x}"'


def serialize_env(literal_env: Dict[str, str], env: Dict[str, str], base_env: Dict[str, str], for_python: bool = False) -> bytes:
    lines = []
    literal_quote = True

    if for_python:
        def a(k: str, val: str = '', prefix: str = 'export') -> None:
            if val:
                lines.append(f'{prefix} {json.dumps((k, val, literal_quote))}')
            else:
                lines.append(f'{prefix} {json.dumps((k,))}')
    else:
        def a(k: str, val: str = '', prefix: str = 'export') -> None:
            if val:
                lines.append(f'{prefix} {shlex.quote(k)}={quote_env_val(val, literal_quote)}')
            else:
                lines.append(f'{prefix} {shlex.quote(k)}')

    for k, v in literal_env.items():
        a(k, v)

    literal_quote = False
    for k in sorted(env):
        v = env[k]
        if v == DELETE_ENV_VAR:
            a(k, prefix='unset')
        elif v == '_kitty_copy_env_var_':
            q = base_env.get(k)
            if q is not None:
                a(k, q)
        else:
            a(k, v)
    return '\n'.join(lines).encode('utf-8')


def make_tarfile(ssh_opts: SSHOptions, base_env: Dict[str, str], compression: str = 'gz', literal_env: Dict[str, str] = {}) -> bytes:

    def normalize_tarinfo(tarinfo: tarfile.TarInfo) -> tarfile.TarInfo:
        tarinfo.uname = tarinfo.gname = ''
        tarinfo.uid = tarinfo.gid = 0
        # some distro's like nix mess with installed file permissions so ensure
        # files are at least readable and writable by owning user
        tarinfo.mode |= stat.S_IWUSR | stat.S_IRUSR
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
        from kitty.options.types import Options
        from kitty.options.utils import shell_integration
        ksi = get_effective_ksi_env_var(Options({'shell_integration': shell_integration(ssh_opts.shell_integration)}))

    env = {
        'TERM': os.environ.get('TERM') or kitty_opts().term,
        'COLORTERM': 'truecolor',
    }
    env.update(ssh_opts.env)
    for q in ('KITTY_WINDOW_ID', 'WINDOWID'):
        val = os.environ.get(q)
        if val is not None:
            env[q] = val
    env['KITTY_SHELL_INTEGRATION'] = ksi or DELETE_ENV_VAR
    env['KITTY_SSH_KITTEN_DATA_DIR'] = ssh_opts.remote_dir
    if ssh_opts.login_shell:
        env['KITTY_LOGIN_SHELL'] = ssh_opts.login_shell
    if ssh_opts.cwd:
        env['KITTY_LOGIN_CWD'] = ssh_opts.cwd
    if ssh_opts.remote_kitty != 'no':
        env['KITTY_REMOTE'] = ssh_opts.remote_kitty
    if os.environ.get('KITTY_PUBLIC_KEY'):
        env.pop('KITTY_PUBLIC_KEY', None)
        literal_env['KITTY_PUBLIC_KEY'] = os.environ['KITTY_PUBLIC_KEY']
    env_script = serialize_env(literal_env, env, base_env, for_python=compression != 'gz')
    buf = io.BytesIO()
    with tarfile.open(mode=f'w:{compression}', fileobj=buf, encoding='utf-8') as tf:
        rd = ssh_opts.remote_dir.rstrip('/')
        for ci in ssh_opts.copy.values():
            tf.add(ci.local_path, arcname=ci.arcname, filter=filter_from_globs(*ci.exclude_patterns))
        add_data_as_file(tf, 'data.sh', env_script)
        if compression == 'gz':
            tf.add(f'{shell_integration_dir}/ssh/bootstrap-utils.sh', arcname='bootstrap-utils.sh', filter=normalize_tarinfo)
        if ksi:
            arcname = 'home/' + rd + '/shell-integration'
            tf.add(shell_integration_dir, arcname=arcname, filter=filter_from_globs(
                f'{arcname}/ssh/*',          # bootstrap files are sent as command line args
                f'{arcname}/zsh/kitty.zsh',  # present for legacy compat not needed by ssh kitten
            ))
        if ssh_opts.remote_kitty != 'no':
            arcname = 'home/' + rd + '/kitty'
            add_data_as_file(tf, arcname + '/version', str_version.encode('ascii'))
            tf.add(shell_integration_dir + '/ssh/kitty', arcname=arcname + '/bin/kitty', filter=normalize_tarinfo)
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
            env_data = read_data_from_shared_memory(pwfilename)
            if pw != env_data['pw']:
                raise ValueError('Incorrect password')
            if rq_id != request_id:
                raise ValueError(f'Incorrect request id: {rq_id!r} expecting the KITTY_PID-KITTY_WINDOW_ID for the current kitty window')
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


def prepare_script(ans: str, replacements: Dict[str, str], script_type: str) -> str:
    for k in ('EXEC_CMD', 'EXPORT_HOME_CMD'):
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
    return f"""unset KITTY_SHELL_INTEGRATION; exec "$login_shell" -c '{args}'"""


def prepare_export_home_cmd(ssh_opts: SSHOptions, is_python: bool) -> str:
    home = ssh_opts.env.get('HOME')
    if home == '_kitty_copy_env_var_':
        home = os.environ.get('HOME')
    if home:
        if is_python:
            return standard_b64encode(home.encode('utf-8')).decode('ascii')
        else:
            return f'export HOME={quote_env_val(home)}; cd "$HOME"'
    return ''


def bootstrap_script(
    ssh_opts: SSHOptions, script_type: str = 'sh', remote_args: Sequence[str] = (),
    test_script: str = '', request_id: Optional[str] = None, cli_hostname: str = '', cli_uname: str = '',
    request_data: bool = False, echo_on: bool = True, literal_env: Dict[str, str] = {}
) -> Tuple[str, Dict[str, str], str]:
    if request_id is None:
        request_id = os.environ['KITTY_PID'] + '-' + os.environ['KITTY_WINDOW_ID']
    is_python = script_type == 'py'
    export_home_cmd = prepare_export_home_cmd(ssh_opts, is_python) if 'HOME' in ssh_opts.env else ''
    exec_cmd = prepare_exec_cmd(remote_args, is_python) if remote_args else ''
    with open(os.path.join(shell_integration_dir, 'ssh', f'bootstrap.{script_type}')) as f:
        ans = f.read()
    pw = secrets.token_hex()
    tfd = standard_b64encode(make_tarfile(ssh_opts, dict(os.environ), 'gz' if script_type == 'sh' else 'bz2', literal_env=literal_env)).decode('ascii')
    data = {'pw': pw, 'opts': ssh_opts._asdict(), 'hostname': cli_hostname, 'uname': cli_uname, 'tarfile': tfd}
    shm_name = create_shared_memory(data, prefix=f'kssh-{os.getpid()}-')
    sensitive_data = {'REQUEST_ID': request_id, 'DATA_PASSWORD': pw, 'PASSWORD_FILENAME': shm_name}
    replacements = {
        'EXPORT_HOME_CMD': export_home_cmd,
        'EXEC_CMD': exec_cmd, 'TEST_SCRIPT': test_script,
        'REQUEST_DATA': '1' if request_data else '0', 'ECHO_ON': '1' if echo_on else '0',
    }
    sd = replacements.copy()
    if request_data:
        sd.update(sensitive_data)
    replacements.update(sensitive_data)
    return prepare_script(ans, sd, script_type), replacements, shm_name


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


class InvalidSSHArgs(ValueError):

    def __init__(self, msg: str = ''):
        super().__init__(msg)
        self.err_msg = msg

    def system_exit(self) -> None:
        if self.err_msg:
            print(self.err_msg, file=sys.stderr)
        os.execlp(ssh_exe(), 'ssh')


passthrough_args = {f'-{x}' for x in 'NnfGT'}


def parse_ssh_args(args: List[str], extra_args: Tuple[str, ...] = ()) -> Tuple[List[str], List[str], bool, Tuple[str, ...]]:
    boolean_ssh_args, other_ssh_args = get_ssh_cli()
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
    remote_args: List[str], ssh_opts: SSHOptions, cli_hostname: str = '', cli_uname: str = '',
    echo_on: bool = True, request_data: bool = False, literal_env: Dict[str, str] = {}
) -> Tuple[List[str], Dict[str, str], str]:
    interpreter = ssh_opts.interpreter
    q = os.path.basename(interpreter).lower()
    is_python = 'python' in q
    sh_script, replacements, shm_name = bootstrap_script(
        ssh_opts, script_type='py' if is_python else 'sh', remote_args=remote_args, literal_env=literal_env,
        cli_hostname=cli_hostname, cli_uname=cli_uname, echo_on=echo_on, request_data=request_data)
    return wrap_bootstrap_script(sh_script, interpreter), replacements, shm_name


def connection_sharing_args(kitty_pid: int) -> List[str]:
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
        print(end=SAVE_PRIVATE_MODE_VALUES)
        print(end=set_mode(Mode.HANDLE_TERMIOS_SIGNALS), flush=True)
        try:
            yield bool(val[3] & termios.ECHO)
        finally:
            termios.tcsetattr(f.fileno(), termios.TCSAFLUSH, val)
            print(end=RESTORE_PRIVATE_MODE_VALUES, flush=True)


def dcs_to_kitty(payload: Union[bytes, str], type: str = 'ssh') -> bytes:
    if isinstance(payload, str):
        payload = payload.encode('utf-8')
    payload = standard_b64encode(payload)
    ans = b'\033P@kitty-' + type.encode('ascii') + b'|' + payload
    tmux = running_in_tmux()
    if tmux:
        cp = subprocess.run([tmux, 'set', '-p', 'allow-passthrough', 'on'])
        if cp.returncode != 0:
            raise SystemExit(cp.returncode)
        ans = b'\033Ptmux;\033' + ans + b'\033\033\\\033\\'
    else:
        ans += b'\033\\'
    return ans


@run_once
def ssh_version() -> Tuple[int, int]:
    o = subprocess.check_output([ssh_exe(), '-V'], stderr=subprocess.STDOUT).decode()
    m = re.match(r'OpenSSH_(\d+).(\d+)', o)
    if m is None:
        raise ValueError(f'Invalid version string for OpenSSH: {o}')
    return int(m.group(1)), int(m.group(2))


@contextmanager
def drain_potential_tty_garbage(p: 'subprocess.Popen[bytes]', data_request: str) -> Iterator[None]:
    with open(os.open(os.ctermid(), os.O_CLOEXEC | os.O_RDWR | os.O_NOCTTY), 'wb') as tty:
        if data_request:
            turn_off_echo(tty.fileno())
            tty.write(dcs_to_kitty(data_request))
            tty.flush()
        try:
            yield
        finally:
            # discard queued input data on tty in case data transmission was
            # interrupted due to SSH failure, avoids spewing garbage to screen
            from uuid import uuid4
            canary = uuid4().hex.encode('ascii')
            turn_off_echo(tty.fileno())
            tty.write(dcs_to_kitty(canary + b'\n\r', type='echo'))
            tty.flush()
            data = b''
            give_up_at = time.monotonic() + 2
            tty_fd = tty.fileno()
            while time.monotonic() < give_up_at and canary not in data:
                with suppress(KeyboardInterrupt):
                    rd, wr, err = select([tty_fd], [], [tty_fd], max(0, give_up_at - time.monotonic()))
                    if err or not rd:
                        break
                    q = os.read(tty_fd, io.DEFAULT_BUFFER_SIZE)
                    if not q:
                        break
                    data += q


def change_colors(color_scheme: str) -> bool:
    if not color_scheme:
        return False
    from kittens.themes.collection import (
        NoCacheFound, load_themes, text_as_opts
    )
    from kittens.themes.main import colors_as_escape_codes
    if color_scheme.endswith('.conf'):
        conf_file = resolve_abs_or_config_path(color_scheme)
        try:
            with open(conf_file) as f:
                opts = text_as_opts(f.read())
        except FileNotFoundError:
            raise SystemExit(f'Failed to find the color conf file: {expandvars(conf_file)}')
    else:
        try:
            themes = load_themes(-1)
        except NoCacheFound:
            themes = load_themes()
        cs = expandvars(color_scheme)
        try:
            theme = themes[cs]
        except KeyError:
            raise SystemExit(f'Failed to find the color theme: {cs}')
        opts = theme.kitty_opts
    raw = colors_as_escape_codes(opts)
    print(save_colors(), sep='', end=raw, flush=True)
    return True


def add_cloned_env(shm_name: str) -> Dict[str, str]:
    try:
        return cast(Dict[str, str], read_data_from_shared_memory(shm_name))
    except FileNotFoundError:
        pass
    return {}


def run_ssh(ssh_args: List[str], server_args: List[str], found_extra_args: Tuple[str, ...]) -> NoReturn:
    cmd = [ssh_exe()] + ssh_args
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
        hostname_for_match = purl.hostname or hostname[6:].split('/', 1)[0]
        uname = purl.username or uname
    elif '@' in hostname and hostname[0] != '@':
        uname, hostname_for_match = hostname.split('@', 1)
    else:
        hostname_for_match = hostname
    hostname_for_match = hostname_for_match.split('@', 1)[-1].split(':', 1)[0]
    overrides: List[str] = []
    literal_env: Dict[str, str] = {}
    pat = re.compile(r'^([a-zA-Z0-9_]+)[ \t]*=')
    for i, a in enumerate(found_extra_args):
        if i % 2 == 1:
            aq = pat.sub(r'\1 ', a.lstrip())
            key = aq.split(maxsplit=1)[0]
            if key == 'clone_env':
                literal_env = add_cloned_env(aq.split(maxsplit=1)[1])
            elif key != 'hostname':
                overrides.append(aq)
    if overrides:
        overrides.insert(0, f'hostname {uname}@{hostname_for_match}')
    host_opts = init_config(hostname_for_match, uname, overrides)
    if host_opts.share_connections:
        cmd[insertion_point:insertion_point] = connection_sharing_args(int(os.environ['KITTY_PID']))
    use_kitty_askpass = host_opts.askpass == 'native' or (host_opts.askpass == 'unless-set' and 'SSH_ASKPASS' not in os.environ)
    need_to_request_data = True
    if use_kitty_askpass:
        sentinel = os.path.join(cache_dir(), 'openssh-is-new-enough-for-askpass')
        sentinel_exists = os.path.exists(sentinel)
        if sentinel_exists or ssh_version() >= (8, 4):
            if not sentinel_exists:
                open(sentinel, 'w').close()
            # SSH_ASKPASS_REQUIRE was introduced in 8.4 release on 2020-09-27
            need_to_request_data = False
            os.environ['SSH_ASKPASS_REQUIRE'] = 'force'
        os.environ['SSH_ASKPASS'] = os.path.join(shell_integration_dir, 'ssh', 'askpass.py')
    if need_to_request_data and host_opts.share_connections:
        cp = subprocess.run(cmd[:1] + ['-O', 'check'] + cmd[1:], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if cp.returncode == 0:
            # we will use the master connection so SSH does not need to use the tty
            need_to_request_data = False
    with restore_terminal_state() as echo_on:
        rcmd, replacements, shm_name = get_remote_command(
            remote_args, host_opts, hostname_for_match, uname, echo_on, request_data=need_to_request_data, literal_env=literal_env)
        cmd += rcmd
        colors_changed = change_colors(host_opts.color_scheme)
        try:
            p = subprocess.Popen(cmd)
        except FileNotFoundError:
            raise SystemExit('Could not find the ssh executable, is it in your PATH?')
        else:
            rq = '' if need_to_request_data else 'id={REQUEST_ID}:pwfile={PASSWORD_FILENAME}:pw={DATA_PASSWORD}'.format(**replacements)
            with drain_potential_tty_garbage(p, rq):
                raise SystemExit(p.wait())
        finally:
            if colors_changed:
                print(end=restore_colors(), flush=True)


def main(args: List[str]) -> None:
    args = args[1:]
    if args and args[0] == 'use-python':
        args = args[1:]  # backwards compat from when we had a python implementation
    try:
        ssh_args, server_args, passthrough, found_extra_args = parse_ssh_args(args, extra_args=('--kitten',))
    except InvalidSSHArgs as e:
        e.system_exit()
    if passthrough:
        if found_extra_args:
            raise SystemExit(f'The SSH kitten cannot work with the options: {", ".join(passthrough_args)}')
        os.execlp(ssh_exe(), 'ssh', *args)

    if not os.environ.get('KITTY_WINDOW_ID') or not os.environ.get('KITTY_PID'):
        raise SystemExit('The SSH kitten is meant to run inside a kitty window')
    if not sys.stdin.isatty():
        raise SystemExit('The SSH kitten is meant for interactive use only, STDIN must be a terminal')
    try:
        run_ssh(ssh_args, server_args, found_extra_args)
    except KeyboardInterrupt:
        sys.excepthook = lambda *a: None
        raise


if __name__ == '__main__':
    main(sys.argv)
elif __name__ == '__wrapper_of__':
    cd = sys.cli_docs  # type: ignore
    cd['wrapper_of'] = 'ssh'
elif __name__ == '__conf__':
    from .options.definition import definition
    sys.options_definition = definition  # type: ignore
