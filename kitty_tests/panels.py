#!/usr/bin/env python
# License: GPLv3 Copyright: 2025, Kovid Goyal <kovid at kovidgoyal.net>

import shlex
import subprocess


def r(msg: str, cmdline: str) -> None:
    try:
        q = input('Test ' + msg + '? (y/n): ').lower()
        if q in ('y', 'yes'):
            try:
                subprocess.run(['kitten'] + shlex.split(cmdline))
            except KeyboardInterrupt:
                pass
    except KeyboardInterrupt:
        raise SystemExit(1)

if __name__ == '__main__':
    r('top panel check transpareny, no input focus, margins and struts',
    'panel -o background_opacity=0.2 --edge=top --lines=2 --margin-left=50 --margin-right=100')

    r('bottom panel, check struts', 'panel -o background_opacity=0.2 --edge=bottom --lines=2 --margin-left=100 --margin-right=50')

    r('left panel, check struts', 'panel -o background_opacity=0.2 --edge=left --columns=2 --margin-top=50 --margin-bottom=100')

    r('right panel, check struts', 'panel -o background_opacity=0.2 --edge=right --columns=2 --margin-top=50 --margin-bottom=100')

    r('background, check transparency and margins and no input focus',
    'panel -o background_opacity=0.2 --edge=background --margin-top=50 --margin-bottom=50 --margin-left=100 --margin-right=100')

    r('quake, check transparency and focus on show/re-show', 'quick-access-terminal')
