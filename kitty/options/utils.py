#!/usr/bin/env python
# License: GPLv3 Copyright: 2021, Kovid Goyal <kovid at kovidgoyal.net>


import enum
import re
import sys
from collections import defaultdict
from dataclasses import dataclass, fields
from functools import lru_cache
from typing import (
    Any,
    Callable,
    Container,
    Dict,
    FrozenSet,
    Generic,
    Iterable,
    Iterator,
    List,
    Literal,
    NamedTuple,
    Optional,
    Sequence,
    Tuple,
    TypeVar,
    Union,
    get_args,
)

import kitty.fast_data_types as defines
from kitty.conf.utils import (
    CurrentlyParsing,
    KeyAction,
    KeyFuncWrapper,
    currently_parsing,
    positive_float,
    positive_int,
    python_string,
    to_bool,
    to_cmdline,
    to_color,
    uniq,
    unit_float,
)
from kitty.constants import is_macos
from kitty.fast_data_types import CURSOR_BEAM, CURSOR_BLOCK, CURSOR_UNDERLINE, Color, Shlex, SingleKey
from kitty.fonts import FontFeature, FontModification, ModificationType, ModificationUnit, ModificationValue
from kitty.key_names import character_key_name_aliases, functional_key_name_aliases, get_key_name_lookup
from kitty.rgb import color_as_int
from kitty.types import FloatEdges, MouseEvent
from kitty.utils import expandvars, log_error, resolve_abs_or_config_path, shlex_split

KeyMap = Dict[SingleKey, List['KeyDefinition']]
MouseMap = Dict[MouseEvent, str]
KeySequence = Tuple[SingleKey, ...]
MINIMUM_FONT_SIZE = 4
default_tab_separator = ' ┇'
mod_map = {'⌃': 'CONTROL', 'CTRL': 'CONTROL', '⇧': 'SHIFT', '⌥': 'ALT', 'OPTION': 'ALT', 'OPT': 'ALT',
           '⌘': 'SUPER', 'COMMAND': 'SUPER', 'CMD': 'SUPER', 'KITTY_MOD': 'KITTY'}
character_key_name_aliases_with_ascii_lowercase: Dict[str, str] = character_key_name_aliases.copy()
for x in 'ABCDEFGHIJKLMNOPQRSTUVWXYZ':
    character_key_name_aliases_with_ascii_lowercase[x] = x.lower()
sequence_sep = '>'
mouse_button_map = {'left': 'b1', 'middle': 'b3', 'right': 'b2'}
mouse_trigger_count_map = {'doubleclick': -3, 'click': -2, 'release': -1, 'press': 1, 'doublepress': 2, 'triplepress': 3}
FuncArgsType = Tuple[str, Sequence[Any]]
func_with_args = KeyFuncWrapper[FuncArgsType]()
DELETE_ENV_VAR = '_delete_this_env_var_'


class MapType(enum.Enum):
    MAP = 'map'
    MOUSE_MAP = 'mouse_map'
    OPEN_ACTION = 'open_action'


class InvalidMods(ValueError):
    pass


# Actions {{{
@func_with_args(
    'pass_selection_to_program', 'new_window', 'new_tab', 'new_os_window',
    'new_window_with_cwd', 'new_tab_with_cwd', 'new_os_window_with_cwd',
    'launch', 'mouse_handle_click', 'show_error',
    )
def shlex_parse(func: str, rest: str) -> FuncArgsType:
    return func, to_cmdline(rest)


def parse_send_text_bytes(text: str) -> bytes:
    return defines.expand_ansi_c_escapes(text).encode('utf-8')


@func_with_args('send_text')
def send_text_parse(func: str, rest: str) -> FuncArgsType:
    args = rest.split(maxsplit=1)
    mode = ''
    data = b''
    if len(args) > 1:
        mode = args[0]
        try:
            data = parse_send_text_bytes(args[1])
        except Exception:
            log_error('Ignoring invalid send_text string: ' + args[1])
    return func, [mode, data]


@func_with_args('send_key')
def send_key(func: str, rest: str) -> FuncArgsType:
    return func, rest.split()


@func_with_args('run_kitten', 'run_simple_kitten', 'kitten')
def kitten_parse(func: str, rest: str) -> FuncArgsType:
    if func == 'kitten':
        args = rest.split(maxsplit=1)
    else:
        args = rest.split(maxsplit=2)[1:]
        func = 'kitten'
    return func, [args[0]] + (to_cmdline(args[1]) if len(args) > 1 else [])


@func_with_args('open_url')
def open_url_parse(func: str, rest: str) -> FuncArgsType:
    from urllib.parse import urlparse
    url = ''
    try:
        url = python_string(rest)
        tokens = urlparse(url)
        if not all((tokens.scheme, tokens.netloc,)):
            raise ValueError('Invalid URL')
    except Exception:
        log_error('Ignoring invalid URL string: ' + rest)
    return func, (url,)


@func_with_args('goto_tab')
def goto_tab_parse(func: str, rest: str) -> FuncArgsType:
    args = (max(0, int(rest)), )
    return func, args


@func_with_args('detach_window')
def detach_window_parse(func: str, rest: str) -> FuncArgsType:
    if rest not in ('new', 'new-tab', 'new-tab-neighbor', 'ask', 'tab-prev', 'tab-left', 'tab-right'):
        log_error(f'Ignoring invalid detach_window argument: {rest}')
        rest = 'new'
    return func, (rest,)


@func_with_args('close_window_with_confirmation')
def close_window_with_confirmation(func: str, rest: str) -> FuncArgsType:
    ignore_shell = rest == 'ignore-shell'
    return func, (ignore_shell,)


@func_with_args('detach_tab')
def detach_tab_parse(func: str, rest: str) -> FuncArgsType:
    if rest not in ('new', 'ask'):
        log_error(f'Ignoring invalid detach_tab argument: {rest}')
        rest = 'new'
    return func, (rest,)


@func_with_args('set_background_opacity', 'goto_layout', 'toggle_layout', 'kitty_shell', 'show_kitty_doc', 'set_tab_title', 'push_keyboard_mode')
def simple_parse(func: str, rest: str) -> FuncArgsType:
    return func, [rest]


