#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPLv3 Copyright: 2021, Kovid Goyal <kovid at kovidgoyal.net>


import os
import re
import sys
from typing import (
    Any, Callable, Dict, Iterable, List, NamedTuple, Optional, Sequence, Tuple,
    Union
)

import kitty.fast_data_types as defines
from kitty.conf.utils import (
    KeyAction, key_func, positive_float, positive_int, python_string, to_bool,
    to_cmdline, to_color, uniq, unit_float
)
from kitty.constants import config_dir, is_macos
from kitty.fast_data_types import CURSOR_BEAM, CURSOR_BLOCK, CURSOR_UNDERLINE
from kitty.fonts import FontFeature
from kitty.key_names import (
    character_key_name_aliases, functional_key_name_aliases,
    get_key_name_lookup
)
from kitty.rgb import Color, color_as_int
from kitty.types import FloatEdges, MouseEvent, SingleKey
from kitty.utils import expandvars, log_error

KeyMap = Dict[SingleKey, KeyAction]
MouseMap = Dict[MouseEvent, KeyAction]
KeySequence = Tuple[SingleKey, ...]
SubSequenceMap = Dict[KeySequence, KeyAction]
SequenceMap = Dict[SingleKey, SubSequenceMap]
MINIMUM_FONT_SIZE = 4
default_tab_separator = ' ┇'
mod_map = {'CTRL': 'CONTROL', 'CMD': 'SUPER', '⌘': 'SUPER',
           '⌥': 'ALT', 'OPTION': 'ALT', 'KITTY_MOD': 'KITTY'}
character_key_name_aliases_with_ascii_lowercase: Dict[str, str] = character_key_name_aliases.copy()
for x in 'ABCDEFGHIJKLMNOPQRSTUVWXYZ':
    character_key_name_aliases_with_ascii_lowercase[x] = x.lower()
sequence_sep = '>'
func_with_args, args_funcs = key_func()
FuncArgsType = Tuple[str, Sequence[Any]]


class InvalidMods(ValueError):
    pass


# Actions {{{
@func_with_args(
    'pass_selection_to_program', 'new_window', 'new_tab', 'new_os_window',
    'new_window_with_cwd', 'new_tab_with_cwd', 'new_os_window_with_cwd',
    'launch'
    )
def shlex_parse(func: str, rest: str) -> FuncArgsType:
    return func, to_cmdline(rest)


@func_with_args('combine')
def combine_parse(func: str, rest: str) -> FuncArgsType:
    sep, rest = rest.split(maxsplit=1)
    parts = re.split(r'\s*' + re.escape(sep) + r'\s*', rest)
    args = tuple(map(parse_key_action, filter(None, parts)))
    return func, args


def parse_send_text_bytes(text: str) -> bytes:
    return python_string(text).encode('utf-8')


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


@func_with_args('run_kitten', 'run_simple_kitten', 'kitten')
def kitten_parse(func: str, rest: str) -> FuncArgsType:
    if func == 'kitten':
        args = rest.split(maxsplit=1)
    else:
        args = rest.split(maxsplit=2)[1:]
        func = 'kitten'
    return func, args


@func_with_args('goto_tab')
def goto_tab_parse(func: str, rest: str) -> FuncArgsType:
    args = (max(0, int(rest)), )
    return func, args


@func_with_args('detach_window')
def detach_window_parse(func: str, rest: str) -> FuncArgsType:
    if rest not in ('new', 'new-tab', 'ask'):
        log_error('Ignoring invalid detach_window argument: {}'.format(rest))
        rest = 'new'
    return func, (rest,)


@func_with_args('detach_tab')
def detach_tab_parse(func: str, rest: str) -> FuncArgsType:
    if rest not in ('new', 'ask'):
        log_error('Ignoring invalid detach_tab argument: {}'.format(rest))
        rest = 'new'
    return func, (rest,)


