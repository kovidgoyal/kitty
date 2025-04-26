#!/usr/bin/env python
# License: GPLv3 Copyright: 2022, Kovid Goyal <kovid at kovidgoyal.net>


import os
import sys


def icat(args: list[str]) -> None:
    from kitty.constants import kitten_exe
    os.execl(kitten_exe(), "kitten", *args)


def list_fonts(args: list[str]) -> None:
    from kitty.fonts.list import main as list_main
    list_main(args)


def runpy(args: list[str]) -> None:
    if len(args) < 2:
        raise SystemExit('Usage: kitty +runpy "some python code"')
    sys.argv = ['kitty'] + args[2:]
    exec(args[1])


def hold(args: list[str]) -> None:
    from kitty.constants import kitten_exe
    args = ['kitten', '__hold_till_enter__'] + args[1:]
    os.execvp(kitten_exe(), args)


def complete(args: list[str]) -> None:
    # Delegate to kitten to maintain backward compatibility
    if len(args) < 2 or args[1] not in ('setup', 'zsh', 'fish2', 'bash'):
        raise SystemExit(1)
    if args[1] == 'fish2':
        args[1:1] = ['fish', '_legacy_completion=fish2']
    elif len(args) >= 3 and args [1:3] == ['setup', 'fish2']:
        args[2] = 'fish'
    from kitty.constants import kitten_exe
    args = ['kitten', '__complete__'] + args[1:]
    os.execvp(kitten_exe(), args)


def open_urls(args: list[str]) -> None:
    setattr(sys, 'cmdline_args_for_open', True)
    sys.argv = ['kitty'] + args[1:]
    from kitty.main import main as kitty_main
    kitty_main()


def launch(args: list[str]) -> None:
    import runpy
    sys.argv = args[1:]
    try:
        exe = args[1]
    except IndexError:
        raise SystemExit(
            'usage: kitty +launch script.py [arguments to be passed to script.py ...]\n\n'
            'script.py will be run with full access to kitty code. If script.py is '
            'prefixed with a : it will be searched for in PATH. If script.py is a directory '
            'the __main__.py file inside it is run just as with the normal Python interpreter.'
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


def edit(args: list[str]) -> None:
    import shutil

    from .constants import is_macos
    if is_macos:
        # On macOS vim fails to handle SIGWINCH if it occurs early, so add a small delay.
        import time
        time.sleep(0.05)
    exe = args[1]
    if not os.path.isabs(exe):
        exe = shutil.which(exe) or ''
    if not exe or not os.access(exe, os.X_OK):
        print('Cannot find an editor on your system. Set the \x1b[33meditor\x1b[39m value in kitty.conf'
              ' to the absolute path of your editor of choice.', file=sys.stderr)
        from kitty.utils import hold_till_enter
        hold_till_enter()
        raise SystemExit(1)
    os.execv(exe, args[1:])


def shebang(args: list[str]) -> None:
    from kitty.constants import kitten_exe
    os.execvp(kitten_exe(), ['kitten', '__shebang__', 'confirm-if-needed'] + args[1:])


def run_kitten(args: list[str]) -> None:
    try:
        kitten = args[1]
    except IndexError:
        from kittens.runner import list_kittens
        list_kittens()
        raise SystemExit(1)
    sys.argv = args[1:]
    from kittens.runner import run_kitten as rk
    rk(kitten)


def edit_config_file(args: list[str]) -> None:
    from kitty.cli import create_default_opts
    from kitty.fast_data_types import set_options
    from kitty.utils import edit_config_file as f
    set_options(create_default_opts())
    f()


def namespaced(args: list[str]) -> None:
    try:
        func = namespaced_entry_points[args[1]]
    except IndexError:
        raise SystemExit('The kitty command line is incomplete')
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

    '+': namespaced,
}
namespaced_entry_points = {k: v for k, v in entry_points.items() if k[0] not in '+@'}
namespaced_entry_points['hold'] = hold
namespaced_entry_points['complete'] = complete
namespaced_entry_points['runpy'] = runpy
namespaced_entry_points['launch'] = launch
namespaced_entry_points['open'] = open_urls
namespaced_entry_points['kitten'] = run_kitten
namespaced_entry_points['edit-config'] = edit_config_file
namespaced_entry_points['shebang'] = shebang
namespaced_entry_points['edit'] = edit


def setup_openssl_environment(ext_dir: str) -> None:
    # Use our bundled CA certificates instead of the system ones, since
    # many systems come with no certificates in a usable form or have various
    # locations for the certificates.
    d = os.path.dirname
    if 'darwin' in sys.platform.lower():
        cert_file = os.path.join(d(d(d(ext_dir))), 'cacert.pem')
    else:
        cert_file = os.path.join(d(ext_dir), 'cacert.pem')
    os.environ['SSL_CERT_FILE'] = cert_file
    setattr(sys, 'kitty_ssl_env_var', 'SSL_CERT_FILE')


def main() -> None:
    if getattr(sys, 'frozen', False) and (ext_dir := getattr(sys, 'kitty_run_data', {}).get('extensions_dir')):
        setup_openssl_environment(ext_dir)
    first_arg = '' if len(sys.argv) < 2 else sys.argv[1]
    func = entry_points.get(first_arg)
    if func is None:
        if first_arg.startswith('+'):
            namespaced(['+', first_arg[1:]] + sys.argv[2:])
        else:
            from kitty.main import main as kitty_main
            kitty_main()
    else:
        func(sys.argv[1:])