@func_with_args('set_font_size')
def float_parse(func: str, rest: str) -> FuncArgsType:
    return func, (float(rest),)


@func_with_args('signal_child')
def signal_child_parse(func: str, rest: str) -> FuncArgsType:
    import signal
    signals = []
    for q in rest.split():
        try:
            signum = getattr(signal, q.upper())
        except AttributeError:
            log_error(f'Unknown signal: {rest} ignoring')
        else:
            signals.append(signum)
    return func, tuple(signals)


@func_with_args('change_font_size')
def parse_change_font_size(func: str, rest: str) -> Tuple[str, Tuple[bool, Optional[str], float]]:
    vals = rest.strip().split(maxsplit=1)
    if len(vals) != 2:
        log_error(f'Invalid change_font_size specification: {rest}, treating it as default')
        return func, (True, None, 0)
    c_all = vals[0].lower() == 'all'
    sign: Optional[str] = None
    amt = vals[1]
    if amt[0] in '+-':
        sign = amt[0]
        amt = amt[1:]
    return func, (c_all, sign, float(amt.strip()))


@func_with_args('clear_terminal')
def clear_terminal(func: str, rest: str) -> FuncArgsType:
    vals = rest.strip().split(maxsplit=1)
    if len(vals) != 2:
        log_error('clear_terminal needs two arguments, using defaults')
        args = ['reset', True]
    else:
        action = vals[0].lower()
        if action not in ('reset', 'scroll', 'scrollback', 'clear', 'to_cursor',):
            log_error(f'{action} is unknown for clear_terminal, using reset')
            action = 'reset'
        args = [action, vals[1].lower() == 'active']
    return func, args


@func_with_args('copy_to_buffer')
def copy_to_buffer(func: str, rest: str) -> FuncArgsType:
    return func, [rest]


@func_with_args('paste_from_buffer')
def paste_from_buffer(func: str, rest: str) -> FuncArgsType:
    return func, [rest]


@func_with_args('paste')
def paste_parse(func: str, rest: str) -> FuncArgsType:
    text = ''
    try:
        text = defines.expand_ansi_c_escapes(rest)
    except Exception:
        log_error('Ignoring invalid paste string: ' + rest)
    return func, [text]


@func_with_args('neighboring_window')
def neighboring_window(func: str, rest: str) -> FuncArgsType:
    rest = rest.lower()
    rest = {'up': 'top', 'down': 'bottom'}.get(rest, rest)
    if rest not in ('left', 'right', 'top', 'bottom'):
        log_error(f'Invalid neighbor specification: {rest}')
        rest = 'right'
    return func, [rest]


@func_with_args('resize_window')
def resize_window(func: str, rest: str) -> FuncArgsType:
    vals = rest.strip().split(maxsplit=1)
    if len(vals) > 2:
        log_error('resize_window needs one or two arguments, using defaults')
        args = ['wider', 1]
    else:
        quality = vals[0].lower()
        if quality not in ('reset', 'taller', 'shorter', 'wider', 'narrower'):
            log_error(f'Invalid quality specification: {quality}')
            quality = 'wider'
        increment = 1
        if len(vals) == 2:
            try:
                increment = int(vals[1])
            except Exception:
                log_error(f'Invalid increment specification: {vals[1]}')
        args = [quality, increment]
    return func, args


@func_with_args('move_window')
def move_window(func: str, rest: str) -> FuncArgsType:
    rest = rest.lower()
    rest = {'up': 'top', 'down': 'bottom'}.get(rest, rest)
    prest: Union[int, str] = rest
    try:
        prest = int(prest)
    except Exception:
        if prest not in ('left', 'right', 'top', 'bottom'):
            log_error(f'Invalid move_window specification: {rest}')
            prest = 0
    return func, [prest]


@func_with_args('pipe')
def pipe(func: str, rest: str) -> FuncArgsType:
    r = list(shlex_split(rest))
    if len(r) < 3:
        log_error('Too few arguments to pipe function')
        r = ['none', 'none', 'true']
    return func, r


@func_with_args('set_colors')
def set_colors(func: str, rest: str) -> FuncArgsType:
    r = list(shlex_split(rest))
    if len(r) < 1:
        log_error('Too few arguments to set_colors function')
    return func, r


@func_with_args('remote_control')
def remote_control(func: str, rest: str) -> FuncArgsType:
    func, args = shlex_parse(func, rest)
    if len(args) < 1:
        log_error('Too few arguments to remote_control function')
    return func, args


@func_with_args('remote_control_script')
def remote_control_script(func: str, rest: str) -> FuncArgsType:
    func, args = shlex_parse(func, rest)
    if len(args) < 1:
        log_error('Too few arguments to remote_control_script function')
    return func, args


@func_with_args('nth_os_window', 'nth_window', 'scroll_to_prompt', 'visual_window_select_action_trigger', 'next_layout')
def single_integer_arg(func: str, rest: str) -> FuncArgsType:
    try:
        num = int(rest)
    except Exception:
        if rest:
            log_error(f'Invalid number for {func}: {rest}')
        num = -1 if func == 'scroll_to_prompt' else 1
    return func, [num]


@func_with_args('sleep')
def sleep(func: str, sleep_time: str) -> FuncArgsType:
    mult = 1
    sleep_time = sleep_time or '1'
    if sleep_time[-1] in 'shmd':
        mult = {'s': 1, 'm': 60, 'h': 3600, 'd': 24 * 3600}[sleep_time[-1]]
        sleep_time = sleep_time[:-1]
    return func, [abs(float(sleep_time)) * mult]


@func_with_args('disable_ligatures_in')
def disable_ligatures_in(func: str, rest: str) -> FuncArgsType:
    parts = rest.split(maxsplit=1)
    if len(parts) == 1:
        where, strategy = 'active', parts[0]
    else:
        where, strategy = parts
    if where not in ('active', 'all', 'tab'):
        raise ValueError(f'{where} is not a valid set of windows to disable ligatures in')
    if strategy not in ('never', 'always', 'cursor'):
        raise ValueError(f'{strategy} is not a valid disable ligatures strategy')
    return func, [where, strategy]


