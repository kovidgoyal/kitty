#!/usr/bin/env python
# License: GPL v3 Copyright: 2018, Kovid Goyal <kovid at kovidgoyal.net>


import importlib
import os
import sys
from collections.abc import Callable, Generator
from contextlib import contextmanager
from functools import partial
from typing import TYPE_CHECKING, Any, NamedTuple, cast

from datty.constants import list_datty_resources
from datty.types import run_once
from datty.typing_compat import BossType, WindowType
from datty.utils import resolve_abs_or_config_path

aliases = {'url_hints': 'hints'}
if TYPE_CHECKING:
    from datty.conf.types import Definition
else:
    Definition = object


def resolved_daddy(k: str) -> str:
    ans = aliases.get(k, k)
    head, tail = os.path.split(ans)
    tail = tail.replace('-', '_')
    return os.path.join(head, tail)


def path_to_custom_daddy(config_dir: str, daddy: str) -> str:
    path = resolve_abs_or_config_path(daddy, conf_dir=config_dir)
    return os.path.abspath(path)


@contextmanager
def preserve_sys_path() -> Generator[None, None, None]:
    orig = sys.path[:]
    try:
        yield
    finally:
        if sys.path != orig:
            del sys.path[:]
            sys.path.extend(orig)


class CLIOnlyDaddy(TypeError):
    def __init__(self, daddy: str):
        super().__init__(f'The {daddy} daddy must be run only at the commandline, as: daddy {daddy}')


def import_daddy_main_module(config_dir: str, daddy: str) -> dict[str, Any]:
    if daddy.endswith('.py'):
        with preserve_sys_path():
            path = path_to_custom_daddy(config_dir, daddy)
            if os.path.dirname(path):
                sys.path.insert(0, os.path.dirname(path))
            with open(path) as f:
                src = f.read()
            code = compile(src, path, 'exec')
            g = {'__name__': 'daddy'}
            exec(code, g)
            hr = g.get('handle_result', lambda *a, **kw: None)
        return {'start': g['main'], 'end': hr}

    daddy = resolved_daddy(daddy)
    m = importlib.import_module(f'daddies.{daddy}.main')
    if not hasattr(m, 'main'):
        raise CLIOnlyDaddy(daddy)
    return {
        'start': getattr(m, 'main'),
        'end': getattr(m, 'handle_result', lambda *a, **k: None),
    }


class DaddyMetadata(NamedTuple):
    handle_result: Callable[[Any, int, BossType], None] = lambda *a: None

    type_of_input: str | None = None
    no_ui: bool = False
    has_ready_notification: bool = False
    open_url_handler: Callable[[BossType, WindowType, str, int, str], bool] | None = None
    allow_remote_control: bool = False
    remote_control_password: str | bool = False


def create_daddy_handler(daddy: str, orig_args: list[str]) -> DaddyMetadata:
    from datty.constants import config_dir

    m = import_daddy_main_module(config_dir, daddy)
    daddy = resolved_daddy(daddy)
    main = m['start']
    handle_result = m['end']
    return DaddyMetadata(
        handle_result=partial(handle_result, [daddy] + orig_args),
        type_of_input=getattr(handle_result, 'type_of_input', None),
        no_ui=getattr(handle_result, 'no_ui', False),
        allow_remote_control=getattr(main, 'allow_remote_control', False),
        remote_control_password=getattr(main, 'remote_control_password', True),
        has_ready_notification=getattr(handle_result, 'has_ready_notification', False),
        open_url_handler=getattr(handle_result, 'open_url_handler', None),
    )


def set_debug(daddy: str) -> None:
    import builtins

    from daddies.tui.loop import debug

    setattr(builtins, 'debug', debug)


