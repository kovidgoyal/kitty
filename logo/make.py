#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2017, Kovid Goyal <kovid at kovidgoyal.net>

import os
import shutil
import subprocess

base = os.path.dirname(os.path.abspath(__file__))
unframed_src = os.path.join(base, 'kitty.svg')
framed_src = os.path.join(base, 'kitty-framed.svg')


def abspath(x):
    return os.path.join(base, x)


def run(*args):
    try:
        subprocess.check_call(args)
    except OSError:
        raise SystemExit(f'You are missing the {args[0]} program needed to generate the kitty logo')


def render(output, sz=256, src=unframed_src):
    print(f'Rendering {os.path.basename(src)} at {sz}x{sz}...')
    run('rsvg-convert', '-w', str(sz), '-h', str(sz), '-o', output, src)
    run('optipng', '-quiet', '-o7', '-strip', 'all', output)


def main():
    render(abspath('kitty.png'))
    render(abspath('kitty-128.png'), sz=128)
    iconset = abspath('kitty.iconset')
    if os.path.exists(iconset):
        shutil.rmtree(iconset)
    os.mkdir(iconset)
    os.chdir(iconset)
    for sz in (16, 32, 64, 128, 256, 512, 1024):
        iname = os.path.join(iconset, 'icon_{0}x{0}.png'.format(sz))
        iname2x = 'icon_{0}x{0}@2x.png'.format(sz // 2)
        render(iname, sz, src=framed_src)
        if sz > 16 and sz != 128:
            shutil.copy2(iname, iname2x)
        if sz in (64, 1024):
            os.remove(iname)


if __name__ == '__main__':
    main()
