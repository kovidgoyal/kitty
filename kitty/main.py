#!/usr/bin/env python3
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2016, Kovid Goyal <kovid at kovidgoyal.net>

import locale
import os
import shutil
import sys
from contextlib import contextmanager, suppress
from typing import Dict, Generator, List, Optional, Sequence

from .borders import load_borders_program
from .boss import Boss
from .child import set_default_env
from .cli import create_opts, parse_args
from .cli_stub import CLIOptions
from .conf.utils import BadLine
from .config import cached_values_for
from .constants import (
    appname, beam_cursor_data_file, config_dir, glfw_path, is_macos,
    is_wayland, kitty_exe, logo_png_file, running_in_kitty
)
from .fast_data_types import (
    GLFW_IBEAM_CURSOR, GLFW_MOD_ALT, GLFW_MOD_SHIFT, create_os_window,
    free_font_data, glfw_init, glfw_terminate, load_png_data,
    set_custom_cursor, set_default_window_icon, set_options
)
from .fonts.box_drawing import set_scale
from .fonts.render import set_font_family
from .options_stub import Options as OptionsStub
from .os_window_size import initial_window_size_func
from .session import get_os_window_sizing_data
from .types import SingleKey
from .utils import (
    detach, expandvars, log_error, single_instance,
    startup_notification_handler, unix_socket_paths
)
from .window import load_shader_programs


def set_custom_ibeam_cursor() -> None:
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


def talk_to_instance(args: CLIOptions) -> None:
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

    sdata = json.dumps(data, ensure_ascii=False).encode('utf-8')
    assert single_instance.socket is not None
    single_instance.socket.sendall(sdata)
    with suppress(OSError):
        single_instance.socket.shutdown(socket.SHUT_RDWR)
    single_instance.socket.close()

    if args.wait_for_single_instance_window_close:
        assert notify_socket is not None
        conn = notify_socket.accept()[0]
        conn.recv(1)
        with suppress(OSError):
            conn.shutdown(socket.SHUT_RDWR)
        conn.close()


def load_all_shaders(semi_transparent: bool = False) -> None:
    load_shader_programs(semi_transparent)
    load_borders_program()


def init_glfw_module(glfw_module: str, debug_keyboard: bool = False, debug_rendering: bool = False) -> None:
    if not glfw_init(glfw_path(glfw_module), debug_keyboard, debug_rendering):
        raise SystemExit('GLFW initialization failed')


def init_glfw(opts: OptionsStub, debug_keyboard: bool = False, debug_rendering: bool = False) -> str:
    glfw_module = 'cocoa' if is_macos else ('wayland' if is_wayland(opts) else 'x11')
    init_glfw_module(glfw_module, debug_keyboard, debug_rendering)
    return glfw_module


def get_macos_shortcut_for(opts: OptionsStub, function: str = 'new_os_window') -> Optional[SingleKey]:
    ans = None
    candidates = []
    for k, v in opts.keymap.items():
        if v.func == function:
            candidates.append(k)
    if candidates:
        from .fast_data_types import cocoa_set_global_shortcut
        alt_mods = GLFW_MOD_ALT, GLFW_MOD_ALT | GLFW_MOD_SHIFT
        # Reverse list so that later defined keyboard shortcuts take priority over earlier defined ones
        for candidate in reversed(candidates):
            if candidate.mods in alt_mods:
                # Option based shortcuts dont work in the global menubar,
                # presumably because Apple reserves them for IME, see
                # https://github.com/kovidgoyal/kitty/issues/3515
                continue
            if cocoa_set_global_shortcut(function, candidate[0], candidate[2]):
                ans = candidate
                break
    return ans


def set_x11_window_icon() -> None:
    # max icon size on X11 64bits is 128x128
    path, ext = os.path.splitext(logo_png_file)
    set_default_window_icon(path + '-128' + ext)


def _run_app(opts: OptionsStub, args: CLIOptions, bad_lines: Sequence[BadLine] = ()) -> None:
    global_shortcuts: Dict[str, SingleKey] = {}
    if is_macos:
        for ac in ('new_os_window', 'close_os_window', 'close_tab', 'edit_config_file', 'previous_tab',
                   'next_tab', 'new_tab', 'new_window', 'close_window'):
            val = get_macos_shortcut_for(opts, ac)
            if val is not None:
                global_shortcuts[ac] = val
    if is_macos and opts.macos_custom_beam_cursor:
        set_custom_ibeam_cursor()
    if not is_wayland() and not is_macos:  # no window icons on wayland
        set_x11_window_icon()
    load_shader_programs.use_selection_fg = opts.selection_foreground is not None
    with cached_values_for(run_app.cached_values_name) as cached_values:
        with startup_notification_handler(extra_callback=run_app.first_window_callback) as pre_show_callback:
            window_id = create_os_window(
                    run_app.initial_window_size_func(get_os_window_sizing_data(opts), cached_values),
                    pre_show_callback,
                    args.title or appname, args.name or args.cls or appname,
                    args.cls or appname, load_all_shaders)
        boss = Boss(opts, args, cached_values, global_shortcuts)
        boss.start(window_id)
        if bad_lines:
            boss.show_bad_config_lines(bad_lines)
        try:
            boss.child_monitor.main_loop()
        finally:
            boss.destroy()


