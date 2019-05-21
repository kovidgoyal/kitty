#!/usr/bin/env python3
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2018, Kovid Goyal <kovid at kovidgoyal.net>

import sys
from contextlib import contextmanager
from functools import wraps

from kitty.rgb import Color, color_as_sharp, to_color

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


def set_mode(which, private=True) -> str:
    num, private = MODES[which]
    return '\033[{}{}h'.format(private, num)


def reset_mode(which) -> str:
    num, private = MODES[which]
    return '\033[{}{}l'.format(private, num)


def clear_screen() -> str:
    return '\033[H\033[2J'


def clear_to_eol() -> str:
    return '\033[K'


def bell() -> str:
    return '\a'


def beep() -> str:
    return '\a'


def set_window_title(value) -> str:
    return ('\033]2;' + value.replace('\033', '').replace('\x9c', '') + '\033\\')


def set_line_wrapping(yes_or_no) -> str:
    return (set_mode if yes_or_no else reset_mode)('DECAWM')


def set_cursor_visible(yes_or_no) -> str:
    return (set_mode if yes_or_no else reset_mode)('DECTCEM')


def set_cursor_position(x, y) -> str:  # (0, 0) is top left
    return '\033[{};{}H'.format(y + 1, x + 1)


def set_cursor_shape(shape='block', blink=True) -> str:
    val = {'block': 1, 'underline': 3, 'bar': 5}.get(shape, 1)
    if not blink:
        val += 1
    return '\033[{} q'.format(val)


def set_scrolling_region(screen_size=None, top=None, bottom=None) -> str:
    if screen_size is None:
        return '\033[r'
    if top is None:
        top = 0
    if bottom is None:
        bottom = screen_size.rows - 1
    if bottom < 0:
        bottom = screen_size.rows - 1 + bottom
    else:
        bottom += 1
    return '\033[{};{}r'.format(top + 1, bottom + 1)


def scroll_screen(amt=1) -> str:
    return '\033[' + str(abs(amt)) + ('T' if amt < 0 else 'S')


STANDARD_COLORS = {name: i for i, name in enumerate(
    'black red green yellow blue magenta cyan gray'.split())}
STANDARD_COLORS['white'] = STANDARD_COLORS['gray']
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


def sgr(*parts) -> str:
    return '\033[{}m'.format(';'.join(parts))


def colored(text, color, intense=False, reset_to=None, reset_to_intense=False) -> str:
    e = color_code(color, intense)
    return '\033[{}m{}\033[{}m'.format(e, text, 39 if reset_to is None else color_code(reset_to, reset_to_intense))


def faint(text) -> str:
    return colored(text, 'black', True)


def styled(text, fg=None, bg=None, fg_intense=False, bg_intense=False, italic=None, bold=None, underline=None, underline_color=None, reverse=None) -> str:
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


def serialize_gr_command(cmd, payload=None):
    cmd = ','.join('{}={}'.format(k, v) for k, v in cmd.items())
    ans = []
    w = ans.append
    w(b'\033_G'), w(cmd.encode('ascii'))
    if payload:
        w(b';')
        w(payload)
    w(b'\033\\')
    return b''.join(ans)


def gr_command(cmd, payload=None) -> str:
    return serialize_gr_command(cmd, payload)


def clear_images_on_screen(delete_data=False) -> str:
    return serialize_gr_command({'a': 'd', 'd': 'A' if delete_data else 'a'})


def init_state(alternate_screen=True):
    ans = (
        S7C1T + SAVE_CURSOR + SAVE_PRIVATE_MODE_VALUES + reset_mode('LNM') +
        reset_mode('IRM') + reset_mode('DECKM') + reset_mode('DECSCNM') +
        set_mode('DECARM') + reset_mode('DECOM') + set_mode('DECAWM') +
        set_mode('DECTCEM') + reset_mode('MOUSE_BUTTON_TRACKING') +
        reset_mode('MOUSE_MOTION_TRACKING') + reset_mode('MOUSE_MOVE_TRACKING') +
        reset_mode('FOCUS_TRACKING') + reset_mode('MOUSE_UTF8_MODE') +
        reset_mode('MOUSE_SGR_MODE') + reset_mode('MOUSE_UTF8_MODE') +
        set_mode('BRACKETED_PASTE') + set_mode('EXTENDED_KEYBOARD') +
        '\033]30001\033\\' +
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
    ans += '\033]30101\033\\'
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


def set_default_colors(fg=None, bg=None, cursor=None, select_bg=None, select_fg=None) -> str:
    ans = ''

    def item(which, num):
        nonlocal ans
        if which is None:
            ans += '\x1b]1{}\x1b\\'.format(num)
        else:
            ans += '\x1b]{};{}\x1b\\'.format(num, color_as_sharp(which if isinstance(which, Color) else to_color(which)))

    item(fg, 10)
    item(bg, 11)
    item(cursor, 12)
    item(select_bg, 17)
    item(select_fg, 19)
    return ans


def write_to_clipboard(data, use_primary=False) -> str:
    if isinstance(data, str):
        data = data.encode('utf-8')
    from base64 import standard_b64encode
    fmt = 'p' if use_primary else 'c'

    def esc(chunk):
        return '\x1b]52;{};{}\x07'.format(fmt, chunk)
    ans = esc('!')  # clear clipboard buffer
    for chunk in (data[i:i+512] for i in range(0, len(data), 512)):
        chunk = standard_b64encode(chunk).decode('ascii')
        ans += esc(chunk)
    return ans


def request_from_clipboard(use_primary=False) -> str:
    return '\x1b]52;{};?\x07'.format('p' if use_primary else 'c')


all_cmds = tuple(
        (name, obj) for name, obj in globals().items()
        if hasattr(obj, '__annotations__') and obj.__annotations__.get('return') is str)


def writer(handler, func):
    @wraps(func)
    def f(self, *a, **kw):
        handler.write(func(*a, **kw))
    return f


def commander(handler):
    ans = {name: writer(handler, obj) for name, obj in all_cmds}
    return type('CMD', (), ans)()
