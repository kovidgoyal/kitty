#!/usr/bin/env python3
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2018, Kovid Goyal <kovid at kovidgoyal.net>

import os
import re
import shlex
from collections import namedtuple
from typing import (
    Any, Callable, Dict, FrozenSet, Iterable, List, Optional, Sequence, Tuple,
    Type, Union
)

from ..rgb import Color, to_color as as_color
from ..utils import log_error

key_pat = re.compile(r'([a-zA-Z][a-zA-Z0-9_-]*)\s+(.+)$')
BadLine = namedtuple('BadLine', 'number line exception')


def to_color(x: str) -> Color:
    ans = as_color(x, validate=True)
    if ans is None:  # this is only for type-checking
        ans = Color(0, 0, 0)
    return ans


def to_color_or_none(x: str) -> Optional[Color]:
    return None if x.lower() == 'none' else to_color(x)


ConvertibleToNumbers = Union[str, bytes, int, float]


def positive_int(x: ConvertibleToNumbers) -> int:
    return max(0, int(x))


def positive_float(x: ConvertibleToNumbers) -> float:
    return max(0, float(x))


def unit_float(x: ConvertibleToNumbers) -> float:
    return max(0, min(float(x), 1))


def to_bool(x: str) -> bool:
    return x.lower() in ('y', 'yes', 'true')


def to_cmdline(x: str) -> List[str]:
    return list(
        map(
            lambda y: os.path.expandvars(os.path.expanduser(y)),
            shlex.split(x)
        )
    )


def python_string(text: str) -> str:
    import ast
    ans: str = ast.literal_eval("'''" + text.replace("'''", "'\\''") + "'''")
    return ans


def choices(*choices: str) -> Callable[[str], str]:
    defval = choices[0]
    uc = frozenset(choices)

    def choice(x: str) -> str:
        x = x.lower()
        if x not in uc:
            x = defval
        return x

    return choice


def parse_line(
    line: str,
    type_convert: Callable[[str, Any], Any],
    special_handling: Callable,
    ans: Dict[str, Any], all_keys: Optional[FrozenSet[str]],
    base_path_for_includes: str
) -> None:
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
                _parse(include, type_convert, special_handling, ans, all_keys)
        except FileNotFoundError:
            log_error(
                'Could not find included config file: {}, ignoring'.
                format(val)
            )
        except OSError:
            log_error(
                'Could not read from included config file: {}, ignoring'.
                format(val)
            )
        return
    if all_keys is not None and key not in all_keys:
        log_error('Ignoring unknown config key: {}'.format(key))
        return
    ans[key] = type_convert(key, val)


def _parse(
    lines: Iterable[str],
    type_convert: Callable[[str, Any], Any],
    special_handling: Callable,
    ans: Dict[str, Any],
    all_keys: Optional[FrozenSet[str]],
    accumulate_bad_lines: Optional[List[BadLine]] = None
) -> None:
    name = getattr(lines, 'name', None)
    if name:
        base_path_for_includes = os.path.dirname(os.path.abspath(name))
    else:
        from ..constants import config_dir
        base_path_for_includes = config_dir
    for i, line in enumerate(lines):
        try:
            parse_line(
                line, type_convert, special_handling, ans, all_keys,
                base_path_for_includes
            )
        except Exception as e:
            if accumulate_bad_lines is None:
                raise
            accumulate_bad_lines.append(BadLine(i + 1, line.rstrip(), e))


def parse_config_base(
    lines: Iterable[str],
    defaults: Any,
    type_convert: Callable[[str, Any], Any],
    special_handling: Callable,
    ans: Dict[str, Any],
    check_keys=True,
    accumulate_bad_lines: Optional[List[BadLine]] = None
):
    all_keys: Optional[FrozenSet[str]] = defaults._asdict() if check_keys else None
    _parse(
        lines, type_convert, special_handling, ans, all_keys, accumulate_bad_lines
    )


