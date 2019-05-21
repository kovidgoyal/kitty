#!/usr/bin/env python3
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2015, Kovid Goyal <kovid at kovidgoyal.net>

import sys
import os


def icat(args):
    from kittens.runner import run_kitten
    sys.argv = args
    run_kitten('icat')


def list_fonts(args):
    from kitty.fonts.list import main
    main(args)


def remote_control(args):
    from kitty.remote_control import main
    main(args)


def runpy(args):
    sys.argv = ['kitty'] + args[2:]
    exec(args[1])


def hold(args):
    import subprocess
    ret = subprocess.Popen(args[1:]).wait()
    sys.stdin.read()
    raise SystemExit(ret)


def complete(args):
    from kitty.complete import main
    main(args[1:], entry_points, namespaced_entry_points)


def launch(args):
    import runpy
    sys.argv = args[1:]
    exe = args[1]
    if exe.startswith(':'):
        import shutil
        exe = shutil.which(exe[1:])
        if not exe:
            raise SystemExit('{} not found in PATH'.format(args[1][1:]))
    runpy.run_path(exe, run_name='__main__')


def run_kitten(args):
    try:
        kitten = args[1]
    except IndexError:
        from kittens.runner import list_kittens
        list_kittens()
        raise SystemExit(1)
    sys.argv = args[1:]
    from kittens.runner import run_kitten
    run_kitten(kitten)


def namespaced(args):
    func = namespaced_entry_points[args[1]]
    func(args[1:])


entry_points = {
    # These two are here for backwards compat
    'icat': icat,
    'list-fonts': list_fonts,
    'runpy': runpy,
    'launch': launch,
    'kitten': run_kitten,

    '@': remote_control,
    '+': namespaced,
}
namespaced_entry_points = {k: v for k, v in entry_points.items() if k[0] not in '+@'}
namespaced_entry_points['hold'] = hold
namespaced_entry_points['complete'] = complete


def setup_openssl_environment():
    # Workaround for Linux distros that have still failed to get their heads
    # out of their asses and implement a common location for SSL certificates.
    # It's not that hard people, there exists a wonderful tool called the symlink
    # See https://www.mobileread.com/forums/showthread.php?t=256095
    if 'SSL_CERT_FILE' not in os.environ and 'SSL_CERT_DIR' not in os.environ:
        if os.access('/etc/pki/tls/certs/ca-bundle.crt', os.R_OK):
            os.environ['SSL_CERT_FILE'] = '/etc/pki/tls/certs/ca-bundle.crt'
        elif os.path.isdir('/etc/ssl/certs'):
            os.environ['SSL_CERT_DIR'] = '/etc/ssl/certs'


def main():
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
            from kitty.main import main
            main()
    else:
        func(sys.argv[1:])


if __name__ == '__main__':
    main()
