#!/usr/bin/env python
# License: GPL v3 Copyright: 2018, Kovid Goyal <kovid at kovidgoyal.net>

import base64
import hmac
import json
import os
import re
import sys
from collections.abc import Iterable, Iterator, Sequence
from contextlib import suppress
from functools import lru_cache, partial
from heapq import heappop, heappush
from time import time_ns
from types import GeneratorType
from typing import TYPE_CHECKING, Any, NamedTuple, Optional, TypeVar, cast

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
from .utils import TTYIO, log_error, parse_address_spec, resolve_custom_file, shlex_split

active_async_requests: dict[str, float] = {}


class ActiveStream(NamedTuple):
    cmd: str
    # The origin of the request that opened the stream: the socket peer or the
    # window the request was received from
    peer_id: int
    window_id: int
    # The parts of the request that must be the same for every chunk of the stream
    fingerprint: str


active_streams: dict[str, ActiveStream] = {}
T = TypeVar('T')
if TYPE_CHECKING:
    from .window import Window


def encode_response_for_peer(response: Any) -> bytes:
    return b'\x1bP@kitty-cmd' + json.dumps(response).encode('utf-8') + b'\x1b\\'


# Encrypted commands are accepted if their timestamp is within this many
# nanoseconds of the current time
ENCRYPTED_CMD_MAX_AGE = 5 * 60 * 10**9
# Upper bound on the number of encrypted commands remembered for replay
# detection. Every chunk of a streamed command is a separate encrypted command.
MAX_SEEN_ENCRYPTED_CMDS = 1 << 16


class SeenEncryptedCommands:
    """Remembers recently accepted encrypted commands so that they cannot be
    replayed while their timestamps are still acceptable."""

    def __init__(self) -> None:
        self.seen: set[bytes] = set()
        self.expiry_heap: list[tuple[int, bytes]] = []

    def clear(self) -> None:
        self.seen.clear()
        self.expiry_heap.clear()

    def check_and_add(self, key: bytes, timestamp: int, now: int) -> str:
        "Return an error message if the command must be rejected, otherwise remember it and return an empty string"
        heap = self.expiry_heap
        while heap and heap[0][0] < now:
            self.seen.discard(heappop(heap)[1])
        if key in self.seen:
            return 'Ignoring encrypted rc command that has already been received. Could be an attempt at a replay attack.'
        if len(self.seen) >= MAX_SEEN_ENCRYPTED_CMDS:
            # Forgetting unexpired commands would allow them to be replayed, so refuse new ones instead
            return 'Ignoring encrypted rc command as too many encrypted commands have been received recently.'
        self.seen.add(key)
        heappush(heap, (timestamp + ENCRYPTED_CMD_MAX_AGE, key))
        return ''


seen_encrypted_commands = SeenEncryptedCommands()


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
            return {}
        iv, tag = base64.b85decode(pcmd['iv']), base64.b85decode(pcmd['tag'])
        d = AES256GCMDecrypt(encryption_key.derive_secret(base64.b85decode(pubkey)), iv, tag)
        data = d.add_data_to_be_decrypted(base64.b85decode(pcmd['encrypted']), True)
        pcmd = json.loads(data)
        if not isinstance(pcmd, dict) or 'version' not in pcmd:
            return {}
        timestamp = pcmd.pop('timestamp', None)
        if not isinstance(timestamp, int) or isinstance(timestamp, bool):
            log_error('Ignoring encrypted rc command without a valid timestamp')
            return {}
        now = time_ns()
        delta = now - timestamp
        if abs(delta) > ENCRYPTED_CMD_MAX_AGE:
            log_error(
                f'Ignoring encrypted rc command with timestamp {delta / 1e9:.1f} seconds from now.'
                ' Could be an attempt at a replay attack or an incorrect clock on a remote machine.'
            )
            return {}
        # The GCM tag authenticates the ciphertext, so an attacker cannot
        # change it without knowing the key, while a replayed command has
        # the same iv and tag as the original.
        if err := seen_encrypted_commands.check_and_add(iv + tag, timestamp, now):
            log_error(err)
            return {}
        if not isinstance(pcmd.get('password', ''), str):
            log_error('Ignoring encrypted rc command with a password that is not a string')
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


def password_as_bytes(pw: str) -> bytes:
    # surrogatepass as JSON can contain lone surrogates
    return pw.encode('utf-8', 'surrogatepass')


def constant_time_lookup(passwords: dict[str, T], pw: str) -> T | None:
    # Compare as bytes, since hmac.compare_digest() raises for str with non-ASCII characters
    result = None
    c = hmac.compare_digest
    q = password_as_bytes(pw)
    for k, v in passwords.items():
        if c(password_as_bytes(k), q):
            result = v
    return result


def remote_control_allowed(
    pcmd: dict[str, Any], remote_control_passwords: dict[str, Sequence[str]] | None, window: Optional['Window'], extra_data: dict[str, Any]
) -> bool:
    if not remote_control_passwords:
        return True
    pw = pcmd.get('password', '')
    auth_items = constant_time_lookup(remote_control_passwords, pw)
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


def kitten_password_restrictions(remote_control_password: str | bool) -> tuple[str, ...]:
    # A string is a space separated list of allowed actions, same as for
    # remote_control_password in kitty.conf. It must not be passed as is to
    # PasswordAuthorizer as that would treat every character as a pattern.
    if isinstance(remote_control_password, str):
        return tuple(x for x in shlex_split(remote_control_password) if x)
    return ()


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


