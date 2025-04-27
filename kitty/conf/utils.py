#!/usr/bin/env python
# License: GPL v3 Copyright: 2018, Kovid Goyal <kovid at kovidgoyal.net>

import os
import re
import sys
from collections.abc import Callable, Generator, Iterable, Iterator, Sequence
from contextlib import contextmanager
from typing import (
    Any,
    Generic,
    Literal,
    NamedTuple,
    TypeVar,
)

from ..constants import _plat, is_macos
from ..fast_data_types import Color
from ..rgb import to_color as as_color
from ..types import ConvertibleToNumbers, ParsedShortcut, run_once
from ..typing_compat import Protocol
from ..utils import expandvars, log_error, shlex_split

key_pat = re.compile(r'([a-zA-Z][a-zA-Z0-9_-]*)\s+(.+)$')
number_unit_pat = re.compile(r'\s*([-+]?\d+\.?\d*)\s*([^\d\s]*)?')
ItemParser = Callable[[str, str, dict[str, Any]], bool]
T = TypeVar('T')


class OptionsProtocol(Protocol):

    def _asdict(self) -> dict[str, Any]:
        pass


class BadLine(NamedTuple):
    number: int
    line: str
    exception: Exception
    file: str


def positive_int(x: ConvertibleToNumbers) -> int:
    return max(0, int(x))


def positive_float(x: ConvertibleToNumbers) -> float:
    return max(0, float(x))


def percent(x: str) -> float:
    return float(x.rstrip('%')) / 100.


def to_color(x: str) -> Color:
    ans = as_color(x, validate=True)
    if ans is None:  # this is only for type-checking
        ans = Color(0, 0, 0)
    return ans


def to_color_or_none(x: str) -> Color | None:
    return None if x.lower() == 'none' else to_color(x)


def unit_float(x: ConvertibleToNumbers) -> float:
    return max(0, min(float(x), 1))


def number_with_unit(x: str, default_unit: str, *extra_units: str) -> tuple[float, str]:
    if (mat := number_unit_pat.match(x)) is not None:
        try:
            value = float(mat.group(1))
        except Exception as e:
            raise ValueError(f'Not a number: {x} with error: {e}')
        unit = mat.group(2) or default_unit
        if unit != default_unit and unit not in extra_units:
            raise ValueError(f'Not a valid unit: {x}. Allowed units are: {default_unit}, {", ".join(extra_units)}')
        return value, unit
    raise ValueError(f'Invalid number with unit: {x}')


def to_bool(x: str) -> bool:
    return x.lower() in ('y', 'yes', 'true')


class ToCmdline:

    def __init__(self) -> None:
        self.override_env: dict[str, str] | None = None

    def __enter__(self) -> 'ToCmdline':
        return self

    def __exit__(self, *a: Any) -> None:
        self.override_env = None

    def filter_env_vars(self, *a: str, **override: str) -> 'ToCmdline':
        remove = frozenset(a)
        self.override_env = {k: v for k, v in os.environ.items() if k not in remove}
        self.override_env.update(override)
        return self

    def __call__(self, x: str, expand: bool = True) -> list[str]:
        if expand:
            ans = list(
                map(
                    lambda y: expandvars(
                        os.path.expanduser(y),
                        os.environ if self.override_env is None else self.override_env,
                        fallback_to_os_env=False
                    ),
                    shlex_split(x)
                )
            )
        else:
            ans = list(shlex_split(x))
        return ans


to_cmdline_implementation = ToCmdline()


def to_cmdline(x: str, expand: bool = True) -> list[str]:
    return to_cmdline_implementation(x, expand)


def python_string(text: str) -> str:
    from ast import literal_eval
    ans: str = literal_eval("'''" + text.replace("'''", "'\\''") + "'''")
    return ans


class Choice:

    def __init__(self, choices: Sequence[str]):
        self.defval = choices[0]
        self.all_choices = frozenset(choices)

    def __call__(self, x: str) -> str:
        x = x.lower()
        if x not in self.all_choices:
            raise ValueError(f'The value {x} is not a known choice')
        return x


def choices(*choices: str) -> Choice:
    return Choice(choices)


