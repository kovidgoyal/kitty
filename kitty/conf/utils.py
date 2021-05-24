#!/usr/bin/env python3
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2018, Kovid Goyal <kovid at kovidgoyal.net>

import os
import re
import shlex
from typing import (
    Any, Callable, Dict, FrozenSet, Generator, Iterable, Iterator, List,
    NamedTuple, Optional, Sequence, Tuple, Type, TypeVar, Union, Set
)

from ..rgb import Color, to_color as as_color
from ..types import ParsedShortcut, ConvertibleToNumbers
from ..utils import expandvars, log_error

key_pat = re.compile(r'([a-zA-Z][a-zA-Z0-9_-]*)\s+(.+)$')
T = TypeVar('T')


class BadLine(NamedTuple):
    number: int
    line: str
    exception: Exception


def positive_int(x: ConvertibleToNumbers) -> int:
    return max(0, int(x))


def positive_float(x: ConvertibleToNumbers) -> float:
    return max(0, float(x))


def to_color(x: str) -> Color:
    ans = as_color(x, validate=True)
    if ans is None:  # this is only for type-checking
        ans = Color(0, 0, 0)
    return ans


def to_color_or_none(x: str) -> Optional[Color]:
    return None if x.lower() == 'none' else to_color(x)


def unit_float(x: ConvertibleToNumbers) -> float:
    return max(0, min(float(x), 1))


def to_bool(x: str) -> bool:
    return x.lower() in ('y', 'yes', 'true')


class ToCmdline:

    def __init__(self) -> None:
        self.override_env: Optional[Dict[str, str]] = None

    def __enter__(self) -> 'ToCmdline':
        return self

    def __exit__(self, *a: Any) -> None:
        self.override_env = None

    def filter_env_vars(self, *a: str) -> 'ToCmdline':
        remove = frozenset(a)
        self.override_env = {k: v for k, v in os.environ.items() if k not in remove}
        return self

    def __call__(self, x: str) -> List[str]:
        return list(
            map(
                lambda y: expandvars(
                    os.path.expanduser(y),
                    os.environ if self.override_env is None else self.override_env,
                    fallback_to_os_env=False
                ),
                shlex.split(x)
            )
        )


to_cmdline_implementation = ToCmdline()


def to_cmdline(x: str) -> List[str]:
    return to_cmdline_implementation(x)


def python_string(text: str) -> str:
    import ast
    ans: str = ast.literal_eval("'''" + text.replace("'''", "'\\''") + "'''")
    return ans


class Choice:

    def __init__(self, choices: Sequence[str]):
        self.defval = choices[0]
        self.all_choices = frozenset(choices)

    def __call__(self, x: str) -> str:
        x = x.lower()
        if x not in self.all_choices:
            x = self.defval
        return x


def choices(*choices: str) -> Choice:
    return Choice(choices)


def create_type_converter(all_options: Dict) -> Callable[[str, Any], Any]:
    from .definition import Option

    def type_convert(name: str, val: Any) -> Any:
        o = all_options.get(name)
        if isinstance(o, Option):
            val = o.option_type(val)
        return val
    return type_convert


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
    all_option_names: Optional[FrozenSet],
    all_options: Dict[str, Any],
    special_handling: Callable,
    ans: Dict[str, Any],
    accumulate_bad_lines: Optional[List[BadLine]] = None
) -> None:
    _parse(
        lines, create_type_converter(all_options), special_handling, ans, all_option_names, accumulate_bad_lines
    )


def create_options_class(all_keys: Iterable[str]) -> Type:
    keys = tuple(sorted(all_keys))
    slots = keys + ('_fields', )

    def __init__(self: Any, kw: Dict[str, Any]) -> None:
        for k, v in kw.items():
            setattr(self, k, v)

    def __iter__(self: Any) -> Iterator[str]:
        return iter(keys)

    def __len__(self: Any) -> int:
        return len(keys)

    def __getitem__(self: Any, i: Union[int, str]) -> Any:
        if isinstance(i, int):
            i = keys[i]
        try:
            return getattr(self, i)
        except AttributeError:
            raise KeyError('No option named: {}'.format(i))

    def _asdict(self: Any) -> Dict[str, Any]:
        return {k: getattr(self, k) for k in self._fields}

    def _replace(self: Any, **kw: Dict) -> Any:
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


def resolve_config(SYSTEM_CONF: str, defconf: str, config_files_on_cmd_line: Sequence[str]) -> Generator[str, None, None]:
    if config_files_on_cmd_line:
        if 'NONE' not in config_files_on_cmd_line:
            yield SYSTEM_CONF
            for cf in config_files_on_cmd_line:
                yield cf
    else:
        yield SYSTEM_CONF
        yield defconf


def load_config(
        Options: Type[T],
        defaults: Any,
        parse_config: Callable[[Iterable[str]], Dict[str, Any]],
        merge_configs: Callable[[Dict, Dict], Dict],
        *paths: str,
        overrides: Optional[Iterable[str]] = None
) -> T:
    ans: Dict = defaults._asdict()
    for path in paths:
        if not path:
            continue
        try:
            with open(path, encoding='utf-8', errors='replace') as f:
                vals = parse_config(f)
        except (FileNotFoundError, PermissionError):
            continue
        ans = merge_configs(ans, vals)
    if overrides is not None:
        vals = parse_config(overrides)
        ans = merge_configs(ans, vals)
    return Options(ans)  # type: ignore


def init_config(default_config_lines: Iterable[str], parse_config: Callable) -> Tuple[Type, Any]:
    defaults = parse_config(default_config_lines, check_keys=False)
    Options = create_options_class(defaults.keys())
    defaults = Options(defaults)
    return Options, defaults


def key_func() -> Tuple[Callable[..., Callable], Dict[str, Callable]]:
    ans: Dict[str, Callable] = {}

    def func_with_args(*names: str) -> Callable:

        def w(f: Callable) -> Callable:
            for name in names:
                if ans.setdefault(name, f) is not f:
                    raise ValueError(
                        'the args_func {} is being redefined'.format(name)
                    )
            return f

        return w

    return func_with_args, ans


KittensKeyAction = Tuple[str, Tuple[str, ...]]


def parse_kittens_func_args(action: str, args_funcs: Dict[str, Callable]) -> KittensKeyAction:
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
) -> Optional[Tuple[KittensKeyAction, ParsedShortcut]]:
    from ..key_encoding import parse_shortcut
    sc, action = val.partition(' ')[::2]
    if not sc or not action:
        return None
    ans = parse_kittens_func_args(action, funcs_with_args)
    return ans, parse_shortcut(sc)


def uniq(vals: Iterable[T]) -> List[T]:
    seen: Set[T] = set()
    seen_add = seen.add
    return [x for x in vals if x not in seen and not seen_add(x)]
