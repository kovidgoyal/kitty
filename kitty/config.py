#!/usr/bin/env python3
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2016, Kovid Goyal <kovid at kovidgoyal.net>

import json
import os
from contextlib import contextmanager, suppress
from functools import partial
from typing import (
    Any, Callable, Dict, FrozenSet, Generator, Iterable, List, Optional,
    Tuple, Type
)

from .conf.definition import as_conf_file, config_lines
from .conf.utils import (
    BadLine, init_config, load_config as _load_config, merge_dicts,
    parse_config_base, to_bool
)
from .config_data import all_options
from .constants import cache_dir, defconf, is_macos
from .options_stub import Options as OptionsStub
from .options.utils import (
    KeyDefinition, KeyMap, MouseMap, MouseMapping, SequenceMap, env,
    font_features, kitten_alias, parse_map, parse_mouse_map, symbol_map
)
from .typing import TypedDict
from .utils import log_error


def parse_send_text(val: str, key_definitions: List[KeyDefinition]) -> None:
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
        key_definitions.append(k)


SpecialHandlerFunc = Callable[[str, str, Dict[str, Any]], None]
special_handlers: Dict[str, SpecialHandlerFunc] = {}


def special_handler(func: SpecialHandlerFunc) -> SpecialHandlerFunc:
    special_handlers[func.__name__.partition('_')[2]] = func
    return func


def deprecated_handler(*names: str) -> Callable[[SpecialHandlerFunc], SpecialHandlerFunc]:
    def special_handler(func: SpecialHandlerFunc) -> SpecialHandlerFunc:
        for name in names:
            special_handlers[name] = func
        return func
    return special_handler


@special_handler
def handle_map(key: str, val: str, ans: Dict[str, Any]) -> None:
    for k in parse_map(val):
        ans['key_definitions'].append(k)


@special_handler
def handle_mouse_map(key: str, val: str, ans: Dict[str, Any]) -> None:
    for ma in parse_mouse_map(val):
        ans['mouse_mappings'].append(ma)


@special_handler
def handle_symbol_map(key: str, val: str, ans: Dict[str, Any]) -> None:
    for k, v in symbol_map(val):
        ans['symbol_map'][k] = v


@special_handler
def handle_font_features(key: str, val: str, ans: Dict[str, Any]) -> None:
    for key, features in font_features(val):
        ans['font_features'][key] = features


@special_handler
def handle_kitten_alias(key: str, val: str, ans: Dict[str, Any]) -> None:
    for k, v in kitten_alias(val):
        ans['kitten_alias'][k] = v


@special_handler
def handle_send_text(key: str, val: str, ans: Dict[str, Any]) -> None:
    # For legacy compatibility
    parse_send_text(val, ans['key_definitions'])


@special_handler
def handle_clear_all_shortcuts(key: str, val: str, ans: Dict[str, Any]) -> None:
    if to_bool(val):
        ans['key_definitions'] = [None]


@deprecated_handler('x11_hide_window_decorations', 'macos_hide_titlebar')
def handle_deprecated_hide_window_decorations_aliases(key: str, val: str, ans: Dict[str, Any]) -> None:
    if not hasattr(handle_deprecated_hide_window_decorations_aliases, key):
        setattr(handle_deprecated_hide_window_decorations_aliases, key, True)
        log_error('The option {} is deprecated. Use hide_window_decorations instead.'.format(key))
    if to_bool(val):
        if is_macos and key == 'macos_hide_titlebar' or (not is_macos and key == 'x11_hide_window_decorations'):
            ans['hide_window_decorations'] = True


@deprecated_handler('macos_show_window_title_in_menubar')
def handle_deprecated_macos_show_window_title_in_menubar_alias(key: str, val: str, ans: Dict[str, Any]) -> None:
    if not hasattr(handle_deprecated_macos_show_window_title_in_menubar_alias, key):
        setattr(handle_deprecated_macos_show_window_title_in_menubar_alias, 'key', True)
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


@special_handler
def handle_env(key: str, val: str, ans: Dict[str, Any]) -> None:
    for key, val in env(val, ans['env']):
        ans['env'][key] = val


def special_handling(key: str, val: str, ans: Dict[str, Any]) -> bool:
    func = special_handlers.get(key)
    if func is not None:
        func(key, val, ans)
        return True


def option_names_for_completion() -> Generator[str, None, None]:
    yield from defaults
    yield from special_handlers


def parse_config(lines: Iterable[str], check_keys: bool = True, accumulate_bad_lines: Optional[List[BadLine]] = None) -> Dict[str, Any]:
    ans: Dict[str, Any] = {
        'symbol_map': {}, 'keymap': {}, 'sequence_map': {}, 'key_definitions': [],
        'env': {}, 'kitten_alias': {}, 'font_features': {}, 'mouse_mappings': [],
        'mousemap': {}
    }
    defs: Optional[FrozenSet] = None
    if check_keys:
        defs = frozenset(defaults._fields)  # type: ignore

    parse_config_base(
        lines,
        defs,
        all_options,
        special_handling,
        ans,
        accumulate_bad_lines=accumulate_bad_lines
    )
    return ans


def parse_defaults(lines: Iterable[str], check_keys: bool = False) -> Dict[str, Any]:
    return parse_config(lines, check_keys)


xc = init_config(config_lines(all_options), parse_defaults)
Options: Type[OptionsStub] = xc[0]
defaults: OptionsStub = xc[1]
no_op_actions = frozenset({'noop', 'no-op', 'no_op'})


