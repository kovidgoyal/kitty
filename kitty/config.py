#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2016, Kovid Goyal <kovid at kovidgoyal.net>

import json
import os
import re
import sys
from collections import namedtuple
from contextlib import contextmanager

from . import fast_data_types as defines
from .conf.definition import as_conf_file, config_lines
from .conf.utils import (
    init_config, key_func, load_config as _load_config, merge_dicts,
    parse_config_base, python_string, to_bool, to_cmdline
)
from .config_data import all_options, parse_mods, type_map
from .constants import cache_dir, defconf, is_macos
from .utils import log_error

named_keys = {
    "'": 'APOSTROPHE',
    ',': 'COMMA',
    '-': 'MINUS',
    '.': 'PERIOD',
    '/': 'SLASH',
    ';': 'SEMICOLON',
    '=': 'EQUAL',
    '[': 'LEFT_BRACKET',
    ']': 'RIGHT_BRACKET',
    '`': 'GRAVE_ACCENT'
}


def parse_shortcut(sc):
    parts = sc.split('+')
    mods = 0
    if len(parts) > 1:
        mods = parse_mods(parts[:-1], sc)
        if mods is None:
            return None, None, None
    key = parts[-1].upper()
    key = getattr(defines, 'GLFW_KEY_' + named_keys.get(key, key), None)
    is_native = False
    if key is None:
        if parts[-1].startswith('0x'):
            try:
                key = int(parts[-1], 16)
            except Exception:
                pass
        else:
            key = defines.key_for_native_key_name(parts[-1])
        is_native = key is not None
    return mods, is_native, key


KeyAction = namedtuple('KeyAction', 'func args')
func_with_args, args_funcs = key_func()


@func_with_args(
    'pass_selection_to_program', 'new_window', 'new_tab', 'new_os_window',
    'new_window_with_cwd', 'new_tab_with_cwd', 'new_os_window_with_cwd'
    )
def shlex_parse(func, rest):
    return func, to_cmdline(rest)


@func_with_args('combine')
def combine_parse(func, rest):
    sep, rest = rest.split(maxsplit=1)
    parts = re.split(r'\s*' + re.escape(sep) + r'\s*', rest)
    args = tuple(map(parse_key_action, filter(None, parts)))
    return func, args


@func_with_args('send_text')
def send_text_parse(func, rest):
    args = rest.split(maxsplit=1)
    if len(args) > 0:
        try:
            args[1] = parse_send_text_bytes(args[1])
        except Exception:
            log_error('Ignoring invalid send_text string: ' + args[1])
            args[1] = ''
    return func, args


@func_with_args('run_kitten', 'run_simple_kitten', 'kitten')
def kitten_parse(func, rest):
    if func == 'kitten':
        args = rest.split(maxsplit=1)
    else:
        args = rest.split(maxsplit=2)[1:]
        func = 'kitten'
    return func, args


@func_with_args('goto_tab')
def goto_tab_parse(func, rest):
    args = (max(0, int(rest)), )
    return func, args


@func_with_args('set_background_opacity', 'goto_layout', 'kitty_shell')
def simple_parse(func, rest):
    return func, [rest]


@func_with_args('set_font_size')
def float_parse(func, rest):
    return func, (float(rest),)


@func_with_args('change_font_size')
def parse_change_font_size(func, rest):
    vals = rest.strip().split(maxsplit=1)
    if len(vals) != 2:
        log_error('Invalid change_font_size specification: {}, treating it as default'.format(rest))
        args = [True, None, 0]
    else:
        args = [vals[0].lower() == 'all', None, 0]
        amt = vals[1]
        if amt[0] in '+-':
            args[1] = amt[0]
            amt = amt[1:]
        args[2] = float(amt.strip())
    return func, args


@func_with_args('clear_terminal')
def clear_terminal(func, rest):
    vals = rest.strip().split(maxsplit=1)
    if len(vals) != 2:
        log_error('clear_terminal needs two arguments, using defaults')
        args = ['reset', 'active']
    else:
        args = [vals[0].lower(), vals[1].lower() == 'active']
    return func, args


@func_with_args('copy_to_buffer')
def copy_to_buffer(func, rest):
    return func, [rest]


@func_with_args('paste_from_buffer')
def paste_from_buffer(func, rest):
    return func, [rest]


@func_with_args('neighboring_window')
def neighboring_window(func, rest):
    rest = rest.lower()
    rest = {'up': 'top', 'down': 'bottom'}.get(rest, rest)
    if rest not in ('left', 'right', 'top', 'bottom'):
        log_error('Invalid neighbor specification: {}'.format(rest))
        rest = 'right'
    return func, [rest]


@func_with_args('resize_window')
def resize_window(func, rest):
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
def move_window(func, rest):
    rest = rest.lower()
    rest = {'up': 'top', 'down': 'bottom'}.get(rest, rest)
    try:
        rest = int(rest)
    except Exception:
        if rest not in ('left', 'right', 'top', 'bottom'):
            log_error('Invalid move_window specification: {}'.format(rest))
            rest = 0
    return func, [rest]