@func_with_args('set_background_opacity', 'goto_layout', 'toggle_layout', 'kitty_shell')
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
        log_error('Invalid change_font_size specification: {}, treating it as default'.format(rest))
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
        args: List[Union[str, bool]] = ['reset', 'active']
    else:
        args = [vals[0].lower(), vals[1].lower() == 'active']
    return func, args


@func_with_args('copy_to_buffer')
def copy_to_buffer(func: str, rest: str) -> FuncArgsType:
    return func, [rest]


@func_with_args('paste_from_buffer')
def paste_from_buffer(func: str, rest: str) -> FuncArgsType:
    return func, [rest]


@func_with_args('neighboring_window')
def neighboring_window(func: str, rest: str) -> FuncArgsType:
    rest = rest.lower()
    rest = {'up': 'top', 'down': 'bottom'}.get(rest, rest)
    if rest not in ('left', 'right', 'top', 'bottom'):
        log_error('Invalid neighbor specification: {}'.format(rest))
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
        if quality not in ('taller', 'shorter', 'wider', 'narrower'):
            log_error('Invalid quality specification: {}'.format(quality))
            quality = 'wider'
        increment = 1
        if len(vals) == 2:
            try:
                increment = int(vals[1])
            except Exception:
                log_error('Invalid increment specification: {}'.format(vals[1]))
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
            log_error('Invalid move_window specification: {}'.format(rest))
            prest = 0
    return func, [prest]


@func_with_args('pipe')
def pipe(func: str, rest: str) -> FuncArgsType:
    import shlex
    r = shlex.split(rest)
    if len(r) < 3:
        log_error('Too few arguments to pipe function')
        r = ['none', 'none', 'true']
    return func, r


@func_with_args('set_colors')
def set_colors(func: str, rest: str) -> FuncArgsType:
    import shlex
    r = shlex.split(rest)
    if len(r) < 1:
        log_error('Too few arguments to set_colors function')
    return func, r


@func_with_args('remote_control')
def remote_control(func: str, rest: str) -> FuncArgsType:
    import shlex
    r = shlex.split(rest)
    if len(r) < 1:
        log_error('Too few arguments to remote_control function')
    return func, r


@func_with_args('nth_window')
def nth_window(func: str, rest: str) -> FuncArgsType:
    try:
        num = int(rest)
    except Exception:
        log_error('Invalid nth_window number: {}'.format(rest))
        num = 1
    return func, [num]


@func_with_args('disable_ligatures_in')
def disable_ligatures_in(func: str, rest: str) -> FuncArgsType:
    parts = rest.split(maxsplit=1)
    if len(parts) == 1:
        where, strategy = 'active', parts[0]
    else:
        where, strategy = parts
    if where not in ('active', 'all', 'tab'):
        raise ValueError('{} is not a valid set of windows to disable ligatures in'.format(where))
    if strategy not in ('never', 'always', 'cursor'):
        raise ValueError('{} is not a valid disable ligatures strategy'.format(strategy))
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
            raise ValueError('No color specified in marker: {}'.format(' '.join(parts)))
        ans = []
        for i in range(0, len(parts), 2):
            try:
                color = max(1, min(int(parts[i]), 3))
            except Exception:
                raise ValueError('color {} in marker specification is not an integer'.format(parts[i]))
            sspec = parts[i + 1]
            if 'regex' not in ftype:
                sspec = re.escape(sspec)
            ans.append((color, sspec))
        ftype = 'regex'
        spec: Union[str, Tuple[Tuple[int, str], ...]] = tuple(ans)
    elif ftype == 'function':
        spec = ' '.join(parts)
    else:
        raise ValueError('Unknown marker type: {}'.format(ftype))
    return ftype, spec, flags


@func_with_args('toggle_marker')
def toggle_marker(func: str, rest: str) -> FuncArgsType:
    import shlex
    parts = rest.split(maxsplit=1)
    if len(parts) != 2:
        raise ValueError('{} is not a valid marker specification'.format(rest))
    ftype, spec = parts
    parts = shlex.split(spec)
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
            raise ValueError('{} is not a valid scroll_to_mark destination'.format(rest))
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
        }
        setattr(mouse_selection, 'code_map', cmap)
    return func, [cmap[rest]]


