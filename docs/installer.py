#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2018, Kovid Goyal <kovid at kovidgoyal.net>

from __future__ import (
    absolute_import, division, print_function, unicode_literals
)

import atexit
import json
import os
import platform
import re
import shlex
import shutil
import subprocess
import sys
import tempfile

py3 = sys.version_info[0] > 2
is64bit = platform.architecture()[0] == '64bit'
is_macos = 'darwin' in sys.platform.lower()

try:
    __file__
    from_file = True
except NameError:
    from_file = False

if py3:
    unicode = str
    raw_input = input
    import urllib.request as urllib

    def encode_for_subprocess(x):
        return x
else:
    from future_builtins import map
    import urllib2 as urllib

    def encode_for_subprocess(x):
        if isinstance(x, unicode):
            x = x.encode('utf-8')
        return x


def run(*args):
    if len(args) == 1:
        args = shlex.split(args[0])
    args = list(map(encode_for_subprocess, args))
    ret = subprocess.Popen(args).wait()
    if ret != 0:
        raise SystemExit(ret)


class Reporter:  # {{{

    def __init__(self, fname):
        self.fname = fname
        self.last_percent = 0

    def __call__(self, blocks, block_size, total_size):
        percent = (blocks*block_size)/float(total_size)
        report = '\rDownloaded {:.1%}         '.format(percent)
        if percent - self.last_percent > 0.05:
            self.last_percent = percent
            print(report, end='')
            sys.stdout.flush()
# }}}


def get_latest_release_data():
    print('Checking for latest release on GitHub...')
    req = urllib.Request('https://api.github.com/repos/kovidgoyal/kitty/releases/latest', headers={'Accept': 'application/vnd.github.v3+json'})
    try:
        res = urllib.urlopen(req).read().decode('utf-8')
    except Exception as err:
        raise SystemExit('Failed to contact {} with error: {}'.format(req.get_full_url(), err))
    data = json.loads(res)
    html_url = data['html_url'].replace('/tag/', '/download/').rstrip('/')
    for asset in data.get('assets', ()):
        name = asset['name']
        if is_macos:
            if name.endswith('.dmg'):
                return html_url + '/' + name, asset['size']
        else:
            if name.endswith('.txz'):
                if is64bit:
                    if name.endswith('-x86_64.txz'):
                        return html_url + '/' + name, asset['size']
                else:
                    if name.endswith('-i686.txz'):
                        return html_url + '/' + name, asset['size']
    raise SystemExit('Failed to find the installer package on github')


def do_download(url, size, dest):
    print('Will download and install', os.path.basename(dest))
    reporter = Reporter(os.path.basename(dest))

    # Get content length and check if range is supported
    rq = urllib.urlopen(url)
    headers = rq.info()
    sent_size = int(headers['content-length'])
    if sent_size != size:
        raise SystemExit('Failed to download from {} Content-Length ({}) != {}'.format(url, sent_size, size))
    with open(dest, 'wb') as f:
        while f.tell() < size:
            raw = rq.read(8192)
            if not raw:
                break
            f.write(raw)
            reporter(f.tell(), 1, size)
    rq.close()
    if os.path.getsize(dest) < size:
        raise SystemExit('Download failed, try again later')
    print('\rDownloaded {} bytes'.format(os.path.getsize(dest)))


def clean_cache(cache, fname):
    for x in os.listdir(cache):
        if fname not in x:
            os.remove(os.path.join(cache, x))


def download_installer(url, size):
    fname = url.rpartition('/')[-1]
    tdir = tempfile.gettempdir()
    cache = os.path.join(tdir, 'kitty-installer-cache')
    if not os.path.exists(cache):
        os.makedirs(cache)
    clean_cache(cache, fname)
    dest = os.path.join(cache, fname)
    if os.path.exists(dest) and os.path.getsize(dest) == size:
        print('Using previously downloaded', fname)
        return dest
    if os.path.exists(dest):
        os.remove(dest)
    do_download(url, size, dest)
    return dest


