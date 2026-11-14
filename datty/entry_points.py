#!/usr/bin/env python
# License: GPLv3 Copyright: 2022, Kovid Goyal <kovid at kovidgoyal.net>


import os
import sys


def icat(args: list[str]) -> None:
    from datty.constants import daddy_exe

    os.execl(daddy_exe(), 'daddy', *args)


def list_fonts(args: list[str]) -> None:
    from datty.fonts.list import main as list_main

    list_main(args)


def runpy(args: list[str]) -> None:
    if len(args) < 2:
        raise SystemExit('Usage: datty +runpy "some python code"')
    sys.argv = ['datty'] + args[2:]
    exec(args[1])


def hold(args: list[str]) -> None:
    from datty.constants import daddy_exe

    args = ['daddy', '__hold_till_enter__'] + args[1:]
    os.execvp(daddy_exe(), args)


def complete(args: list[str]) -> None:
    # Delegate to daddy to maintain backward compatibility
    if len(args) < 2 or args[1] not in ('setup', 'zsh', 'fish2', 'bash'):
        raise SystemExit(1)
    if args[1] == 'fish2':
        args[1:1] = ['fish', '_legacy_completion=fish2']
    elif len(args) >= 3 and args[1:3] == ['setup', 'fish2']:
        args[2] = 'fish'
    from datty.constants import daddy_exe

    args = ['daddy', '__complete__'] + args[1:]
    os.execvp(daddy_exe(), args)


def open_urls(args: list[str]) -> None:
    setattr(sys, 'cmdline_args_for_open', True)
    sys.argv = ['datty'] + args[1:]
    from datty.main import main as datty_main

    datty_main()


def launch(args: list[str]) -> None:
    import runpy

    sys.argv = args[1:]
    try:
        exe = args[1]
    except IndexError:
        raise SystemExit(
            'usage: datty +launch script.py [arguments to be passed to script.py ...]\n\n'
            'script.py will be run with full access to datty code. If script.py is '
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


def shebang(args: list[str]) -> None:
    from datty.constants import daddy_exe

    os.execvp(daddy_exe(), ['daddy', '__shebang__', 'confirm-if-needed'] + args[1:])


def run_daddy(args: list[str]) -> None:
    try:
        daddy = args[1]
    except IndexError:
        from daddies.runner import list_daddies

        list_daddies()
        raise SystemExit(1)
    sys.argv = args[1:]
    from daddies.runner import run_daddy as rk

    rk(daddy)


def namespaced(args: list[str]) -> None:
    try:
        func = namespaced_entry_points[args[1]]
    except IndexError:
        raise SystemExit('The datty command line is incomplete')
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
namespaced_entry_points['daddy'] = run_daddy
namespaced_entry_points['shebang'] = shebang


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
    setattr(sys, 'datty_ssl_env_var', 'SSL_CERT_FILE')


def main() -> None:
    if getattr(sys, 'frozen', False) and (ext_dir := getattr(sys, 'datty_run_data', {}).get('extensions_dir')):
        setup_openssl_environment(ext_dir)
    first_arg = '' if len(sys.argv) < 2 else sys.argv[1]
    func = entry_points.get(first_arg)
    if func is None:
        if first_arg.startswith('+'):
            namespaced(['+', first_arg[1:]] + sys.argv[2:])
        else:
            from datty.main import main as datty_main

            datty_main()
    else:
        func(sys.argv[1:])
