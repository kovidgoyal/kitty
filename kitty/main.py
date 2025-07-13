#!/usr/bin/env python
# License: GPL v3 Copyright: 2016, Kovid Goyal <kovid at kovidgoyal.net>

import json
import locale
import os
import shutil
import sys
from collections.abc import Generator, Sequence
from contextlib import contextmanager, suppress

from .borders import load_borders_program
from .boss import Boss
from .child import set_default_env, set_LANG_in_default_env
from .cli import create_opts, parse_args
from .cli_stub import CLIOptions
from .colors import theme_colors
from .conf.utils import BadLine
from .config import cached_values_for
from .constants import (
    appname,
    beam_cursor_data_file,
    clear_handled_signals,
    glfw_path,
    is_macos,
    is_quick_access_terminal_app,
    is_wayland,
    kitten_exe,
    kitty_exe,
    launched_by_launch_services,
    logo_png_file,
    running_in_kitty,
    supports_window_occlusion,
    website_url,
)
from .fast_data_types import (
    GLFW_MOD_ALT,
    GLFW_MOD_SHIFT,
    SingleKey,
    create_os_window,
    free_font_data,
    glfw_get_monitor_names,
    glfw_get_monitor_workarea,
    glfw_init,
    glfw_terminate,
    grab_keyboard,
    is_layer_shell_supported,
    load_png_data,
    mask_kitty_signals_process_wide,
    run_at_exit_cleanup_functions,
    set_custom_cursor,
    set_default_window_icon,
    set_options,
    set_use_os_log,
)
from .fonts.render import dump_font_debug, set_font_family
from .options.types import Options
from .options.utils import DELETE_ENV_VAR
from .os_window_size import edge_spacing, initial_window_size_func
from .session import create_sessions, get_os_window_sizing_data
from .shaders import CompileError, load_shader_programs
from .types import LayerShellConfig
from .utils import (
    cleanup_ssh_control_masters,
    expandvars,
    get_custom_window_icon,
    log_error,
    parse_os_window_state,
    safe_mtime,
    startup_notification_handler,
)


def set_custom_ibeam_cursor() -> None:
    with open(beam_cursor_data_file, 'rb') as f:
        data = f.read()
    rgba_data, width, height = load_png_data(data)
    c2x = os.path.splitext(beam_cursor_data_file)
    with open(f'{c2x[0]}@2x{c2x[1]}', 'rb') as f:
        data = f.read()
    rgba_data2, width2, height2 = load_png_data(data)
    images = (rgba_data, width, height), (rgba_data2, width2, height2)
    try:
        set_custom_cursor("beam", images, 4, 8)
    except Exception as e:
        log_error(f'Failed to set custom beam cursor with error: {e}')


def load_all_shaders(semi_transparent: bool = False) -> None:
    try:
        load_shader_programs(semi_transparent)
        load_borders_program()
    except CompileError as err:
        raise SystemExit(err)


def init_glfw_module(glfw_module: str = 'wayland', debug_keyboard: bool = False, debug_rendering: bool = False, wayland_enable_ime: bool = True) -> None:
    ok, swo = glfw_init(glfw_path(glfw_module), edge_spacing, debug_keyboard, debug_rendering, wayland_enable_ime)
    if not ok:
        raise SystemExit('GLFW initialization failed')
    supports_window_occlusion(swo)


def init_glfw(opts: Options, debug_keyboard: bool = False, debug_rendering: bool = False) -> str:
    glfw_module = 'cocoa' if is_macos else ('wayland' if is_wayland(opts) else 'x11')
    init_glfw_module(glfw_module, debug_keyboard, debug_rendering, wayland_enable_ime=opts.wayland_enable_ime)
    return glfw_module


def get_macos_shortcut_for(
    func_map: dict[tuple[str, ...], list[SingleKey]], defn: str = 'new_os_window', lookup_name: str = ''
) -> SingleKey | None:
    # for maximum robustness we should use opts.alias_map to resolve
    # aliases however this requires parsing everything on startup which could
    # be potentially slow. Lets just hope the user doesn't alias these
    # functions.
    ans = None
    candidates = []
    qkey = tuple(defn.split())
    candidates = func_map[qkey]
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
            if cocoa_set_global_shortcut(lookup_name or qkey[0], candidate[0], candidate[2]):
                ans = candidate
                break
    return ans


