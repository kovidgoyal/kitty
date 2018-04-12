#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2018, Kovid Goyal <kovid at kovidgoyal.net>


import importlib
import os
import sys
from functools import partial

aliases = {'url_hints': 'hints'}


def resolved_kitten(k):
    return aliases.get(k, k)


def import_kitten_main_module(config_dir, kitten):
    if kitten.endswith('.py'):
        path = os.path.expanduser(kitten)
        if not os.path.isabs(path):
            path = os.path.join(config_dir, path)
        path = os.path.abspath(path)
        if os.path.dirname(path):
            sys.path.insert(0, os.path.dirname(path))
        with open(path) as f:
            src = f.read()
        code = compile(src, path, 'exec')
        g = {'__name__': 'kitten'}
        exec(code, g)
        return {'start': g['main'], 'end': g['handle_result']}
    else:
        kitten = resolved_kitten(kitten)
        m = importlib.import_module('kittens.{}.main'.format(kitten))
        return {'start': m.main, 'end': m.handle_result}


def create_kitten_handler(kitten, orig_args):
    from kitty.constants import config_dir
    kitten = resolved_kitten(kitten)
    m = import_kitten_main_module(config_dir, kitten)
    return partial(m['end'], [kitten] + orig_args)


def launch(args):
    config_dir, kitten = args[:2]
    kitten = resolved_kitten(kitten)
    del args[:2]
    args = [kitten] + args
    os.environ['KITTY_CONFIG_DIRECTORY'] = config_dir
    from kittens.tui.operations import clear_screen, reset_mode
    m = import_kitten_main_module(config_dir, kitten)
    result = m['start'](args)
    print(reset_mode('ALTERNATE_SCREEN') + clear_screen(), end='')
    if result is not None:
        import json
        print('OK:', json.dumps(result))
    sys.stderr.flush()
    sys.stdout.flush()


def run_kitten(kitten):
    import runpy
    kitten = resolved_kitten(kitten)
    runpy.run_module('kittens.{}.main'.format(kitten), run_name='__main__')


def main():
    try:
        args = sys.argv[1:]
        launch(args)
    except Exception:
        print('Unhandled exception running kitten:')
        import traceback
        traceback.print_exc()
        input('Press Enter to quit...')
