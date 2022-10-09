#!/usr/bin/env python3
# License: GPL v3 Copyright: 2018, Kovid Goyal <kovid at kovidgoyal.net>

import base64
import json
import os
import re
import sys
from contextlib import suppress
from functools import lru_cache, partial
from time import monotonic, time_ns
from types import GeneratorType
from typing import (
    TYPE_CHECKING, Any, Dict, FrozenSet, Iterable, Iterator, List, Optional,
    Tuple, Union, cast
)

from .cli import emph, parse_args
from .cli_stub import RCOptions
from .constants import RC_ENCRYPTION_PROTOCOL_VERSION, appname, version
from .fast_data_types import (
    AES256GCMDecrypt, AES256GCMEncrypt, EllipticCurveKey, get_boss,
    get_options, read_command_response, send_data_to_peer
)
from .rc.base import (
    NoResponse, ParsingOfArgsFailed, PayloadGetter, all_command_names,
    command_for_name, parse_subcommand_cli
)
from .types import AsyncResponse
from .typing import BossType, WindowType
from .utils import TTYIO, log_error, parse_address_spec, resolve_custom_file

active_async_requests: Dict[str, float] = {}
if TYPE_CHECKING:
    from .window import Window


def encode_response_for_peer(response: Any) -> bytes:
    return b'\x1bP@kitty-cmd' + json.dumps(response).encode('utf-8') + b'\x1b\\'


def parse_cmd(serialized_cmd: str, encryption_key: EllipticCurveKey) -> Dict[str, Any]:
    try:
        pcmd = json.loads(serialized_cmd)
    except Exception:
        return {}
    if not isinstance(pcmd, dict) or 'version' not in pcmd:
        return {}
    pcmd.pop('password', None)
    if 'encrypted' in pcmd:
        if pcmd.get('enc_proto', '1') != RC_ENCRYPTION_PROTOCOL_VERSION:
            log_error(f'Ignoring encrypted rc command with unsupported protocol: {pcmd.get("enc_proto")}')
            return {}
        pubkey = pcmd.get('pubkey', '')
        if not pubkey:
            log_error('Ignoring encrypted rc command without a public key')
        d = AES256GCMDecrypt(encryption_key.derive_secret(base64.b85decode(pubkey)), base64.b85decode(pcmd['iv']), base64.b85decode(pcmd['tag']))
        data = d.add_data_to_be_decrypted(base64.b85decode(pcmd['encrypted']), True)
        pcmd = json.loads(data)
        if not isinstance(pcmd, dict) or 'version' not in pcmd:
            return {}
        delta = time_ns() - pcmd.pop('timestamp')
        if abs(delta) > 5 * 60 * 1e9:
            log_error(
                f'Ignoring encrypted rc command with timestamp {delta / 1e9:.1f} seconds from now.'
                ' Could be an attempt at a replay attack or an incorrect clock on a remote machine.')
            return {}
    return pcmd


class CMDChecker:

    def __call__(self, pcmd: Dict[str, Any], window: Optional['Window'], from_socket: bool, extra_data: Dict[str, Any]) -> Optional[bool]:
        return False


@lru_cache(maxsize=64)
def is_cmd_allowed_loader(path: str) -> CMDChecker:
    import runpy
    try:
        m = runpy.run_path(path)
        func: CMDChecker = m['is_cmd_allowed']
    except Exception as e:
        log_error(f'Failed to load cmd check function from {path} with error: {e}')
        func = CMDChecker()
    return func


@lru_cache(maxsize=1024)
def fnmatch_pattern(pat: str) -> 're.Pattern[str]':
    from fnmatch import translate
    return re.compile(translate(pat))


