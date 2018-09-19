#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2016, Kovid Goyal <kovid at kovidgoyal.net>

import locale
import os
import sys
from contextlib import contextmanager

from .borders import load_borders_program
from .boss import Boss
from .child import set_default_env
from .cli import create_opts, parse_args
from .config import cached_values_for, initial_window_size_func
from .constants import (
    appname, beam_cursor_data_file, config_dir, glfw_path, is_macos,
    is_wayland, kitty_exe, logo_data_file
)
from .fast_data_types import (
    GLFW_IBEAM_CURSOR, GLFW_MOD_SUPER, create_os_window, free_font_data,
    glfw_init, glfw_terminate, load_png_data, set_custom_cursor,
    set_default_window_icon, set_options
)
from .fonts.box_drawing import set_scale
from .fonts.render import set_font_family
from .utils import (
    detach, log_error, single_instance, startup_notification_handler,
    unix_socket_paths
)
from .window import load_shader_programs


def set_custom_ibeam_cursor():
    with open(beam_cursor_data_file, 'rb') as f:
        data = f.read()
    rgba_data, width, height = load_png_data(data)
    c2x = os.path.splitext(beam_cursor_data_file)
    with open(c2x[0] + '@2x' + c2x[1], 'rb') as f:
        data = f.read()
    rgba_data2, width2, height2 = load_png_data(data)
    images = (rgba_data, width, height), (rgba_data2, width2, height2)
    try:
        set_custom_cursor(GLFW_IBEAM_CURSOR, images, 4, 8)
    except Exception as e:
        log_error('Failed to set custom beam cursor with error: {}'.format(e))


def talk_to_instance(args):
    import json
    import socket
    data = {'cmd': 'new_instance', 'args': tuple(sys.argv),
            'startup_id': os.environ.get('DESKTOP_STARTUP_ID'),
            'cwd': os.getcwd()}
    notify_socket = None
    if args.wait_for_single_instance_window_close:
        address = '\0{}-os-window-close-notify-{}-{}'.format(appname, os.getpid(), os.geteuid())
        notify_socket = socket.socket(family=socket.AF_UNIX)
        try:
            notify_socket.bind(address)
        except FileNotFoundError:
            for address in unix_socket_paths(address[1:], ext='.sock'):
                notify_socket.bind(address)
                break
        data['notify_on_os_window_death'] = address
        notify_socket.listen()

    data = json.dumps(data, ensure_ascii=False).encode('utf-8')
    single_instance.socket.sendall(data)
    try:
        single_instance.socket.shutdown(socket.SHUT_RDWR)
    except EnvironmentError:
        pass
    single_instance.socket.close()

    if args.wait_for_single_instance_window_close:
        conn = notify_socket.accept()[0]
        conn.recv(1)
        try:
            conn.shutdown(socket.SHUT_RDWR)
        except EnvironmentError:
            pass
        conn.close()


def load_all_shaders(semi_transparent=0):
    load_shader_programs(semi_transparent, load_all_shaders.cursor_text_color)
    load_borders_program()


load_all_shaders.cursor_text_color = None


def init_glfw(debug_keyboard=False):
    glfw_module = 'cocoa' if is_macos else ('wayland' if is_wayland else 'x11')
    if not glfw_init(glfw_path(glfw_module), debug_keyboard):
        raise SystemExit('GLFW initialization failed')
    return glfw_module


def prefer_cmd_shortcuts(x):
    return x[0] == GLFW_MOD_SUPER


def get_new_os_window_trigger(opts):
    new_os_window_trigger = None
    if is_macos:
        new_os_window_shortcuts = []
        for k, v in opts.keymap.items():
            if v.func == 'new_os_window':
                new_os_window_shortcuts.append(k)
        if new_os_window_shortcuts:
            from .fast_data_types import cocoa_set_new_window_trigger
            new_os_window_shortcuts.sort(key=prefer_cmd_shortcuts, reverse=True)
            for candidate in new_os_window_shortcuts:
                if cocoa_set_new_window_trigger(candidate[0], candidate[2]):
                    new_os_window_trigger = candidate
                    break
    return new_os_window_trigger