@func_with_args('load_config_file')
def load_config_file(func: str, rest: str) -> FuncArgsType:
    import shlex
    return func, shlex.split(rest)
# }}}


def parse_mods(parts: Iterable[str], sc: str) -> Optional[int]:

    def map_mod(m: str) -> str:
        return mod_map.get(m, m)

    mods = 0
    for m in parts:
        try:
            mods |= getattr(defines, 'GLFW_MOD_' + map_mod(m.upper()))
        except AttributeError:
            if m.upper() != 'NONE':
                log_error('Shortcut: {} has unknown modifier, ignoring'.format(sc))
            return None

    return mods


def to_modifiers(val: str) -> int:
    return parse_mods(val.split('+'), val) or 0


def parse_shortcut(sc: str) -> SingleKey:
    if sc.endswith('+') and len(sc) > 1:
        sc = sc[:-1] + 'plus'
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


def adjust_line_height(x: str) -> Union[int, float]:
    if x.endswith('%'):
        ans = float(x[:-1].strip()) / 100.0
        if ans < 0:
            log_error('Percentage adjustments of cell sizes must be positive numbers')
            return 0
        return ans
    return int(x)


def adjust_baseline(x: str) -> Union[int, float]:
    if x.endswith('%'):
        ans = float(x[:-1].strip()) / 100.0
        if abs(ans) > 1:
            log_error('Percentage adjustments of the baseline cannot exceed 100%')
            return 0
        return ans
    return int(x)


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


def url_style(x: str) -> int:
    return url_style_map.get(x, url_style_map['curly'])


url_style_map = dict(
    ((v, i) for i, v in enumerate('none single double curly'.split()))
)


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


def to_layout_names(raw: str) -> List[str]:
    from kitty.layout.interface import all_layouts
    parts = [x.strip().lower() for x in raw.split(',')]
    ans: List[str] = []
    for p in parts:
        if p in ('*', 'all'):
            ans.extend(sorted(all_layouts))
            continue
        name = p.partition(':')[0]
        if name not in all_layouts:
            raise ValueError('The window layout {} is unknown'.format(p))
        ans.append(p)
    return uniq(ans)


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
    if to_bool(x):
        return 0b01
    return 0b00


def resize_draw_strategy(x: str) -> int:
    cmap = {'static': 0, 'scale': 1, 'blank': 2, 'size': 3}
    return cmap.get(x.lower(), 0)


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


def tab_activity_symbol(x: str) -> Optional[str]:
    if x == 'none':
        return None
    return x or None


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


def config_or_absolute_path(x: str) -> Optional[str]:
    if x.lower() == 'none':
        return None
    x = os.path.expanduser(x)
    x = os.path.expandvars(x)
    if not os.path.isabs(x):
        x = os.path.join(config_dir, x)
    return x


def allow_remote_control(x: str) -> str:
    if x != 'socket-only':
        x = 'y' if to_bool(x) else 'n'
    return x


def clipboard_control(x: str) -> Tuple[str, ...]:
    return tuple(x.lower().split())


def allow_hyperlinks(x: str) -> int:
    if x == 'ask':
        return 0b11
    return 1 if to_bool(x) else 0


def macos_titlebar_color(x: str) -> int:
    x = x.strip('"')
    if x == 'system':
        return 0
    if x == 'background':
        return 1
    return (color_as_int(to_color(x)) << 8) | 2


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
        log_error(f'Invalid tab_bar_margin_height: {tab_bar_margin_height}, ignoring')
        return TabBarMarginHeight()
    ans = map(positive_float, parts)
    return TabBarMarginHeight(next(ans), next(ans))


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
        log_error("Ignoring invalid font_features {}".format(val))
        return
    if parts[0]:
        features = []
        for feat in parts[1:]:
            try:
                parsed = defines.parse_font_feature(feat)
            except ValueError:
                log_error('Ignoring invalid font feature: {}'.format(feat))
            else:
                features.append(FontFeature(feat, parsed))
        yield parts[0], tuple(features)


