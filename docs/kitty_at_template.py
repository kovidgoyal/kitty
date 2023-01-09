#!/usr/bin/env python
# License: GPLv3 Copyright: 2022, Kovid Goyal <kovid at kovidgoyal.net>
import argparse
import base64
import hashlib
import json
import os
import sys
import termios
import time
import tty
from contextlib import contextmanager
from ctypes import CDLL, POINTER, byref, c_char_p, c_int, c_size_t, c_void_p, create_string_buffer
from ctypes.util import find_library

_plat = sys.platform.lower()
is_macos: bool = 'darwin' in _plat


def build_crypto_tools():  # {{{
    class EVP_PKEY_POINTER(c_void_p):

        algorithm = 0

        def __del__(self):
            EVP_PKEY_free(self)

        @property
        def public(self):
            sz = c_size_t(0)
            EVP_PKEY_get_raw_public_key(self, None, byref(sz))
            buf = create_string_buffer(sz.value)
            EVP_PKEY_get_raw_public_key(self, buf, byref(sz))
            return buf.raw

        def derive_secret(self, pubkey):
            pubkey = EVP_PKEY_new_raw_public_key(self.algorithm, None, pubkey, len(pubkey))
            ctx = EVP_PKEY_CTX_new(self, None)
            EVP_PKEY_derive_init(ctx)
            EVP_PKEY_derive_set_peer(ctx, pubkey)
            sz = c_size_t(0)
            EVP_PKEY_derive(ctx, None, byref(sz))
            buf = create_string_buffer(sz.value)
            EVP_PKEY_derive(ctx, buf, byref(sz))
            return hashlib.sha256(buf.raw).digest()

    class EVP_PKEY_CTX_POINTER(c_void_p):

        def __del__(self):
            EVP_PKEY_CTX_free(self)

    class EVP_CIPHER_CTX_POINTER(c_void_p):

        def __del__(self):
            EVP_CIPHER_CTX_free(self)

    class EVP_CIPHER_POINTER(c_void_p):
        pass

    cl = find_library('crypto')
    if not cl:
        raise SystemExit('Failed to find libcrypto on your system, make sure OpenSSL is installed')
    crypto = CDLL(cl)
    libc = CDLL(None)

    def create_crypto_func(name, *argtypes, restype=c_int, int_return_ok=lambda x: x == 1):

        impl = getattr(crypto, name)
        impl.restype = restype
        impl.argtypes = argtypes

        def func(*a):
            res = impl(*a)
            if restype is c_int:
                if not int_return_ok(res):
                    print('Call to', name, 'failed with return code:', res, file=sys.stderr)
                    abort_on_openssl_error()
            elif restype is not None and issubclass(restype, c_void_p):
                if res.value is None:
                    print('Call to', name, 'failed with NULL return', file=sys.stderr)
                    abort_on_openssl_error()
            return res
        return func

    OBJ_txt2nid = create_crypto_func('OBJ_txt2nid', c_char_p, int_return_ok=bool)
    EVP_PKEY_CTX_new_id = create_crypto_func('EVP_PKEY_CTX_new_id', c_int, c_void_p, restype=EVP_PKEY_CTX_POINTER)
    EVP_PKEY_CTX_new = create_crypto_func('EVP_PKEY_CTX_new', EVP_PKEY_POINTER, c_void_p, restype=EVP_PKEY_CTX_POINTER)
    EVP_PKEY_keygen_init = create_crypto_func('EVP_PKEY_keygen_init', EVP_PKEY_CTX_POINTER)
    EVP_PKEY_keygen = create_crypto_func('EVP_PKEY_keygen', EVP_PKEY_CTX_POINTER, POINTER(EVP_PKEY_POINTER))
    ERR_print_errors_fp = create_crypto_func('ERR_print_errors_fp', c_void_p, restype=None)
    EVP_PKEY_free = create_crypto_func('EVP_PKEY_free', EVP_PKEY_POINTER, restype=None)
    EVP_PKEY_CTX_free = create_crypto_func('EVP_PKEY_CTX_free', EVP_PKEY_CTX_POINTER, restype=None)
    EVP_PKEY_get_raw_public_key = create_crypto_func('EVP_PKEY_get_raw_public_key', EVP_PKEY_POINTER, c_char_p, POINTER(c_size_t))
    EVP_PKEY_new_raw_public_key = create_crypto_func('EVP_PKEY_new_raw_public_key', c_int, c_void_p, c_char_p, c_size_t, restype=EVP_PKEY_POINTER)
    EVP_PKEY_derive_init = create_crypto_func('EVP_PKEY_derive_init', EVP_PKEY_CTX_POINTER)
    EVP_PKEY_derive_set_peer = create_crypto_func('EVP_PKEY_derive_set_peer', EVP_PKEY_CTX_POINTER, EVP_PKEY_POINTER)
    EVP_PKEY_derive = create_crypto_func('EVP_PKEY_derive', EVP_PKEY_CTX_POINTER, c_char_p, POINTER(c_size_t))
    EVP_CIPHER_CTX_free = create_crypto_func('EVP_CIPHER_CTX_free', EVP_CIPHER_CTX_POINTER, restype=None)
    EVP_get_cipherbyname = create_crypto_func('EVP_get_cipherbyname', c_char_p, restype=EVP_CIPHER_POINTER)
    EVP_CIPHER_key_length = create_crypto_func('EVP_CIPHER_key_length', EVP_CIPHER_POINTER, int_return_ok=bool)
    EVP_CIPHER_iv_length = create_crypto_func('EVP_CIPHER_iv_length', EVP_CIPHER_POINTER, int_return_ok=bool)
    EVP_CIPHER_CTX_block_size = create_crypto_func('EVP_CIPHER_CTX_block_size', EVP_CIPHER_CTX_POINTER, int_return_ok=bool)
    EVP_CIPHER_CTX_new = create_crypto_func('EVP_CIPHER_CTX_new', restype=EVP_CIPHER_CTX_POINTER)
    EVP_EncryptInit_ex = create_crypto_func('EVP_EncryptInit_ex', EVP_CIPHER_CTX_POINTER, EVP_CIPHER_POINTER, c_void_p, c_char_p, c_char_p)
    EVP_EncryptUpdate = create_crypto_func('EVP_EncryptUpdate', EVP_CIPHER_CTX_POINTER, c_char_p, POINTER(c_int), c_char_p, c_int)
    EVP_EncryptFinal_ex = create_crypto_func('EVP_EncryptFinal_ex', EVP_CIPHER_CTX_POINTER, c_char_p, POINTER(c_int))
    EVP_CIPHER_CTX_ctrl = create_crypto_func('EVP_CIPHER_CTX_ctrl', EVP_CIPHER_CTX_POINTER, c_int, c_int, c_char_p)
    try:
        EVP_CIPHER_CTX_tag_length = create_crypto_func('EVP_CIPHER_CTX_tag_length', EVP_CIPHER_CTX_POINTER, int_return_ok=bool)
    except AttributeError:  # need openssl >= 3
        def EVP_CIPHER_CTX_tag_length(cipher):
            return 16
    EVP_CTRL_AEAD_GET_TAG, EVP_CTRL_AEAD_SET_TAG = 0x10, 0x11  # these are defines in the header dont know how to get them programmatically
    EVP_CTRL_AEAD_SET_TAG

    def abort_on_openssl_error():
        stderr = c_void_p.in_dll(libc, 'stderr')
        ERR_print_errors_fp(stderr)
        raise SystemExit(1)

    def elliptic_curve_keypair(algorithm='X25519'):
        nid = OBJ_txt2nid(algorithm.encode())
        pctx = EVP_PKEY_CTX_new_id(nid, None)
        EVP_PKEY_keygen_init(pctx)
        key = EVP_PKEY_POINTER()
        EVP_PKEY_keygen(pctx, byref(key))
        key.algorithm = nid
        return key

    def encrypt(plaintext, symmetric_key, algorithm='aes-256-gcm'):
        cipher = EVP_get_cipherbyname(algorithm.encode())
        if len(symmetric_key) != EVP_CIPHER_key_length(cipher):
            raise KeyError(f'The symmetric key has length {len(symmetric_key)} != {EVP_CIPHER_key_length(cipher)} needed for {algorithm}')
        ctx = EVP_CIPHER_CTX_new()
        iv = os.urandom(EVP_CIPHER_iv_length(cipher))
        EVP_EncryptInit_ex(ctx, cipher, None, symmetric_key, iv)
        bs = EVP_CIPHER_CTX_block_size(ctx)
        ciphertext = create_string_buffer(len(plaintext) + 2 * bs)
        outlen = c_int(len(ciphertext))
        EVP_EncryptUpdate(ctx, ciphertext, byref(outlen), plaintext, len(plaintext))
        ans = ciphertext[:outlen.value]
        outlen = c_int(len(ciphertext))
        EVP_EncryptFinal_ex(ctx, ciphertext, byref(outlen))
        if outlen.value:
            ans += ciphertext[:outlen.value]
        tag = create_string_buffer(EVP_CIPHER_CTX_tag_length(cipher))
        EVP_CIPHER_CTX_ctrl(ctx, EVP_CTRL_AEAD_GET_TAG, len(tag), tag)
        return iv, ans, tag.raw
    return elliptic_curve_keypair, encrypt