def create_options_class(all_keys: Iterable[str]) -> Type:
    keys = tuple(sorted(all_keys))
    slots = keys + ('_fields', )

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

    ans = type(
        'Options', (), {
            '__slots__': slots,
            '__init__': __init__,
            '_asdict': _asdict,
            '_replace': _replace,
            '__iter__': __iter__,
            '__len__': __len__,
            '__getitem__': __getitem__
        }
    )
    ans._fields = keys  # type: ignore
    return ans


def merge_dicts(defaults: Dict, newvals: Dict) -> Dict:
    ans = defaults.copy()
    ans.update(newvals)
    return ans


def resolve_config(SYSTEM_CONF: str, defconf: str, config_files_on_cmd_line: Sequence[str]):
    if config_files_on_cmd_line:
        if 'NONE' not in config_files_on_cmd_line:
            yield SYSTEM_CONF
            for cf in config_files_on_cmd_line:
                yield cf
    else:
        yield SYSTEM_CONF
        yield defconf


def load_config(
        Options: Type,
        defaults: Any,
        parse_config: Callable[[Iterable[str]], Dict[str, Any]],
        merge_configs: Callable[[Dict, Dict], Dict],
        *paths: str,
        overrides: Optional[Iterable[str]] = None
):
    ans: Dict = defaults._asdict()
    for path in paths:
        if not path:
            continue
        try:
            with open(path, encoding='utf-8', errors='replace') as f:
                vals = parse_config(f)
        except FileNotFoundError:
            continue
        ans = merge_configs(ans, vals)
    if overrides is not None:
        vals = parse_config(overrides)
        ans = merge_configs(ans, vals)
    return Options(ans)


def init_config(default_config_lines: Iterable[str], parse_config: Callable):
    defaults = parse_config(default_config_lines, check_keys=False)
    Options = create_options_class(defaults.keys())
    defaults = Options(defaults)
    return Options, defaults


def key_func():
    ans: Dict[str, Callable] = {}

    def func_with_args(*names):

        def w(f):
            for name in names:
                if ans.setdefault(name, f) is not f:
                    raise ValueError(
                        'the args_func {} is being redefined'.format(name)
                    )
            return f

        return w

    return func_with_args, ans


def parse_kittens_shortcut(sc: str) -> Tuple[Optional[int], str, bool]:
    from ..key_encoding import config_key_map, config_mod_map, text_match
    if sc.endswith('+'):
        parts = list(filter(None, sc.rstrip('+').split('+') + ['+']))
    else:
        parts = sc.split('+')
    qmods = parts[:-1]
    if qmods:
        resolved_mods = 0
        for mod in qmods:
            m = config_mod_map.get(mod.upper())
            if m is None:
                raise ValueError('Unknown shortcut modifiers: {}'.format(sc))
            resolved_mods |= m
        mods: Optional[int] = resolved_mods
    else:
        mods = None
    is_text = False
    rkey = parts[-1]
    tkey = text_match(rkey)
    if tkey is None:
        rkey = rkey.upper()
        q = config_key_map.get(rkey)
        if q is None:
            raise ValueError('Unknown shortcut key: {}'.format(sc))
        rkey = q
    else:
        is_text = True
        rkey = tkey
    return mods, rkey, is_text


def parse_kittens_func_args(action: str, args_funcs: Dict[str, Callable]) -> Tuple[str, Tuple[str, ...]]:
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
        args = (args, )

    return func, tuple(args)


def parse_kittens_key(
    val: str, funcs_with_args: Dict[str, Callable]
) -> Optional[Tuple[Tuple[str, Tuple[str, ...]], str, Optional[int], bool]]:
    sc, action = val.partition(' ')[::2]
    if not sc or not action:
        return None
    mods, key, is_text = parse_kittens_shortcut(sc)
    ans = parse_kittens_func_args(action, funcs_with_args)
    return ans, key, mods, is_text