def set_macos_app_custom_icon() -> None:
    custom_icon_mtime, custom_icon_path = get_custom_window_icon()
    if custom_icon_mtime is not None and custom_icon_path is not None:
        from .fast_data_types import cocoa_set_app_icon, cocoa_set_dock_icon
        krd = getattr(sys, 'kitty_run_data')
        bundle_path = os.path.dirname(os.path.dirname(krd.get('bundle_exe_dir')))
        icon_sentinel = os.path.join(bundle_path, 'Icon\r')
        sentinel_mtime = safe_mtime(icon_sentinel)
        if sentinel_mtime is None or sentinel_mtime < custom_icon_mtime:
            try:
                cocoa_set_app_icon(custom_icon_path, bundle_path)
            except (FileNotFoundError, OSError) as e:
                log_error(str(e))
                log_error('Failed to set custom app icon, ignoring')
        # macOS Dock does not reload icons until it is restarted, so we set
        # the application icon here. This will revert when kitty quits, but
        # can't be helped since there appears to be no way to get the dock
        # to reload short of killing it.
        cocoa_set_dock_icon(custom_icon_path)


def get_icon128_path(base_path: str) -> str:
    # max icon size on X11 64bits is 128x128
    path, ext = os.path.splitext(base_path)
    return f'{path}-128{ext}'


def set_window_icon() -> None:
    custom_icon_path = get_custom_window_icon()[1]
    is_x11 = not is_macos and not is_wayland()
    try:
        if custom_icon_path is not None:
            custom_icon128_path = get_icon128_path(custom_icon_path)
            if is_x11 and safe_mtime(custom_icon128_path) is not None:
                set_default_window_icon(custom_icon128_path)
            else:
                set_default_window_icon(custom_icon_path)
        else:
            if is_x11:
                set_default_window_icon(get_icon128_path(logo_png_file))
    except ValueError as err:
        log_error(err)


def set_cocoa_global_shortcuts(opts: Options) -> dict[str, SingleKey]:
    global_shortcuts: dict[str, SingleKey] = {}
    if is_macos:
        from collections import defaultdict
        func_map = defaultdict(list)
        for single_key, v in opts.keyboard_modes[''].keymap.items():
            kd = v[-1]  # the last definition is the active one
            if kd.is_suitable_for_global_shortcut:
                parts = tuple(kd.definition.split())
                func_map[parts].append(single_key)

        for ac in ('new_os_window', 'close_os_window', 'close_tab', 'edit_config_file', 'previous_tab',
                   'next_tab', 'new_tab', 'new_window', 'close_window', 'toggle_macos_secure_keyboard_entry', 'toggle_fullscreen',
                   'hide_macos_app', 'hide_macos_other_apps', 'minimize_macos_window', 'quit'):
            val = get_macos_shortcut_for(func_map, ac)
            if val is not None:
                global_shortcuts[ac] = val
        val = get_macos_shortcut_for(func_map, 'clear_terminal reset active', lookup_name='reset_terminal')
        if val is not None:
            global_shortcuts['reset_terminal'] = val
        val = get_macos_shortcut_for(func_map, 'clear_terminal to_cursor active', lookup_name='clear_terminal_and_scrollback')
        if val is not None:
            global_shortcuts['clear_terminal_and_scrollback'] = val
        val = get_macos_shortcut_for(func_map, 'clear_terminal scrollback active', lookup_name='clear_scrollback')
        if val is not None:
            global_shortcuts['clear_scrollback'] = val
        val = get_macos_shortcut_for(func_map, 'clear_terminal to_cursor_scroll active', lookup_name='clear_screen')
        if val is not None:
            global_shortcuts['clear_screen'] = val
        val = get_macos_shortcut_for(func_map, 'load_config_file', lookup_name='reload_config')
        if val is not None:
            global_shortcuts['reload_config'] = val
        val = get_macos_shortcut_for(func_map, f'open_url {website_url()}', lookup_name='open_kitty_website')
        if val is not None:
            global_shortcuts['open_kitty_website'] = val
    return global_shortcuts


_is_panel_kitten = False


def is_panel_kitten() -> bool:
    return _is_panel_kitten


def list_monitors(json_output: bool = False) -> None:
    monitor_names = glfw_get_monitor_names()
    has_descriptions = False
    for (name, desc) in monitor_names:
        if desc:
            has_descriptions = True
            break

    if json_output:
        if has_descriptions:
            monitors_list_of_dict = [{'name': name, 'description': desc} for name, desc in monitor_names]
        else:
            monitors_list_of_dict = [{'name': name} for name, _ in monitor_names]
        json.dump(monitors_list_of_dict, sys.stdout, indent=2, sort_keys=True)
        print()
        return

    isatty = sys.stdout.isatty()
    for (name, desc) in monitor_names:
        if isatty:
            name = f'\x1b[32m{name}\x1b[39m'  # ]]
        print(name)
        if desc:
            print(f'\t{desc}')
        if has_descriptions:
            print()


