#!/usr/bin/env python
# License: GPL v3 Copyright: 2018, Kovid Goyal <kovid at kovidgoyal.net>

import os
import sys
from collections.abc import Callable, Generator
from contextlib import contextmanager
from enum import Enum, auto
from functools import wraps
from typing import Any, Optional, TypeVar, Union

from kitty.fast_data_types import Color
from kitty.rgb import color_as_sharp, to_color
from kitty.typing_compat import GraphicsCommandType, HandlerType, ScreenSize, UnderlineLiteral

from .operations_stub import CMD

GraphicsCommandType, ScreenSize  # needed for stub generation
SAVE_CURSOR = '\0337'
RESTORE_CURSOR = '\0338'
SAVE_PRIVATE_MODE_VALUES = '\033[?s'
RESTORE_PRIVATE_MODE_VALUES = '\033[?r'
SAVE_COLORS = '\033[#P'
RESTORE_COLORS = '\033[#Q'
F = TypeVar('F')
all_cmds: dict[str, Callable[..., Any]] = {}


class Mode(Enum):
    LNM = 20, ''
    IRM = 4, ''
    DECKM = 1, '?'
    DECSCNM = 5, '?'
    DECOM = 6, '?'
    DECAWM = 7, '?'
    DECARM = 8, '?'
    DECTCEM = 25, '?'
    MOUSE_BUTTON_TRACKING = 1000, '?'
    MOUSE_MOTION_TRACKING = 1002, '?'
    MOUSE_MOVE_TRACKING = 1003, '?'
    FOCUS_TRACKING = 1004, '?'
    MOUSE_UTF8_MODE = 1005, '?'
    MOUSE_SGR_MODE = 1006, '?'
    MOUSE_URXVT_MODE = 1015, '?'
    MOUSE_SGR_PIXEL_MODE = 1016, '?'
    ALTERNATE_SCREEN = 1049, '?'
    BRACKETED_PASTE = 2004, '?'
    PENDING_UPDATE = 2026, '?'
    HANDLE_TERMIOS_SIGNALS = 19997, '?'


def cmd(f: F) -> F:
    all_cmds[f.__name__] = f  # type: ignore
    return f


@cmd
def set_mode(which: Mode) -> str:
    num, private = which.value
    return f'\033[{private}{num}h'


@cmd
def reset_mode(which: Mode) -> str:
    num, private = which.value
    return f'\033[{private}{num}l'


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
    return set_mode(Mode.DECAWM) if yes_or_no else reset_mode(Mode.DECAWM)


@contextmanager
def without_line_wrap(write: Callable[[str], None]) -> Generator[None, None, None]:
    write(set_line_wrapping(False))
    try:
        yield
    finally:
        write(set_line_wrapping(True))


@cmd
def repeat(char: str, count: int) -> str:
    if count > 5:
        return f'{char}\x1b[{count-1}b'
    return char * count


@cmd
def set_cursor_visible(yes_or_no: bool) -> str:
    return set_mode(Mode.DECTCEM) if yes_or_no else reset_mode(Mode.DECTCEM)


@cmd
def set_cursor_position(x: int = 0, y: int = 0) -> str:  # (0, 0) is top left
    return f'\033[{y + 1};{x + 1}H'


@cmd
def move_cursor_by(amt: int, direction: str) -> str:
    suffix = {'up': 'A', 'down': 'B', 'right': 'C', 'left': 'D'}[direction]
    return f'\033[{amt}{suffix}'


@cmd
def set_cursor_shape(shape: str = 'block', blink: bool = True) -> str:
    val = {'block': 1, 'underline': 3, 'beam': 5}.get(shape, 1)
    if not blink:
        val += 1
    return f'\033[{val} q'


@cmd
def set_scrolling_region(screen_size: Optional['ScreenSize'] = None, top: int | None = None, bottom: int | None = None) -> str:
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
    return f'\033[{top + 1};{bottom + 1}r'


@cmd
def scroll_screen(amt: int = 1) -> str:
    return f'\033[{abs(amt)}{"T" if amt < 0 else "S"}'


STANDARD_COLORS = {'black': 0, 'red': 1, 'green': 2, 'yellow': 3, 'blue': 4, 'magenta': 5, 'cyan': 6, 'gray': 7, 'white': 7}
UNDERLINE_STYLES = {'straight': 1, 'double': 2, 'curly': 3, 'dotted': 4, 'dashed': 5}


ColorSpec = Union[int, str, Color]


