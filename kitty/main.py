#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2016, Kovid Goyal <kovid at kovidgoyal.net>

import argparse
import tempfile
import os
import sys
from queue import Empty
from gettext import gettext as _


from .config import load_config
from .constants import appname, str_version, config_dir, viewport_size
from .layout import all_layouts
from .tabs import TabManager
from .shaders import GL_VERSION
from .fast_data_types import (
    glewInit, enable_automatic_opengl_error_checking, glClear, glClearColor,
    GL_COLOR_BUFFER_BIT, GLFW_CONTEXT_VERSION_MAJOR,
    GLFW_CONTEXT_VERSION_MINOR, GLFW_OPENGL_PROFILE,
    GLFW_OPENGL_FORWARD_COMPAT, GLFW_OPENGL_CORE_PROFILE, GLFW_SAMPLES,
    glfw_set_error_callback, glfw_init, glfw_terminate, glfw_window_hint,
    glfw_swap_interval, glfw_wait_events, Window
)


def option_parser():
    parser = argparse.ArgumentParser(prog=appname, description=_('The {} terminal emulator').format(appname))
    defconf = os.path.join(config_dir, 'kitty.conf')
    a = parser.add_argument
    a('--class', default=appname, dest='cls', help=_('Set the WM_CLASS property'))
    a('--config', default=defconf, help=_('Specify a path to the config file to use. Default: {}').format(defconf))
    a('--cmd', '-c', default=None, help=_('Run python code in the kitty context'))
    a('-d', '--directory', default='.', help=_('Change to the specified directory when launching'))
    a('--version', action='version', version='{} {} by Kovid Goyal'.format(appname, '.'.join(str_version)))
    a('--profile', action='store_true', default=False, help=_('Show profiling data after exit'))
    a('--dump-commands', action='store_true', default=False, help=_('Output commands received from child process to stdout'))
    a('--replay-commands', default=None, help=_('Replay previously dumped commands'))
    a('--window-layout', default=None, choices=frozenset(all_layouts.keys()), help=_(
        'The window layout to use on startup. Choices: {}').format(', '.join(all_layouts)))
    a('args', nargs=argparse.REMAINDER, help=_(
        'The remaining arguments are used to launch a program other than the default shell. Any further options are passed'
        ' directly to the program being invoked.'
    ))
    return parser


def setup_opengl():
    glfw_window_hint(GLFW_CONTEXT_VERSION_MAJOR, GL_VERSION[0])
    glfw_window_hint(GLFW_CONTEXT_VERSION_MINOR, GL_VERSION[1])
    glfw_window_hint(GLFW_OPENGL_PROFILE, GLFW_OPENGL_CORE_PROFILE)
    glfw_window_hint(GLFW_OPENGL_FORWARD_COMPAT, True)
    glfw_window_hint(GLFW_SAMPLES, 0)


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


def dispatch_pending_calls(tabs):
    while True:
        try:
            func, args = tabs.pending_ui_thread_calls.get_nowait()
        except Empty:
            break
        try:
            func(*args)
        except Exception:
            import traceback
            traceback.print_exc()
    tabs.ui_timers()


def run_app(opts, args):
    setup_opengl()
    window = Window(
        viewport_size.width, viewport_size.height, args.cls)
    window.set_title(appname)
    window.make_context_current()
    glewInit()
    tabs = TabManager(window, opts, args)
    tabs.start()
    clear_buffers(window, opts)
    try:
        while not window.should_close():
            tabs.render()
            window.swap_buffers()
            glfw_wait_events(tabs.ui_timers.timeout())
            dispatch_pending_calls(tabs)
    finally:
        tabs.destroy()
    del window


def on_glfw_error(code, msg):
    if isinstance(msg, bytes):
        try:
            msg = msg.decode('utf-8')
        except Exception:
            msg = repr(msg)
    print('[glfw error] ', msg, file=sys.stderr)


def main():
    args = option_parser().parse_args()
    if args.cmd:
        exec(args.cmd)
        return
    if args.replay_commands:
        from kitty.client import main
        main(args.replay_commands)
        return
    opts = load_config(args.config)
    glfw_set_error_callback(on_glfw_error)
    enable_automatic_opengl_error_checking(False)
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
        os.closerange(3, 100)