@func_with_args('pipe')
def pipe(func, rest):
    import shlex
    rest = shlex.split(rest)
    if len(rest) < 3:
        log_error('Too few arguments to pipe function')
        rest = ['none', 'none', 'true']
    return func, rest


@func_with_args('nth_window')
def nth_window(func, rest):
    try:
        num = int(rest)
    except Exception:
        log_error('Invalid nth_window number: {}'.format(rest))
        num = 1
    return func, [num]


def parse_key_action(action):
    parts = action.strip().split(maxsplit=1)
    func = parts[0]
    if len(parts) == 1:
        return KeyAction(func, ())
    rest = parts[1]
    parser = args_funcs.get(func)
    if parser is not None:
        try:
            func, args = parser(func, rest)
        except Exception:
            log_error('Ignoring invalid key action: {}'.format(action))
        else:
            return KeyAction(func, args)


all_key_actions = set()
sequence_sep = '>'


class KeyDefinition:

    def __init__(self, is_sequence, action, mods, is_native, key, rest=()):
        self.is_sequence = is_sequence
        self.action = action
        self.trigger = mods, is_native, key
        self.rest = rest

    def resolve(self, kitty_mod):
        self.trigger = defines.resolve_key_mods(kitty_mod, self.trigger[0]), self.trigger[1], self.trigger[2]
        self.rest = tuple((defines.resolve_key_mods(kitty_mod, mods), is_native, key) for mods, is_native, key in self.rest)


def parse_key(val, key_definitions):
    parts = val.split(maxsplit=1)
    if len(parts) != 2:
        return
    sc, action = parts
    sc, action = sc.strip().strip(sequence_sep), action.strip()
    if not sc or not action:
        return
    is_sequence = sequence_sep in sc
    if is_sequence:
        trigger = None
        rest = []
        for part in sc.split(sequence_sep):
            mods, is_native, key = parse_shortcut(part)
            if key is None:
                if mods is not None:
                    log_error('Shortcut: {} has unknown key, ignoring'.format(sc))
                return
            if trigger is None:
                trigger = mods, is_native, key
            else:
                rest.append((mods, is_native, key))
        rest = tuple(rest)
    else:
        mods, is_native, key = parse_shortcut(sc)
        if key is None:
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
            all_key_actions.add(paction.func)
            if is_sequence:
                key_definitions.append(KeyDefinition(True, paction, trigger[0], trigger[1], trigger[2], rest))
            else:
                key_definitions.append(KeyDefinition(False, paction, mods, is_native, key))


def parse_symbol_map(val):
    parts = val.split()
    symbol_map = {}

    def abort():
        log_error('Symbol map: {} is invalid, ignoring'.format(
            val))
        return {}

    if len(parts) < 2:
        return abort()
    family = ' '.join(parts[1:])

    def to_chr(x):
        if not x.startswith('U+'):
            raise ValueError()
        x = int(x[2:], 16)
        return x

    for x in parts[0].split(','):
        a, b = x.partition('-')[::2]
        b = b or a
        try:
            a, b = map(to_chr, (a, b))
        except Exception:
            return abort()
        if b < a or max(a, b) > sys.maxunicode or min(a, b) < 1:
            return abort()
        symbol_map[(a, b)] = family
    return symbol_map


def parse_send_text_bytes(text):
    return python_string(text).encode('utf-8')


def parse_send_text(val, key_definitions):
    parts = val.split(' ')

    def abort(msg):
        log_error('Send text: {} is invalid ({}), ignoring'.format(
            val, msg))
        return {}

    if len(parts) < 3:
        return abort('Incomplete')
    mode, sc = parts[:2]
    text = ' '.join(parts[2:])
    key_str = '{} send_text {} {}'.format(sc, mode, text)
    return parse_key(key_str, key_definitions)


special_handlers = {}


def special_handler(func):
    special_handlers[func.__name__.partition('_')[2]] = func
    return func


def deprecated_handler(*names):
    def special_handler(func):
        for name in names:
            special_handlers[name] = func
        return func
    return special_handler


@special_handler
def handle_map(key, val, ans):
    parse_key(val, ans['key_definitions'])


@special_handler
def handle_symbol_map(key, val, ans):
    ans['symbol_map'].update(parse_symbol_map(val))


@special_handler
def handle_send_text(key, val, ans):
    # For legacy compatibility
    parse_send_text(val, ans['key_definitions'])


@special_handler
def handle_clear_all_shortcuts(key, val, ans):
    if to_bool(val):
        ans['key_definitions'] = [None]


@deprecated_handler('x11_hide_window_decorations', 'macos_hide_titlebar')
def handle_deprecated_hide_window_decorations_aliases(key, val, ans):
    if not hasattr(handle_deprecated_hide_window_decorations_aliases, key):
        handle_deprecated_hide_window_decorations_aliases.key = True
        log_error('The option {} is deprecated. Use hide_window_decorations instead.'.format(key))
    if to_bool(val):
        ans['hide_window_decorations'] = True