def color_code(color: ColorSpec, intense: bool = False, base: int = 30) -> str:
    if isinstance(color, str):
        e = str((base + 60 if intense else base) + STANDARD_COLORS[color])
    elif isinstance(color, int):
        e = f'{base + 8}:5:{max(0, min(color, 255))}'
    else:
        e = f'{base + 8}{color.as_sgr}'
    return e


@cmd
def sgr(*parts: str) -> str:
    return '\033[{}m'.format(';'.join(parts))


@cmd
def colored(
    text: str,
    color: ColorSpec,
    intense: bool = False,
    reset_to: ColorSpec | None = None,
    reset_to_intense: bool = False
) -> str:
    e = color_code(color, intense)
    return f'\033[{e}m{text}\033[{39 if reset_to is None else color_code(reset_to, reset_to_intense)}m'


@cmd
def faint(text: str) -> str:
    return colored(text, 'black', True)


@cmd
def styled(
    text: str,
    fg: ColorSpec | None = None,
    bg: ColorSpec | None = None,
    fg_intense: bool = False,
    bg_intense: bool = False,
    italic: bool | None = None,
    bold: bool | None = None,
    underline: UnderlineLiteral | None = None,
    underline_color: ColorSpec | None = None,
    reverse: bool | None = None,
    dim: bool | None = None,
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
        start.append(f'4:{UNDERLINE_STYLES[underline]}')
        end.append('4:0')
    if italic is not None:
        s, e = (start, end) if italic else (end, start)
        s.append('3')
        e.append('23')
    if bold is not None:
        s, e = (start, end) if bold else (end, start)
        s.append('1')
        e.append('22')
    if dim is not None:
        s, e = (start, end) if dim else (end, start)
        s.append('2')
        e.append('22')
    if reverse is not None:
        s, e = (start, end) if reverse else (end, start)
        s.append('7')
        e.append('27')
    if not start:
        return text
    return '\033[{}m{}\033[{}m'.format(';'.join(start), text, ';'.join(end))


def serialize_gr_command(cmd: dict[str, int | str], payload: bytes | None = None) -> bytes:
    from .images import GraphicsCommand
    gc = GraphicsCommand()
    for k, v in cmd.items():
        setattr(gc, k, v)
    return gc.serialize(payload or b'')


@cmd
def gr_command(cmd: Union[dict[str, int | str], 'GraphicsCommandType'], payload: bytes | None = None) -> str:
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


class MouseTracking(Enum):
    none = auto()
    buttons_only = auto()
    buttons_and_drag = auto()
    full = auto()


def init_state(alternate_screen: bool = True, mouse_tracking: MouseTracking = MouseTracking.none, kitty_keyboard_mode: bool = True) -> str:
    sc = SAVE_CURSOR if alternate_screen else ''
    ans = (
        sc + SAVE_PRIVATE_MODE_VALUES + reset_mode(Mode.LNM) +
        reset_mode(Mode.IRM) + reset_mode(Mode.DECKM) + reset_mode(Mode.DECSCNM) +
        set_mode(Mode.DECARM) + set_mode(Mode.DECAWM) +
        set_mode(Mode.DECTCEM) + reset_mode(Mode.MOUSE_BUTTON_TRACKING) +
        reset_mode(Mode.MOUSE_MOTION_TRACKING) + reset_mode(Mode.MOUSE_MOVE_TRACKING) +
        reset_mode(Mode.FOCUS_TRACKING) + reset_mode(Mode.MOUSE_UTF8_MODE) +
        reset_mode(Mode.MOUSE_SGR_MODE) + set_mode(Mode.BRACKETED_PASTE) + SAVE_COLORS +
        '\033[*x'  # reset DECSACE to default region select
    )
    if alternate_screen:
        ans += set_mode(Mode.ALTERNATE_SCREEN) + reset_mode(Mode.DECOM)
        ans += clear_screen()
    if mouse_tracking is not MouseTracking.none:
        ans += set_mode(Mode.MOUSE_SGR_PIXEL_MODE)
        if mouse_tracking is MouseTracking.buttons_only:
            ans += set_mode(Mode.MOUSE_BUTTON_TRACKING)
        elif mouse_tracking is MouseTracking.buttons_and_drag:
            ans += set_mode(Mode.MOUSE_MOTION_TRACKING)
        elif mouse_tracking is MouseTracking.full:
            ans += set_mode(Mode.MOUSE_MOVE_TRACKING)
    if kitty_keyboard_mode:
        ans += '\033[>31u'  # extended keyboard mode
    else:
        ans += '\033[>u'  # legacy keyboard mode
    return ans


def reset_state(normal_screen: bool = True) -> str:
    ans = '\033[<u'  # restore keyboard mode
    if normal_screen:
        ans += reset_mode(Mode.ALTERNATE_SCREEN)
    else:
        ans += SAVE_CURSOR
    ans += RESTORE_PRIVATE_MODE_VALUES
    ans += RESTORE_CURSOR
    ans += RESTORE_COLORS
    return ans


@contextmanager
def pending_update(write: Callable[[str], None]) -> Generator[None, None, None]:
    write(set_mode(Mode.PENDING_UPDATE))
    try:
        yield
    finally:
        write(reset_mode(Mode.PENDING_UPDATE))


@contextmanager
def cursor(write: Callable[[str], None]) -> Generator[None, None, None]:
    write(SAVE_CURSOR)
    try:
        yield
    finally:
        write(RESTORE_CURSOR)


@contextmanager
def alternate_screen() -> Generator[None, None, None]:
    with open(os.ctermid(), 'w') as f:
        print(set_mode(Mode.ALTERNATE_SCREEN), end='', file=f, flush=True)
        try:
            yield
        finally:
            print(reset_mode(Mode.ALTERNATE_SCREEN), end='', file=f, flush=True)


@contextmanager
def raw_mode(fd: int | None = None) -> Generator[None, None, None]:
    import termios
    import tty
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
    fg: Color | str | None = None,
    bg: Color | str | None = None,
    cursor: Color | str | None = None,
    select_bg: Color | str | None = None,
    select_fg: Color | str | None = None
) -> str:
    ans = ''

    def item(which: Color | str | None, num: int) -> None:
        nonlocal ans
        if which is None:
            ans += f'\x1b]1{num}\x1b\\'
        else:
            if isinstance(which, Color):
                q = color_as_sharp(which)
            else:
                x = to_color(which)
                assert x is not None
                q = color_as_sharp(x)
            ans += f'\x1b]{num};{q}\x1b\\'

    item(fg, 10)
    item(bg, 11)
    item(cursor, 12)
    item(select_bg, 17)
    item(select_fg, 19)
    return ans


