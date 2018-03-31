#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2017, Kovid Goyal <kovid at kovidgoyal.net>

import os
import subprocess
import shutil

os.chdir(os.path.dirname(os.path.abspath(__file__)))
src = os.path.abspath('kitty.svg')


def run(*args):
    try:
        subprocess.check_call(args)
    except EnvironmentError:
        raise SystemExit('You are missing the {} program needed to generate the kitty logo'.format(args[0]))


def render(output, sz=256):
    print('Rendering at {0}x{0}...'.format(sz))
    run('rsvg-convert', '-w', str(sz), '-h', str(sz), '-o', output, src)
    run('optipng', '-quiet', '-o7', '-strip', 'all', output)


render('kitty.png')
run('convert', 'kitty.png', '-depth', '8', 'kitty.rgba')
iconset = 'kitty.iconset'
if os.path.exists(iconset):
    shutil.rmtree(iconset)
os.mkdir(iconset)
os.chdir(iconset)
for sz in (16, 32, 64, 128, 256, 512, 1024):
    iname = 'icon_{0}x{0}.png'.format(sz)
    iname2x = 'icon_{0}x{0}@2x.png'.format(sz // 2)
    render(iname, sz)
    if sz > 16 and sz != 128:
        shutil.copy2(iname, iname2x)
    if sz in (64, 1024):
        os.remove(iname)
