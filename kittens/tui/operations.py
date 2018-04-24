#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2018, Kovid Goyal <kovid at kovidgoyal.net>

import sys
from contextlib import contextmanager

from kitty.rgb import Color, color_as_sharp, to_color
from kitty.terminfo import string_capabilities

S7C1T = '\033 F'
SAVE_CURSOR = '\0337'
RESTORE_CURSOR = '\0338'
SAVE_PRIVATE_MODE_VALUES = '\033[?s'
RESTORE_PRIVATE_MODE_VALUES = '\033[?r'

MODES = dict(
    LNM=(20, ''),
    IRM=(4, ''),
    DECKM=(1, '?'),
    DECSCNM=(5, '?'),
    DECOM=(6, '?'),
    DECAWM=(7, '?'),
    DECARM=(8, '?'),
    DECTCEM=(25, '?'),
    MOUSE_BUTTON_TRACKING=(1000, '?'),
    MOUSE_MOTION_TRACKING=(1002, '?'),
    MOUSE_MOVE_TRACKING=(1003, '?'),
    FOCUS_TRACKING=(1004, '?'),
    MOUSE_UTF8_MODE=(1005, '?'),
    MOUSE_SGR_MODE=(1006, '?'),
    MOUSE_URXVT_MODE=(1015, '?'),
    ALTERNATE_SCREEN=(1049, '?'),
    BRACKETED_PASTE=(2004, '?'),
    EXTENDED_KEYBOARD=(2017, '?'),
)


def set_mode(which, private=True):
    num, private = MODES[which]
    return '\033[{}{}h'.format(private, num)


def reset_mode(which):
    num, private = MODES[which]
    return '\033[{}{}l'.format(private, num)


def clear_screen():
    return string_capabilities['clear'].replace(r'\E', '\033')


def set_window_title(value):
    return ('\033]2;' + value.replace('\033', '').replace('\x9c', '') + '\033\\')


def set_line_wrapping(yes_or_no):
    return (set_mode if yes_or_no else reset_mode)('DECAWM')


def set_cursor_visible(yes_or_no):
    return (set_mode if yes_or_no else reset_mode)('DECTCEM')


STANDARD_COLORS = {name: i for i, name in enumerate(
    'black red green yellow blue magenta cyan gray'.split())}
UNDERLINE_STYLES = {name: i + 1 for i, name in enumerate(
    'straight double curly'.split())}


def color_code(color, intense=False, base=30):
    if isinstance(color, str):
        e = str((base + 60 if intense else base) + STANDARD_COLORS[color])
    elif isinstance(color, int):
        e = '{}:5:{}'.format(base + 8, max(0, min(color, 255)))
    else:
        e = '{}:2:{}:{}:{}'.format(base + 8, *color)
    return e


def sgr(*parts):
    return '\033[{}m'.format(';'.join(parts))


def colored(text, color, intense=False, reset_to=None, reset_to_intense=False):
    e = color_code(color, intense)
    return '\033[{}m{}\033[{}m'.format(e, text, 39 if reset_to is None else color_code(reset_to, reset_to_intense))


def faint(text):
    return colored(text, 'black', True)


def styled(text, fg=None, bg=None, fg_intense=False, bg_intense=False, italic=None, bold=None, underline=None, underline_color=None, reverse=None):
    start, end = [], []
    if fg is not None:
        start.append(color_code(fg, fg_intense))
        end.append('39')
    if bg is not None:
        start.append(color_code(bg, bg_intense, 40))
        end.append('49')
    if underline_color is not None:
        if isinstance(underline_color, str):
            underline_color = STANDARD_COLORS[underline_color]
        start.append(color_code(underline_color, base=50))
        end.append('59')
    if underline is not None:
        start.append('4:{}'.format(UNDERLINE_STYLES[underline]))
        end.append('4:0')
    if italic is not None:
        s, e = (start, end) if italic else (end, start)
        s.append('3'), e.append('23')
    if bold is not None:
        s, e = (start, end) if bold else (end, start)
        s.append('1'), e.append('22')
    if reverse is not None:
        s, e = (start, end) if reverse else (end, start)
        s.append('7'), e.append('27')
    if not start:
        return text
    return '\033[{}m{}\033[{}m'.format(';'.join(start), text, ';'.join(end))


def init_state(alternate_screen=True):
    ans = (
        S7C1T + SAVE_CURSOR + SAVE_PRIVATE_MODE_VALUES + reset_mode('LNM') +
        reset_mode('IRM') + reset_mode('DECKM') + reset_mode('DECSCNM') +
        set_mode('DECARM') + reset_mode('DECOM') + set_mode('DECAWM') +
        set_mode('DECTCEM') + reset_mode('MOUSE_BUTTON_TRACKING') +
        reset_mode('MOUSE_MOTION_TRACKING') + reset_mode('MOUSE_MOVE_TRACKING')
        + reset_mode('FOCUS_TRACKING') + reset_mode('MOUSE_UTF8_MODE') +
        reset_mode('MOUSE_SGR_MODE') + reset_mode('MOUSE_UTF8_MODE') +
        set_mode('BRACKETED_PASTE') + set_mode('EXTENDED_KEYBOARD') +
        '\033[*x'  # reset DECSACE to default region select
    )
    if alternate_screen:
        ans += set_mode('ALTERNATE_SCREEN')
        ans += clear_screen()
    return ans


def reset_state(normal_screen=True):
    ans = ''
    if normal_screen:
        ans += reset_mode('ALTERNATE_SCREEN')
    ans += RESTORE_PRIVATE_MODE_VALUES
    ans += RESTORE_CURSOR
    return ans


@contextmanager
def cursor(write):
    write(SAVE_CURSOR)
    yield
    write(RESTORE_CURSOR)


@contextmanager
def alternate_screen(f=None):
    f = f or sys.stdout
    print(set_mode('ALTERNATE_SCREEN'), end='', file=f)
    yield
    print(reset_mode('ALTERNATE_SCREEN'), end='', file=f)


def set_default_colors(fg=None, bg=None):
    ans = ''
    if fg is None:
        ans += '\x1b]110\x1b\\'
    else:
        ans += '\x1b]10;{}\x1b\\'.format(color_as_sharp(fg if isinstance(fg, Color) else to_color(fg)))
    if bg is None:
        ans += '\x1b]111\x1b\\'
    else:
        ans += '\x1b]11;{}\x1b\\'.format(color_as_sharp(bg if isinstance(bg, Color) else to_color(bg)))
    return ans