class CurrentlyParsing:
    __slots__ = 'line', 'number', 'file'

    def __init__(self, line: str = '', number: int = -1, file: str = ''):
        self.line = line
        self.number = number
        self.file = file

    def __copy__(self) -> 'CurrentlyParsing':
        return CurrentlyParsing(self.line, self.number, self.file)

    @contextmanager
    def set_line(self, line: str, number: int) -> Iterator['CurrentlyParsing']:
        orig = self.line, self.number
        self.line = line
        self.number = number
        try:
            yield self
        finally:
            self.line, self.number = orig

    @contextmanager
    def set_file(self, file: str) -> Iterator['CurrentlyParsing']:
        orig = self.file
        self.file = file
        try:
            yield self
        finally:
            self.file = orig


currently_parsing = CurrentlyParsing()
OSNames = Literal['macos', 'bsd', 'linux', 'unknown']

@run_once
def os_name() -> OSNames:
    if is_macos:
        return 'macos'
    if 'bsd' in _plat:
        return 'bsd'
    if 'linux' in _plat:
        return 'linux'
    return 'unknown'


class NamedLineIterator:

    def __init__(self, name: str, lines: Iterator[str]):
        self.lines = lines
        self.name = name

    def __iter__(self) -> Iterator[str]:
        return self.lines


class GenincludeError(Exception): ...


def pygeninclude(path: str) -> list[str]:
    import io
    import runpy
    before = sys.stdout
    buf = sys.stdout = io.StringIO()
    try:
        runpy.run_path(path, run_name='__main__')
    except FileNotFoundError:
        raise
    except Exception:
        import traceback
        tb = traceback.format_exc()
        raise GenincludeError(f'Running the geninclude program: {path} failed with the error:\n{tb}')
    finally:
        sys.stdout = before
    return buf.getvalue().splitlines()