@func_with_args('layout_action')
def layout_action(func: str, rest: str) -> FuncArgsType:
    parts = rest.split(maxsplit=1)
    if not parts:
        raise ValueError('layout_action must have at least one argument')
    return func, [parts[0], tuple(parts[1:])]


def parse_marker_spec(ftype: str, parts: Sequence[str]) -> Tuple[str, Union[str, Tuple[Tuple[int, str], ...]], int]:
    flags = re.UNICODE
    if ftype in ('text', 'itext', 'regex', 'iregex'):
        if ftype.startswith('i'):
            flags |= re.IGNORECASE
        if not parts or len(parts) % 2 != 0:
            raise ValueError('Mark group number and text/regex are not specified in pairs: {}'.format(' '.join(parts)))
        ans = []
        for i in range(0, len(parts), 2):
            try:
                color = max(1, min(int(parts[i]), 3))
            except Exception:
                raise ValueError(f'Mark group in marker specification is not an integer: {parts[i]}')
            sspec = parts[i + 1]
            if 'regex' not in ftype:
                sspec = re.escape(sspec)
            ans.append((color, sspec))
        ftype = 'regex'
        spec: Union[str, Tuple[Tuple[int, str], ...]] = tuple(ans)
    elif ftype == 'function':
        spec = ' '.join(parts)
    else:
        raise ValueError(f'Unknown marker type: {ftype}')
    return ftype, spec, flags


@func_with_args('toggle_marker')
def toggle_marker(func: str, rest: str) -> FuncArgsType:
    parts = rest.split(maxsplit=1)
    if len(parts) != 2:
        raise ValueError(f'{rest} is not a valid marker specification')
    ftype, spec = parts
    parts = list(shlex_split(spec))
    return func, list(parse_marker_spec(ftype, parts))


@func_with_args('scroll_to_mark')
def scroll_to_mark(func: str, rest: str) -> FuncArgsType:
    parts = rest.split()
    if not parts or not rest:
        return func, [True, 0]
    if len(parts) == 1:
        q = parts[0].lower()
        if q in ('prev', 'previous', 'next'):
            return func, [q != 'next', 0]
        try:
            return func, [True, max(0, min(int(q), 3))]
        except Exception:
            raise ValueError(f'{rest} is not a valid scroll_to_mark destination')
    return func, [parts[0] != 'next', max(0, min(int(parts[1]), 3))]


@func_with_args('mouse_selection')
def mouse_selection(func: str, rest: str) -> FuncArgsType:
    cmap = getattr(mouse_selection, 'code_map', None)
    if cmap is None:
        cmap = {
            'normal': defines.MOUSE_SELECTION_NORMAL,
            'extend': defines.MOUSE_SELECTION_EXTEND,
            'move-end': defines.MOUSE_SELECTION_MOVE_END,
            'rectangle': defines.MOUSE_SELECTION_RECTANGLE,
            'word': defines.MOUSE_SELECTION_WORD,
            'line': defines.MOUSE_SELECTION_LINE,
            'line_from_point': defines.MOUSE_SELECTION_LINE_FROM_POINT,
            'word_and_line_from_point': defines.MOUSE_SELECTION_WORD_AND_LINE_FROM_POINT,
        }
        setattr(mouse_selection, 'code_map', cmap)
    return func, [cmap[rest]]


@func_with_args('load_config_file')
def load_config_file(func: str, rest: str) -> FuncArgsType:
    return func, list(shlex_split(rest))
# }}}


def parse_mods(parts: Iterable[str], sc: str) -> Optional[int]:

    def map_mod(m: str) -> str:
        return mod_map.get(m, m)

    mods = 0
    for m in parts:
        try:
            mods |= getattr(defines, f'GLFW_MOD_{map_mod(m.upper())}')
        except AttributeError:
            if m.upper() != 'NONE':
                log_error(f'Shortcut: {sc} has unknown modifier, ignoring')
            return None

    return mods


def to_modifiers(val: str) -> int:
    return parse_mods(val.split('+'), val) or 0


def parse_shortcut(sc: str) -> SingleKey:
    if sc.endswith('+') and len(sc) > 1:
        sc = f'{sc[:-1]}plus'
    parts = sc.split('+')
    mods = 0
    if len(parts) > 1:
        mods = parse_mods(parts[:-1], sc) or 0
        if not mods:
            raise InvalidMods('Invalid shortcut')
    q = parts[-1]
    q = character_key_name_aliases_with_ascii_lowercase.get(q.upper(), q)
    is_native = False
    if q.startswith('0x'):
        try:
            key = int(q, 16)
        except Exception:
            key = 0
        else:
            is_native = True
    else:
        try:
            key = ord(q)
        except Exception:
            uq = q.upper()
            uq = functional_key_name_aliases.get(uq, uq)
            x: Optional[int] = getattr(defines, f'GLFW_FKEY_{uq}', None)
            if x is None:
                lf = get_key_name_lookup()
                key = lf(q, False) or 0
                is_native = key > 0
            else:
                key = x

    return SingleKey(mods, is_native, key or 0)


def to_font_size(x: str) -> float:
    return max(MINIMUM_FONT_SIZE, float(x))


def disable_ligatures(x: str) -> int:
    cmap = {'never': 0, 'cursor': 1, 'always': 2}
    return cmap.get(x.lower(), 0)


def box_drawing_scale(x: str) -> Tuple[float, float, float, float]:
    ans = tuple(float(q.strip()) for q in x.split(','))
    if len(ans) != 4:
        raise ValueError('Invalid box_drawing scale, must have four entries')
    return ans[0], ans[1], ans[2], ans[3]


def cursor_text_color(x: str) -> Optional[Color]:
    if x.lower() == 'background':
        return None
    return to_color(x)


cshapes = {
    'block': CURSOR_BLOCK,
    'beam': CURSOR_BEAM,
    'underline': CURSOR_UNDERLINE
}


