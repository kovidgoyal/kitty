#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2018, Kovid Goyal <kovid at kovidgoyal.net>

import os
import re
import shlex

from ..rgb import to_color as as_color
from ..utils import log_error

key_pat = re.compile(r'([a-zA-Z][a-zA-Z0-9_-]*)\s+(.+)$')


def to_color(x):
    return as_color(x, validate=True)


def to_color_or_none(x):
    return None if x.lower() == 'none' else to_color(x)


def positive_int(x):
    return max(0, int(x))


def positive_float(x):
    return max(0, float(x))


def unit_float(x):
    return max(0, min(float(x), 1))


def to_bool(x):
    return x.lower() in ('y', 'yes', 'true')


def to_cmdline(x):
    ans = shlex.split(x)
    ans[0] = os.path.expandvars(os.path.expanduser(ans[0]))
    return ans


def python_string(text):
    import ast
    return ast.literal_eval("'''" + text.replace("'''", "'\\''") + "'''")


def choices(*choices):
    defval = choices[0]
    choices = frozenset(choices)

    def choice(x):
        x = x.lower()
        if x not in choices:
            x = defval
        return x
    return choice


def parse_line(line, type_map, special_handling, ans, all_keys, base_path_for_includes):
    line = line.strip()
    if not line or line.startswith('#'):
        return
    m = key_pat.match(line)
    if m is None:
        log_error('Ignoring invalid config line: {}'.format(line))
        return
    key, val = m.groups()
    if special_handling(key, val, ans):
        return
    if key == 'include':
        val = os.path.expandvars(os.path.expanduser(val.strip()))
        if not os.path.isabs(val):
            val = os.path.join(base_path_for_includes, val)
        try:
            with open(val, encoding='utf-8', errors='replace') as include:
                _parse(include, type_map, special_handling, ans, all_keys)
        except FileNotFoundError:
            log_error('Could not find included config file: {}, ignoring'.format(val))
        except EnvironmentError:
            log_error('Could not read from included config file: {}, ignoring'.format(val))
        return
    if all_keys is not None and key not in all_keys:
        log_error('Ignoring unknown config key: {}'.format(key))
        return
    tm = type_map.get(key)
    if tm is not None:
        val = tm(val)
    ans[key] = val


def _parse(lines, type_map, special_handling, ans, all_keys):
    name = getattr(lines, 'name', None)
    if name:
        base_path_for_includes = os.path.dirname(os.path.abspath(name))
    else:
        from ..constants import config_dir
        base_path_for_includes = config_dir
    for line in lines:
        parse_line(line, type_map, special_handling, ans, all_keys, base_path_for_includes)


def parse_config_base(
    lines, defaults, type_map, special_handling, ans, check_keys=True
):
    all_keys = defaults._asdict() if check_keys else None
    _parse(lines, type_map, special_handling, ans, all_keys)


def create_options_class(keys):
    keys = tuple(sorted(keys))
    slots = keys + ('_fields',)

    def __init__(self, kw):
        for k, v in kw.items():
            setattr(self, k, v)

    def __iter__(self):
        return iter(keys)

    def __len__(self):
        return len(keys)

    def __getitem__(self, i):
        if isinstance(i, int):
            i = keys[i]
        try:
            return getattr(self, i)
        except AttributeError:
            raise KeyError('No option named: {}'.format(i))

    def _asdict(self):
        return {k: getattr(self, k) for k in self._fields}

    def _replace(self, **kw):
        ans = self._asdict()
        ans.update(kw)
        return self.__class__(ans)

    ans = type('Options', (), {
        '__slots__': slots, '__init__': __init__, '_asdict': _asdict, '_replace': _replace, '__iter__': __iter__,
        '__len__': __len__, '__getitem__': __getitem__
    })
    ans._fields = keys
    return ans


def merge_dicts(defaults, newvals):
    ans = defaults.copy()
    ans.update(newvals)
    return ans


def resolve_config(SYSTEM_CONF, defconf, config_files_on_cmd_line):
    if config_files_on_cmd_line:
        if 'NONE' not in config_files_on_cmd_line:
            yield SYSTEM_CONF
            for cf in config_files_on_cmd_line:
                yield cf
    else:
        yield SYSTEM_CONF
        yield defconf


def load_config(Options, defaults, parse_config, merge_configs, *paths, overrides=None):
    ans = defaults._asdict()
    for path in paths:
        if not path:
            continue
        try:
            f = open(path, encoding='utf-8', errors='replace')
        except FileNotFoundError:
            continue
        with f:
            vals = parse_config(f)
            ans = merge_configs(ans, vals)
    if overrides is not None:
        vals = parse_config(overrides)
        ans = merge_configs(ans, vals)
    return Options(ans)


def init_config(default_config_lines, parse_config):
    defaults = parse_config(default_config_lines, check_keys=False)
    Options = create_options_class(defaults.keys())
    defaults = Options(defaults)
    return Options, defaults


def key_func():
    ans = {}

    def func_with_args(*names):

        def w(f):
            for name in names:
                if ans.setdefault(name, f) is not f:
                    raise ValueError('the args_func {} is being redefined'.format(name))
            return f

        return w
    return func_with_args, ans


def parse_kittens_shortcut(sc):
    from ..key_encoding import config_key_map, config_mod_map, text_match
    if sc.endswith('+'):
        parts = list(filter(None, sc.rstrip('+').split('+') + ['+']))
    else:
        parts = sc.split('+')
    mods = parts[:-1] or None
    if mods is not None:
        resolved_mods = 0
        for mod in mods:
            m = config_mod_map.get(mod.upper())
            if m is None:
                raise ValueError('Unknown shortcut modifiers: {}'.format(sc))
            resolved_mods |= m
        mods = resolved_mods
    is_text = False
    rkey = parts[-1]
    tkey = text_match(rkey)
    if tkey is None:
        rkey = rkey.upper()
        rkey = config_key_map.get(rkey)
        if rkey is None:
            raise ValueError('Unknown shortcut key: {}'.format(sc))
    else:
        is_text = True
        rkey = tkey
    return mods, rkey, is_text


def parse_kittens_func_args(action, args_funcs):
    parts = action.strip().split(' ', 1)
    func = parts[0]
    if len(parts) == 1:
        return func, ()
    rest = parts[1]

    try:
        parser = args_funcs[func]
    except KeyError as e:
        raise KeyError(
            'Unknown action: {}. Check if map action: '
            '{} is valid'.format(func, action)
        ) from e

    try:
        func, args = parser(func, rest)
    except Exception:
        raise ValueError('Unknown key action: {}'.format(action))

    if not isinstance(args, (list, tuple)):
        args = (args,)

    return func, tuple(args)


def parse_kittens_key(val, funcs_with_args):
    sc, action = val.partition(' ')[::2]
    if not sc or not action:
        return
    mods, key, is_text = parse_kittens_shortcut(sc)
    action = parse_kittens_func_args(action, funcs_with_args)
    return action, key, mods, is_text
