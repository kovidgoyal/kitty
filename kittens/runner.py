#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2018, Kovid Goyal <kovid at kovidgoyal.net>


import importlib
import os
import sys
from functools import partial

aliases = {'url_hints': 'hints'}


def resolved_kitten(k):
    return aliases.get(k, k).replace('-', '_')


def import_kitten_main_module(config_dir, kitten):
    if kitten.endswith('.py'):
        path_modified = False
        path = os.path.expanduser(kitten)
        if not os.path.isabs(path):
            path = os.path.join(config_dir, path)
        path = os.path.abspath(path)
        if os.path.dirname(path):
            sys.path.insert(0, os.path.dirname(path))
            path_modified = True
        with open(path) as f:
            src = f.read()
        code = compile(src, path, 'exec')
        g = {'__name__': 'kitten'}
        exec(code, g)
        hr = g.get('handle_result', lambda *a, **kw: None)
        if path_modified:
            del sys.path[0]
        return {'start': g['main'], 'end': hr}

    kitten = resolved_kitten(kitten)
    m = importlib.import_module('kittens.{}.main'.format(kitten))
    return {'start': m.main, 'end': getattr(m, 'handle_result', lambda *a, **k: None)}


def create_kitten_handler(kitten, orig_args):
    from kitty.constants import config_dir
    kitten = resolved_kitten(kitten)
    m = import_kitten_main_module(config_dir, kitten)
    ans = partial(m['end'], [kitten] + orig_args)
    ans.type_of_input = getattr(m['end'], 'type_of_input', None)
    ans.no_ui = getattr(m['end'], 'no_ui', False)
    return ans


def set_debug(kitten):
    from kittens.tui.loop import debug
    import builtins
    builtins.debug = debug


def launch(args):
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


def deserialize(output):
    import json
    if output.startswith('OK: '):
        try:
            prefix, sz, rest = output.split(' ', 2)
            return json.loads(rest[:int(sz)])
        except Exception:
            raise ValueError('Failed to parse kitten output: {!r}'.format(output))


def run_kitten(kitten, run_name='__main__'):
    import runpy
    kitten = resolved_kitten(kitten)
    set_debug(kitten)
    try:
        runpy.run_module('kittens.{}.main'.format(kitten), run_name=run_name)
    except ImportError:
        raise SystemExit('No kitten named {}'.format(kitten))


def all_kitten_names():
    ans = getattr(all_kitten_names, 'ans', None)
    if ans is None:
        n = []
        import glob
        base = os.path.dirname(os.path.abspath(__file__))
        for x in glob.glob(os.path.join(base, '*', '__init__.py')):
            q = os.path.basename(os.path.dirname(x))
            if q != 'tui':
                n.append(q)
        all_kitten_names.ans = ans = frozenset(n)
    return ans


def list_kittens():
    print('You must specify the name of a kitten to run')
    print('Choose from:')
    print()
    for kitten in all_kitten_names():
        print(kitten)


def get_kitten_cli_docs(kitten):
    sys.cli_docs = {}
    run_kitten(kitten, run_name='__doc__')
    ans = sys.cli_docs
    del sys.cli_docs
    if 'help_text' in ans and 'usage' in ans and 'options' in ans:
        return ans


def get_kitten_conf_docs(kitten):
    sys.all_options = None
    run_kitten(kitten, run_name='__conf__')
    ans = sys.all_options
    del sys.all_options
    return ans


def main():
    try:
        args = sys.argv[1:]
        launch(args)
    except Exception:
        print('Unhandled exception running kitten:')
        import traceback
        traceback.print_exc()
        input('Press Enter to quit...')