def _run_app(opts: Options, args: CLIOptions, bad_lines: Sequence[BadLine] = (), talk_fd: int = -1) -> None:
    global _is_panel_kitten
    _is_panel_kitten = run_app.cached_values_name == 'panel'
    if _is_panel_kitten and run_app.layer_shell_config and run_app.layer_shell_config.output_name in ('list', 'listjson'):
        list_monitors(run_app.layer_shell_config.output_name == 'listjson')
        return
    if is_macos:
        global_shortcuts = set_cocoa_global_shortcuts(opts)
        if opts.macos_custom_beam_cursor:
            set_custom_ibeam_cursor()
        set_macos_app_custom_icon()
    else:
        global_shortcuts = {}
        set_window_icon()
    if _is_panel_kitten and not is_layer_shell_supported():
        raise SystemExit('Cannot create panels as the window manager/compositor does not support the necessary protocols')
    pos_x, pos_y = None, None
    if args.grab_keyboard:
        grab_keyboard(True)
    with cached_values_for(run_app.cached_values_name) as cached_values:
        if not _is_panel_kitten and not is_wayland():
            if opts.remember_window_position:
                cached_workarea = tuple(tuple(x) for x in cached_values.get('monitor-workarea', ()))
                if cached_workarea and glfw_get_monitor_workarea() == tuple(cached_workarea):
                    pos_x, pos_y = cached_values.get('window-pos', (None, None))
            if args.position:
                pos_x, pos_y = map(int, args.position.lower().partition('x')[::2])
        startup_sessions = tuple(create_sessions(opts, args, default_session=opts.startup_session))
        wincls = (startup_sessions[0].os_window_class if startup_sessions else '') or args.cls or appname
        winname = (startup_sessions[0].os_window_name if startup_sessions else '') or args.name or wincls or appname
        window_state = (args.start_as if args.start_as and args.start_as != 'normal' else None) or (
            getattr(startup_sessions[0], 'os_window_state', None) if startup_sessions else None
        )
        wstate = parse_os_window_state(window_state) if window_state is not None else None

        with startup_notification_handler(extra_callback=run_app.first_window_callback) as pre_show_callback:
            window_id = create_os_window(
                    run_app.initial_window_size_func(get_os_window_sizing_data(opts, startup_sessions[0] if startup_sessions else None), cached_values),
                    pre_show_callback,
                    args.title or appname, winname,
                    wincls, wstate, load_all_shaders, disallow_override_title=bool(args.title), layer_shell_config=run_app.layer_shell_config, x=pos_x, y=pos_y)
        boss = Boss(opts, args, cached_values, global_shortcuts, talk_fd)
        boss.start(window_id, startup_sessions)
        if args.debug_font_fallback:
            dump_font_debug()
        if bad_lines or boss.misc_config_errors:
            boss.show_bad_config_lines(bad_lines, boss.misc_config_errors)
            boss.misc_config_errors = []
        try:
            boss.child_monitor.main_loop()
        finally:
            boss.destroy()


class AppRunner:

    def __init__(self) -> None:
        self.cached_values_name = 'main'
        self.first_window_callback = lambda window_handle: None
        self.layer_shell_config: LayerShellConfig | None = None
        self.initial_window_size_func = initial_window_size_func

    def __call__(self, opts: Options, args: CLIOptions, bad_lines: Sequence[BadLine] = (), talk_fd: int = -1) -> None:
        if theme_colors.refresh():
            theme_colors.patch_opts(opts, args.debug_rendering)
        set_options(opts, is_wayland(), args.debug_rendering, args.debug_font_fallback)
        try:
            set_font_family(opts, add_builtin_nerd_font=True)
            _run_app(opts, args, bad_lines, talk_fd)
        finally:
            set_options(None)
            free_font_data()  # must free font data before glfw/freetype/fontconfig/opengl etc are finalized
            if is_macos:
                from kitty.fast_data_types import (
                    cocoa_set_notification_activated_callback,
                )
                cocoa_set_notification_activated_callback(None)


run_app = AppRunner()


