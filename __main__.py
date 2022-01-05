#!/usr/bin/env python3
# License: GPL v3 Copyright: 2015, Kovid Goyal <kovid at kovidgoyal.net>

import os
import sys
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
    if len(args) < 2:
        raise SystemExit('Usage: kitty +runpy "some python code"')
    sys.argv = ['kitty'] + args[2:]
    exec(args[1])


def hold(args: List[str]) -> None:
    import subprocess
    import termios
    from contextlib import suppress
    from kittens.tui.operations import init_state, set_cursor_visible
    ret = subprocess.Popen(args[1:]).wait()
    with suppress(BaseException):
        print(
            '\n\x1b[1;32mPress Enter to exit',
            end=init_state(alternate_screen=False, kitty_keyboard_mode=False) + set_cursor_visible(False),
            flush=True)
    with suppress(BaseException):
        fd = sys.stdin.fileno()
        old = termios.tcgetattr(fd)
        new = old[:]
        new[3] &= ~termios.ECHO  # 3 == 'lflags'
        tcsetattr_flags = termios.TCSAFLUSH
        if hasattr(termios, 'TCSASOFT'):
            tcsetattr_flags |= getattr(termios, 'TCSASOFT')
        termios.tcsetattr(fd, tcsetattr_flags, new)
        with suppress(KeyboardInterrupt):
            input()
    raise SystemExit(ret)


def complete(args: List[str]) -> None:
    from kitty.complete import main as complete_main
    complete_main(args[1:], entry_points, namespaced_entry_points)


def launch(args: List[str]) -> None:
    import runpy
    sys.argv = args[1:]
    try:
        exe = args[1]
    except IndexError:
        raise SystemExit(
            'usage: kitty +launch script.py [arguments to be passed to script.py ...]\n\n'
            'script.py will be run with full access to kitty code. If script.py is '
            'prefixed with a : it will be searched for in PATH'
        )
    if exe.startswith(':'):
        import shutil
        q = shutil.which(exe[1:])
        if not q:
            raise SystemExit(f'{exe[1:]} not found in PATH')
        exe = q
    if not os.path.exists(exe):
        raise SystemExit(f'{exe} does not exist')
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
    from kitty.cli import create_default_opts
    from kitty.fast_data_types import set_options
    from kitty.utils import edit_config_file as f
    set_options(create_default_opts())
    f()


def namespaced(args: List[str]) -> None:
    try:
        func = namespaced_entry_points[args[1]]
    except KeyError:
        pass
    else:
        func(args[1:])
        return
    raise SystemExit(f'{args[1]} is not a known entry point. Choices are: ' + ', '.join(namespaced_entry_points))


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
    # Use our bundled CA certificates instead of the system ones, since
    # many systems come with no certificates in a useable form or have various
    # locations for the certificates.
    d = os.path.dirname
    ext_dir: str = getattr(sys, 'kitty_extensions_dir')
    if 'darwin' in sys.platform.lower():
        cert_file = os.path.join(d(d(d(ext_dir))), 'cacert.pem')
    else:
        cert_file = os.path.join(d(ext_dir), 'cacert.pem')
    os.environ['SSL_CERT_FILE'] = cert_file
    setattr(sys, 'kitty_ssl_env_var', 'SSL_CERT_FILE')


def main() -> None:
    if getattr(sys, 'frozen', False) and getattr(sys, 'kitty_extensions_dir', ''):
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
