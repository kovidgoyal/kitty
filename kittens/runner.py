#!/usr/bin/env python3
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2018, Kovid Goyal <kovid at kovidgoyal.net>


import importlib
import os
import sys
from contextlib import contextmanager
from functools import partial
from typing import TYPE_CHECKING, Any, Dict, FrozenSet, Generator, List, cast

from kitty.types import run_once

aliases = {'url_hints': 'hints'}
if TYPE_CHECKING:
    from kitty.conf.types import Definition
else:
    Definition = object


def resolved_kitten(k: str) -> str:
    ans = aliases.get(k, k)
    head, tail = os.path.split(ans)
    tail = tail.replace('-', '_')
    return os.path.join(head, tail)


def path_to_custom_kitten(config_dir: str, kitten: str) -> str:
    path = os.path.expanduser(kitten)
    if not os.path.isabs(path):
        path = os.path.join(config_dir, path)
    path = os.path.abspath(path)
    return path


@contextmanager
def preserve_sys_path() -> Generator[None, None, None]:
    orig = sys.path[:]
    try:
        yield
    finally:
        if sys.path != orig:
            del sys.path[:]
            sys.path.extend(orig)


def import_kitten_main_module(config_dir: str, kitten: str) -> Dict[str, Any]:
    if kitten.endswith('.py'):
        with preserve_sys_path():
            path = path_to_custom_kitten(config_dir, kitten)
            if os.path.dirname(path):
                sys.path.insert(0, os.path.dirname(path))
            with open(path) as f:
                src = f.read()
            code = compile(src, path, 'exec')
            g = {'__name__': 'kitten'}
            exec(code, g)
            hr = g.get('handle_result', lambda *a, **kw: None)
        return {'start': g['main'], 'end': hr}

    kitten = resolved_kitten(kitten)
    m = importlib.import_module('kittens.{}.main'.format(kitten))
    return {'start': getattr(m, 'main'), 'end': getattr(m, 'handle_result', lambda *a, **k: None)}


def create_kitten_handler(kitten: str, orig_args: List[str]) -> Any:
    from kitty.constants import config_dir
    kitten = resolved_kitten(kitten)
    m = import_kitten_main_module(config_dir, kitten)
    ans = partial(m['end'], [kitten] + orig_args)
    setattr(ans, 'type_of_input', getattr(m['end'], 'type_of_input', None))
    setattr(ans, 'no_ui', getattr(m['end'], 'no_ui', False))
    return ans


def set_debug(kitten: str) -> None:
    import builtins

    from kittens.tui.loop import debug
    setattr(builtins, 'debug', debug)


def launch(args: List[str]) -> None:
    config_dir, kitten = args[:2]
    kitten = resolved_kitten(kitten)
    del args[:2]
    args = [kitten] + args
    os.environ['KITTY_CONFIG_DIRECTORY'] = config_dir
    from kittens.tui.operations import clear_screen, reset_mode
    set_debug(kitten)
    m = import_kitten_main_module(config_dir, kitten)
    try:
        result = m['start'](args)
    finally:
        sys.stdin = sys.__stdin__
    print(reset_mode('ALTERNATE_SCREEN') + clear_screen(), end='')
    if result is not None:
        import json
        data = json.dumps(result)
        print('OK:', len(data), data)
    sys.stderr.flush()
    sys.stdout.flush()


def deserialize(output: str) -> Any:
    import json
    if output.startswith('OK: '):
        try:
            prefix, sz, rest = output.split(' ', 2)
            return json.loads(rest[:int(sz)])
        except Exception:
            raise ValueError('Failed to parse kitten output: {!r}'.format(output))


def run_kitten(kitten: str, run_name: str = '__main__') -> None:
    import runpy
    original_kitten_name = kitten
    kitten = resolved_kitten(kitten)
    set_debug(kitten)
    try:
        runpy.run_module('kittens.{}.main'.format(kitten), run_name=run_name)
        return
    except ImportError:
        pass
    # Look for a custom kitten
    if not kitten.endswith('.py'):
        kitten += '.py'
    from kitty.constants import config_dir
    path = path_to_custom_kitten(config_dir, kitten)
    if not os.path.exists(path):
        print('Available builtin kittens:', file=sys.stderr)
        for kitten in all_kitten_names():
            print(kitten, file=sys.stderr)
        raise SystemExit('No kitten named {}'.format(original_kitten_name))
    m = runpy.run_path(path, init_globals={'sys': sys, 'os': os}, run_name='__run_kitten__')
    m['main'](sys.argv)


@run_once
def all_kitten_names() -> FrozenSet[str]:
    try:
        from importlib.resources import contents
    except ImportError:
        from importlib_resources import contents  # type: ignore
    ans = []
    for name in contents('kittens'):
        if '__' not in name and '.' not in name and name != 'tui':
            ans.append(name)
    return frozenset(ans)


def list_kittens() -> None:
    print('You must specify the name of a kitten to run')
    print('Choose from:')
    print()
    for kitten in all_kitten_names():
        print(kitten)


def get_kitten_cli_docs(kitten: str) -> Any:
    setattr(sys, 'cli_docs', {})
    run_kitten(kitten, run_name='__doc__')
    ans = getattr(sys, 'cli_docs')
    delattr(sys, 'cli_docs')
    if 'help_text' in ans and 'usage' in ans and 'options' in ans:
        return ans


def get_kitten_completer(kitten: str) -> Any:
    run_kitten(kitten, run_name='__completer__')
    ans = getattr(sys, 'kitten_completer', None)
    if ans is not None:
        delattr(sys, 'kitten_completer')
    return ans


def get_kitten_conf_docs(kitten: str) -> Definition:
    setattr(sys, 'options_definition', None)
    run_kitten(kitten, run_name='__conf__')
    ans = getattr(sys, 'options_definition')
    delattr(sys, 'options_definition')
    return cast(Definition, ans)


def main() -> None:
    try:
        args = sys.argv[1:]
        launch(args)
    except Exception:
        print('Unhandled exception running kitten:')
        import traceback
        traceback.print_exc()
        input('Press Enter to quit...')