def ensure_macos_locale() -> None:
    # Ensure the LANG env var is set. See
    # https://github.com/kovidgoyal/kitty/issues/90
    from .fast_data_types import cocoa_get_lang, locale_is_valid
    if 'LANG' not in os.environ:
        lang_code, country_code, identifier = cocoa_get_lang()
        lang = 'en_US'
        if identifier and locale_is_valid(identifier):
            lang = identifier
        elif lang_code and country_code and locale_is_valid(f'{lang_code}_{country_code}'):
            lang = f'{lang_code}_{country_code}'
        elif lang_code:
            if lang_code != 'en':
                with suppress(OSError):
                    found = sorted(x for x in os.listdir('/usr/share/locale') if x.startswith(f'{lang_code}_'))
                    if found:
                        lang = found[0].partition('.')[0]
        os.environ['LANG'] = f'{lang}.UTF-8'
        set_LANG_in_default_env(os.environ['LANG'])


@contextmanager
def setup_profiling() -> Generator[None, None, None]:
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
            subprocess.Popen(['kcachegrind', cg], preexec_fn=clear_handled_signals)
        except FileNotFoundError:
            subprocess.call(['pprof', '--text', exe, '/tmp/kitty-profile.log'])
            print('To view the graphical call data, use: kcachegrind', cg)


def expand_listen_on(listen_on: str, from_config_file: bool) -> str:
    if from_config_file and listen_on == 'none':
        return ''
    listen_on = expandvars(listen_on)
    if '{kitty_pid}' not in listen_on and from_config_file and listen_on.startswith('unix:'):
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
    elif listen_on.startswith('tcp:') or listen_on.startswith('tcp6:'):
        if from_config_file:  # use a random port
            listen_on = ':'.join(listen_on.split(':', 2)[:2]) + ':0'
    return listen_on


def safe_samefile(a: str, b: str) -> bool:
    with suppress(OSError):
        return os.path.samefile(a, b)
    return os.path.abspath(os.path.realpath(a)) == os.path.abspath(os.path.realpath(b))


def prepend_if_not_present(path: str, paths_serialized: str) -> str:
    # prepend a path only if path/kitty is not already present, even as a symlink
    pq = os.path.join(path, 'kitty')
    for candidate in paths_serialized.split(os.pathsep):
        q = os.path.join(candidate, 'kitty')
        if safe_samefile(q, pq):
            return paths_serialized
    return path + os.pathsep + paths_serialized


def ensure_kitty_in_path() -> None:
    # Ensure the correct kitty is in PATH
    krd = getattr(sys, 'kitty_run_data')
    rpath = krd.get('bundle_exe_dir')
    if not rpath:
        return
    if rpath:
        modify_path = is_macos or getattr(sys, 'frozen', False) or krd.get('from_source')
        existing = shutil.which('kitty')
        if modify_path or not existing:
            env_path = os.environ.get('PATH', '')
            correct_kitty = os.path.join(rpath, 'kitty')
            if not existing or not safe_samefile(existing, correct_kitty):
                os.environ['PATH'] = prepend_if_not_present(rpath, env_path)


def ensure_kitten_in_path() -> None:
    correct_kitten = kitten_exe()
    existing = shutil.which('kitten')
    if existing and safe_samefile(existing, correct_kitten):
        return
    env_path = os.environ.get('PATH', '')
    os.environ['PATH'] = prepend_if_not_present(os.path.dirname(correct_kitten), env_path)


def setup_manpath(env: dict[str, str]) -> None:
    # Ensure kitty manpages are available in frozen builds
    if not getattr(sys, 'frozen', False):
        return
    from .constants import local_docs
    mp = os.environ.get('MANPATH', env.get('MANPATH', ''))
    d = os.path.dirname
    kitty_man = os.path.join(d(d(d(local_docs()))), 'man')
    if not mp:
        env['MANPATH'] = f'{kitty_man}:'
    elif mp.startswith(':'):
        env['MANPATH'] = f':{kitty_man}:{mp}'
    else:
        env['MANPATH'] = f'{kitty_man}:{mp}'


def setup_environment(opts: Options, cli_opts: CLIOptions) -> None:
    from_config_file = False
    if not cli_opts.listen_on:
        cli_opts.listen_on = opts.listen_on
        from_config_file = True
    if cli_opts.listen_on:
        cli_opts.listen_on = expand_listen_on(cli_opts.listen_on, from_config_file)
    env = opts.env.copy()
    ensure_kitty_in_path()
    ensure_kitten_in_path()
    kitty_path = shutil.which('kitty')
    if kitty_path:
        child_path = env.get('PATH')
        # if child_path is None it will be inherited from os.environ,
        # the other values mean the user doesn't want a PATH
        if child_path not in ('', DELETE_ENV_VAR) and child_path is not None:
            env['PATH'] = prepend_if_not_present(os.path.dirname(kitty_path), env['PATH'])
    setup_manpath(env)
    set_default_env(env)