class PasswordAuthorizer:

    def __init__(self, auth_items: FrozenSet[str]) -> None:
        self.command_patterns = []
        self.function_checkers = []
        self.name = ''
        for item in auth_items:
            if item.endswith('.py'):
                path = os.path.abspath(resolve_custom_file(item))
                self.function_checkers.append(is_cmd_allowed_loader(path))
            else:
                self.command_patterns.append(fnmatch_pattern(item))

    def is_cmd_allowed(self, pcmd: Dict[str, Any], window: Optional['Window'], from_socket: bool, extra_data: Dict[str, Any]) -> bool:
        cmd_name = pcmd.get('cmd')
        if not cmd_name:
            return False
        if not self.function_checkers and not self.command_patterns:
            return True
        for x in self.command_patterns:
            if x.match(cmd_name) is not None:
                return True
        for f in self.function_checkers:
            try:
                ret = f(pcmd, window, from_socket, extra_data)
            except Exception as e:
                import traceback
                traceback.print_exc()
                log_error(f'There was an error using a custom RC auth function, blocking the remote command. Error: {e}')
                ret = False
            if ret is not None:
                return ret
        return False


@lru_cache(maxsize=256)
def password_authorizer(auth_items: FrozenSet[str]) -> PasswordAuthorizer:
    return PasswordAuthorizer(auth_items)


user_password_allowed: Dict[str, bool] = {}


def is_cmd_allowed(pcmd: Dict[str, Any], window: Optional['Window'], from_socket: bool, extra_data: Dict[str, Any]) -> Optional[bool]:
    pw = pcmd.get('password', '')
    if not pw:
        auth_items = get_options().remote_control_password.get('')
        if auth_items is None:
            return False
        pa = password_authorizer(auth_items)
        return pa.is_cmd_allowed(pcmd, window, from_socket, extra_data)
    q = user_password_allowed.get(pw)
    if q is not None:
        return q
    auth_items = get_options().remote_control_password.get(pw)
    if auth_items is None:
        return None
    pa = password_authorizer(auth_items)
    return pa.is_cmd_allowed(pcmd, window, from_socket, extra_data)


def set_user_password_allowed(pwd: str, allowed: bool = True) -> None:
    user_password_allowed[pwd] = allowed


def handle_cmd(boss: BossType, window: Optional[WindowType], cmd: Dict[str, Any], peer_id: int) -> Union[Dict[str, Any], None, AsyncResponse]:
    v = cmd['version']
    no_response = cmd.get('no_response', False)
    if tuple(v)[:2] > version[:2]:
        if no_response:
            return None
        return {'ok': False, 'error': 'The kitty client you are using to send remote commands is newer than this kitty instance. This is not supported.'}
    c = command_for_name(cmd['cmd'])
    payload = cmd.get('payload') or {}
    payload['peer_id'] = peer_id
    async_id = str(cmd.get('async', ''))
    if async_id:
        payload['async_id'] = async_id
        if 'cancel_async' in cmd:
            active_async_requests.pop(async_id, None)
            c.cancel_async_request(boss, window, PayloadGetter(c, payload))
            return None
        active_async_requests[async_id] = monotonic()
        if len(active_async_requests) > 32:
            oldest = next(iter(active_async_requests))
            del active_async_requests[oldest]
    try:
        ans = c.response_from_kitty(boss, window, PayloadGetter(c, payload))
    except Exception:
        if no_response:  # don't report errors if --no-response was used
            return None
        raise
    if isinstance(ans, NoResponse):
        return None
    if isinstance(ans, AsyncResponse):
        return ans
    response: Dict[str, Any] = {'ok': True}
    if ans is not None:
        response['data'] = ans
    if not c.no_response and not no_response:
        return response
    return None