def is_cmd_allowed(pcmd: dict[str, Any], window: Optional['Window'], from_socket: bool, extra_data: dict[str, Any], peer_id: int = 0) -> bool | None:
    if is_stream_continuation(pcmd, window, peer_id):
        # The request that opened the stream was authorized
        return True
    if 'cancel_async' in pcmd and str(pcmd.get('async', '')):
        # we allow these without authentication as they are sent on error
        # conditions and we can't have users prompted for these. The worst side
        # effect of a malicious cancel_async request is that it can prevent
        # another async request from getting a result or cancel it, if it knows
        # the async_id of that request. Implementations of
        # cancel_async_request() must therefore only cancel the request with
        # the specified async_id. The condition here must match the one in
        # handle_cmd() exactly, so that these requests are guaranteed to only
        # cancel and never execute the command.
        return True
    pw = pcmd.get('password', '')
    if not pw:
        auth_items = get_options().remote_control_password.get('')
        if auth_items is None:
            return False
        pa = password_authorizer(auth_items)
        return pa.is_cmd_allowed(pcmd, window, from_socket, extra_data)
    q = constant_time_lookup(user_password_allowed, pw)
    if q is not None:
        return q
    auth_items = constant_time_lookup(get_options().remote_control_password, pw)
    if auth_items is None:
        return None
    pa = password_authorizer(auth_items)
    return pa.is_cmd_allowed(pcmd, window, from_socket, extra_data)


def set_user_password_allowed(pwd: str, allowed: bool = True) -> None:
    user_password_allowed[pwd] = allowed


def stream_fingerprint(pcmd: dict[str, Any]) -> str:
    # Every chunk of a stream repeats the request with only the data changed,
    # so everything else must match the authorized request that opened the stream
    payload = pcmd.get('payload') or {}
    if isinstance(payload, dict):
        # peer_id, stream_id and async_id are added to the payload by handle_cmd()
        payload = {k: v for k, v in payload.items() if k not in ('data', 'peer_id', 'stream_id', 'async_id')}
    return json.dumps({'cmd': pcmd.get('cmd'), 'async': str(pcmd.get('async', '')), 'payload': payload}, sort_keys=True)


def window_id_of(window: WindowType | None) -> int:
    return 0 if window is None else window.id


def is_stream_continuation(pcmd: dict[str, Any], window: WindowType | None, peer_id: int) -> bool:
    sid = str(pcmd.get('stream_id', ''))
    s = active_streams.get(sid) if sid else None
    return (
        s is not None
        and s.cmd == pcmd.get('cmd')
        and s.peer_id == peer_id
        and s.window_id == window_id_of(window)
        and s.fingerprint == stream_fingerprint(pcmd)
    )


def register_active_stream(stream_id: str, pcmd: dict[str, Any], window: WindowType | None, peer_id: int) -> None:
    active_streams[stream_id] = ActiveStream(pcmd['cmd'], peer_id, window_id_of(window), stream_fingerprint(pcmd))
    while len(active_streams) > 32:
        abort_active_stream(next(iter(active_streams)))


def close_active_stream(stream_id: str) -> None:
    active_streams.pop(stream_id, None)


def abort_active_stream(stream_id: str) -> None:
    # Close the stream and discard any data already received on it
    s = active_streams.pop(stream_id, None)
    if s is not None:
        command_for_name(s.cmd).stream_in_flight.discard(stream_id)


def abort_active_streams_from(peer_id: int = 0, window_id: int = 0) -> None:
    # Called when the socket peer or window that opened streams goes away, as
    # the streams can no longer be completed
    for sid in [sid for sid, s in active_streams.items() if s.peer_id == peer_id and s.window_id == window_id]:
        abort_active_stream(sid)


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
    if async_id:
        payload['async_id'] = async_id
        if 'cancel_async' in cmd:
            active_async_requests.pop(async_id, None)
            # Cancellations are allowed without authentication, so only let
            # them abort a stream opened from the same origin
            s = active_streams.get(stream_id) if stream_id else None
            if s is not None and s.peer_id == peer_id and s.window_id == window_id_of(window):
                abort_active_stream(stream_id)
            c.cancel_async_request(boss, self_window or window, PayloadGetter(c, payload))
            return None
        active_async_requests[async_id] = monotonic()
        if len(active_async_requests) > 32:
            oldest = next(iter(active_async_requests))
            del active_async_requests[oldest]
    if stream_id:
        # Register the stream only after cancellations have returned, as they
        # are allowed without authentication and requests on a registered
        # stream are allowed without authentication as well
        register_active_stream(stream_id, cmd, window, peer_id)
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


global_options_spec = partial(
    """\
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
""".format,
    appname=appname,
)


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
        dcs = re.compile(rb'\x1bP@kitty-cmd([^\x1b]+)\x1b\\')
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


def do_io(to: str | None, original_cmd: dict[str, Any], no_response: bool, response_timeout: float, encrypter: 'CommandEncrypter') -> dict[str, Any]:
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
    'Control {appname} by sending it commands. Set the :opt:`allow_remote_control` option in :file:`kitty.conf` or use a password, for this to work.'
).format(appname=appname)


def parse_rc_args(args: list[str]) -> tuple[RCOptions, list[str]]:
    cmap = {name: command_for_name(name) for name in sorted(all_command_names())}
    cmds = (f'  :green:`{cmd.name}`\n    {cmd.short_desc}' for c, cmd in cmap.items())
    msg = cli_msg + ('\n\n:title:`Commands`:\n{cmds}\n\nYou can get help for each individual command by using:\n{appname} @ :italic:`command` -h').format(
        appname=appname, cmds='\n'.join(cmds)
    )
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
            'version': version,
            'iv': encode_as_base85(encrypter.iv),
            'tag': encode_as_base85(encrypter.tag),
            'pubkey': encode_as_base85(self.pubkey),
            'encrypted': encode_as_base85(encrypted),
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
        w = get_boss().window_id_map.get(window_id)
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
