#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2016, Kovid Goyal <kovid at kovidgoyal.net>

import argparse
import locale
import os
import sys
from contextlib import contextmanager
from gettext import gettext as _

from .boss import Boss
from .config import (
    cached_values, load_cached_values, load_config, save_cached_values
)
from .constants import (
    appname, config_dir, isosx, logo_data_file, str_version, viewport_size
)
from .fast_data_types import (
    GL_VERSION_REQUIRED, GLFW_CONTEXT_VERSION_MAJOR,
    GLFW_CONTEXT_VERSION_MINOR, GLFW_DECORATED, GLFW_OPENGL_CORE_PROFILE,
    GLFW_OPENGL_FORWARD_COMPAT, GLFW_OPENGL_PROFILE, GLFW_SAMPLES,
    GLFW_STENCIL_BITS, Window, change_wcwidth, check_for_extensions,
    clear_buffers, glewInit, glfw_init, glfw_init_hint_string,
    glfw_set_error_callback, glfw_swap_interval, glfw_terminate,
    glfw_window_hint
)
from .layout import all_layouts
from .utils import color_as_int, detach, safe_print

try:
    from .fast_data_types import GLFW_X11_WM_CLASS_NAME, GLFW_X11_WM_CLASS_CLASS
except ImportError:
    GLFW_X11_WM_CLASS_NAME = GLFW_X11_WM_CLASS_CLASS = None


defconf = os.path.join(config_dir, 'kitty.conf')


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
        '--debug-kitty-gl',
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


def setup_opengl(opts):
    if opts.macos_hide_titlebar:
        glfw_window_hint(GLFW_DECORATED, False)
    glfw_window_hint(GLFW_CONTEXT_VERSION_MAJOR, GL_VERSION_REQUIRED[0])
    glfw_window_hint(GLFW_CONTEXT_VERSION_MINOR, GL_VERSION_REQUIRED[1])
    glfw_window_hint(GLFW_OPENGL_PROFILE, GLFW_OPENGL_CORE_PROFILE)
    glfw_window_hint(GLFW_OPENGL_FORWARD_COMPAT, True)
    glfw_window_hint(GLFW_SAMPLES, 0)
    if isosx:
        # OS X cannot handle 16bit stencil buffers
        glfw_window_hint(GLFW_STENCIL_BITS, 8)


def run_app(opts, args):
    setup_opengl(opts)
    load_cached_values()
    if 'window-size' in cached_values and opts.remember_window_size:
        ws = cached_values['window-size']
        try:
            viewport_size.width, viewport_size.height = map(int, ws)
        except Exception:
            safe_print('Invalid cached window size, ignoring', file=sys.stderr)
        viewport_size.width = max(100, viewport_size.width)
        viewport_size.height = max(80, viewport_size.height)
    else:
        viewport_size.width = opts.initial_window_width
        viewport_size.height = opts.initial_window_height
    try:
        window = Window(viewport_size.width, viewport_size.height, args.cls)
    except ValueError:
        safe_print('Failed to create GLFW window with initial size:', viewport_size)
        viewport_size.width = 640
        viewport_size.height = 400
        window = Window(viewport_size.width, viewport_size.height, args.cls)
    window.set_title(appname)
    window.make_context_current()
    if isosx:
        from .fast_data_types import cocoa_make_window_resizable, cocoa_create_global_menu
        check_for_extensions()
        cocoa_create_global_menu()
        if opts.macos_hide_titlebar:
            cocoa_make_window_resizable(window.cocoa_window_id())
    else:
        with open(logo_data_file, 'rb') as f:
            window.set_icon(f.read(), 256, 256)
    viewport_size.width, viewport_size.height = window.get_framebuffer_size()
    w, h = window.get_window_size()
    viewport_size.x_ratio = viewport_size.width / float(w)
    viewport_size.y_ratio = viewport_size.height / float(h)
    glewInit()
    boss = Boss(window, opts, args)
    boss.start()
    glfw_swap_interval(0)
    clear_buffers(window.swap_buffers, color_as_int(opts.background))
    # We dont turn this on as it causes rendering performance to be much worse,
    # for example, dragging the mouse to select is laggy
    # glfw_swap_interval(1)
    try:
        boss.child_monitor.main_loop()
    finally:
        boss.destroy()
    del window
    cached_values['window-size'] = viewport_size.width, viewport_size.height
    save_cached_values()


def on_glfw_error(code, msg):
    if isinstance(msg, bytes):
        try:
            msg = msg.decode('utf-8')
        except Exception:
            msg = repr(msg)
    safe_print('[glfw error] ', msg, file=sys.stderr)


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
        subprocess.check_call(['pprof', '--callgrind', exe, '/tmp/kitty-profile.log'], stdout=open(cg, 'wb'))
        try:
            subprocess.Popen(['kcachegrind', cg])
        except FileNotFoundError:
            subprocess.check_call(['pprof', '--text', exe, '/tmp/kitty-profile.log'])
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
    glfw_set_error_callback(on_glfw_error)
    if GLFW_X11_WM_CLASS_CLASS is not None:
        glfw_init_hint_string(GLFW_X11_WM_CLASS_CLASS, opts.cls)
    if not glfw_init():
        raise SystemExit('GLFW initialization failed')
    try:
        with setup_profiling(args):
            run_app(opts, args)
    finally:
        glfw_terminate()
