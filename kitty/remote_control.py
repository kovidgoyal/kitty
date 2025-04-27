#!/usr/bin/env python
# License: GPL v3 Copyright: 2018, Kovid Goyal <kovid at kovidgoyal.net>

import base64
import json
import os
import re
import sys
from collections.abc import Iterable, Iterator, Sequence
from contextlib import suppress
from functools import lru_cache, partial
from time import time_ns
from types import GeneratorType
from typing import (
    TYPE_CHECKING,
    Any,
    Optional,
    cast,
)

from .cli import parse_args
from .cli_stub import RCOptions
from .constants import RC_ENCRYPTION_PROTOCOL_VERSION, appname, version
from .fast_data_types import (
    AES256GCMDecrypt,
    AES256GCMEncrypt,
    EllipticCurveKey,
    get_boss,
    get_options,
    monotonic,
    read_command_response,
    send_data_to_peer,
)
from .rc.base import NoResponse, PayloadGetter, all_command_names, command_for_name
from .types import AsyncResponse
from .typing_compat import BossType, WindowType
from .utils import TTYIO, log_error, parse_address_spec, resolve_custom_file

active_async_requests: dict[str, float] = {}
active_streams: dict[str, str] = {}
if TYPE_CHECKING:
    from .window import Window


def encode_response_for_peer(response: Any) -> bytes:
    return b'\x1bP@kitty-cmd' + json.dumps(response).encode('utf-8') + b'\x1b\\'


def parse_cmd(serialized_cmd: memoryview, encryption_key: EllipticCurveKey) -> dict[str, Any]:
    # See https://github.com/python/cpython/issues/74379 for why we cant use
    # memoryview directly :((
    try:
        pcmd = json.loads(bytes(serialized_cmd))
    except Exception:
        log_error('Failed to parse JSON payload of remote command, ignoring it')
        return {}
    if not isinstance(pcmd, dict) or 'version' not in pcmd:
        log_error('JSON payload of remote command is invalid, must be an object with a version field')
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

    def __call__(self, pcmd: dict[str, Any], window: Optional['Window'], from_socket: bool, extra_data: dict[str, Any]) -> bool | None:
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


def remote_control_allowed(
    pcmd: dict[str, Any], remote_control_passwords: dict[str, Sequence[str]] | None,
    window: Optional['Window'], extra_data: dict[str, Any]
) -> bool:
    if not remote_control_passwords:
        return True
    pw = pcmd.get('password', '')
    auth_items = remote_control_passwords.get(pw)
    if pw == '!':
        auth_items = None
    if auth_items is None:
        if '!' in remote_control_passwords:
            raise PermissionError()
        return False
    from .remote_control import password_authorizer
    pa = password_authorizer(auth_items)
    if not pa.is_cmd_allowed(pcmd, window, False, extra_data):
        raise PermissionError()
    return True


class PasswordAuthorizer:

    def __init__(self, auth_items: Iterable[str]) -> None:
        self.command_patterns = []
        self.function_checkers = []
        self.name = ''
        for item in auth_items:
            if item.endswith('.py'):
                path = os.path.abspath(resolve_custom_file(item))
                self.function_checkers.append(is_cmd_allowed_loader(path))
            else:
                self.command_patterns.append(fnmatch_pattern(item))

    def is_cmd_allowed(self, pcmd: dict[str, Any], window: Optional['Window'], from_socket: bool, extra_data: dict[str, Any]) -> bool:
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
def password_authorizer(auth_items: frozenset[str]) -> PasswordAuthorizer:
    return PasswordAuthorizer(auth_items)


user_password_allowed: dict[str, bool] = {}


def is_cmd_allowed(pcmd: dict[str, Any], window: Optional['Window'], from_socket: bool, extra_data: dict[str, Any]) -> bool | None:
    sid = pcmd.get('stream_id', '')
    if sid and active_streams.get(sid, '') == pcmd['cmd']:
        return True
    if 'cancel_async' in pcmd and pcmd.get('async_id'):
        # we allow these without authentication as they are sent on error
        # conditions and we can't have users prompted for these. The worst side
        # effect of a malicious cancel_async request is that it can prevent
        # another async request from getting a result, if it knows the async_id
        # of that request.
        return True
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


def close_active_stream(stream_id: str) -> None:
    active_streams.pop(stream_id, None)