def to_cursor_shape(x: str) -> int:
    try:
        return cshapes[x.lower()]
    except KeyError:
        raise ValueError(
            'Invalid cursor shape: {} allowed values are {}'.format(
                x, ', '.join(cshapes)
            )
        )


def scrollback_lines(x: str) -> int:
    ans = int(x)
    if ans < 0:
        ans = 2 ** 32 - 1
    return ans


def scrollback_pager_history_size(x: str) -> int:
    ans = int(max(0, float(x)) * 1024 * 1024)
    return min(ans, 4096 * 1024 * 1024 - 1)


# "single" for backwards compat
url_style_map = {'none': 0, 'single': 1, 'straight': 1, 'double': 2, 'curly': 3, 'dotted': 4, 'dashed': 5}


def url_style(x: str) -> int:
    return url_style_map.get(x, url_style_map['curly'])


def url_prefixes(x: str) -> Tuple[str, ...]:
    return tuple(a.lower() for a in x.replace(',', ' ').split())


def copy_on_select(raw: str) -> str:
    q = raw.lower()
    # boolean values special cased for backwards compat
    if q in ('y', 'yes', 'true', 'clipboard'):
        return 'clipboard'
    if q in ('n', 'no', 'false', ''):
        return ''
    return raw


def window_size(val: str) -> Tuple[int, str]:
    val = val.lower()
    unit = 'cells' if val.endswith('c') else 'px'
    return positive_int(val.rstrip('c')), unit


def parse_layout_names(parts: Iterable[str]) -> List[str]:
    from kitty.layout.interface import all_layouts
    ans = []
    for p in parts:
        p = p.lower()
        if p in ('*', 'all'):
            ans.extend(sorted(all_layouts))
            continue
        name = p.partition(':')[0]
        if name not in all_layouts:
            raise ValueError(f'The window layout {p} is unknown')
        ans.append(p)
    return uniq(ans)


def to_layout_names(raw: str) -> List[str]:
    return parse_layout_names(x.strip() for x in raw.split(','))


def window_border_width(x: Union[str, int, float]) -> Tuple[float, str]:
    unit = 'pt'
    if isinstance(x, str):
        trailer = x[-2:]
        if trailer in ('px', 'pt'):
            unit = trailer
            val = float(x[:-2])
        else:
            val = float(x)
    else:
        val = float(x)
    return max(0, val), unit


def edge_width(x: str, converter: Callable[[str], float] = positive_float) -> FloatEdges:
    parts = str(x).split()
    num = len(parts)
    if num == 1:
        val = converter(parts[0])
        return FloatEdges(val, val, val, val)
    if num == 2:
        v = converter(parts[0])
        h = converter(parts[1])
        return FloatEdges(h, v, h, v)
    if num == 3:
        top, h, bottom = map(converter, parts)
        return FloatEdges(h, top, h, bottom)
    top, right, bottom, left = map(converter, parts)
    return FloatEdges(left, top, right, bottom)


def optional_edge_width(x: str) -> FloatEdges:
    return edge_width(x, float)


def hide_window_decorations(x: str) -> int:
    if x == 'titlebar-only':
        return 0b10
    if x == 'titlebar-and-corners':
        return 0b100
    if to_bool(x):
        return 0b01
    return 0b00


def resize_draw_strategy(x: str) -> int:
    cmap = {'static': 0, 'scale': 1, 'blank': 2, 'size': 3}
    return cmap.get(x.lower(), 0)


def resize_debounce_time(x: str) -> Tuple[float, float]:
    parts = x.split(maxsplit=1)
    if len(parts) == 1:
        return positive_float(parts[0]), 0.5
    return positive_float(parts[0]), positive_float(parts[1])


def visual_window_select_characters(x: str) -> str:
    import string
    valid_characters = string.digits + string.ascii_uppercase + "-=[]\\;',./`"
    ans = x.upper()
    ans_chars = set(ans)
    if not ans_chars.issubset(set(valid_characters)):
        raise ValueError(f'Invalid characters in visual_window_select_characters: {x} Only numbers (0-9) and alphabets (a-z,A-Z) are allowed. Ignoring.')
    if len(ans_chars) < len(x):
        raise ValueError(f'Invalid characters in visual_window_select_characters: {x} Contains identical numbers or alphabets, case insensitive. Ignoring.')
    return ans


def tab_separator(x: str) -> str:
    for q in '\'"':
        if x.startswith(q) and x.endswith(q):
            x = x[1:-1]
            if not x:
                return ''
            break
    if not x.strip():
        x = ('\xa0' * len(x)) if x else default_tab_separator
    return x


def tab_bar_edge(x: str) -> int:
    return {'top': 1, 'bottom': 3}.get(x.lower(), 3)


def tab_font_style(x: str) -> Tuple[bool, bool]:
    return {
        'bold-italic': (True, True),
        'bold': (True, False),
        'italic': (False, True)
    }.get(x.lower().replace('_', '-'), (False, False))


def tab_bar_min_tabs(x: str) -> int:
    return max(1, positive_int(x))


def tab_fade(x: str) -> Tuple[float, ...]:
    return tuple(map(unit_float, x.split()))


def tab_activity_symbol(x: str) -> str:
    if x == 'none':
        return ''
    return tab_title_template(x)


def bell_on_tab(x: str) -> str:
    xl = x.lower()
    if xl in ('yes', 'y', 'true'):
        return '🔔 '
    if xl in ('no', 'n', 'false', 'none'):
        return ''
    return tab_title_template(x)


def tab_title_template(x: str) -> str:
    if x:
        for q in '\'"':
            if x.startswith(q) and x.endswith(q):
                x = x[1:-1]
                break
    return x


def active_tab_title_template(x: str) -> Optional[str]:
    x = tab_title_template(x)
    return None if x == 'none' else x


class NotifyOnCmdFinish(NamedTuple):
    when: str
    duration: float
    action: str
    cmdline: Tuple[str, ...]