def merge_configs(defaults: Dict, vals: Dict) -> Dict:
    ans = {}
    for k, v in defaults.items():
        if isinstance(v, dict):
            newvals = vals.get(k, {})
            ans[k] = merge_dicts(v, newvals)
        elif k in ('key_definitions', 'mouse_mappings'):
            ans[k] = v + vals.get(k, [])
        else:
            ans[k] = vals.get(k, v)
    return ans


def build_ansi_color_table(opts: OptionsStub = defaults) -> List[int]:

    def as_int(x: Tuple[int, int, int]) -> int:
        return (x[0] << 16) | (x[1] << 8) | x[2]

    def col(i: int) -> int:
        return as_int(getattr(opts, 'color{}'.format(i)))

    return list(map(col, range(256)))


def atomic_save(data: bytes, path: str) -> None:
    import tempfile
    fd, p = tempfile.mkstemp(dir=os.path.dirname(path), suffix='.tmp')
    try:
        with os.fdopen(fd, 'wb') as f:
            f.write(data)
        os.rename(p, path)
    finally:
        try:
            os.remove(p)
        except FileNotFoundError:
            pass
        except Exception as err:
            log_error('Failed to delete temp file {} for atomic save with error: {}'.format(
                p, err))


@contextmanager
def cached_values_for(name: str) -> Generator[Dict, None, None]:
    cached_path = os.path.join(cache_dir(), name + '.json')
    cached_values: Dict = {}
    try:
        with open(cached_path, 'rb') as f:
            cached_values.update(json.loads(f.read().decode('utf-8')))
    except FileNotFoundError:
        pass
    except Exception as err:
        log_error('Failed to load cached in {} values with error: {}'.format(
            name, err))

    yield cached_values

    try:
        data = json.dumps(cached_values).encode('utf-8')
        atomic_save(data, cached_path)
    except Exception as err:
        log_error('Failed to save cached values with error: {}'.format(
            err))


def commented_out_default_config() -> str:
    ans = []
    for line in as_conf_file(all_options.values()):
        if line and line[0] != '#':
            line = '# ' + line
        ans.append(line)
    return '\n'.join(ans)


def prepare_config_file_for_editing() -> str:
    if not os.path.exists(defconf):
        d = os.path.dirname(defconf)
        with suppress(FileExistsError):
            os.makedirs(d)
        with open(defconf, 'w', encoding='utf-8') as f:
            f.write(commented_out_default_config())
    return defconf


def finalize_keys(opts: OptionsStub) -> None:
    defns: List[KeyDefinition] = []
    for d in getattr(opts, 'key_definitions'):
        if d is None:  # clear_all_shortcuts
            defns = []
        else:
            defns.append(d.resolve_and_copy(opts.kitty_mod, opts.kitten_alias))
    keymap: KeyMap = {}
    sequence_map: SequenceMap = {}

    for defn in defns:
        is_no_op = defn.action.func in no_op_actions
        if defn.is_sequence:
            keymap.pop(defn.trigger, None)
            s = sequence_map.setdefault(defn.trigger, {})
            if is_no_op:
                s.pop(defn.rest, None)
                if not s:
                    del sequence_map[defn.trigger]
            else:
                s[defn.rest] = defn.action
        else:
            sequence_map.pop(defn.trigger, None)
            if is_no_op:
                keymap.pop(defn.trigger, None)
            else:
                keymap[defn.trigger] = defn.action
    opts.keymap = keymap
    opts.sequence_map = sequence_map


def finalize_mouse_mappings(opts: OptionsStub) -> None:
    defns: List[MouseMapping] = []
    for d in getattr(opts, 'mouse_mappings'):
        if d is None:  # clear_all_shortcuts
            defns = []
        else:
            defns.append(d.resolve_and_copy(opts.kitty_mod, opts.kitten_alias))

    mousemap: MouseMap = {}
    for defn in defns:
        is_no_op = defn.action.func in no_op_actions
        if is_no_op:
            mousemap.pop(defn.trigger, None)
        else:
            mousemap[defn.trigger] = defn.action
    opts.mousemap = mousemap


def load_config(*paths: str, overrides: Optional[Iterable[str]] = None, accumulate_bad_lines: Optional[List[BadLine]] = None) -> OptionsStub:
    parser = parse_config
    if accumulate_bad_lines is not None:
        parser = partial(parse_config, accumulate_bad_lines=accumulate_bad_lines)
    opts = _load_config(Options, defaults, parser, merge_configs, *paths, overrides=overrides)
    finalize_keys(opts)
    finalize_mouse_mappings(opts)
    # delete no longer needed definitions, replacing with empty placeholders
    setattr(opts, 'kitten_alias', {})
    setattr(opts, 'mouse_mappings', [])
    setattr(opts, 'key_definitions', [])
    if opts.background_opacity < 1.0 and opts.macos_titlebar_color:
        log_error('Cannot use both macos_titlebar_color and background_opacity')
        opts.macos_titlebar_color = 0
    return opts


class KittyCommonOpts(TypedDict):
    select_by_word_characters: str
    open_url_with: List[str]
    url_prefixes: Tuple[str, ...]


def common_opts_as_dict(opts: Optional[OptionsStub] = None) -> KittyCommonOpts:
    if opts is None:
        opts = defaults
    return {
        'select_by_word_characters': opts.select_by_word_characters,
        'open_url_with': opts.open_url_with,
        'url_prefixes': opts.url_prefixes,
    }
