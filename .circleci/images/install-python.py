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
SRC = f'/usr/src/{PY}'

os.chdir('/usr/src')
before = frozenset(os.listdir('.'))


def run(cmd):
    cmd = shlex.split(cmd)
    p = subprocess.Popen(cmd)
    if p.wait() != 0:
        raise SystemExit(p.returncode)


with urlopen(URL) as f:
    data = f.read()

with tarfile.open(fileobj=io.BytesIO(data), mode='r:xz') as tf:
    tf.extractall()
after = frozenset(os.listdir('.'))
src_dir = tuple(after - before)[0]
os.rename(src_dir, SRC)
os.chdir(SRC)
run(f'./configure --prefix=/opt/{PY} --enable-shared --with-system-expat --with-system-ffi --without-ensurepip')
run(f'make -j {os.cpu_count()}')
run('make install')
os.chdir('/')
shutil.rmtree(SRC)