def notify_on_cmd_finish(x: str) -> NotifyOnCmdFinish:
    parts = x.split(maxsplit=3)
    if parts[0] not in ('never', 'unfocused', 'invisible', 'always'):
        raise ValueError(f'Unknown notify_on_cmd_finish value: {parts[0]}')
    when = parts[0]
    duration = 5.0
    if len(parts) > 1:
        duration = float(parts[1])
    action = 'notify'
    cmdline: Tuple[str, ...] = ()
    if len(parts) > 2:
        if parts[2] not in ('notify', 'bell', 'command'):
            raise ValueError(f'Unknown notify_on_cmd_finish action: {parts[2]}')
        action = parts[2]
        if action == 'command':
            if len(parts) > 3:
                cmdline = tuple(to_cmdline(parts[3]))
            else:
                raise ValueError('notify_on_cmd_finish `command` action needs a command line')
    return NotifyOnCmdFinish(when, duration, action, cmdline)


def config_or_absolute_path(x: str, env: Optional[Dict[str, str]] = None) -> Optional[str]:
    if not x or x.lower() == 'none':
        return None
    return resolve_abs_or_config_path(x, env)


def remote_control_password(val: str, current_val: Dict[str, str]) -> Iterable[Tuple[str, Sequence[str]]]:
    val = val.strip()
    if val:
        parts = to_cmdline(val, expand=False)
        if parts[0].startswith('-'):
            # this is done so in the future we can add --options to the cmd
            # line of remote_control_password
            raise ValueError('Passwords are not allowed to start with hyphens, ignoring this password')
        if len(parts) == 1:
            yield parts[0], tuple()
        else:
            yield parts[0], tuple(parts[1:])


def clipboard_control(x: str) -> Tuple[str, ...]:
    return tuple(x.lower().split())


def allow_hyperlinks(x: str) -> int:
    if x == 'ask':
        return 0b11
    return 1 if to_bool(x) else 0


def titlebar_color(x: str) -> int:
    x = x.strip('"')
    if x == 'system':
        return 0
    if x == 'background':
        return 1
    try:
        return (color_as_int(to_color(x)) << 8) | 2
    except ValueError:
        log_error(f'Ignoring invalid title bar color: {x}')
    return 0


def macos_titlebar_color(x: str) -> int:
    x = x.strip('"')
    if x == 'light':
        return -1
    if x == 'dark':
        return -2
    return titlebar_color(x)


def macos_option_as_alt(x: str) -> int:
    x = x.lower()
    if x == 'both':
        return 0b11
    if x == 'left':
        return 0b10
    if x == 'right':
        return 0b01
    if to_bool(x):
        return 0b11
    return 0


class TabBarMarginHeight(NamedTuple):
    outer: float = 0
    inner: float = 0

    def __bool__(self) -> bool:
        return (self.outer + self.inner) > 0


def tab_bar_margin_height(x: str) -> TabBarMarginHeight:
    parts = x.split(maxsplit=1)
    if len(parts) != 2:
        log_error(f'Invalid tab_bar_margin_height: {x}, ignoring')
        return TabBarMarginHeight()
    ans = map(positive_float, parts)
    return TabBarMarginHeight(next(ans), next(ans))


def clone_source_strategies(x: str) -> FrozenSet[str]:
    return frozenset({'venv', 'conda', 'path', 'env_var'} & set(x.lower().split(',')))


def clear_all_mouse_actions(val: str, dict_with_parse_results: Optional[Dict[str, Any]] = None) -> bool:
    ans = to_bool(val)
    if ans and dict_with_parse_results is not None:
        dict_with_parse_results['mouse_map'] = [None]
    return ans


def clear_all_shortcuts(val: str, dict_with_parse_results: Optional[Dict[str, Any]] = None) -> bool:
    ans = to_bool(val)
    if ans and dict_with_parse_results is not None:
        dict_with_parse_results['map'] = [None]
    return ans


def font_features(val: str) -> Iterable[Tuple[str, Tuple[FontFeature, ...]]]:
    if val == 'none':
        return
    parts = val.split()
    if len(parts) < 2:
        log_error(f"Ignoring invalid font_features {val}")
        return
    if parts[0]:
        features = []
        for feat in parts[1:]:
            try:
                parsed = defines.parse_font_feature(feat)
            except ValueError:
                log_error(f'Ignoring invalid font feature: {feat}')
            else:
                features.append(FontFeature(feat, parsed))
        yield parts[0], tuple(features)


def modify_font(val: str) -> Iterable[Tuple[str, FontModification]]:
    parts = val.split()
    pos, plen = 0, len(parts)
    if plen < 2:
        log_error(f"Ignoring invalid modify_font: {val}")
        return
    mtype: Optional[ModificationType] = getattr(ModificationType, parts[pos], None)
    if mtype is None:
        log_error(f"Ignoring invalid modify_font with unknown modification type: {parts[pos]}")
        return
    pos += 1
    font_name = ''
    if mtype is ModificationType.size:
        font_name = parts[pos]
        pos += 1
    if plen - pos < 1:
        log_error(f"Ignoring invalid modify_font: {val}")
        return
    sz = parts[pos]
    pos += 1
    munit = ModificationUnit.pt
    if sz.endswith('%'):
        munit = ModificationUnit.percent
        sz = sz[:-1]
    elif sz.endswith('px'):
        munit = ModificationUnit.pixel
        sz = sz[:-2]
    try:
        mvalue = float(sz)
    except Exception:
        log_error(f'Ignoring modify_font with invalid size: {sz}')
        return
    key = mtype.name
    if font_name:
        key += f':{font_name}'
    yield key, FontModification(mtype, ModificationValue(mvalue, munit), font_name)


def env(val: str, current_val: Dict[str, str]) -> Iterable[Tuple[str, str]]:
    val = val.strip()
    if val:
        if '=' in val:
            key, v = val.split('=', 1)
            key, v = key.strip(), v.strip()
            if key:
                if v:
                    v = expandvars(v, current_val)
                yield key, v
        else:
            yield val, DELETE_ENV_VAR


def store_multiple(val: str, current_val: Container[str]) -> Iterable[Tuple[str, str]]:
    val = val.strip()
    if val not in current_val:
        yield val, val


