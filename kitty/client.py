#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2016, Kovid Goyal <kovid at kovidgoyal.net>

# Replay the log from --dump-commands. To use first run
# kitty --dump-commands > file.txt
# then run
# kitty --replay-commands file.txt
# will replay the commands and pause at the end waiting for user to press enter

import sys


CSI = '\033['


def write(x):
    sys.stdout.write(x)
    sys.stdout.flush()


def screen_cursor_position(y, x):
    write(CSI + '%s;%sH' % (y, x))


def screen_designate_charset(which, to):
    which = '()'[int(which)]
    to = chr(int(to))
    write('\033' + which + to)


def select_graphic_rendition(*a):
    write(CSI + '%sm' % ';'.join(map(str, a)))


def screen_cursor_to_column(c):
    write(CSI + '%dG' % c)


def screen_cursor_to_line(l):
    write(CSI + '%dd' % l)


def screen_set_mode(x, private):
    write(CSI + ('?' if private else '') + str(x) + 'h')


def screen_reset_mode(x, private):
    write(CSI + ('?' if private else '') + str(x) + 'l')


def screen_set_margins(t, b):
    write(CSI + '%d;%dr' % (t, b))


def screen_erase_in_display(how, private):
    write(CSI + ('?' if private else '') + str(how) + 'J')


def screen_cursor_up2(count):
    write(CSI + '%dA' % count)


def screen_carriage_return():
    write('\r')


def screen_backspace():
    write('\x08')


def draw(*a):
    write(' '.join(a))


def replay(raw):
    for line in raw.splitlines():
        if line.strip():
            cmd, rest = line.partition(' ')[::2]
            if cmd == 'draw':
                draw(rest)
            else:
                rest = map(int, rest.split()) if rest else ()
                globals()[cmd](*rest)


def main(path):
    raw = open(path).read()
    replay(raw)
    input()
