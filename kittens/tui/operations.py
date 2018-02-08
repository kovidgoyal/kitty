#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2018, Kovid Goyal <kovid at kovidgoyal.net>

from kitty.terminfo import string_capabilities

S7C1T = b'\033 F'
SAVE_CURSOR = b'\0337'
RESTORE_CURSOR = b'\0338'
SAVE_PRIVATE_MODE_VALUES = b'\033[?s'
RESTORE_PRIVATE_MODE_VALUES = b'\033[?r'

MODES = dict(
    LNM=(20, ''),
    IRM=(4, ''),
    DECKM=(1, '?'),
    DECSCNM=(5, '?'),
    DECOM=(6, '?'),
    DECAWM=(6, '?'),
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
    return '\033[{}{}h'.format(private, num).encode('ascii')


def reset_mode(which):
    num, private = MODES[which]
    return '\033[{}{}l'.format(private, num).encode('ascii')


def clear_screen():
    return string_capabilities['clear'].replace(r'\E', '\033').encode('ascii')


def set_window_title(value):
    return ('\033]2;' + value.replace('\033', '').replace('\x9c', '') + '\033\\').encode('utf-8')


def set_line_wrapping(yes_or_no):
    return (set_mode if yes_or_no else reset_mode)('DECAWM')


STANDARD_COLORS = {name: i for i, name in enumerate(
    'black red green yellow blue magenta cyan gray'.split())}


def colored(text, color, intense=False):
    if isinstance(color, str):
        e = (90 if intense else 30) + STANDARD_COLORS[color]
    elif isinstance(color, int):
        e = '38:5:{}'.format(max(0, min(color, 255)))
    else:
        e = '38:2:{}:{}:{}'.format(*color)
    return '\033[{}m{}\033[39m'.format(e, text)


def init_state(alternate_screen=True):
    ans = (
        S7C1T + SAVE_CURSOR + SAVE_PRIVATE_MODE_VALUES + reset_mode('LNM') +
        reset_mode('IRM') + reset_mode('DECKM') + reset_mode('DECSCNM') +
        set_mode('DECARM') + reset_mode('DECOM') + set_mode('DECAWM') +
        set_mode('DECTCEM') + reset_mode('MOUSE_BUTTON_TRACKING') +
        reset_mode('MOUSE_MOTION_TRACKING') + reset_mode('MOUSE_MOVE_TRACKING')
        + reset_mode('FOCUS_TRACKING') + reset_mode('MOUSE_UTF8_MODE') +
        reset_mode('MOUSE_SGR_MODE') + reset_mode('MOUSE_UTF8_MODE') +
        set_mode('BRACKETED_PASTE') + set_mode('EXTENDED_KEYBOARD')
    )
    if alternate_screen:
        ans += set_mode('ALTERNATE_SCREEN')
        ans += clear_screen()
    return ans


def reset_state(normal_screen=True):
    ans = b''
    if normal_screen:
        ans += reset_mode('ALTERNATE_SCREEN')
    ans += RESTORE_PRIVATE_MODE_VALUES
    ans += RESTORE_CURSOR
    return ans