def _run_app(opts, args):
    new_os_window_trigger = get_new_os_window_trigger(opts)
    if is_macos and opts.macos_custom_beam_cursor:
        set_custom_ibeam_cursor()
    load_all_shaders.cursor_text_color = opts.cursor_text_color
    if not is_wayland and not is_macos:  # no window icons on wayland
        with open(logo_data_file, 'rb') as f:
            set_default_window_icon(f.read(), 256, 256)
    with cached_values_for(run_app.cached_values_name) as cached_values:
        with startup_notification_handler(extra_callback=run_app.first_window_callback) as pre_show_callback:
            window_id = create_os_window(
                    run_app.initial_window_size_func(opts, cached_values),
                    pre_show_callback,
                    appname, args.name or args.cls or appname,
                    args.cls or appname, load_all_shaders)
        boss = Boss(window_id, opts, args, cached_values, new_os_window_trigger)
        boss.start()
        try:
            boss.child_monitor.main_loop()
        finally:
            boss.destroy()


def run_app(opts, args):
    set_scale(opts.box_drawing_scale)
    set_options(opts, is_wayland, args.debug_gl, args.debug_font_fallback)
    set_font_family(opts, debug_font_matching=args.debug_font_fallback)
    try:
        _run_app(opts, args)
    finally:
        free_font_data()  # must free font data before glfw/freetype/fontconfig/opengl etc are finalized


run_app.cached_values_name = 'main'
run_app.first_window_callback = lambda window_handle: None
run_app.initial_window_size_func = initial_window_size_func


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


def macos_cmdline(argv_args):
    try:
        with open(os.path.join(config_dir, 'macos-launch-services-cmdline')) as f:
            raw = f.read()
    except FileNotFoundError:
        return argv_args
    import shlex
    raw = raw.strip()
    ans = shlex.split(raw)
    if ans and ans[0] == 'kitty':
        del ans[0]
    return ans


def setup_environment(opts, args):
    extra_env = opts.env.copy()
    if opts.editor != '.':
        os.environ['EDITOR'] = opts.editor
    if args.listen_on:
        os.environ['KITTY_LISTEN_ON'] = args.listen_on
    set_default_env(extra_env)


def _main():
    try:
        sys.setswitchinterval(1000.0)  # we have only a single python thread
    except AttributeError:
        pass  # python compiled without threading
    if is_macos:
        ensure_osx_locale()
    try:
        locale.setlocale(locale.LC_ALL, '')
    except Exception:
        if not is_macos:
            raise
        log_error('Failed to set locale with LANG:', os.environ.get('LANG'))
        os.environ.pop('LANG', None)
        try:
            locale.setlocale(locale.LC_ALL, '')
        except Exception:
            log_error('Failed to set locale with no LANG, ignoring')

    # Ensure kitty is in PATH
    rpath = os.path.dirname(kitty_exe())
    items = frozenset(os.environ['PATH'].split(os.pathsep))
    if rpath and rpath not in items:
        os.environ['PATH'] += os.pathsep + rpath

    args = sys.argv[1:]
    if is_macos and os.environ.pop('KITTY_LAUNCHED_BY_LAUNCH_SERVICES', None) == '1':
        os.chdir(os.path.expanduser('~'))
        args = macos_cmdline(args)
    try:
        cwd_ok = os.path.isdir(os.getcwd())
    except Exception:
        cwd_ok = False
    if not cwd_ok:
        os.chdir(os.path.expanduser('~'))
    args, rest = parse_args(args=args)
    args.args = rest
    if args.debug_config:
        init_glfw(args.debug_keyboard)  # needed for parsing native keysyms
        create_opts(args, debug_config=True)
        return
    if getattr(args, 'detach', False):
        detach()
    if args.replay_commands:
        from kitty.client import main
        main(args.replay_commands)
        return
    if args.single_instance:
        is_first = single_instance(args.instance_group)
        if not is_first:
            talk_to_instance(args)
            return
    init_glfw(args.debug_keyboard)  # needed for parsing native keysyms
    opts = create_opts(args)
    setup_environment(opts, args)
    try:
        with setup_profiling(args):
            # Avoid needing to launch threads to reap zombies
            run_app(opts, args)
    finally:
        glfw_terminate()


def main():
    try:
        _main()
    except Exception:
        import traceback
        tb = traceback.format_exc()
        log_error(tb)
        raise SystemExit(1)