# }}}


# utils {{{
def encrypt_cmd(cmd, password, pubkey=None):
    elliptic_curve_keypair, encrypt = build_crypto_tools()
    if pubkey is None:
        pubkey = os.environ['KITTY_PUBLIC_KEY']
        v, d = pubkey.split(':', 1)
        if v != '1':
            raise SystemExit(f'Unsupported encryption protocol: {v}')
        pubkey = base64.b85decode(d)
    k = elliptic_curve_keypair()
    sk = k.derive_secret(pubkey)
    cmd['timestamp'] = time.time_ns()
    cmd['password'] = password
    data = json.dumps(cmd).encode()
    iv, encrypted, tag = encrypt(data, sk)

    def e(x):
        return base64.b85encode(x).decode('ascii')

    return {
        'encrypted': e(encrypted), 'iv': e(iv), 'tag': e(tag), 'pubkey': e(k.public), 'version': cmd['version']
    }


@contextmanager
def raw_mode(fd):
    old = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        yield
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)


def config_dir():
    if 'KITTY_CONFIG_DIRECTORY' in os.environ:
        return os.path.abspath(os.path.expanduser(os.environ['KITTY_CONFIG_DIRECTORY']))
    locations = []
    if 'XDG_CONFIG_HOME' in os.environ:
        locations.append(os.path.abspath(os.path.expanduser(os.environ['XDG_CONFIG_HOME'])))
    locations.append(os.path.expanduser('~/.config'))
    if is_macos:
        locations.append(os.path.expanduser('~/Library/Preferences'))
    for loc in filter(None, os.environ.get('XDG_CONFIG_DIRS', '').split(os.pathsep)):
        locations.append(os.path.abspath(os.path.expanduser(loc)))
    for loc in locations:
        if loc:
            q = os.path.join(loc, 'kitty')
            if os.access(q, os.W_OK) and os.path.exists(os.path.join(q, 'kitty.conf')):
                return q
    for loc in locations:
        if loc:
            q = os.path.join(loc, 'kitty')
            if os.path.isdir(q) and os.access(q, os.W_OK):
                return q
    return ''