@cmd
def save_colors() -> str:
    return '\x1b[#P'


@cmd
def restore_colors() -> str:
    return '\x1b[#Q'


@cmd
def overlay_ready() -> str:
    return '\x1bP@kitty-overlay-ready|\x1b\\'


@cmd
def write_to_clipboard(data: str | bytes, use_primary: bool = False) -> str:
    from base64 import standard_b64encode
    fmt = 'p' if use_primary else 'c'
    if isinstance(data, str):
        data = data.encode('utf-8')
    payload = standard_b64encode(data).decode('ascii')
    return f'\x1b]52;{fmt};{payload}\a'


@cmd
def request_from_clipboard(use_primary: bool = False) -> str:
    return '\x1b]52;{};?\a'.format('p' if use_primary else 'c')


# Boilerplate to make operations available via Handler.cmd  {{{


def writer(handler: HandlerType, func: Callable[..., bytes | str]) -> Callable[..., None]:
    @wraps(func)
    def f(*a: Any, **kw: Any) -> None:
        handler.write(func(*a, **kw))
    return f


def commander(handler: HandlerType) -> CMD:
    ans = CMD()
    for name, func in all_cmds.items():
        setattr(ans, name, writer(handler, func))
    return ans


def func_sig(func: Callable[..., Any]) -> Generator[str, None, None]:
    import inspect
    import re
    s = inspect.signature(func)
    for val in s.parameters.values():
        yield re.sub(r'ForwardRef\([\'"](\w+?)[\'"]\)', r'\1', str(val).replace('NoneType', 'None'))


def as_type_stub() -> str:
    ans = [
        'from typing import *  # noqa',
        'from kitty.typing_compat import GraphicsCommandType, ScreenSize',
        'from kitty.fast_data_types import Color',
        'import kitty.rgb',
        'import kittens.tui.operations',
    ]
    methods = []
    for name, func in all_cmds.items():
        args = ', '.join(func_sig(func))
        if args:
            args = f', {args}'
        methods.append(f'    def {name}(self{args}) -> str: pass')
    ans += ['', '', 'class CMD:'] + methods

    return '\n'.join(ans) + '\n\n\n'
# }}}
