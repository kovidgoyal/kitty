#!/usr/bin/env python3
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2017, Kovid Goyal <kovid at kovidgoyal.net>

import os
import subprocess
import shutil

base = os.path.dirname(os.path.abspath(__file__))
src = os.path.join(base, 'kitty.svg')


def abspath(x):
    return os.path.join(base, x)


def run(*args):
    try:
        subprocess.check_call(args)
    except OSError:
        raise SystemExit('You are missing the {} program needed to generate the kitty logo'.format(args[0]))


def render(output, sz=256):
    print('Rendering at {0}x{0}...'.format(sz))
    run('rsvg-convert', '-w', str(sz), '-h', str(sz), '-o', output, src)
    run('optipng', '-quiet', '-o7', '-strip', 'all', output)


def main():
    render(abspath('kitty.png'))
    iconset = abspath('kitty.iconset')
    if os.path.exists(iconset):
        shutil.rmtree(iconset)
    os.mkdir(iconset)
    os.chdir(iconset)
    for sz in (16, 32, 64, 128, 256, 512, 1024):
        iname = os.path.join(iconset, 'icon_{0}x{0}.png'.format(sz))
        iname2x = 'icon_{0}x{0}@2x.png'.format(sz // 2)
        render(iname, sz)
        if sz == 128:
            shutil.copyfile(iname, abspath('kitty-128.png'))
        if sz > 16 and sz != 128:
            shutil.copy2(iname, iname2x)
        if sz in (64, 1024):
            os.remove(iname)


if __name__ == '__main__':
    main()