def set_locale() -> None:
    if is_macos:
        ensure_macos_locale()
    try:
        locale.setlocale(locale.LC_ALL, '')
    except Exception:
        log_error('Failed to set locale with LANG:', os.environ.get('LANG'))
        old_lang = os.environ.pop('LANG', None)
        if old_lang is not None:
            try:
                locale.setlocale(locale.LC_ALL, '')
            except Exception:
                log_error('Failed to set locale with no LANG')
            os.environ['LANG'] = old_lang
            set_LANG_in_default_env(old_lang)


def kitty_main(called_from_panel: bool = False) -> None:
    running_in_kitty(True)

    args = sys.argv[1:]
    try:
        cwd_ok = os.path.isdir(os.getcwd())
    except Exception:
        cwd_ok = False
    if not cwd_ok:
        os.chdir(os.path.expanduser('~'))
    cli_flags = None
    if getattr(sys, 'cmdline_args_for_open', False):
        usage: str | None = 'file_or_url ...'
        appname: str | None = 'kitty +open'
        msg: str | None = (
            'Run kitty and open the specified files or URLs in it, using launch-actions.conf. For details'
            ' see https://sw.kovidgoyal.net/kitty/open_actions/#scripting-the-opening-of-files-with-kitty-on-macos'
            '\n\nAll the normal kitty options can be used.')
    else:
        if not called_from_panel:
            cli_flags = getattr(sys, 'kitty_run_data', {}).get('cli_flags', None)
        usage = msg = appname = None
    cli_opts, rest = parse_args(args=args, result_class=CLIOptions, usage=usage, message=msg, appname=appname, preparsed_from_c=cli_flags)
    if getattr(sys, 'cmdline_args_for_open', False):
        setattr(sys, 'cmdline_args_for_open', rest)
        cli_opts.args = []
    else:
        cli_opts.args = rest
    talk_fd = -1
    if cli_opts.single_instance:
        si_data = os.environ.pop('KITTY_SI_DATA', '')
        if si_data:
            talk_fd = int(si_data)

    if cli_opts.detach:
        if cli_opts.session == '-':
            from .session import PreReadSession
            cli_opts.session = PreReadSession(sys.stdin.read(), os.environ)
    if cli_opts.replay_commands:
        from kitty.client import main as client_main
        client_main(cli_opts.replay_commands)
        return
    bad_lines: list[BadLine] = []
    opts = create_opts(cli_opts, accumulate_bad_lines=bad_lines)
    if is_quick_access_terminal_app:
        opts.macos_hide_from_tasks = True
    setup_environment(opts, cli_opts)

    # set_locale on macOS uses cocoa APIs when LANG is not set, so we have to
    # call it after the fork
    try:
        set_locale()
    except Exception:
        log_error('Failed to set locale, ignoring')
    with suppress(AttributeError):  # python compiled without threading
        sys.setswitchinterval(1000.0)  # we have only a single python thread

    if cli_opts.watcher:
        from .window import global_watchers
        global_watchers.set_extra(cli_opts.watcher)
        log_error('The --watcher command line option has been deprecated in favor of using the watcher option in kitty.conf')
    # mask the signals now as on some platforms the display backend starts
    # threads. These threads must not handle the masked signals, to ensure
    # kitty can handle them. See https://github.com/kovidgoyal/kitty/issues/4636
    mask_kitty_signals_process_wide()
    init_glfw(opts, cli_opts.debug_keyboard, cli_opts.debug_rendering)
    try:
        with setup_profiling():
            # Avoid needing to launch threads to reap zombies
            run_app(opts, cli_opts, bad_lines, talk_fd)
    finally:
        glfw_terminate()
        cleanup_ssh_control_masters()



def main(called_from_panel: bool = False) -> None:
    global redirected_for_quick_access
    try:
        if is_macos and launched_by_launch_services and not called_from_panel:
            with suppress(OSError):
                os.chdir(os.path.expanduser('~'))
            if is_quick_access_terminal_app:
                # we were started by launch services, use the kitten to read
                # the config and re-run
                os.execl(kitten_exe(), kitten_exe(), 'quick-access-terminal')
            set_use_os_log(True)
        kitty_main(called_from_panel)
    except Exception:
        import traceback
        tb = traceback.format_exc()
        log_error(tb)
        raise SystemExit(1)
    finally:
        # we cant rely on this running during module unloading of fast_data_types as Python fails
        # to unload the module, due to reference cycles, I am guessing.
        run_at_exit_cleanup_functions()