class AppRunner:

    def __init__(self) -> None:
        self.cached_values_name = 'main'
        self.first_window_callback = lambda window_handle: None
        self.initial_window_size_func = initial_window_size_func

    def __call__(self, opts: OptionsStub, args: CLIOptions, bad_lines: Sequence[BadLine] = ()) -> None:
        set_scale(opts.box_drawing_scale)
        set_options(opts, is_wayland(), args.debug_rendering, args.debug_font_fallback)
        try:
            set_font_family(opts, debug_font_matching=args.debug_font_fallback)
            _run_app(opts, args, bad_lines)
        finally:
            set_options(None)
            free_font_data()  # must free font data before glfw/freetype/fontconfig/opengl etc are finalized


run_app = AppRunner()


def ensure_macos_locale() -> None:
    # Ensure the LANG env var is set. See
    # https://github.com/kovidgoyal/kitty/issues/90
    from .fast_data_types import cocoa_get_lang
    if 'LANG' not in os.environ:
        lang = cocoa_get_lang()
        if lang is not None:
            os.environ['LANG'] = lang + '.UTF-8'


@contextmanager
def setup_profiling(args: CLIOptions) -> Generator[None, None, None]:
    try:
        from .fast_data_types import start_profiler, stop_profiler
        do_profile = True
    except ImportError:
        do_profile = False
    if do_profile:
        start_profiler('/tmp/kitty-profile.log')
    yield
    if do_profile:
        import subprocess
        stop_profiler()
        exe = kitty_exe()
        cg = '/tmp/kitty-profile.callgrind'
        print('Post processing profile data for', exe, '...')
        with open(cg, 'wb') as f:
            subprocess.call(['pprof', '--callgrind', exe, '/tmp/kitty-profile.log'], stdout=f)
        try:
            subprocess.Popen(['kcachegrind', cg])
        except FileNotFoundError:
            subprocess.call(['pprof', '--text', exe, '/tmp/kitty-profile.log'])
            print('To view the graphical call data, use: kcachegrind', cg)


def macos_cmdline(argv_args: List[str]) -> List[str]:
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


def expand_listen_on(listen_on: str, from_config_file: bool) -> str:
    listen_on = expandvars(listen_on)
    if '{kitty_pid}' not in listen_on and from_config_file:
        listen_on += '-{kitty_pid}'
    listen_on = listen_on.replace('{kitty_pid}', str(os.getpid()))
    if listen_on.startswith('unix:'):
        path = listen_on[len('unix:'):]
        if not path.startswith('@'):
            if path.startswith('~'):
                listen_on = f'unix:{os.path.expanduser(path)}'
            elif not os.path.isabs(path):
                import tempfile
                listen_on = f'unix:{os.path.join(tempfile.gettempdir(), path)}'
    return listen_on


def setup_environment(opts: OptionsStub, cli_opts: CLIOptions) -> None:
    from_config_file = False
    if not cli_opts.listen_on and opts.listen_on.startswith('unix:'):
        cli_opts.listen_on = opts.listen_on
        from_config_file = True
    if cli_opts.listen_on and opts.allow_remote_control != 'n':
        cli_opts.listen_on = expand_listen_on(cli_opts.listen_on, from_config_file)
        os.environ['KITTY_LISTEN_ON'] = cli_opts.listen_on
    set_default_env(opts.env.copy())


def set_locale() -> None:
    if is_macos:
        ensure_macos_locale()
    try:
        locale.setlocale(locale.LC_ALL, '')
    except Exception:
        log_error('Failed to set locale with LANG:', os.environ.get('LANG'))
        os.environ.pop('LANG', None)
        try:
            locale.setlocale(locale.LC_ALL, '')
        except Exception:
            log_error('Failed to set locale with no LANG')


def _main() -> None:
    running_in_kitty(True)
    with suppress(AttributeError):  # python compiled without threading
        sys.setswitchinterval(1000.0)  # we have only a single python thread

    try:
        set_locale()
    except Exception:
        log_error('Failed to set locale, ignoring')

    # Ensure the correct kitty is in PATH
    rpath = sys._xoptions.get('bundle_exe_dir')
    if rpath:
        modify_path = is_macos or getattr(sys, 'frozen', False) or sys._xoptions.get('kitty_from_source') == '1'
        if modify_path or not shutil.which('kitty'):
            existing_paths = list(filter(None, os.environ.get('PATH', '').split(os.pathsep)))
            existing_paths.insert(0, rpath)
            os.environ['PATH'] = os.pathsep.join(existing_paths)

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
    cli_opts, rest = parse_args(args=args, result_class=CLIOptions)
    cli_opts.args = rest
    if cli_opts.debug_config:
        create_opts(cli_opts, debug_config=True)
        return
    if cli_opts.detach:
        if cli_opts.session == '-':
            from .session import PreReadSession
            cli_opts.session = PreReadSession(sys.stdin.read())
        detach()
    if cli_opts.replay_commands:
        from kitty.client import main as client_main
        client_main(cli_opts.replay_commands)
        return
    if cli_opts.single_instance:
        is_first = single_instance(cli_opts.instance_group)
        if not is_first:
            talk_to_instance(cli_opts)
            return
    bad_lines: List[BadLine] = []
    opts = create_opts(cli_opts, accumulate_bad_lines=bad_lines)
    init_glfw(opts, cli_opts.debug_keyboard, cli_opts.debug_rendering)
    setup_environment(opts, cli_opts)
    try:
        with setup_profiling(cli_opts):
            # Avoid needing to launch threads to reap zombies
            run_app(opts, cli_opts, bad_lines)
    finally:
        glfw_terminate()


def main() -> None:
    try:
        _main()
    except Exception:
        import traceback
        tb = traceback.format_exc()
        log_error(tb)
        raise SystemExit(1)