def env(val: str, current_val: Dict[str, str]) -> Iterable[Tuple[str, str]]:
    key, val = val.partition('=')[::2]
    key, val = key.strip(), val.strip()
    if key:
        yield key, expandvars(val, current_val)


def kitten_alias(val: str) -> Iterable[Tuple[str, List[str]]]:
    parts = val.split(maxsplit=2)
    if len(parts) >= 2:
        name = parts.pop(0)
        yield name, parts


def symbol_map(val: str) -> Iterable[Tuple[Tuple[int, int], str]]:
    parts = val.split()

    def abort() -> Dict[Tuple[int, int], str]:
        log_error(f'Symbol map: {val} is invalid, ignoring')

    if len(parts) < 2:
        return abort()
    family = ' '.join(parts[1:])

    def to_chr(x: str) -> int:
        if not x.startswith('U+'):
            raise ValueError()
        return int(x[2:], 16)

    for x in parts[0].split(','):
        a_, b_ = x.partition('-')[::2]
        b_ = b_ or a_
        try:
            a, b = map(to_chr, (a_, b_))
        except Exception:
            return abort()
        if b < a or max(a, b) > sys.maxunicode or min(a, b) < 1:
            return abort()
        yield (a, b), family


def parse_key_action(action: str, action_type: str = 'map') -> Optional[KeyAction]:
    parts = action.strip().split(maxsplit=1)
    func = parts[0]
    if len(parts) == 1:
        return KeyAction(func, ())
    rest = parts[1]
    parser = args_funcs.get(func)
    if parser is not None:
        try:
            func, args = parser(func, rest)
        except Exception as err:
            log_error(f'Ignoring invalid {action_type} action: {action} with err: {err}')
        else:
            return KeyAction(func, tuple(args))
    else:
        log_error(f'Ignoring unknown {action_type} action: {action}')
    return None


class BaseDefinition:
    action: KeyAction

    def resolve_kitten_aliases(self, aliases: Dict[str, List[str]]) -> KeyAction:
        if not self.action.args or not aliases:
            return self.action
        kitten = self.action.args[0]
        rest = str(self.action.args[1] if len(self.action.args) > 1 else '')
        changed = False
        for key, expanded in aliases.items():
            if key == kitten:
                changed = True
                kitten = expanded[0]
                if len(expanded) > 1:
                    rest = expanded[1] + ' ' + rest
        return self.action._replace(args=(kitten, rest.rstrip())) if changed else self.action


class MouseMapping(BaseDefinition):

    def __init__(self, button: int, mods: int, repeat_count: int, grabbed: bool, action: KeyAction):
        self.button = button
        self.mods = mods
        self.repeat_count = repeat_count
        self.grabbed = grabbed
        self.action = action

    def __repr__(self) -> str:
        return f'MouseMapping({self.button}, {self.mods}, {self.repeat_count}, {self.grabbed}, {self.action})'

    def resolve_and_copy(self, kitty_mod: int, aliases: Dict[str, List[str]]) -> 'MouseMapping':
        return MouseMapping(self.button, defines.resolve_key_mods(kitty_mod, self.mods), self.repeat_count, self.grabbed, self.resolve_kitten_aliases(aliases))

    @property
    def trigger(self) -> MouseEvent:
        return MouseEvent(self.button, self.mods, self.repeat_count, self.grabbed)


class KeyDefinition(BaseDefinition):

    def __init__(self, is_sequence: bool, action: KeyAction, mods: int, is_native: bool, key: int, rest: Tuple[SingleKey, ...] = ()):
        self.is_sequence = is_sequence
        self.action = action
        self.trigger = SingleKey(mods, is_native, key)
        self.rest = rest

    def __repr__(self) -> str:
        return f'KeyDefinition({self.is_sequence}, {self.action}, {self.trigger.mods}, {self.trigger.is_native}, {self.trigger.key}, {self.rest})'

    def resolve_and_copy(self, kitty_mod: int, aliases: Dict[str, List[str]]) -> 'KeyDefinition':
        def r(k: SingleKey) -> SingleKey:
            mods = defines.resolve_key_mods(kitty_mod, k.mods)
            return k._replace(mods=mods)
        return KeyDefinition(
            self.is_sequence, self.resolve_kitten_aliases(aliases),
            defines.resolve_key_mods(kitty_mod, self.trigger.mods),
            self.trigger.is_native, self.trigger.key, tuple(map(r, self.rest)))