def handle_cmd(
    boss: BossType, window: WindowType | None, cmd: dict[str, Any], peer_id: int, self_window: WindowType | None
) -> dict[str, Any] | None | AsyncResponse:
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
    stream_id = str(cmd.get('stream_id', ''))
    stream = bool(cmd.get('stream', False))
    if (stream or stream_id) and not c.reads_streaming_data:
        return {'ok': False, 'error': 'Streaming send of data is not supported for this command'}
    if stream_id:
        payload['stream_id'] = stream_id
        active_streams[stream_id] = cmd['cmd']
        if len(active_streams) > 32:
            oldest = next(iter(active_streams))
            del active_streams[oldest]
    if async_id:
        payload['async_id'] = async_id
        if 'cancel_async' in cmd:
            active_async_requests.pop(async_id, None)
            c.cancel_async_request(boss, self_window or window, PayloadGetter(c, payload))
            return None
        active_async_requests[async_id] = monotonic()
        if len(active_async_requests) > 32:
            oldest = next(iter(active_async_requests))
            del active_async_requests[oldest]
    try:
        ans = c.response_from_kitty(boss, self_window or window, PayloadGetter(c, payload))
    except Exception:
        if no_response:  # don't report errors if --no-response was used
            return None
        raise
    if isinstance(ans, NoResponse):
        return None
    if isinstance(ans, AsyncResponse):
        if stream:
            return {'ok': True, 'stream': True}
        return ans
    response: dict[str, Any] = {'ok': True}
    if ans is not None:
        response['data'] = ans
    if not no_response:
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
accepted before or is pre-configured in :file:`kitty.conf`. To use a blank password
specify :option:`kitten @ --use-password` as :code:`always`.


--password-file
completion=type:file relative:conf kwds:-
default=rc-pass
A file from which to read the password. Trailing whitespace is ignored. Relative
paths are resolved from the kitty configuration directory. Use - to read from STDIN.
Use :code:`fd:num` to read from the file descriptor :code:`num`.
Used if no :option:`kitten @ --password` is supplied. Defaults to checking for the
:file:`rc-pass` file in the kitty configuration directory.


--password-env
default=KITTY_RC_PASSWORD
The name of an environment variable to read the password from.
Used if no :option:`kitten @ --password-file` is supplied. Defaults
to checking the environment variable :envvar:`KITTY_RC_PASSWORD`.


--use-password
default=if-available
choices=if-available,never,always
If no password is available, kitty will usually just send the remote control command
without a password. This option can be used to force it to :code:`always` or :code:`never` use
the supplied password. If set to always and no password is provided, the blank password is used.
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

    def send(self, data: bytes | Iterable[str | bytes]) -> None:
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
        ans: list[bytes] = []
        read_command_response(self.tty_fd, timeout, ans)
        return b''.join(ans)


def do_io(
    to: str | None, original_cmd: dict[str, Any], no_response: bool, response_timeout: float, encrypter: 'CommandEncrypter'
) -> dict[str, Any]:
    payload = original_cmd.get('payload')
    if not isinstance(payload, GeneratorType):
        send_data: bytes | Iterator[bytes] = encode_send(encrypter(original_cmd))
    else:
        def send_generator() -> Iterator[bytes]:
            assert payload is not None
            for chunk in payload:
                original_cmd['payload'] = chunk
                yield encode_send(encrypter(original_cmd))
        send_data = send_generator()

    io: SocketIO | RCIO = SocketIO(to) if to else RCIO()
    with io:
        io.send(send_data)
        if no_response:
            return {'ok': True}
        received = io.simple_recv(timeout=response_timeout)

    return cast(dict[str, Any], json.loads(received.decode('ascii')))


cli_msg = (
    'Control {appname} by sending it commands. Set the'
    ' :opt:`allow_remote_control` option in :file:`kitty.conf` or use a password, for this'
    ' to work.'
).format(appname=appname)


def parse_rc_args(args: list[str]) -> tuple[RCOptions, list[str]]:
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

    def __call__(self, cmd: dict[str, Any]) -> dict[str, Any]:
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

    def __call__(self, cmd: dict[str, Any]) -> dict[str, Any]:
        return cmd

    def adjust_response_timeout_for_password(self, response_timeout: float) -> float:
        return response_timeout


def create_basic_command(name: str, payload: Any = None, no_response: bool = False, is_asynchronous: bool = False) -> dict[str, Any]:
    ans = {'cmd': name, 'version': version, 'no_response': no_response}
    if payload is not None:
        ans['payload'] = payload
    if is_asynchronous:
        from kitty.short_uuid import uuid4
        ans['async'] = uuid4()
    return ans


def send_response_to_client(data: Any = None, error: str = '', peer_id: int = 0, window_id: int = 0, async_id: str = '') -> None:
    if active_async_requests.pop(async_id, None) is None:
        return
    if error:
        response: dict[str, bool | int | str] = {'ok': False, 'error': error}
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


def get_pubkey() -> tuple[str, bytes]:
    raw = os.environ.get('KITTY_PUBLIC_KEY', '')
    if not raw:
        raise SystemExit('Password usage requested but KITTY_PUBLIC_KEY environment variable is not available')
    version, pubkey = raw.split(':', 1)
    if version != RC_ENCRYPTION_PROTOCOL_VERSION:
        raise SystemExit('KITTY_PUBLIC_KEY has unknown version, if you are running on a remote system, update kitty on this system')
    from base64 import b85decode
    return version, b85decode(pubkey)