def expandvars(val, env):

    def sub(m):
        key = m.group(1)
        result = env.get(key)
        if result is None:
            result = os.environ.get(key)
        if result is None:
            result = m.group()
        return result

    return re.sub(r'\$\{(\S+?)\}', sub, val)


@special_handler
def handle_env(key, val, ans):
    key, val = val.partition('=')[::2]
    key, val = key.strip(), val.strip()
    ans['env'][key] = expandvars(val, ans['env'])


def special_handling(key, val, ans):
    func = special_handlers.get(key)
    if func is not None:
        func(key, val, ans)
        return True


defaults = None


def option_names_for_completion():
    yield from defaults
    yield from special_handlers


def parse_config(lines, check_keys=True):
    ans = {'symbol_map': {}, 'keymap': {}, 'sequence_map': {}, 'key_definitions': [], 'env': {}}
    parse_config_base(
        lines,
        defaults,
        type_map,
        special_handling,
        ans,
        check_keys=check_keys
    )
    return ans


def parse_defaults(lines, check_keys=False):
    ans = parse_config(lines, check_keys)
    return ans


Options, defaults = init_config(config_lines(all_options), parse_defaults)
actions = frozenset(all_key_actions) | frozenset(
    'run_simple_kitten combine send_text goto_tab goto_layout set_font_size new_tab_with_cwd new_window_with_cwd new_os_window_with_cwd'.
    split()
)
no_op_actions = frozenset({'noop', 'no-op', 'no_op'})


def merge_configs(defaults, vals):
    ans = {}
    for k, v in defaults.items():
        if isinstance(v, dict):
            newvals = vals.get(k, {})
            ans[k] = merge_dicts(v, newvals)
        elif k == 'key_definitions':
            ans['key_definitions'] = v + vals.get('key_definitions', [])
        else:
            ans[k] = vals.get(k, v)
    return ans


def build_ansi_color_table(opts=defaults):

    def as_int(x):
        return (x[0] << 16) | (x[1] << 8) | x[2]

    def col(i):
        return as_int(getattr(opts, 'color{}'.format(i)))

    return list(map(col, range(256)))


def atomic_save(data, path):
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
def cached_values_for(name):
    cached_path = os.path.join(cache_dir(), name + '.json')
    cached_values = {}
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


def initial_window_size_func(opts, cached_values):

    if 'window-size' in cached_values and opts.remember_window_size:
        ws = cached_values['window-size']
        try:
            w, h = map(int, ws)

            def initial_window_size(*a):
                return w, h
            return initial_window_size
        except Exception:
            log_error('Invalid cached window size, ignoring')

    w, w_unit = opts.initial_window_width
    h, h_unit = opts.initial_window_height

    def get_window_size(cell_width, cell_height, dpi_x, dpi_y, xscale, yscale):
        if not is_macos:
            # scaling is not needed on Wayland, but is needed on macOS. Not
            # sure about X11.
            xscale = yscale = 1
        if w_unit == 'cells':
            width = cell_width * w / xscale + (dpi_x / 72) * (opts.window_margin_width + opts.window_padding_width) + 1
        else:
            width = w
        if h_unit == 'cells':
            height = cell_height * h / yscale + (dpi_y / 72) * (opts.window_margin_width + opts.window_padding_width) + 1
        else:
            height = h
        return width, height

    return get_window_size


def commented_out_default_config():
    ans = []
    for line in as_conf_file(all_options.values()):
        if line and line[0] != '#':
            line = '# ' + line
        ans.append(line)
    return '\n'.join(ans)


def prepare_config_file_for_editing():
    if not os.path.exists(defconf):
        d = os.path.dirname(defconf)
        try:
            os.makedirs(d)
        except FileExistsError:
            pass
        with open(defconf, 'w', encoding='utf-8') as f:
            f.write(commented_out_default_config())
    return defconf


def finalize_keys(opts):
    defns = []
    for d in opts.key_definitions:
        if d is None:  # clear_all_shortcuts
            defns = []
        else:
            defns.append(d)
    for d in defns:
        d.resolve(opts.kitty_mod)
    keymap = {}
    sequence_map = {}

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


def load_config(*paths, overrides=None):
    opts = _load_config(Options, defaults, parse_config, merge_configs, *paths, overrides=overrides)
    finalize_keys(opts)
    if opts.background_opacity < 1.0 and opts.macos_titlebar_color:
        log_error('Cannot use both macos_titlebar_color and background_opacity')
        opts.macos_titlebar_color = 0
    if (is_macos and getattr(opts, 'macos_hide_titlebar', False)) or (not is_macos and getattr(opts, 'x11_hide_window_decorations', False)):
        opts.hide_window_decorations = True
    return opts
