#!/usr/bin/env python3
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2018, Kovid Goyal <kovid at kovidgoyal.net>

import sys
from contextlib import contextmanager
from functools import wraps
from typing import (
    IO, Any, Callable, Dict, Generator, Optional, Tuple, TypeVar, Union
)

from kitty.rgb import Color, color_as_sharp, to_color
from kitty.typing import GraphicsCommandType, HandlerType, ScreenSize

from .operations_stub import CMD

GraphicsCommandType, ScreenSize  # needed for stub generation
S7C1T = '\033 F'
SAVE_CURSOR = '\0337'
RESTORE_CURSOR = '\0338'
SAVE_PRIVATE_MODE_VALUES = '\033[?s'
RESTORE_PRIVATE_MODE_VALUES = '\033[?r'
SAVE_COLORS = '\033[#P'
RESTORE_COLORS = '\033[#Q'
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
)

F = TypeVar('F')
all_cmds: Dict[str, Callable] = {}


def cmd(f: F) -> F:
    all_cmds[f.__name__] = f  # type: ignore
    return f


@cmd
def set_mode(which: str, private: bool = True) -> str:
    num, private_ = MODES[which]
    return '\033[{}{}h'.format(private_, num)


@cmd
def reset_mode(which: str) -> str:
    num, private = MODES[which]
    return '\033[{}{}l'.format(private, num)


@cmd
def clear_screen() -> str:
    return '\033[H\033[2J'


@cmd
def clear_to_end_of_screen() -> str:
    return '\033[J'


@cmd
def clear_to_eol() -> str:
    return '\033[K'


@cmd
def reset_terminal() -> str:
    return '\033]\033\\\033c'


@cmd
def bell() -> str:
    return '\a'


@cmd
def beep() -> str:
    return '\a'


@cmd
def set_window_title(value: str) -> str:
    return '\033]2;' + value.replace('\033', '').replace('\x9c', '') + '\033\\'


@cmd
def set_line_wrapping(yes_or_no: bool) -> str:
    return set_mode('DECAWM') if yes_or_no else reset_mode('DECAWM')


@cmd
def set_cursor_visible(yes_or_no: bool) -> str:
    return set_mode('DECTCEM') if yes_or_no else reset_mode('DECTCEM')


@cmd
def set_cursor_position(x: int, y: int) -> str:  # (0, 0) is top left
    return '\033[{};{}H'.format(y + 1, x + 1)


@cmd
def move_cursor_by(amt: int, direction: str) -> str:
    suffix = {'up': 'A', 'down': 'B', 'right': 'C', 'left': 'D'}[direction]
    return f'\033[{amt}{suffix}'


@cmd
def set_cursor_shape(shape: str = 'block', blink: bool = True) -> str:
    val = {'block': 1, 'underline': 3, 'bar': 5}.get(shape, 1)
    if not blink:
        val += 1
    return '\033[{} q'.format(val)


@cmd
def set_scrolling_region(screen_size: Optional['ScreenSize'] = None, top: Optional[int] = None, bottom: Optional[int] = None) -> str:
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


@cmd
def scroll_screen(amt: int = 1) -> str:
    return '\033[' + str(abs(amt)) + ('T' if amt < 0 else 'S')


STANDARD_COLORS = {name: i for i, name in enumerate(
    'black red green yellow blue magenta cyan gray'.split())}
STANDARD_COLORS['white'] = STANDARD_COLORS['gray']
UNDERLINE_STYLES = {name: i + 1 for i, name in enumerate(
    'straight double curly'.split())}


ColorSpec = Union[int, str, Tuple[int, int, int]]


def color_code(color: ColorSpec, intense: bool = False, base: int = 30) -> str:
    if isinstance(color, str):
        e = str((base + 60 if intense else base) + STANDARD_COLORS[color])
    elif isinstance(color, int):
        e = '{}:5:{}'.format(base + 8, max(0, min(color, 255)))
    else:
        e = '{}:2:{}:{}:{}'.format(base + 8, *color)
    return e


@cmd
def sgr(*parts: str) -> str:
    return '\033[{}m'.format(';'.join(parts))


@cmd
def colored(
    text: str,
    color: ColorSpec,
    intense: bool = False,
    reset_to: Optional[ColorSpec] = None,
    reset_to_intense: bool = False
) -> str:
    e = color_code(color, intense)
    return '\033[{}m{}\033[{}m'.format(e, text, 39 if reset_to is None else color_code(reset_to, reset_to_intense))


@cmd
def faint(text: str) -> str:
    return colored(text, 'black', True)


@cmd
def styled(
    text: str,
    fg: Optional[ColorSpec] = None,
    bg: Optional[ColorSpec] = None,
    fg_intense: bool = False,
    bg_intense: bool = False,
    italic: Optional[bool] = None,
    bold: Optional[bool] = None,
    underline: Optional[str] = None,
    underline_color: Optional[ColorSpec] = None,
    reverse: Optional[bool] = None
) -> str:
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
        s.append('3')
        e.append('23')
    if bold is not None:
        s, e = (start, end) if bold else (end, start)
        s.append('1')
        e.append('22')
    if reverse is not None:
        s, e = (start, end) if reverse else (end, start)
        s.append('7')
        e.append('27')
    if not start:
        return text
    return '\033[{}m{}\033[{}m'.format(';'.join(start), text, ';'.join(end))


def serialize_gr_command(cmd: Dict[str, Union[int, str]], payload: Optional[bytes] = None) -> bytes:
    from .images import GraphicsCommand
    gc = GraphicsCommand()
    for k, v in cmd.items():
        setattr(gc, k, v)
    return gc.serialize(payload or b'')


