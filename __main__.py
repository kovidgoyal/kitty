#!/usr/bin/env python3
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2015, Kovid Goyal <kovid at kovidgoyal.net>

import sys
import os
from typing import List


def icat(args: List[str]) -> None:
    from kittens.runner import run_kitten as rk
    sys.argv = args
    rk('icat')


def list_fonts(args: List[str]) -> None:
    from kitty.fonts.list import main as list_main
    list_main(args)


def remote_control(args: List[str]) -> None:
    from kitty.remote_control import main as rc_main
    rc_main(args)


def runpy(args: List[str]) -> None:
    sys.argv = ['kitty'] + args[2:]
    exec(args[1])


def hold(args: List[str]) -> None:
    import subprocess
    from contextlib import suppress
    import tty
    ret = subprocess.Popen(args[1:]).wait()
    with suppress(BaseException):
        print('\n\x1b[1;32mPress any key to exit', end='', flush=True)
    with suppress(BaseException):
        tty.setraw(sys.stdin.fileno())
        sys.stdin.buffer.read(1)
    raise SystemExit(ret)


def complete(args: List[str]) -> None:
    from kitty.complete import main as complete_main
    complete_main(args[1:], entry_points, namespaced_entry_points)


def launch(args: List[str]) -> None:
    import runpy
    sys.argv = args[1:]
    exe = args[1]
    if exe.startswith(':'):
        import shutil
        q = shutil.which(exe[1:])
        if not q:
            raise SystemExit('{} not found in PATH'.format(args[1][1:]))
        exe = q
    runpy.run_path(exe, run_name='__main__')


def run_kitten(args: List[str]) -> None:
    try:
        kitten = args[1]
    except IndexError:
        from kittens.runner import list_kittens
        list_kittens()
        raise SystemExit(1)
    sys.argv = args[1:]
    from kittens.runner import run_kitten as rk
    rk(kitten)


def edit_config_file(args: List[str]) -> None:
    from kitty.utils import edit_config_file as f
    f()


def namespaced(args: List[str]) -> None:
    func = namespaced_entry_points[args[1]]
    func(args[1:])


entry_points = {
    # These two are here for backwards compat
    'icat': icat,
    'list-fonts': list_fonts,
    'runpy': runpy,
    'launch': launch,
    'kitten': run_kitten,
    'edit-config': edit_config_file,

    '@': remote_control,
    '+': namespaced,
}
namespaced_entry_points = {k: v for k, v in entry_points.items() if k[0] not in '+@'}
namespaced_entry_points['hold'] = hold
namespaced_entry_points['complete'] = complete


def setup_openssl_environment() -> None:
    # Workaround for Linux distros that have still failed to get their heads
    # out of their asses and implement a common location for SSL certificates.
    # It's not that hard people, there exists a wonderful tool called the symlink
    # See https://www.mobileread.com/forums/showthread.php?t=256095
    if 'SSL_CERT_FILE' not in os.environ and 'SSL_CERT_DIR' not in os.environ:
        if os.access('/etc/pki/tls/certs/ca-bundle.crt', os.R_OK):
            os.environ['SSL_CERT_FILE'] = '/etc/pki/tls/certs/ca-bundle.crt'
            setattr(sys, 'kitty_ssl_env_var', 'SSL_CERT_FILE')
        elif os.path.isdir('/etc/ssl/certs'):
            os.environ['SSL_CERT_DIR'] = '/etc/ssl/certs'
            setattr(sys, 'kitty_ssl_env_var', 'SSL_CERT_DIR')


def main() -> None:
    if getattr(sys, 'frozen', False) and 'darwin' not in sys.platform.lower():
        setup_openssl_environment()
    first_arg = '' if len(sys.argv) < 2 else sys.argv[1]
    func = entry_points.get(first_arg)
    if func is None:
        if first_arg.startswith('@'):
            remote_control(['@', first_arg[1:]] + sys.argv[2:])
        elif first_arg.startswith('+'):
            namespaced(['+', first_arg[1:]] + sys.argv[2:])
        else:
            from kitty.main import main as kitty_main
            kitty_main()
    else:
        func(sys.argv[1:])


if __name__ == '__main__':
    main()