def parse_map(val: str) -> Iterable[KeyDefinition]:
    parts = val.split(maxsplit=1)
    if len(parts) != 2:
        return
    sc, action = parts
    sc, action = sc.strip().strip(sequence_sep), action.strip()
    if not sc or not action:
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
                    log_error('Shortcut: {} has unknown key, ignoring'.format(sc))
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
                log_error('Shortcut: {} has unknown key, ignoring'.format(sc))
            return
    try:
        paction = parse_key_action(action)
    except Exception:
        log_error('Invalid shortcut action: {}. Ignoring.'.format(
            action))
    else:
        if paction is not None:
            if is_sequence:
                if trigger is not None:
                    yield KeyDefinition(True, paction, trigger[0], trigger[1], trigger[2], rest)
            else:
                assert key is not None
                yield KeyDefinition(False, paction, mods, is_native, key)


def parse_mouse_map(val: str) -> Iterable[MouseMapping]:
    parts = val.split(maxsplit=3)
    if len(parts) != 4:
        log_error(f'Ignoring invalid mouse action: {val}')
        return
    xbutton, event, modes, action = parts
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
        b = {'left': 'b1', 'middle': 'b3', 'right': 'b2'}.get(obutton, obutton)[1:]
        button = getattr(defines, f'GLFW_MOUSE_BUTTON_{b}')
    except Exception:
        log_error(f'Mouse button: {xbutton} not recognized, ignoring')
        return
    try:
        count = {'doubleclick': -3, 'click': -2, 'release': -1, 'press': 1, 'doublepress': 2, 'triplepress': 3}[event.lower()]
    except KeyError:
        log_error(f'Mouse event type: {event} not recognized, ignoring')
        return
    specified_modes = frozenset(modes.lower().split(','))
    if specified_modes - {'grabbed', 'ungrabbed'}:
        log_error(f'Mouse modes: {modes} not recognized, ignoring')
        return
    try:
        paction = parse_key_action(action, 'mouse_map')
    except Exception:
        log_error(f'Invalid mouse action: {action}. Ignoring.')
        return
    if paction is None:
        return
    for mode in sorted(specified_modes):
        yield MouseMapping(button, mods, count, mode == 'grabbed', paction)


def deprecated_hide_window_decorations_aliases(key: str, val: str, ans: Dict[str, Any]) -> None:
    if not hasattr(deprecated_hide_window_decorations_aliases, key):
        setattr(deprecated_hide_window_decorations_aliases, key, True)
        log_error('The option {} is deprecated. Use hide_window_decorations instead.'.format(key))
    if to_bool(val):
        if is_macos and key == 'macos_hide_titlebar' or (not is_macos and key == 'x11_hide_window_decorations'):
            ans['hide_window_decorations'] = True


def deprecated_macos_show_window_title_in_menubar_alias(key: str, val: str, ans: Dict[str, Any]) -> None:
    if not hasattr(deprecated_macos_show_window_title_in_menubar_alias, key):
        setattr(deprecated_macos_show_window_title_in_menubar_alias, 'key', True)
        log_error('The option {} is deprecated. Use macos_show_window_title_in menubar instead.'.format(key))
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
        log_error('Send text: {} is invalid ({}), ignoring'.format(
            val, msg))

    if len(parts) < 3:
        return abort('Incomplete')
    mode, sc = parts[:2]
    text = ' '.join(parts[2:])
    key_str = '{} send_text {} {}'.format(sc, mode, text)
    for k in parse_map(key_str):
        ans['map'].append(k)
