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
OSC = '\033]'


def write(x):
    sys.stdout.write(x)
    sys.stdout.flush()


def set_title(*args):
    pass


def set_icon(*args):
    pass


def screen_bell():
    pass


def screen_cursor_position(y, x):
    write(CSI + '%s;%sH' % (y, x))


def screen_cursor_forward(amt):
    write(CSI + '%sC' % amt)


def screen_cursor_back1(amt):
    write(CSI + '%sD' % amt)


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


def screen_indexn(n):
    write(CSI + '%dS' % n)


def screen_erase_in_display(how, private):
    write(CSI + ('?' if private else '') + str(how) + 'J')


def screen_erase_in_line(how, private):
    write(CSI + ('?' if private else '') + str(how) + 'K')


def screen_delete_lines(num):
    write(CSI + str(num) + 'M')


def screen_cursor_up2(count):
    write(CSI + '%dA' % count)


def screen_cursor_down(count):
    write(CSI + '%dB' % count)


def screen_carriage_return():
    write('\r')


def screen_linefeed():
    write('\n')


def screen_backspace():
    write('\x08')


def screen_set_cursor(mode, secondary):
    write(CSI + '%d q' % secondary)


def screen_insert_lines(num):
    write(CSI + '%dL' % num)


def draw(*a):
    write(' '.join(a))


def report_device_attributes(mode, char):
    x = CSI
    if char:
        x += ord(char)
    if mode:
        x += str(mode)
    write(CSI + x + 'c')


def write_osc(code, string=''):
    if string:
        string = ';' + string
    write(OSC + str(code) + string + '\x07')


set_dynamic_color = set_color_table_color = write_osc


def replay(raw):
    for line in raw.splitlines():
        if line.strip() and not line.startswith('#'):
            cmd, rest = line.partition(' ')[::2]
            if cmd in {'draw', 'set_title', 'set_icon', 'set_dynamic_color', 'set_color_table_color'}:
                globals()[cmd](rest)
            else:
                rest = map(int, rest.split()) if rest else ()
                globals()[cmd](*rest)


def main(path):
    raw = open(path).read()
    replay(raw)
    try:
        input()
    except (EOFError, KeyboardInterrupt):
        pass
