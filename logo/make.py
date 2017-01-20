#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2017, Kovid Goyal <kovid at kovidgoyal.net>

import os
import subprocess
import shutil

os.chdir(os.path.dirname(os.path.abspath(__file__)))
src = os.path.abspath('kitty.svg')


def render(output, sz=256):
    print('Rendering at {0}x{0}...'.format(sz))
    subprocess.check_call(['rsvg-convert', '-w', str(sz), '-h', str(sz), '-o', output, src])
    subprocess.check_call(['optipng', '-quiet', '-o7', '-strip', 'all', output])


render('kitty.png')
subprocess.check_call(['convert', 'kitty.png', '-depth', '8', 'kitty.rgba'])
iconset = 'kitty.iconset'
if os.path.exists(iconset):
    shutil.rmtree(iconset)
os.mkdir(iconset)
os.chdir(iconset)
for sz in (16, 32, 128, 256, 512, 1024):
    iname = 'icon_{0}x{0}.png'.format(sz)
    iname2x = 'icon_{0}x{0}@2x.png'.format(sz // 2)
    render(iname, sz)
    if sz > 16:
        shutil.copy2(iname, iname2x)
    if sz > 512:
        os.remove(iname)