def menu_map(val: str, current_val: Container[str]) -> Iterable[Tuple[Tuple[str, ...], str]]:
    parts = val.split(maxsplit=1)
    if len(parts) != 2:
        raise ValueError(f'Ignoring invalid menu action: {val}')
    if parts[0] != 'global':
        raise ValueError(f'Unknown menu type: {parts[0]}. Known types: global')
    start = 0
    if parts[1].startswith('"'):
        start = 1
        idx = parts[1].find('"', 1)
        if idx == -1:
            raise ValueError(f'The menu entry name in {val} must end with a double quote')
    else:
        idx = parts[1].find(' ')
        if idx == -1:
            raise ValueError(f'The menu entry {val} must have an action')
    location = ('global',) + tuple(parts[1][start:idx].split('::'))
    yield location, parts[1][idx+1:].lstrip()


allowed_shell_integration_values = frozenset({'enabled', 'disabled', 'no-rc', 'no-cursor', 'no-title', 'no-prompt-mark', 'no-complete', 'no-cwd', 'no-sudo'})


def shell_integration(x: str) -> FrozenSet[str]:
    q = frozenset(x.lower().split())
    if not q.issubset(allowed_shell_integration_values):
        log_error(f'Invalid shell integration options: {q - allowed_shell_integration_values}, ignoring')
        return q & allowed_shell_integration_values or frozenset({'invalid'})
    return q


def paste_actions(x: str) -> FrozenSet[str]:
    s = frozenset({'quote-urls-at-prompt', 'confirm', 'filter', 'confirm-if-large', 'replace-dangerous-control-codes', 'replace-newline', 'no-op'})
    q = frozenset(x.lower().split(','))
    if not q.issubset(s):
        raise ValueError(f'Invalid paste actions: {q - s}, ignoring')
    return q


def action_alias(val: str) -> Iterable[Tuple[str, str]]:
    parts = val.split(maxsplit=1)
    if len(parts) > 1:
        alias_name, rest = parts
        yield alias_name, rest


kitten_alias = action_alias


def symbol_map_parser(val: str, min_size: int = 2) -> Iterable[Tuple[Tuple[int, int], str]]:
    parts = val.split()

    def abort() -> None:
        log_error(f'Symbol map: {val} is invalid, ignoring')

    if len(parts) < min_size:
        return abort()
    family = ' '.join(parts[1:])

    def to_chr(x: str) -> int:
        if not x.startswith('U+'):
            raise ValueError(f'{x} is not a unicode codepoint of the form U+number')
        return int(x[2:], 16)

    for x in parts[0].split(','):
        a_, b_ = x.replace('–', '-').partition('-')[::2]
        b_ = b_ or a_
        try:
            a, b = map(to_chr, (a_, b_))
        except Exception:
            return abort()
        if b < a or max(a, b) > sys.maxunicode or min(a, b) < 1:
            return abort()
        yield (a, b), family


def symbol_map(val: str) -> Iterable[Tuple[Tuple[int, int], str]]:
    yield from symbol_map_parser(val)


def narrow_symbols(val: str) -> Iterable[Tuple[Tuple[int, int], int]]:
    for x, y in symbol_map_parser(val, min_size=1):
        yield x, int(y or 1)


def parse_key_action(action: str, action_type: MapType = MapType.MAP) -> KeyAction:
    parts = action.strip().split(maxsplit=1)
    func = parts[0]
    if len(parts) == 1:
        return KeyAction(func, ())
    rest = parts[1]
    parser = func_with_args.get(func)
    if parser is None:
        raise KeyError(f'Unknown action: {func}')
    func, args = parser(func, rest)
    return KeyAction(func, tuple(args))


class ActionAlias(NamedTuple):
    name: str
    value: str
    replace_second_arg: bool = False


class AliasMap:

    def __init__(self) -> None:
        self.aliases: Dict[str, List[ActionAlias]] = {}

    def append(self, name: str, aa: ActionAlias) -> None:
        self.aliases.setdefault(name, []).append(aa)

    def update(self, aa: 'AliasMap') -> None:
        self.aliases.update(aa.aliases)

    @lru_cache(maxsize=256)
    def resolve_aliases(self, definition: str, map_type: MapType = MapType.MAP) -> Tuple[KeyAction, ...]:
        return tuple(resolve_aliases_and_parse_actions(definition, self.aliases, map_type))


def build_action_aliases(raw: Dict[str, str], first_arg_replacement: str = '') -> AliasMap:
    ans = AliasMap()
    if first_arg_replacement:
        for alias_name, rest in raw.items():
            ans.append(first_arg_replacement, ActionAlias(alias_name, rest, True))
    else:
        for alias_name, rest in raw.items():
            ans.append(alias_name, ActionAlias(alias_name, rest))
    return ans


def resolve_aliases_and_parse_actions(
    defn: str, aliases: Dict[str, List[ActionAlias]], map_type: MapType
) -> Iterator[KeyAction]:
    parts = defn.split(maxsplit=1)
    if len(parts) == 1:
        possible_alias = defn
        rest = ''
    else:
        possible_alias = parts[0]
        rest = parts[1]
    for alias in aliases.get(possible_alias, ()):
        if alias.replace_second_arg:  # kitten_alias
            if not rest:
                continue
            parts = rest.split(maxsplit=1)
            if parts[0] != alias.name:
                continue
            new_defn = f'{possible_alias} {alias.value}{f" {parts[1]}" if len(parts) > 1 else ""}'
            new_aliases = aliases.copy()
            new_aliases[possible_alias] = [a for a in aliases[possible_alias] if a is not alias]
            yield from resolve_aliases_and_parse_actions(new_defn, new_aliases, map_type)
            return
        else:  # action_alias
            new_defn = f'{alias.value} {rest}' if rest else alias.value
            new_aliases = aliases.copy()
            new_aliases.pop(possible_alias)
            yield from resolve_aliases_and_parse_actions(new_defn, new_aliases, map_type)
            return

    if possible_alias == 'combine':
        sep, rest = rest.split(maxsplit=1)
        parts = re.split(fr'\s*{re.escape(sep)}\s*', rest)
        for x in parts:
            if x:
                yield from resolve_aliases_and_parse_actions(x, aliases, map_type)
    else:
        yield parse_key_action(defn, map_type)