global_options_spec = partial('''\
--to
An address for the kitty instance to control. Corresponds to the address given
to the kitty instance via the :option:`kitty --listen-on` option or the
:opt:`listen_on` setting in :file:`kitty.conf`. If not specified, the
environment variable :envvar:`KITTY_LISTEN_ON` is checked. If that is also not
found, messages are sent to the controlling terminal for this process, i.e.
they will only work if this process is run within a kitty window.


--password
A password to use when contacting kitty. This will cause kitty to ask the user
for permission to perform the specified action, unless the password has been
accepted before or is pre-configured in :file:`kitty.conf`.


--password-file
completion=type:file relative:conf kwds:-
default=rc-pass
A file from which to read the password. Trailing whitespace is ignored. Relative
paths are resolved from the kitty configuration directory. Use - to read from STDIN.
Used if no :option:`kitty @ --password` is supplied. Defaults to checking for the
:file:`rc-pass` file in the kitty configuration directory.


--password-env
default=KITTY_RC_PASSWORD
The name of an environment variable to read the password from.
Used if no :option:`kitty @ --password-file` is supplied. Defaults
to checking the :envvar:`KITTY_RC_PASSWORD`.


--use-password
default=if-available
choices=if-available,never,always
If no password is available, kitty will usually just send the remote control command
without a password. This option can be used to force it to :code:`always` or :code:`never` use
the supplied password.
'''.format, appname=appname)


def encode_send(send: Any) -> bytes:
    es = ('@kitty-cmd' + json.dumps(send)).encode('ascii')
    return b'\x1bP' + es + b'\x1b\\'


class SocketClosed(EOFError):
    pass


class SocketIO:

    def __init__(self, to: str):
        self.family, self.address = parse_address_spec(to)[:2]

    def __enter__(self) -> None:
        import socket
        self.socket = socket.socket(self.family)
        self.socket.setblocking(True)
        self.socket.connect(self.address)

    def __exit__(self, *a: Any) -> None:
        import socket
        with suppress(OSError):  # on some OSes such as macOS the socket is already closed at this point
            self.socket.shutdown(socket.SHUT_RDWR)
        self.socket.close()

    def send(self, data: Union[bytes, Iterable[Union[str, bytes]]]) -> None:
        import socket
        with self.socket.makefile('wb') as out:
            if isinstance(data, bytes):
                out.write(data)
            else:
                for chunk in data:
                    if isinstance(chunk, str):
                        chunk = chunk.encode('utf-8')
                    out.write(chunk)
                    out.flush()
        self.socket.shutdown(socket.SHUT_WR)

    def simple_recv(self, timeout: float) -> bytes:
        dcs = re.compile(br'\x1bP@kitty-cmd([^\x1b]+)\x1b\\')
        self.socket.settimeout(timeout)
        st = monotonic()
        with self.socket.makefile('rb') as src:
            data = src.read()
        m = dcs.search(data)
        if m is None:
            if monotonic() - st > timeout:
                raise TimeoutError('Timed out while waiting to read cmd response')
            raise SocketClosed('Remote control connection was closed by kitty without any response being received')
        return bytes(m.group(1))


class RCIO(TTYIO):

    def simple_recv(self, timeout: float) -> bytes:
        ans: List[bytes] = []
        read_command_response(self.tty_fd, timeout, ans)
        return b''.join(ans)


def do_io(
    to: Optional[str], original_cmd: Dict[str, Any], no_response: bool, response_timeout: float, encrypter: 'CommandEncrypter'
) -> Dict[str, Any]:
    payload = original_cmd.get('payload')
    if not isinstance(payload, GeneratorType):
        send_data: Union[bytes, Iterator[bytes]] = encode_send(encrypter(original_cmd))
    else:
        def send_generator() -> Iterator[bytes]:
            assert payload is not None
            for chunk in payload:
                original_cmd['payload'] = chunk
                yield encode_send(encrypter(original_cmd))
        send_data = send_generator()

    io: Union[SocketIO, RCIO] = SocketIO(to) if to else RCIO()
    with io:
        io.send(send_data)
        if no_response:
            return {'ok': True}
        received = io.simple_recv(timeout=response_timeout)

    return cast(Dict[str, Any], json.loads(received.decode('ascii')))


cli_msg = (
    'Control {appname} by sending it commands. Set the'
    ' :opt:`allow_remote_control` option in :file:`kitty.conf` or use a password, for this'
    ' to work.'
).format(appname=appname)


