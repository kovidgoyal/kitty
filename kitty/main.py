#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2016, Kovid Goyal <kovid at kovidgoyal.net>

import locale
import os
import signal
import sys
from contextlib import contextmanager

from .borders import load_borders_program
from .boss import Boss
from .cli import create_opts, option_parser
from .config import initial_window_size, load_cached_values, save_cached_values
from .constants import isosx, iswayland, logo_data_file
from .fast_data_types import (
    change_wcwidth, create_os_window, glfw_init, glfw_init_hint_string,
    glfw_terminate, install_sigchld_handler, set_default_window_icon,
    set_logical_dpi, set_options, GLFW_X11_WM_CLASS_NAME, GLFW_X11_WM_CLASS_CLASS
)
from .fonts.box_drawing import set_scale
from .utils import (
    detach, end_startup_notification, get_logical_dpi,
    init_startup_notification, single_instance
)
from .window import load_shader_programs


def load_all_shaders():
    load_shader_programs()
    load_borders_program()


def run_app(opts, args):
    set_scale(opts.box_drawing_scale)
    set_options(opts, iswayland, args.debug_gl)
    load_cached_values()
    w, h = initial_window_size(opts)
    window_id = create_os_window(w, h, args.cls, True, load_all_shaders)
    startup_ctx = init_startup_notification(window_id)
    if not iswayland and not isosx:  # no window icons on wayland
        with open(logo_data_file, 'rb') as f:
            set_default_window_icon(f.read(), 256, 256)
    set_logical_dpi(*get_logical_dpi())
    boss = Boss(window_id, opts, args)
    boss.start()
    end_startup_notification(startup_ctx)
    try:
        boss.child_monitor.main_loop()
    finally:
        boss.destroy()
    save_cached_values()


def ensure_osx_locale():
    # Ensure the LANG env var is set. See
    # https://github.com/kovidgoyal/kitty/issues/90
    from .fast_data_types import cocoa_get_lang
    if 'LANG' not in os.environ:
        lang = cocoa_get_lang()
        if lang is not None:
            os.environ['LANG'] = lang + '.UTF-8'


@contextmanager
def setup_profiling(args):
    try:
        from .fast_data_types import start_profiler, stop_profiler
    except ImportError:
        start_profiler = stop_profiler = None
    if start_profiler is not None:
        start_profiler('/tmp/kitty-profile.log')
    yield
    if stop_profiler is not None:
        import subprocess
        stop_profiler()
        exe = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'kitty-profile')
        cg = '/tmp/kitty-profile.callgrind'
        print('Post processing profile data for', exe, '...')
        subprocess.call(['pprof', '--callgrind', exe, '/tmp/kitty-profile.log'], stdout=open(cg, 'wb'))
        try:
            subprocess.Popen(['kcachegrind', cg])
        except FileNotFoundError:
            subprocess.call(['pprof', '--text', exe, '/tmp/kitty-profile.log'])
            print('To view the graphical call data, use: kcachegrind', cg)


def main():
    try:
        sys.setswitchinterval(1000.0)  # we have only a single python thread
    except AttributeError:
        pass  # python compiled without threading
    base = os.path.dirname(os.path.abspath(__file__))
    if isosx:
        ensure_osx_locale()
    try:
        locale.setlocale(locale.LC_ALL, '')
    except Exception:
        if not isosx:
            raise
        print('Failed to set locale with LANG:', os.environ.get('LANG'), file=sys.stderr)
        os.environ.pop('LANG')
        try:
            locale.setlocale(locale.LC_ALL, '')
        except Exception:
            print('Failed to set locale with no LANG, ignoring', file=sys.stderr)
    if os.environ.pop('KITTY_LAUNCHED_BY_LAUNCH_SERVICES',
                      None) == '1' and getattr(sys, 'frozen', True):
        os.chdir(os.path.expanduser('~'))
    if not os.path.isdir(os.getcwd()):
        os.chdir(os.path.expanduser('~'))
    args = option_parser().parse_args()
    if getattr(args, 'detach', False):
        detach()
    if args.cmd:
        exec(args.cmd)
        return
    if args.replay_commands:
        from kitty.client import main
        main(args.replay_commands)
        return
    if args.single_instance:
        is_first = single_instance(args.instance_group)
        if not is_first:
            import json
            data = {'cmd': 'new_instance', 'args': tuple(sys.argv), 'startup_id': os.environ.get('DESKTOP_STARTUP_ID')}
            data = json.dumps(data, ensure_ascii=False).encode('utf-8')
            single_instance.socket.sendall(data)
            return
    opts = create_opts(args)
    change_wcwidth(not opts.use_system_wcwidth)
    glfw_module = 'cocoa' if isosx else 'x11'
    if not glfw_init(os.path.join(base, 'glfw-{}.so'.format(glfw_module))):
        raise SystemExit('GLFW initialization failed')
    if glfw_module == 'x11':
        glfw_init_hint_string(GLFW_X11_WM_CLASS_CLASS, args.cls)
        glfw_init_hint_string(GLFW_X11_WM_CLASS_NAME, args.cls)
    try:
        with setup_profiling(args):
            # Avoid needing to launch threads to reap zombies
            install_sigchld_handler()
            run_app(opts, args)
            signal.signal(signal.SIGCHLD, signal.SIG_DFL)
    finally:
        glfw_terminate()