class BaseDefinition:
    no_op_actions = frozenset(('noop', 'no-op', 'no_op'))
    map_type: MapType = MapType.MAP
    definition_location: CurrentlyParsing

    def __init__(self, definition: str = '') -> None:
        if definition in BaseDefinition.no_op_actions:
            definition = ''
        self.definition = definition
        self.definition_location = currently_parsing.__copy__()

    def pretty_repr(self, *fields: str) -> str:
        kwds = []
        defaults = self.__class__()
        for f in fields:
            val = getattr(self, f)
            if val != getattr(defaults, f):
                kwds.append(f'{f}={val!r}')
        if self.definition:
            kwds.append(f'definition={self.definition!r}')
        return f'{self.__class__.__name__}({", ".join(kwds)})'


def resolve_key_mods(kitty_mod: int, mods: int) -> int:
    return SingleKey(mods=mods).resolve_kitty_mod(kitty_mod).mods


class MouseMapping(BaseDefinition):
    map_type: MapType = MapType.MOUSE_MAP

    def __init__(
        self, button: int = 0, mods: int = 0, repeat_count: int = 1, grabbed: bool = False,
        definition: str = ''
    ):
        super().__init__(definition)
        self.button = button
        self.mods = mods
        self.repeat_count = repeat_count
        self.grabbed = grabbed

    def __repr__(self) -> str:
        return self.pretty_repr('button', 'mods', 'repeat_count', 'grabbed')

    def resolve_and_copy(self, kitty_mod: int) -> 'MouseMapping':
        ans = MouseMapping(
            self.button, resolve_key_mods(kitty_mod, self.mods), self.repeat_count, self.grabbed,
            self.definition)
        ans.definition_location = self.definition_location
        return ans

    @property
    def trigger(self) -> MouseEvent:
        return MouseEvent(self.button, self.mods, self.repeat_count, self.grabbed)


T = TypeVar('T')


class LiteralField(Generic[T]):
    def __init__(self, vals: Tuple[T, ...]):
        self._vals = vals

    def __set_name__(self, owner: object, name: str) -> None:
        self._name = "_" + name

    def __get__(self, obj: object, type: Optional[type] = None) -> T:
        if obj is None:
            return self._vals[0]
        return getattr(obj, self._name, self._vals[0])

    def __set__(self, obj: object, value: str) -> None:
        if value not in self._vals:
            raise KeyError(f'Invalid value for {self._name[1:]}: {value!r}')
        object.__setattr__(obj, self._name, value)


OnUnknown = Literal['beep', 'end', 'ignore', 'passthrough']
OnAction = Literal['keep', 'end']


@dataclass(init=False, frozen=True)
class KeyMapOptions:
    when_focus_on: str = ''
    new_mode: str = ''
    mode: str = ''
    on_unknown: LiteralField[OnUnknown] = LiteralField[OnUnknown](get_args(OnUnknown))
    on_action: LiteralField[OnAction] = LiteralField[OnAction](get_args(OnAction))


default_key_map_options = KeyMapOptions()
allowed_key_map_options = frozenset(f.name for f in fields(KeyMapOptions))


class KeyDefinition(BaseDefinition):

    def __init__(
        self, is_sequence: bool = False, trigger: SingleKey = SingleKey(),
        rest: Tuple[SingleKey, ...] = (), definition: str = '',
        options: KeyMapOptions = default_key_map_options
    ):
        super().__init__(definition)
        self.is_sequence = is_sequence
        self.trigger = trigger
        self.rest = rest
        self.options = options

    @property
    def is_suitable_for_global_shortcut(self) -> bool:
        return not self.options.when_focus_on and not self.options.mode and not self.options.new_mode and not self.is_sequence

    @property
    def full_key_sequence_to_trigger(self) -> Tuple[SingleKey, ...]:
        return (self.trigger,) + self.rest

    @property
    def unique_identity_within_keymap(self) -> Tuple[Tuple[SingleKey, ...], str]:
        return self.full_key_sequence_to_trigger, self.options.when_focus_on

    def __repr__(self) -> str:
        return self.pretty_repr('is_sequence', 'trigger', 'rest', 'options')

    def human_repr(self) -> str:
        ans = self.definition or 'no-op'
        if self.options.when_focus_on:
            ans = f'[--when-focus-on={self.options.when_focus_on}]{ans}'
        return ans

    def shift_sequence_and_copy(self) -> 'KeyDefinition':
        return KeyDefinition(self.is_sequence, self.trigger, self.rest[1:], self.definition, self.options)

    def resolve_and_copy(self, kitty_mod: int) -> 'KeyDefinition':
        def r(k: SingleKey) -> SingleKey:
            return k.resolve_kitty_mod(kitty_mod)
        ans = KeyDefinition(
            self.is_sequence, r(self.trigger), tuple(map(r, self.rest)),
            self.definition, self.options
        )
        ans.definition_location = self.definition_location
        return ans


class KeyboardMode:

    on_unknown: OnUnknown = get_args(OnUnknown)[0]
    on_action : OnAction = get_args(OnAction)[0]
    sequence_keys: Optional[List[defines.KeyEvent]] = None

    def __init__(self, name: str = '') -> None:
        self.name = name
        self.keymap: KeyMap = defaultdict(list)


KeyboardModeMap = Dict[str, KeyboardMode]


def parse_options_for_map(val: str) -> Tuple[KeyMapOptions, str]:
    expecting_arg = ''
    ans = KeyMapOptions()
    s = Shlex(val)
    while (tok := s.next_word())[0] > -1:
        x = tok[1]
        if expecting_arg:
            object.__setattr__(ans, expecting_arg, x)
            expecting_arg = ''
        elif x.startswith('--'):
            expecting_arg = x[2:]
            k, sep, v = expecting_arg.partition('=')
            k = k.replace('-', '_')
            expecting_arg = k
            if expecting_arg not in allowed_key_map_options:
                raise KeyError(f'The map option {x} is unknown. Allowed options: {", ".join(allowed_key_map_options)}')
            if sep == '=':
                object.__setattr__(ans, k, v)
                expecting_arg = ''
        else:
            return ans, val[tok[0]:]
    return ans, ''