def parse_rc_args(args: List[str]) -> Tuple[RCOptions, List[str]]:
    cmap = {name: command_for_name(name) for name in sorted(all_command_names())}
    cmds = (f'  :green:`{cmd.name}`\n    {cmd.short_desc}' for c, cmd in cmap.items())
    msg = cli_msg + (
            '\n\n:title:`Commands`:\n{cmds}\n\n'
            'You can get help for each individual command by using:\n'
            '{appname} @ :italic:`command` -h').format(appname=appname, cmds='\n'.join(cmds))
    return parse_args(args[1:], global_options_spec, 'command ...', msg, f'{appname} @', result_class=RCOptions)


def encode_as_base85(data: bytes) -> str:
    return base64.b85encode(data).decode('ascii')


class CommandEncrypter:

    encrypts: bool = True

    def __init__(self, pubkey: bytes, encryption_version: str, password: str) -> None:
        skey = EllipticCurveKey()
        self.secret = skey.derive_secret(pubkey)
        self.pubkey = skey.public
        self.encryption_version = encryption_version
        self.password = password

    def __call__(self, cmd: Dict[str, Any]) -> Dict[str, Any]:
        encrypter = AES256GCMEncrypt(self.secret)
        cmd['timestamp'] = time_ns()
        cmd['password'] = self.password
        raw = json.dumps(cmd).encode('utf-8')
        encrypted = encrypter.add_data_to_be_encrypted(raw, True)
        ans = {
            'version': version, 'iv': encode_as_base85(encrypter.iv), 'tag': encode_as_base85(encrypter.tag),
            'pubkey': encode_as_base85(self.pubkey), 'encrypted': encode_as_base85(encrypted),
        }
        if self.encryption_version != '1':
            ans['enc_proto'] = self.encryption_version
        return ans

    def adjust_response_timeout_for_password(self, response_timeout: float) -> float:
        return max(response_timeout, 120)


class NoEncryption(CommandEncrypter):

    encrypts: bool = False

    def __init__(self) -> None: ...

    def __call__(self, cmd: Dict[str, Any]) -> Dict[str, Any]:
        return cmd

    def adjust_response_timeout_for_password(self, response_timeout: float) -> float:
        return response_timeout


def create_basic_command(name: str, payload: Any = None, no_response: bool = False, is_asynchronous: bool = False) -> Dict[str, Any]:
    ans = {'cmd': name, 'version': version, 'no_response': no_response}
    if payload is not None:
        ans['payload'] = payload
    if is_asynchronous:
        from kitty.short_uuid import uuid4
        ans['async'] = uuid4()
    return ans


def send_response_to_client(data: Any = None, error: str = '', peer_id: int = 0, window_id: int = 0, async_id: str = '') -> None:
    ts = active_async_requests.pop(async_id, None)
    if ts is None:
        return
    if error:
        response: Dict[str, Union[bool, int, str]] = {'ok': False, 'error': error}
    else:
        response = {'ok': True, 'data': data}
    if peer_id > 0:
        send_data_to_peer(peer_id, encode_response_for_peer(response))
    elif window_id > 0:
        w = get_boss().window_id_map[window_id]
        if w is not None:
            w.send_cmd_response(response)


def get_password(opts: RCOptions) -> str:
    if opts.use_password == 'never':
        return ''
    ans = ''
    if opts.password:
        ans = opts.password
    if not ans and opts.password_file:
        if opts.password_file == '-':
            if sys.stdin.isatty():
                from getpass import getpass
                ans = getpass()
            else:
                ans = sys.stdin.read().rstrip()
                try:
                    tty_fd = os.open(os.ctermid(), os.O_RDONLY | os.O_CLOEXEC)
                except OSError:
                    pass
                else:
                    with open(tty_fd, closefd=True):
                        os.dup2(tty_fd, sys.stdin.fileno())
        else:
            try:
                with open(resolve_custom_file(opts.password_file)) as f:
                    ans = f.read().rstrip()
            except OSError:
                pass
    if not ans and opts.password_env:
        ans = os.environ.get(opts.password_env, '')
    if not ans and opts.use_password == 'always':
        raise SystemExit('No password was found')
    if ans and len(ans) > 1024:
        raise SystemExit('Specified password is too long')
    return ans