def geninclude(path: str) -> list[str]:
    old = os.environ.get('KITTY_OS')
    os.environ['KITTY_OS'] = os_name()
    try:
        if path.endswith('.py'):
            return pygeninclude(path)
        import subprocess
        cp = subprocess.run([path], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if cp.returncode != 0:
            raise GenincludeError(f'Running the geninclude program: {path} failed with exit code: {cp.returncode} and STDERR:\n{cp.stderr}')
        return cp.stdout.splitlines()
    finally:
        if old is None:
            os.environ.pop('KITTY_OS', None)
        else:
            os.environ['KITTY_OS'] = old



include_keys = 'include', 'globinclude', 'envinclude', 'geninclude'


class RecursiveInclude(Exception):
    pass


class Memory:

    def __init__(self, accumulate_bad_lines: list[BadLine] | None) -> None:
        self.s: set[str] = set()
        if accumulate_bad_lines is None:
            accumulate_bad_lines = []
        self.accumulate_bad_lines = accumulate_bad_lines

    def seen(self, path: str) -> bool:
        key = os.path.normpath(path)
        if key in self.s:
            self.accumulate_bad_lines.append(BadLine(currently_parsing.number, currently_parsing.line.rstrip(), RecursiveInclude(
                f'The file {path} has already been included, ignoring'), currently_parsing.file))
            return True
        self.s.add(key)
        return False


def parse_line(
    line: str,
    parse_conf_item: ItemParser,
    ans: dict[str, Any],
    base_path_for_includes: str,
    effective_config_lines: Callable[[str, str], None],
    memory: Memory,
    accumulate_bad_lines: list[BadLine] | None = None,
) -> None:
    line = line.strip()
    if not line or line.startswith('#'):
        return
    m = key_pat.match(line)
    if m is None:
        log_error(f'Ignoring invalid config line: {line!r}')
        return
    key, val = m.groups()
    if key.endswith('include') and key in include_keys:
        val = expandvars(os.path.expanduser(val.strip()), {'KITTY_OS': os_name()})
        if key == 'globinclude':
            from pathlib import Path
            vals = tuple(map(lambda x: str(os.fspath(x)), sorted(Path(base_path_for_includes).glob(val))))
        elif key == 'envinclude':
            from fnmatch import fnmatchcase
            for x in os.environ:
                if fnmatchcase(x, val):
                    with currently_parsing.set_file(f'<env var: {x}>'):
                        _parse(
                            NamedLineIterator(os.path.join(base_path_for_includes, ''), iter(os.environ[x].splitlines())),
                            parse_conf_item, ans, memory, accumulate_bad_lines, effective_config_lines
                        )
            return
        elif key == 'geninclude':
            if not os.path.isabs(val):
                val = os.path.join(base_path_for_includes, val)
            if not memory.seen(val):
                try:
                    lines = geninclude(val)
                except FileNotFoundError as e:
                    if e.filename == val:
                        log_error(f'Could not find the geninclude file: {val}, ignoring')
                    else:
                        raise
                else:
                    with currently_parsing.set_file(f'<get: {val}>'):
                        _parse(
                            NamedLineIterator(os.path.join(base_path_for_includes, ''), iter(lines)),
                            parse_conf_item, ans, memory, accumulate_bad_lines, effective_config_lines
                        )
            return
        else:
            if not os.path.isabs(val):
                val = os.path.join(base_path_for_includes, val)
            vals = (val,)
        for val in vals:
            if memory.seen(val):
                continue
            try:
                with open(val, encoding='utf-8', errors='replace') as include:
                    with currently_parsing.set_file(val):
                        _parse(include, parse_conf_item, ans, memory, accumulate_bad_lines, effective_config_lines)
            except FileNotFoundError:
                log_error(f'Could not find included config file: {val}, ignoring')
            except OSError:
                log_error(
                    'Could not read from included config file: {}, ignoring'.
                    format(val)
                )
        return
    if parse_conf_item(key, val, ans):
        effective_config_lines(key, line)
    else:
        log_error(f'Ignoring unknown config key: {key}')



def _parse(
    lines: Iterable[str],
    parse_conf_item: ItemParser,
    ans: dict[str, Any],
    memory: Memory,
    accumulate_bad_lines: list[BadLine] | None = None,
    effective_config_lines: Callable[[str, str], None] | None = None,
) -> None:
    name = getattr(lines, 'name', None)
    effective_config_lines = effective_config_lines or (lambda a, b: None)
    if name:
        base_path_for_includes = os.path.abspath(name) if name.endswith(os.path.sep) else os.path.dirname(os.path.abspath(name))
    else:
        from ..constants import config_dir
        base_path_for_includes = config_dir

    it = iter(lines)
    line = ''
    next_line: str = ''
    next_line_num = 0

    while True:
        try:
            if next_line:
                line = next_line
            else:
                line = next(it).lstrip()
                next_line_num += 1
            line_num = next_line_num

            try:
                next_line = next(it).lstrip()
                next_line_num += 1

                while next_line.startswith('\\'):
                    line = line.rstrip('\n') + next_line[1:]
                    try:
                        next_line = next(it).lstrip()
                        next_line_num += 1
                    except StopIteration:
                        next_line = ''
                        break
            except StopIteration:
                next_line = ''
            try:
                with currently_parsing.set_line(line, line_num):
                    parse_line(line, parse_conf_item, ans, base_path_for_includes, effective_config_lines, memory, accumulate_bad_lines)
            except Exception as e:
                if accumulate_bad_lines is None:
                    raise
                accumulate_bad_lines.append(BadLine(line_num, line.rstrip(), e, currently_parsing.file))
        except StopIteration:
            break


def parse_config_base(
    lines: Iterable[str],
    parse_conf_item: ItemParser,
    ans: dict[str, Any],
    accumulate_bad_lines: list[BadLine] | None = None,
    effective_config_lines: Callable[[str, str], None] | None = None,
) -> None:
    _parse(lines, parse_conf_item, ans, Memory(accumulate_bad_lines), accumulate_bad_lines, effective_config_lines)


def merge_dicts(defaults: dict[str, Any], newvals: dict[str, Any]) -> dict[str, Any]:
    ans = defaults.copy()
    ans.update(newvals)
    return ans


def resolve_config(SYSTEM_CONF: str, defconf: str, config_files_on_cmd_line: Sequence[str] = ()) -> Generator[str, None, None]:
    if config_files_on_cmd_line:
        if 'NONE' not in config_files_on_cmd_line:
            yield SYSTEM_CONF
            yield from config_files_on_cmd_line
    else:
        yield SYSTEM_CONF
        yield defconf


def load_config(
    defaults: OptionsProtocol,
    parse_config: Callable[[Iterable[str]], dict[str, Any]],
    merge_configs: Callable[[dict[str, Any], dict[str, Any]], dict[str, Any]],
    *paths: str,
    overrides: Iterable[str] | None = None,
    initialize_defaults: Callable[[dict[str, Any]], dict[str, Any]] = lambda x: x,
) -> tuple[dict[str, Any], tuple[str, ...]]:
    ans = initialize_defaults(defaults._asdict())
    found_paths = []
    for path in paths:
        if not path:
            continue
        if path == '-':
            path = '/dev/stdin'
            with currently_parsing.set_file(path):
                vals = parse_config(sys.stdin)
        else:
            try:
                with open(path, encoding='utf-8', errors='replace') as f:
                    with currently_parsing.set_file(path):
                        vals = parse_config(f)
            except (FileNotFoundError, PermissionError):
                continue
        found_paths.append(path)
        ans = merge_configs(ans, vals)
    if overrides is not None:
        with currently_parsing.set_file('<override>'):
            vals = parse_config(overrides)
        ans = merge_configs(ans, vals)
    return ans, tuple(found_paths)


ReturnType = TypeVar('ReturnType')
KeyFunc = Callable[[str, str], ReturnType]


class KeyFuncWrapper(Generic[ReturnType]):
    def __init__(self) -> None:
        self.args_funcs: dict[str, KeyFunc[ReturnType]] = {}

    def __call__(self, *names: str) -> Callable[[KeyFunc[ReturnType]], KeyFunc[ReturnType]]:

        def w(f: KeyFunc[ReturnType]) -> KeyFunc[ReturnType]:
            for name in names:
                if self.args_funcs.setdefault(name, f) is not f:
                    raise ValueError(f'the args_func {name} is being redefined')
            return f
        return w

    def get(self, name: str) -> KeyFunc[ReturnType] | None:
        return self.args_funcs.get(name)


class KeyAction(NamedTuple):
    func: str
    args: tuple[str | float | bool | int | None, ...] = ()

    def __repr__(self) -> str:
        if self.args:
            return f'KeyAction({self.func!r}, {self.args!r})'
        return f'KeyAction({self.func!r})'

    def pretty(self) -> str:
        ans = self.func
        for x in self.args:
            ans += f' {x}'
        return ans


def parse_kittens_func_args(action: str, args_funcs: dict[str, KeyFunc[tuple[str, Any]]]) -> KeyAction:
    parts = action.strip().split(' ', 1)
    func = parts[0]
    if len(parts) == 1:
        return KeyAction(func, ())
    rest = parts[1]

    try:
        parser = args_funcs[func]
    except KeyError as e:
        raise KeyError(
            f'Unknown action: {func}. Check if map action: {action} is valid'
        ) from e

    try:
        func, args = parser(func, rest)
    except Exception:
        raise ValueError(f'Unknown key action: {action}')

    if not isinstance(args, (list, tuple)):
        args = (args, )

    return KeyAction(func, tuple(args))


KittensKeyDefinition = tuple[ParsedShortcut, KeyAction]
KittensKeyMap = dict[ParsedShortcut, KeyAction]


def parse_kittens_key(
    val: str, funcs_with_args: dict[str, KeyFunc[tuple[str, Any]]]
) -> KittensKeyDefinition | None:
    from ..key_encoding import parse_shortcut
    sc, action = val.partition(' ')[::2]
    if not sc or not action:
        return None
    ans = parse_kittens_func_args(action, funcs_with_args)
    return parse_shortcut(sc), ans


def uniq(vals: Iterable[T]) -> list[T]:
    seen: set[T] = set()
    seen_add = seen.add
    return [x for x in vals if x not in seen and not seen_add(x)]


def save_type_stub(text: str, fpath: str) -> None:
    fpath += 'i'
    preamble = '# Update this file by running: ./test.py mypy\n\n'
    try:
        with open(fpath) as fs:
            existing = fs.read()
    except FileNotFoundError:
        existing = ''
    current = preamble + text
    if existing != current:
        with open(fpath, 'w') as f:
            f.write(current)