def parse_map(val: str) -> Iterable[KeyDefinition]:
    parts = val.split(maxsplit=1)
    options = default_key_map_options
    if len(parts) == 2:
        sc, action = parts
        if sc.startswith('--'):
            options, leftover = parse_options_for_map(val)
            parts = leftover.split(maxsplit=1)
            if len(parts) == 1:
                sc, action = parts[0], ''
            else:
                sc = parts[0]
                action = ' '.join(parts[1:])
    else:
        sc, action = val, ''
    sc, action = sc.strip().strip(sequence_sep), action.strip()
    if not sc:
        return
    is_sequence = sequence_sep in sc
    if is_sequence:
        trigger: Optional[SingleKey] = None
        restl: List[SingleKey] = []
        for part in sc.split(sequence_sep):
            try:
                mods, is_native, key = parse_shortcut(part)
            except InvalidMods:
                return
            if key == 0:
                if mods is not None:
                    log_error(f'Shortcut: {sc} has unknown key, ignoring')
                return
            if trigger is None:
                trigger = SingleKey(mods, is_native, key)
            else:
                restl.append(SingleKey(mods, is_native, key))
        rest = tuple(restl)
    else:
        try:
            mods, is_native, key = parse_shortcut(sc)
        except InvalidMods:
            return
        if key == 0:
            if mods is not None:
                log_error(f'Shortcut: {sc} has unknown key, ignoring')
            return
    if is_sequence:
        if trigger is not None:
            yield KeyDefinition(True, trigger, rest, definition=action, options=options)
    else:
        assert key is not None
        yield KeyDefinition(False, SingleKey(mods, is_native, key), definition=action, options=options)


def parse_mouse_map(val: str) -> Iterable[MouseMapping]:
    parts = val.split(maxsplit=3)
    if len(parts) == 4:
        xbutton, event, modes, action = parts
    elif len(parts) > 2:
        xbutton, event, modes = parts
        action = ''
    else:
        log_error(f'Ignoring invalid mouse action: {val}')
        return
    kparts = xbutton.split('+')
    if len(kparts) > 1:
        mparts, obutton = kparts[:-1], kparts[-1].lower()
        mods = parse_mods(mparts, obutton)
        if mods is None:
            return
    else:
        obutton = parts[0].lower()
        mods = 0
    try:
        b = mouse_button_map.get(obutton, obutton)[1:]
        button = getattr(defines, f'GLFW_MOUSE_BUTTON_{b}')
    except Exception:
        log_error(f'Mouse button: {xbutton} not recognized, ignoring')
        return
    try:
        count = mouse_trigger_count_map[event.lower()]
    except KeyError:
        log_error(f'Mouse event type: {event} not recognized, ignoring')
        return
    specified_modes = frozenset(modes.lower().split(','))
    if specified_modes - {'grabbed', 'ungrabbed'}:
        log_error(f'Mouse modes: {modes} not recognized, ignoring')
        return
    for mode in sorted(specified_modes):
        yield MouseMapping(button, mods, count, mode == 'grabbed', definition=action)


def deprecated_hide_window_decorations_aliases(key: str, val: str, ans: Dict[str, Any]) -> None:
    if not hasattr(deprecated_hide_window_decorations_aliases, key):
        setattr(deprecated_hide_window_decorations_aliases, key, True)
        log_error(f'The option {key} is deprecated. Use hide_window_decorations instead.')
    if to_bool(val):
        if is_macos and key == 'macos_hide_titlebar' or (not is_macos and key == 'x11_hide_window_decorations'):
            ans['hide_window_decorations'] = True


def deprecated_macos_show_window_title_in_menubar_alias(key: str, val: str, ans: Dict[str, Any]) -> None:
    if not hasattr(deprecated_macos_show_window_title_in_menubar_alias, key):
        setattr(deprecated_macos_show_window_title_in_menubar_alias, 'key', True)
        log_error(f'The option {key} is deprecated. Use macos_show_window_title_in menubar instead.')
    macos_show_window_title_in = ans.get('macos_show_window_title_in', 'all')
    if to_bool(val):
        if macos_show_window_title_in == 'none':
            macos_show_window_title_in = 'menubar'
        elif macos_show_window_title_in == 'window':
            macos_show_window_title_in = 'all'
    else:
        if macos_show_window_title_in == 'all':
            macos_show_window_title_in = 'window'
        elif macos_show_window_title_in == 'menubar':
            macos_show_window_title_in = 'none'
    ans['macos_show_window_title_in'] = macos_show_window_title_in


def deprecated_send_text(key: str, val: str, ans: Dict[str, Any]) -> None:
    parts = val.split(' ')

    def abort(msg: str) -> None:
        log_error(f'Send text: {val} is invalid ({msg}), ignoring')

    if len(parts) < 3:
        return abort('Incomplete')
    mode, sc = parts[:2]
    text = ' '.join(parts[2:])
    key_str = f'{sc} send_text {mode} {text}'
    for k in parse_map(key_str):
        ans['map'].append(k)


def deprecated_adjust_line_height(key: str, x: str, opts_dict: Dict[str, Any]) -> None:
    fm = {'adjust_line_height': 'cell_height', 'adjust_baseline': 'baseline', 'adjust_column_width': 'cell_width'}[key]
    mtype = getattr(ModificationType, fm)
    if x.endswith('%'):
        ans = float(x[:-1].strip())
        if ans < 0:
            log_error(f'Percentage adjustments of {key} must be positive numbers')
            return
        opts_dict['modify_font'][fm] = FontModification(mtype, ModificationValue(ans, ModificationUnit.percent))
    else:
        opts_dict['modify_font'][fm] = FontModification(mtype, ModificationValue(int(x), ModificationUnit.pixel))
