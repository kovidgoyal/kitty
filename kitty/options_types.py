#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPLv3 Copyright: 2021, Kovid Goyal <kovid at kovidgoyal.net>


import os
import sys
from typing import (
    Callable, Dict, FrozenSet, Iterable, List, Optional, Tuple, Union
)

import kitty.fast_data_types as defines
from kitty.fast_data_types import CURSOR_BEAM, CURSOR_BLOCK, CURSOR_UNDERLINE

from .conf.utils import (
    positive_float, positive_int, to_bool, to_color, uniq, unit_float
)
from .constants import config_dir
from .fonts import FontFeature
from .key_names import (
    character_key_name_aliases, functional_key_name_aliases,
    get_key_name_lookup
)
from .layout.interface import all_layouts
from .rgb import Color, color_as_int
from .types import FloatEdges, SingleKey
from .utils import expandvars, log_error

MINIMUM_FONT_SIZE = 4
default_tab_separator = ' ┇'
mod_map = {'CTRL': 'CONTROL', 'CMD': 'SUPER', '⌘': 'SUPER',
           '⌥': 'ALT', 'OPTION': 'ALT', 'KITTY_MOD': 'KITTY'}
character_key_name_aliases_with_ascii_lowercase: Dict[str, str] = character_key_name_aliases.copy()
for x in 'ABCDEFGHIJKLMNOPQRSTUVWXYZ':
    character_key_name_aliases_with_ascii_lowercase[x] = x.lower()


class InvalidMods(ValueError):
    pass


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


def clipboard_control(x: str) -> FrozenSet[str]:
    return frozenset(x.lower().split())


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
