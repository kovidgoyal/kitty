#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPLv3 Copyright: 2020, Kovid Goyal <kovid at kovidgoyal.net>

import glob
import io
import os
import shlex
import shutil
import subprocess
import sys
import tarfile
import time
from urllib.request import urlopen

BUNDLE_URL = 'https://download.calibre-ebook.com/ci/kitty/{}-64.tar.xz'
FONTS_URL = 'https://download.calibre-ebook.com/ci/fonts.tar.xz'
NERD_URL = 'https://github.com/ryanoasis/nerd-fonts/releases/latest/download/NerdFontsSymbolsOnly.tar.xz'
is_bundle = os.environ.get('KITTY_BUNDLE') == '1'
is_macos = 'darwin' in sys.platform.lower()
SW = ''


def do_print_crash_reports() -> None:
    print('Printing available crash reports...')
    if is_macos:
        end_time = time.monotonic() + 90
        while time.monotonic() < end_time:
            time.sleep(1)
            items = glob.glob(os.path.join(os.path.expanduser('~/Library/Logs/DiagnosticReports'), 'kitty-*.ips'))
            if items:
                break
        if items:
            time.sleep(1)
            print(os.path.basename(items[0]))
            sdir = os.path.dirname(os.path.abspath(__file__))
            subprocess.check_call([sys.executable, os.path.join(sdir, 'macos_crash_report.py'), items[0]])
    else:
        run('sh -c "echo bt | coredumpctl debug"')
    print(flush=True)


def run(*a: str, print_crash_reports: bool = False) -> None:
    if len(a) == 1:
        a = tuple(shlex.split(a[0]))
    cmd = ' '.join(map(shlex.quote, a))
    print(cmd)
    sys.stdout.flush()
    ret = subprocess.Popen(a).wait()
    if ret != 0:
        if ret < 0:
            import signal
            try:
                sig = signal.Signals(-ret)
            except ValueError:
                pass
            else:
                if print_crash_reports:
                    do_print_crash_reports()
                raise SystemExit(f'The following process was killed by signal: {sig.name}:\n{cmd}')
        raise SystemExit(f'The following process failed with exit code: {ret}:\n{cmd}')


def install_fonts() -> None:
    with urlopen(FONTS_URL) as f:
        data = f.read()
    fonts_dir = os.path.expanduser('~/Library/Fonts' if is_macos else '~/.local/share/fonts')
    os.makedirs(fonts_dir, exist_ok=True)
    with tarfile.open(fileobj=io.BytesIO(data), mode='r:xz') as tf:
        try:
            tf.extractall(fonts_dir, filter='fully_trusted')
        except TypeError:
            tf.extractall(fonts_dir)
    with urlopen(NERD_URL) as f:
        data = f.read()
    with tarfile.open(fileobj=io.BytesIO(data), mode='r:xz') as tf:
        try:
            tf.extractall(fonts_dir, filter='fully_trusted')
        except TypeError:
            tf.extractall(fonts_dir)


def install_deps() -> None:
    print('Installing kitty dependencies...')
    sys.stdout.flush()
    if is_macos:
        items = [x.split()[1].strip('"') for x in open('Brewfile').readlines() if x.strip().startswith('brew ')]
        openssl = 'openssl'
        items.remove('go')  # already installed by ci.yml
        import ssl
        if ssl.OPENSSL_VERSION_INFO[0] == 1:
            openssl += '@1.1'
        run('brew', 'install', 'fish', openssl, *items)
    else:
        run('sudo apt-get update')
        run('sudo apt-get install -y libgl1-mesa-dev libxi-dev libxrandr-dev libxinerama-dev ca-certificates'
            ' libxcursor-dev libxcb-xkb-dev libdbus-1-dev libxkbcommon-dev libharfbuzz-dev libx11-xcb-dev zsh'
            ' libpng-dev liblcms2-dev libfontconfig-dev libxkbcommon-x11-dev libcanberra-dev libxxhash-dev uuid-dev'
            ' libsimde-dev libsystemd-dev libcairo2-dev zsh bash dash systemd-coredump gdb')
        # for some reason these directories are world writable which causes zsh
        # compinit to break
        run('sudo chmod -R og-w /usr/share/zsh')
    if is_bundle:
        install_bundle()
    else:
        cmd = 'python3 -m pip install Pillow pygments'
        if sys.version_info[:2] < (3, 7):
            cmd += ' importlib-resources dataclasses'
        run(cmd)
    install_fonts()


