#!/usr/bin/env python3
# vim:fileencoding=utf-8
# License: GPLv3 Copyright: 2019, Kovid Goyal <kovid at kovidgoyal.net>

import io
import os
import shlex
import shutil
import subprocess
import sys
import tarfile
from urllib.request import urlopen

PY, URL = sys.argv[1], sys.argv[2]
if PY == 'bundle':
    SW = os.environ['SW']
    os.mkdir(SW)
    os.chdir(SW)
else:
    os.chdir('/usr/src')


def run(cmd):
    cmd = shlex.split(cmd)
    p = subprocess.Popen(cmd)
    if p.wait() != 0:
        raise SystemExit(p.returncode)


with urlopen(URL) as f:
    data = f.read()

with tarfile.open(fileobj=io.BytesIO(data), mode='r:xz') as tf:
    tf.extractall()


def replace_in_file(path, src, dest):
    with open(path, 'r+') as f:
        n = f.read().replace(src, dest)
        f.seek(0), f.truncate()
        f.write(n)


if PY == 'bundle':
    replaced = 0
    for dirpath, dirnames, filenames in os.walk(SW):
        for f in filenames:
            if f.endswith('.pc') or (f.endswith('.py') and f.startswith('_sysconfig')):
                replace_in_file(os.path.join(dirpath, f), '/sw/sw', SW)
                replaced += 1
    if replaced < 2:
        raise SystemExit('Failed to replace path to SW in bundle')
else:
    src = os.path.abspath(tuple(os.listdir('.'))[0])
    os.chdir(src)
    run(f'./configure --prefix=/opt/{PY} --enable-shared --with-system-expat --without-ensurepip')
    run(f'make -j {os.cpu_count()}')
    run('make install')
    os.chdir('/')
    shutil.rmtree(src)