def macos_install(dmg, dest='/Applications', launch=True):
    mp = tempfile.mkdtemp()
    atexit.register(shutil.rmtree, mp)
    run('hdiutil', 'attach', dmg, '-mountpoint', mp)
    try:
        os.chdir(mp)
        app = 'kitty.app'
        d = os.path.join(dest, app)
        if os.path.exists(d):
            shutil.rmtree(d)
        dest = os.path.join(dest, app)
        run('ditto', '-v', app, dest)
        print('Successfully installed kitty into', dest)
        if launch:
            run('open', dest)
    finally:
        os.chdir('/')
        run('hdiutil', 'detach', mp)


def linux_install(installer, dest=os.path.expanduser('~/.local'), launch=True):
    dest = os.path.join(dest, 'kitty.app')
    if os.path.exists(dest):
        shutil.rmtree(dest)
    os.makedirs(dest)
    print('Extracting tarball...')
    run('tar', '-C', dest, '-xJof', installer)
    print('kitty successfully installed to', dest)
    kitty = os.path.join(dest, 'bin', 'kitty')
    print('Use', kitty, 'to run kitty')
    if launch:
        run(kitty, '--detach')


def main(dest=None, launch=True, installer=None):
    if not dest:
        if is_macos:
            dest = '/Applications'
        else:
            dest = os.path.expanduser('~/.local')
    machine = os.uname()[4]
    if machine and machine.lower().startswith('arm'):
        raise SystemExit(
            'You are running on an ARM system. The kitty binaries are only'
            ' available for x86 systems. You will have to build from'
            ' source.')
    if not installer:
        url, size = get_latest_release_data()
        installer = download_installer(url, size)
    else:
        installer = os.path.abspath(installer)
        if not os.access(installer, os.R_OK):
            raise SystemExit('Could not read from: {}'.format(installer))
    if is_macos:
        macos_install(installer, dest=dest, launch=launch)
    else:
        linux_install(installer, dest=dest, launch=launch)


def script_launch():
    # To test: python3 -c "import runpy; runpy.run_path('installer.py', run_name='script_launch')"
    def path(x):
        return os.path.expandvars(os.path.expanduser(x))

    def to_bool(x):
        return x.lower() in {'y', 'yes', '1', 'true'}

    type_map = {x: path for x in 'dest installer'.split()}
    type_map['launch'] = to_bool
    kwargs = {}

    for arg in sys.argv[1:]:
        if arg:
            m = re.match('([a-z_]+)=(.+)', arg)
            if m is None:
                raise SystemExit('Unrecognized command line argument: ' + arg)
            k = m.group(1)
            if k not in type_map:
                raise SystemExit('Unrecognized command line argument: ' + arg)
            kwargs[k] = type_map[k](m.group(2))
    main(**kwargs)


def update_intaller_wrapper():
    # To run: python3 -c "import runpy; runpy.run_path('installer.py', run_name='update_wrapper')" installer.sh
    src = open(__file__, 'rb').read().decode('utf-8')
    wrapper = sys.argv[-1]
    with open(wrapper, 'r+b') as f:
        raw = f.read().decode('utf-8')
        nraw = re.sub(r'^# HEREDOC_START.+^# HEREDOC_END', lambda m: '# HEREDOC_START\n{}\n# HEREDOC_END'.format(src), raw, flags=re.MULTILINE | re.DOTALL)
        if 'update_intaller_wrapper()' not in nraw:
            raise SystemExit('regex substitute of HEREDOC failed')
        f.seek(0), f.truncate()
        f.write(nraw.encode('utf-8'))


if __name__ == '__main__' and from_file:
    main()
elif __name__ == 'update_wrapper':
    update_intaller_wrapper()
elif __name__ == 'script_launch':
    script_launch()
