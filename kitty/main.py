#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2016, Kovid Goyal <kovid at kovidgoyal.net>

import argparse
import locale
import os
import signal
import sys
from contextlib import contextmanager
from gettext import gettext as _

from .boss import Boss
from .config import (
    initial_window_size, load_cached_values, load_config, save_cached_values
)
from .constants import (
    appname, defconf, isosx, iswayland, logo_data_file, str_version
)
from .fast_data_types import (
    change_wcwidth, create_os_window, glfw_init, glfw_init_hint_string,
    glfw_terminate, install_sigchld_handler, set_default_window_icon,
    set_logical_dpi, set_options
)
from .fonts.box_drawing import set_scale
from .layout import all_layouts
from .utils import (
    detach, end_startup_notification, get_logical_dpi,
    init_startup_notification
)

try:
    from .fast_data_types import GLFW_X11_WM_CLASS_NAME, GLFW_X11_WM_CLASS_CLASS
except ImportError:
    GLFW_X11_WM_CLASS_NAME = GLFW_X11_WM_CLASS_CLASS = None


def option_parser():
    parser = argparse.ArgumentParser(
        prog=appname,
        description=_('The {} terminal emulator').format(appname)
    )
    a = parser.add_argument
    a(
        '--class',
        default=appname,
        dest='cls',
        help=_('Set the WM_CLASS property')
    )
    a(
        '--config',
        action='append',
        help=_(
            'Specify a path to the config file(s) to use.'
            ' Can be specified multiple times to read multiple'
            ' config files in sequence, which are merged. Default: {}'
        ).format(defconf)
    )
    a(
        '--override',
        '-o',
        action='append',
        help=_(
            'Override individual configuration options, can be specified'
            ' multiple times. Syntax: name=value. For example: {}'
        ).format('-o font_size=20')
    )
    a(
        '--cmd',
        '-c',
        default=None,
        help=_('Run python code in the kitty context')
    )
    a(
        '-d',
        '--directory',
        default='.',
        help=_('Change to the specified directory when launching')
    )
    a(
        '--version',
        '-v',
        action='version',
        version='{} {} by Kovid Goyal'.format(appname, str_version)
    )
    a(
        '--dump-commands',
        action='store_true',
        default=False,
        help=_('Output commands received from child process to stdout')
    )
    if not isosx:
        a(
            '--detach',
            action='store_true',
            default=False,
            help=_('Detach from the controlling terminal, if any')
        )
    a(
        '--replay-commands',
        default=None,
        help=_('Replay previously dumped commands')
    )
    a(
        '--dump-bytes',
        help=_('Path to file in which to store the raw bytes received from the'
               ' child process. Useful for debugging.')
    )
    a(
        '--debug-gl',
        action='store_true',
        default=False,
        help=_('Debug OpenGL commands. This will cause all OpenGL calls'
               ' to check for errors instead of ignoring them. Useful'
               ' when debugging rendering problems.')
    )
    a(
        '--window-layout',
        default=None,
        choices=frozenset(all_layouts.keys()),
        help=_('The window layout to use on startup')
    )
    a(
        '--session',
        default=None,
        help=_(
            'Path to a file containing the startup session (tabs, windows, layout, programs)'
        )
    )
    a(
        'args',
        nargs=argparse.REMAINDER,
        help=_(
            'The remaining arguments are used to launch a program other than the default shell. Any further options are passed'
            ' directly to the program being invoked.'
        )
    )
    return parser


def run_app(opts, args):
    set_scale(opts.box_drawing_scale)
    set_options(opts, iswayland, args.debug_gl)
    load_cached_values()
    w, h = initial_window_size()
    window_id = create_os_window(w, h, args.cls)
    startup_ctx = init_startup_notification(window_id)
    if isosx:
        from .fast_data_types import cocoa_create_global_menu, cocoa_init
        cocoa_init()
        cocoa_create_global_menu()
    elif not iswayland:  # no window icons on wayland
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
    config = args.config or (defconf, )
    overrides = (a.replace('=', ' ', 1) for a in args.override or ())
    opts = load_config(*config, overrides=overrides)
    change_wcwidth(not opts.use_system_wcwidth)
    if GLFW_X11_WM_CLASS_CLASS is not None:
        glfw_init_hint_string(GLFW_X11_WM_CLASS_CLASS, args.cls)
    if not glfw_init():
        raise SystemExit('GLFW initialization failed')
    try:
        with setup_profiling(args):
            # Avoid needing to launch threads to reap zombies
            install_sigchld_handler()
            run_app(opts, args)
            signal.signal(signal.SIGCHLD, signal.SIG_DFL)
    finally:
        glfw_terminate()
