#!/usr/bin/env python3
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2016, Kovid Goyal <kovid at kovidgoyal.net>

# Replay the log from --dump-commands. To use first run
# kitty --dump-commands > file.txt
# then run
# kitty --replay-commands file.txt
# will replay the commands and pause at the end waiting for user to press enter

import sys
from contextlib import suppress
from typing import Any


CSI = '\033['
OSC = '\033]'


def write(x: str) -> None:
    sys.stdout.write(x)
    sys.stdout.flush()


def set_title(*args: Any) -> None:
    pass


def set_icon(*args: Any) -> None:
    pass


def screen_bell() -> None:
    pass


def screen_normal_keypad_mode() -> None:
    write('\x1b>')


def screen_alternate_keypad_mode() -> None:
    write('\x1b=')


def screen_cursor_position(y: int, x: int) -> None:
    write(CSI + '%s;%sH' % (y, x))


def screen_cursor_forward(amt: int) -> None:
    write(CSI + '%sC' % amt)


def screen_cursor_back1(amt: int) -> None:
    write(CSI + '%sD' % amt)


def screen_designate_charset(which: int, to: int) -> None:
    w = '()'[int(which)]
    t = chr(int(to))
    write('\033' + w + t)


def select_graphic_rendition(*a: int) -> None:
    write(CSI + '%sm' % ';'.join(map(str, a)))


def screen_cursor_to_column(c: int) -> None:
    write(CSI + '%dG' % c)


def screen_cursor_to_line(ln: int) -> None:
    write(CSI + '%dd' % ln)


def screen_set_mode(x: int, private: bool) -> None:
    write(CSI + ('?' if private else '') + str(x) + 'h')


def screen_reset_mode(x: int, private: bool) -> None:
    write(CSI + ('?' if private else '') + str(x) + 'l')


def screen_set_margins(t: int, b: int) -> None:
    write(CSI + '%d;%dr' % (t, b))


def screen_indexn(n: int) -> None:
    write(CSI + '%dS' % n)


def screen_delete_characters(count: int) -> None:
    write(CSI + '%dP' % count)


def screen_insert_characters(count: int) -> None:
    write(CSI + '%d@' % count)


def screen_scroll(count: int) -> None:
    write(CSI + '%dS' % count)


def screen_erase_in_display(how: int, private: bool) -> None:
    write(CSI + ('?' if private else '') + str(how) + 'J')


def screen_erase_in_line(how: int, private: bool) -> None:
    write(CSI + ('?' if private else '') + str(how) + 'K')


def screen_delete_lines(num: int) -> None:
    write(CSI + str(num) + 'M')


def screen_cursor_up2(count: int) -> None:
    write(CSI + '%dA' % count)


def screen_cursor_down(count: int) -> None:
    write(CSI + '%dB' % count)


def screen_carriage_return() -> None:
    write('\r')


def screen_linefeed() -> None:
    write('\n')


def screen_tab() -> None:
    write('\t')


def screen_backspace() -> None:
    write('\x08')


def screen_set_cursor(mode: int, secondary: int) -> None:
    write(CSI + '%d q' % secondary)


def screen_insert_lines(num: int) -> None:
    write(CSI + '%dL' % num)


def draw(*a: str) -> None:
    write(' '.join(a))


def screen_manipulate_title_stack(op: int, which: int) -> None:
    write(CSI + '%d;%dt' % (op, which))


def report_device_attributes(mode: int, char: int) -> None:
    x = CSI
    if char:
        x += chr(char)
    if mode:
        x += str(mode)
    write(CSI + x + 'c')


def write_osc(code: int, string: str = '') -> None:
    if string:
        string = ';' + string
    write(OSC + str(code) + string + '\x07')


set_dynamic_color = set_color_table_color = write_osc


def replay(raw: str) -> None:
    for line in raw.splitlines():
        if line.strip() and not line.startswith('#'):
            cmd, rest = line.partition(' ')[::2]
            if cmd in {'draw', 'set_title', 'set_icon', 'set_dynamic_color', 'set_color_table_color'}:
                globals()[cmd](rest)
            else:
                r = map(int, rest.split()) if rest else ()
                globals()[cmd](*r)


def main(path: str) -> None:
    with open(path) as f:
        raw = f.read()
    replay(raw)
    with suppress(EOFError, KeyboardInterrupt):
        input()