def get_pubkey() -> Tuple[str, bytes]:
    raw = os.environ.get('KITTY_PUBLIC_KEY', '')
    if not raw:
        raise SystemExit('Password usage requested but KITTY_PUBLIC_KEY environment variable is not available')
    version, pubkey = raw.split(':', 1)
    if version != RC_ENCRYPTION_PROTOCOL_VERSION:
        raise SystemExit('KITTY_PUBLIC_KEY has unknown version, if you are running on a remote system, update kitty on this system')
    from base64 import b85decode
    return version, b85decode(pubkey)


def main(args: List[str]) -> None:
    global_opts, items = parse_rc_args(args)
    password = get_password(global_opts)
    if password:
        encryption_version, pubkey = get_pubkey()
        encrypter = CommandEncrypter(pubkey, encryption_version, password)
    else:
        encrypter = NoEncryption()

    if not items:
        from kitty.shell import main as smain
        smain(global_opts, encrypter)
        return
    cmd = items[0]
    try:
        c = command_for_name(cmd)
    except KeyError:
        raise SystemExit('{} is not a known command. Known commands are: {}'.format(
            emph(cmd), ', '.join(x.replace('_', '-') for x in all_command_names())))
    opts, items = parse_subcommand_cli(c, items)
    try:
        payload = c.message_to_kitty(global_opts, opts, items)
    except ParsingOfArgsFailed as err:
        exit(str(err))
    no_response = c.no_response
    if hasattr(opts, 'no_response'):
        no_response = opts.no_response
    response_timeout = c.response_timeout
    if hasattr(opts, 'response_timeout'):
        response_timeout = opts.response_timeout
    response_timeout = encrypter.adjust_response_timeout_for_password(response_timeout)
    send = create_basic_command(cmd, payload=payload, no_response=no_response, is_asynchronous=c.is_asynchronous)
    listen_on_from_env = False
    if not global_opts.to and 'KITTY_LISTEN_ON' in os.environ:
        global_opts.to = os.environ['KITTY_LISTEN_ON']
        listen_on_from_env = False
    if global_opts.to:
        try:
            parse_address_spec(global_opts.to)
        except Exception:
            msg = f'Invalid listen on address: {global_opts.to}'
            if listen_on_from_env:
                msg += '. The KITTY_LISTEN_ON environment variable is set incorrectly'
            exit(msg)
    import socket
    try:
        response = do_io(global_opts.to, send, no_response, response_timeout, encrypter)
    except (TimeoutError, socket.timeout):
        send.pop('payload', None)
        send['cancel_async'] = True
        try:
            do_io(global_opts.to, send, True, 10, encrypter)
        except KeyboardInterrupt:
            sys.excepthook = lambda *a: print('Interrupted by user', file=sys.stderr)
            raise
        except SocketClosed as e:
            raise SystemExit(str(e))
        raise SystemExit(f'Timed out after {response_timeout} seconds waiting for response from kitty')
    except KeyboardInterrupt:
        sys.excepthook = lambda *a: print('Interrupted by user', file=sys.stderr)
        raise
    except FileNotFoundError:
        raise SystemExit(f'No listen on socket found at: {global_opts.to}')
    except SocketClosed as e:
        raise SystemExit(str(e))
    if no_response:
        return
    if not response.get('ok'):
        if response.get('tb'):
            print(response['tb'], file=sys.stderr)
        raise SystemExit(response['error'])
    data = response.get('data')
    if data is not None:
        if c.string_return_is_error and isinstance(data, str):
            raise SystemExit(data)
        print(data)
