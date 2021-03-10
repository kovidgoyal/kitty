#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPLv3 Copyright: 2020, Kovid Goyal <kovid at kovidgoyal.net>

import io
import os
import shlex
import shutil
import subprocess
import sys
import tarfile
from urllib.request import urlopen

is_bundle = os.environ.get('KITTY_BUNDLE') == '1'
is_macos = 'darwin' in sys.platform.lower()
SW = None


def run(*a):
    if len(a) == 1:
        a = shlex.split(a[0])
    print(' '.join(map(shlex.quote, a)))
    sys.stdout.flush()
    ret = subprocess.Popen(a).wait()
    if ret != 0:
        raise SystemExit(ret)


def install_deps():
    print('Installing kitty dependencies...')
    sys.stdout.flush()
    if is_macos:
        items = (x.strip() for x in open('Brewfile').readlines() if not x.startswith('#'))
        run('brew', 'install', *items)
    else:
        run('sudo apt-get update')
        run('sudo apt-get install -y libgl1-mesa-dev libxi-dev libxrandr-dev libxinerama-dev'
            ' libxcursor-dev libxcb-xkb-dev libdbus-1-dev libxkbcommon-dev libharfbuzz-dev libx11-xcb-dev'
            ' libpng-dev liblcms2-dev libfontconfig-dev libxkbcommon-x11-dev libcanberra-dev uuid-dev')
    if is_bundle:
        install_bundle()
    else:
        if is_macos:
            # needed for zlib for pillow, should not be needed after pillow 8.0
            os.environ['PKG_CONFIG_PATH'] = '/usr/local/opt/zlib/lib/pkgconfig'
        cmd = 'pip3 install Pillow pygments'
        if sys.version_info[:2] < (3, 7):
            cmd += ' importlib-resources'
        run(cmd)


def build_kitty():
    python = shutil.which('python3') if is_bundle else sys.executable
    cmd = '{} setup.py build --verbose'.format(python)
    if os.environ.get('KITTY_SANITIZE') == '1':
        cmd += ' --debug --sanitize'
    run(cmd)


def test_kitty():
    run('./kitty/launcher/kitty +launch test.py')


def package_kitty():
    py = 'python3' if is_macos else 'python'
    run(py + ' setup.py linux-package --update-check-interval=0 --verbose')
    if is_macos:
        run('python3 setup.py kitty.app --update-check-interval=0 --verbose')
        run('kitty.app/Contents/MacOS/kitty +runpy "from kitty.constants import *; print(kitty_exe())"')


def replace_in_file(path, src, dest):
    with open(path, 'r+') as f:
        n = f.read().replace(src, dest)
        f.seek(0), f.truncate()
        f.write(n)


def setup_bundle_env():
    global SW
    os.environ['SW'] = SW = '/Users/Shared/kitty-build/sw/sw' if is_macos else os.path.join(os.environ['GITHUB_WORKSPACE'], 'sw')
    os.environ['PKG_CONFIG_PATH'] = SW + '/lib/pkgconfig'
    if is_macos:
        os.environ['PATH'] = '{}:{}'.format('/usr/local/opt/sphinx-doc/bin', os.environ['PATH'])
    else:
        os.environ['LD_LIBRARY_PATH'] = SW + '/lib'
        os.environ['PYTHONHOME'] = SW
    os.environ['PATH'] = '{}:{}'.format(os.path.join(SW, 'bin'), os.environ['PATH'])


def install_bundle():
    cwd = os.getcwd()
    os.makedirs(SW)
    os.chdir(SW)
    with urlopen('https://download.calibre-ebook.com/ci/kitty/{}-64.tar.xz'.format(
            'macos' if is_macos else 'linux')) as f:
        data = f.read()
    with tarfile.open(fileobj=io.BytesIO(data), mode='r:xz') as tf:
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


def main():
    if is_bundle:
        setup_bundle_env()
    else:
        if not is_macos and 'pythonLocation' in os.environ:
            os.environ['LD_LIBRARY_PATH'] = '{}/lib'.format(os.environ['pythonLocation'])
    action = sys.argv[-1]
    if action in ('build', 'package'):
        install_deps()
    if action == 'build':
        build_kitty()
    elif action == 'package':
        package_kitty()
    elif action == 'test':
        test_kitty()
    else:
        raise SystemExit('Unknown action: ' + action)


if __name__ == '__main__':
    main()