def build_kitty() -> None:
    python = shutil.which('python3') if is_bundle else sys.executable
    cmd = f'{python} setup.py build --verbose'
    if is_macos:
        cmd += ' --debug'  # for better crash report to debug SIGILL issue
    if os.environ.get('KITTY_SANITIZE') == '1':
        cmd += ' --debug --sanitize'
    run(cmd)


def test_kitty() -> None:
    if is_macos:
        run('ulimit -c unlimited')
        run('sudo chmod -R 777 /cores')
    run('./test.py', print_crash_reports=True)


def package_kitty() -> None:
    python = 'python3' if is_macos else 'python'
    run(f'{python} setup.py linux-package --update-check-interval=0 --verbose')
    if is_macos:
        run('python3 setup.py kitty.app --update-check-interval=0 --verbose')
        run('kitty.app/Contents/MacOS/kitty +runpy "from kitty.constants import *; print(kitty_exe())"')


def replace_in_file(path: str, src: str, dest: str) -> None:
    with open(path, 'r+') as f:
        n = f.read().replace(src, dest)
        f.seek(0), f.truncate()
        f.write(n)


def setup_bundle_env() -> None:
    global SW
    os.environ['SW'] = SW = '/Users/Shared/kitty-build/sw/sw' if is_macos else os.path.join(os.environ['GITHUB_WORKSPACE'], 'sw')
    os.environ['PKG_CONFIG_PATH'] = os.path.join(SW, 'lib', 'pkgconfig')
    if is_macos:
        os.environ['PATH'] = '{}:{}'.format('/usr/local/opt/sphinx-doc/bin', os.environ['PATH'])
    else:
        os.environ['LD_LIBRARY_PATH'] = os.path.join(SW, 'lib')
        os.environ['PYTHONHOME'] = SW
    os.environ['PATH'] = '{}:{}'.format(os.path.join(SW, 'bin'), os.environ['PATH'])


def install_bundle() -> None:
    cwd = os.getcwd()
    os.makedirs(SW)
    os.chdir(SW)
    with urlopen(BUNDLE_URL.format('macos' if is_macos else 'linux')) as f:
        data = f.read()
    with tarfile.open(fileobj=io.BytesIO(data), mode='r:xz') as tf:
        try:
            tf.extractall(filter='fully_trusted')
        except TypeError:
            tf.extractall()
    if not is_macos:
        replaced = 0
        for dirpath, dirnames, filenames in os.walk('.'):
            for f in filenames:
                if f.endswith('.pc') or (f.endswith('.py') and f.startswith('_sysconfig')):
                    replace_in_file(os.path.join(dirpath, f), '/sw/sw', SW)
                    replaced += 1
        if replaced < 2:
            raise SystemExit('Failed to replace path to SW in bundle')
    os.chdir(cwd)


def main() -> None:
    if is_bundle:
        setup_bundle_env()
    else:
        if not is_macos and 'pythonLocation' in os.environ:
            os.environ['LD_LIBRARY_PATH'] = os.path.join(os.environ['pythonLocation'], 'lib')
    action = sys.argv[-1]
    if action in ('build', 'package'):
        install_deps()
    if action == 'build':
        build_kitty()
    elif action == 'package':
        package_kitty()
    elif action == 'test':
        test_kitty()
    elif action == 'gofmt':
        q = subprocess.check_output('gofmt -s -l tools kittens'.split()).decode()
        if q.strip():
            q = '\n'.join(filter(lambda x: not x.rstrip().endswith('_generated.go'), q.strip().splitlines())).strip()
            if q:
                raise SystemExit(q)
    else:
        raise SystemExit(f'Unknown action: {action}')


if __name__ == '__main__':
    main()