def launch(args: list[str]) -> None:
    config_dir, daddy = args[:2]
    original_daddy_name = daddy
    daddy = resolved_daddy(daddy)
    del args[:2]
    args = [daddy] + args
    os.environ['DATTY_CONFIG_DIRECTORY'] = config_dir
    set_debug(daddy)
    m = import_daddy_main_module(config_dir, original_daddy_name)
    try:
        result = m['start'](args)
    finally:
        sys.stdin = sys.__stdin__
    if result is not None:
        import base64
        import json

        data = base64.b85encode(json.dumps(result).encode('utf-8'))
        sys.stdout.buffer.write(b'\x1bP@datty-daddy-result|')
        sys.stdout.buffer.write(data)
        sys.stdout.buffer.write(b'\x1b\\')
    sys.stderr.flush()
    sys.stdout.flush()


def run_daddy(daddy: str, run_name: str = '__main__') -> None:
    import runpy

    original_daddy_name = daddy
    daddy = resolved_daddy(daddy)
    set_debug(daddy)
    if daddy in all_daddy_names():
        runpy.run_module(f'daddies.{daddy}.main', run_name=run_name)
        return
    daddy = original_daddy_name
    # Look for a custom daddy
    if not daddy.endswith('.py'):
        daddy += '.py'
    from datty.constants import config_dir

    path = path_to_custom_daddy(config_dir, daddy)
    if not os.path.exists(path):
        path = path_to_custom_daddy(config_dir, resolved_daddy(daddy))
    if not os.path.exists(path):
        print('Available builtin daddies:', file=sys.stderr)
        for daddy in all_daddy_names():
            print(daddy, file=sys.stderr)
        raise SystemExit(f'No daddy named {original_daddy_name}')
    m = runpy.run_path(path, init_globals={'sys': sys, 'os': os}, run_name='__run_daddy__')
    from datty.fast_data_types import set_options

    try:
        m['main'](sys.argv)
    finally:
        set_options(None)


@run_once
def all_daddy_names() -> frozenset[str]:
    ans = []
    for name in list_datty_resources('daddies'):
        if '__' not in name and '.' not in name and name != 'tui':
            ans.append(name)
    return frozenset(ans)


def list_daddies() -> None:
    print('You must specify the name of a daddy to run')
    print('Choose from:')
    print()
    for daddy in all_daddy_names():
        print(daddy)


def get_daddy_cli_docs(daddy: str) -> Any:
    setattr(sys, 'cli_docs', {})
    run_daddy(daddy, run_name='__doc__')
    ans = getattr(sys, 'cli_docs')
    delattr(sys, 'cli_docs')
    if 'help_text' in ans and 'usage' in ans and 'options' in ans:
        return ans


def get_daddy_wrapper_of(daddy: str) -> str:
    setattr(sys, 'cli_docs', {})
    run_daddy(daddy, run_name='__wrapper_of__')
    ans = getattr(sys, 'cli_docs')
    delattr(sys, 'cli_docs')
    return ans.get('wrapper_of') or ''


def get_daddy_completer(daddy: str) -> Any:
    run_daddy(daddy, run_name='__completer__')
    ans = getattr(sys, 'daddy_completer', None)
    if ans is not None:
        delattr(sys, 'daddy_completer')
    return ans


def get_daddy_conf_docs(daddy: str) -> Definition | None:
    setattr(sys, 'options_definition', None)
    run_daddy(daddy, run_name='__conf__')
    ans = getattr(sys, 'options_definition')
    delattr(sys, 'options_definition')
    return cast(Definition, ans)


def get_daddy_extra_cli_parsers(daddy: str) -> dict[str, str]:
    setattr(sys, 'extra_cli_parsers', {})
    run_daddy(daddy, run_name='__extra_cli_parsers__')
    ans = getattr(sys, 'extra_cli_parsers')
    delattr(sys, 'extra_cli_parsers')
    return cast(dict[str, str], ans)


def main() -> None:
    try:
        args = sys.argv[1:]
        launch(args)
    except Exception:
        print('Unhandled exception running daddy:')
        import traceback

        traceback.print_exc()
        input('Press Enter to quit')
