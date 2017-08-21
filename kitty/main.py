#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2016, Kovid Goyal <kovid at kovidgoyal.net>

import argparse
import locale
import os
import sys
import tempfile
from gettext import gettext as _

from queue import Empty

from .boss import Boss
from .config import (
    cached_values, load_cached_values, load_config, save_cached_values
)
from .constants import (
    appname, config_dir, isosx, logo_data_file, str_version, viewport_size
)
from .fast_data_types import (
    GL_COLOR_BUFFER_BIT, GLFW_CONTEXT_VERSION_MAJOR,
    GLFW_CONTEXT_VERSION_MINOR, GLFW_OPENGL_CORE_PROFILE,
    GLFW_OPENGL_FORWARD_COMPAT, GLFW_OPENGL_PROFILE, GLFW_SAMPLES,
    GLFW_STENCIL_BITS, Window, change_wcwidth,
    enable_automatic_opengl_error_checking, glClear, glClearColor, glewInit,
    glfw_init, glfw_set_error_callback, glfw_swap_interval, glfw_terminate,
    glfw_wait_events, glfw_window_hint, glfw_init_hint_string, check_for_extensions
)
try:
    from .fast_data_types import GLFW_X11_WM_CLASS_NAME, GLFW_X11_WM_CLASS_CLASS
except ImportError:
    GLFW_X11_WM_CLASS_NAME = GLFW_X11_WM_CLASS_CLASS = None
from .layout import all_layouts
from .shaders import GL_VERSION
from .utils import safe_print, detach


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
        '--profile',
        action='store_true',
        default=False,
        help=_('Show profiling data after exit')
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


def setup_opengl():
    glfw_window_hint(GLFW_CONTEXT_VERSION_MAJOR, GL_VERSION[0])
    glfw_window_hint(GLFW_CONTEXT_VERSION_MINOR, GL_VERSION[1])
    glfw_window_hint(GLFW_OPENGL_PROFILE, GLFW_OPENGL_CORE_PROFILE)
    glfw_window_hint(GLFW_OPENGL_FORWARD_COMPAT, True)
    glfw_window_hint(GLFW_SAMPLES, 0)
    if isosx:
        # OS X cannot handle 16bit stencil buffers
        glfw_window_hint(GLFW_STENCIL_BITS, 8)


def clear_buffers(window, opts):
    bg = opts.background
    glClearColor(bg.red / 255, bg.green / 255, bg.blue / 255, 1)
    glfw_swap_interval(0)
    glClear(GL_COLOR_BUFFER_BIT)
    window.swap_buffers()
    glClear(GL_COLOR_BUFFER_BIT)
    # We dont turn this on as it causes rendering performance to be much worse,
    # for example, dragging the mouse to select is laggy
    # glfw_swap_interval(1)


def dispatch_pending_calls(boss):
    while True:
        try:
            func, args = boss.pending_ui_thread_calls.get_nowait()
        except Empty:
            break
        try:
            func(*args)
        except Exception:
            import traceback
            safe_print(traceback.format_exc())
    boss.ui_timers()


def run_app(opts, args):
    setup_opengl()
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
        if opts.macos_hide_titlebar:
            from .fast_data_types import cocoa_hide_titlebar
            cocoa_hide_titlebar(window.cocoa_window_id())
    else:
        with open(logo_data_file, 'rb') as f:
            window.set_icon(f.read(), 256, 256)
    viewport_size.width, viewport_size.height = window.get_framebuffer_size()
    w, h = window.get_window_size()
    viewport_size.x_ratio = viewport_size.width / float(w)
    viewport_size.y_ratio = viewport_size.height / float(h)
    glewInit()
    if isosx:
        check_for_extensions()
    boss = Boss(window, opts, args)
    boss.start()
    clear_buffers(window, opts)
    try:
        while not window.should_close():
            boss.render()
            window.swap_buffers()
            glfw_wait_events(boss.ui_timers.timeout())
            dispatch_pending_calls(boss)
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


def main():
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
    enable_automatic_opengl_error_checking(args.debug_gl)
    if GLFW_X11_WM_CLASS_CLASS is not None:
        glfw_init_hint_string(GLFW_X11_WM_CLASS_CLASS, opts.cls)
    if not glfw_init():
        raise SystemExit('GLFW initialization failed')
    try:
        if args.profile:
            tf = tempfile.NamedTemporaryFile(prefix='kitty-profiling-stats-')
            args.profile = tf.name
            import cProfile
            import pstats
            pr = cProfile.Profile()
            pr.enable()
            run_app(opts, args)
            pr.disable()
            pr.create_stats()
            s = pstats.Stats(pr)
            s.add(args.profile)
            tf.close()
            s.strip_dirs()
            s.sort_stats('time', 'name')
            s.print_stats(30)
        else:
            run_app(opts, args)
    finally:
        glfw_terminate()
