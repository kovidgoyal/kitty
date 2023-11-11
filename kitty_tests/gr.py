#!/usr/bin/env python
# License: GPL v3 Copyright: 2017, Kovid Goyal <kovid at kovidgoyal.net>

import os
import sys
import zlib
from base64 import standard_b64encode
from contextlib import suppress

write = getattr(sys.stdout, 'buffer', sys.stdout).write


def clear_screen():
    write(b'\033[2J')


def move_cursor(x, y):
    write(f'\033[{y};{x}H'.encode('ascii'))


def write_gr_cmd(cmd, payload):
    cmd = ','.join(f'{k}={v}' for k, v in cmd.items())
    w = write
    w(b'\033_G'), w(cmd.encode('ascii')), w(b';'), w(payload), w(b'\033\\')
    sys.stdout.flush()


def display(data, width, height, x, y, z, ncols=0, nrows=0):
    move_cursor(x, y)
    cmd = {'a': 'T', 's': width, 'v': height, 'c': ncols, 'r': nrows, 'S': len(data), 'z': z}
    data = zlib.compress(data)
    cmd['o'] = 'z'
    data = standard_b64encode(data)
    while data:
        chunk, data = data[:4096], data[4096:]
        m = 1 if data else 0
        cmd['m'] = m
        write_gr_cmd(cmd, chunk)
        cmd.clear()


def display_png_file(path):
    cmd = {'a': 'T', 't': 'f', 'f': '100'}
    path = os.path.abspath(path)
    if not isinstance(path, bytes):
        path = path.encode(sys.getfilesystemencoding() or 'utf-8')
    data = standard_b64encode(path)
    write_gr_cmd(cmd, data)


def main():
    from kitty.constants import logo_png_file
    photo = sys.argv[-1]
    if not photo.lower().endswith('.png'):
        raise SystemExit('Must specify a PNG file to display')
    clear_screen()
    display(b'\xdd\xdd\xdd\xff', 1, 1, 0, 0, -10, 40, 20)
    with open(logo_png_file.replace('.png', '.rgba'), 'rb') as f:
        display(f.read(), 256, 256, 0, 5, -9)
    display(b'\0\0\0\xaa', 1, 1, 0, 7, -8, 40, 3)
    move_cursor(5, 8)
    print('kitty is \033[3m\033[32mawesome\033[m!')
    move_cursor(0, 21)
    print('Photo...')
    display_png_file(photo)
    with suppress(EOFError, KeyboardInterrupt):
        input()


if __name__ == '__main__':
    main()