def resolve_custom_file(path):
    path = os.path.expanduser(path)
    path = os.path.expandvars(path)
    if not os.path.isabs(path):
        cdir = config_dir()
        if cdir:
            path = os.path.join(cdir, path)
    return path


def get_password(opts):
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
# }}}


arg_parser = argparse.ArgumentParser(prog='kitty@', description='Control kitty remotely.')
arg_parser.add_argument('--password', default='', help='''\
A password to use when contacting kitty. This will cause kitty to ask the user
for permission to perform the specified action, unless the password has been
accepted before or is pre-configured in kitty.conf''')
arg_parser.add_argument('--password-file', default='rc-pass', help='''\
A file from which to read the password. Trailing whitespace is ignored. Relative
paths are resolved from the kitty configuration directory. Use - to read from STDIN.
Used if no --password is supplied. Defaults to checking for the
rc-pass file in the kitty configuration directory.''')
arg_parser.add_argument('--password-env', default='KITTY_RC_PASSWORD', help='''\
The name of an environment variable to read the password from.
Used if no --password-file is supplied. Defaults to checking the KITTY_RC_PASSWORD.''')
arg_parser.add_argument('--use-password', default='if-available', choices=('if-available', 'always', 'never'), help='''\
If no password is available, kitty will usually just send the remote control command
without a password. This option can be used to force it to always or never use
the supplied password.''')

args = arg_parser.parse_args()


def populate_cmd(cmd):
    raise NotImplementedError()


password = get_password(args)
cmd = {'version': [0, 20, 0]}  # use a random version that's fairly old
populate_cmd(cmd)
if password:
    encrypt_cmd(cmd, password)

# cmd = {'version': [0, 14, 2], 'cmd': 'ls'}
# cmd = encrypt_cmd(cmd, 'test')
# with open(os.open(os.ctermid(), os.O_RDWR | os.O_CLOEXEC), 'w') as tty_file, raw_mode(tty_file.fileno()):
#     print(end=f'\x1bP@kitty-cmd{json.dumps(cmd)}\x1b\\', flush=True, file=tty_file)
#     os.read(tty_file.fileno(), 4096)