@cmd
def gr_command(cmd: Union[Dict, 'GraphicsCommandType'], payload: Optional[bytes] = None) -> str:
    if isinstance(cmd, dict):
        raw = serialize_gr_command(cmd, payload)
    else:
        raw = cmd.serialize(payload or b'')
    return raw.decode('ascii')


@cmd
def clear_images_on_screen(delete_data: bool = False) -> str:
    from .images import GraphicsCommand
    gc = GraphicsCommand()
    gc.a = 'd'
    gc.d = 'A' if delete_data else 'a'
    return gc.serialize().decode('ascii')


def init_state(alternate_screen: bool = True) -> str:
    ans = (
        S7C1T + SAVE_CURSOR + SAVE_PRIVATE_MODE_VALUES + reset_mode('LNM') +
        reset_mode('IRM') + reset_mode('DECKM') + reset_mode('DECSCNM') +
        set_mode('DECARM') + set_mode('DECAWM') +
        set_mode('DECTCEM') + reset_mode('MOUSE_BUTTON_TRACKING') +
        reset_mode('MOUSE_MOTION_TRACKING') + reset_mode('MOUSE_MOVE_TRACKING') +
        reset_mode('FOCUS_TRACKING') + reset_mode('MOUSE_UTF8_MODE') +
        reset_mode('MOUSE_SGR_MODE') + reset_mode('MOUSE_UTF8_MODE') +
        set_mode('BRACKETED_PASTE') + SAVE_COLORS +
        '\033[*x'  # reset DECSACE to default region select
    )
    if alternate_screen:
        ans += set_mode('ALTERNATE_SCREEN') + reset_mode('DECOM')
        ans += clear_screen()
    ans += '\033[>31u'  # extended keyboard mode
    return ans


def reset_state(normal_screen: bool = True) -> str:
    ans = ''
    ans += '\033[<u'  # restore keyboard mode
    if normal_screen:
        ans += reset_mode('ALTERNATE_SCREEN')
    ans += RESTORE_PRIVATE_MODE_VALUES
    ans += RESTORE_CURSOR
    ans += RESTORE_COLORS
    return ans


@contextmanager
def cursor(write: Callable[[str], None]) -> Generator[None, None, None]:
    write(SAVE_CURSOR)
    yield
    write(RESTORE_CURSOR)


@contextmanager
def alternate_screen(f: Optional[IO[str]] = None) -> Generator[None, None, None]:
    f = f or sys.stdout
    print(set_mode('ALTERNATE_SCREEN'), end='', file=f)
    yield
    print(reset_mode('ALTERNATE_SCREEN'), end='', file=f)


@contextmanager
def raw_mode(fd: Optional[int] = None) -> Generator[None, None, None]:
    import tty
    import termios
    if fd is None:
        fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        yield
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)


@cmd
def set_default_colors(
    fg: Optional[Union[Color, str]] = None,
    bg: Optional[Union[Color, str]] = None,
    cursor: Optional[Union[Color, str]] = None,
    select_bg: Optional[Union[Color, str]] = None,
    select_fg: Optional[Union[Color, str]] = None
) -> str:
    ans = ''

    def item(which: Optional[Union[Color, str]], num: int) -> None:
        nonlocal ans
        if which is None:
            ans += '\x1b]1{}\x1b\\'.format(num)
        else:
            if isinstance(which, Color):
                q = color_as_sharp(which)
            else:
                x = to_color(which)
                assert x is not None
                q = color_as_sharp(x)
            ans += '\x1b]{};{}\x1b\\'.format(num, q)

    item(fg, 10)
    item(bg, 11)
    item(cursor, 12)
    item(select_bg, 17)
    item(select_fg, 19)
    return ans


@cmd
def write_to_clipboard(data: Union[str, bytes], use_primary: bool = False) -> str:
    if isinstance(data, str):
        data = data.encode('utf-8')
    from base64 import standard_b64encode
    fmt = 'p' if use_primary else 'c'

    def esc(chunk: str) -> str:
        return '\x1b]52;{};{}\x07'.format(fmt, chunk)

    ans = esc('!')  # clear clipboard buffer
    for chunk in (data[i:i+512] for i in range(0, len(data), 512)):
        s = standard_b64encode(chunk).decode('ascii')
        ans += esc(s)
    return ans


@cmd
def request_from_clipboard(use_primary: bool = False) -> str:
    return '\x1b]52;{};?\x07'.format('p' if use_primary else 'c')


# Boilerplate to make operations available via Handler.cmd  {{{


def writer(handler: HandlerType, func: Callable) -> Callable:
    @wraps(func)
    def f(*a: Any, **kw: Any) -> None:
        handler.write(func(*a, **kw))
    return f


def commander(handler: HandlerType) -> CMD:
    ans = CMD()
    for name, func in all_cmds.items():
        setattr(ans, name, writer(handler, func))
    return ans


def func_sig(func: Callable) -> Generator[str, None, None]:
    import inspect
    import re
    s = inspect.signature(func)
    for val in s.parameters.values():
        yield re.sub(r'ForwardRef\([\'"](\w+?)[\'"]\)', r'\1', str(val).replace('NoneType', 'None'))


def as_type_stub() -> str:
    ans = [
        'from typing import *  # noqa',
        'from kitty.typing import GraphicsCommandType, ScreenSize',
        'from kitty.rgb import Color',
        'import kitty.rgb',
    ]
    methods = []
    for name, func in all_cmds.items():
        args = ', '.join(func_sig(func))
        if args:
            args = ', ' + args
        methods.append('    def {}(self{}) -> str: pass'.format(name, args))
    ans += ['', '', 'class CMD:'] + methods

    return '\n'.join(ans) + '\n\n\n'
# }}}
