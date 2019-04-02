#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2016, Kovid Goyal <kovid at kovidgoyal.net>

import atexit
import json
import os
import re
from functools import partial
from gettext import gettext as _
from weakref import WeakValueDictionary

from .child import cached_process_data
from .cli import create_opts, parse_args
from .conf.utils import to_cmdline
from .config import initial_window_size_func, prepare_config_file_for_editing
from .config_data import MINIMUM_FONT_SIZE
from .constants import (
    appname, config_dir, is_macos, kitty_exe, set_boss,
    supports_primary_selection
)
from .fast_data_types import (
    ChildMonitor, background_opacity_of, change_background_opacity,
    change_os_window_state, create_os_window, current_os_window,
    destroy_global_data, get_clipboard_string, global_font_size,
    mark_os_window_for_close, os_window_font_size, patch_global_colors,
    set_clipboard_string, set_in_sequence_mode, toggle_fullscreen
)
from .keys import get_shortcut, shortcut_matches
from .layout import set_draw_borders_options
from .remote_control import handle_cmd
from .rgb import Color, color_from_int
from .session import create_sessions
from .tabs import SpecialWindow, SpecialWindowInstance, TabManager
from .utils import (
    func_name, get_editor, get_primary_selection, is_path_in_temp_dir,
    log_error, open_url, parse_address_spec, remove_socket_file, safe_print,
    set_primary_selection, single_instance, startup_notification_handler
)


def listen_on(spec):
    import socket
    family, address, socket_path = parse_address_spec(spec)
    s = socket.socket(family)
    atexit.register(remove_socket_file, s, socket_path)
    s.bind(address)
    s.listen()
    return s.fileno()


def data_for_at(w, arg, add_wrap_markers=False):
    def as_text(**kw):
        kw['add_wrap_markers'] = add_wrap_markers
        return w.as_text(**kw)

    if arg == '@selection':
        return w.text_for_selection()
    if arg == '@ansi':
        return as_text(as_ansi=True, add_history=True)
    if arg == '@text':
        return as_text(add_history=True)
    if arg == '@screen':
        return as_text()
    if arg == '@ansi_screen':
        return as_text(as_ansi=True)
    if arg == '@alternate':
        return as_text(alternate_screen=True)
    if arg == '@alternate_scrollback':
        return as_text(alternate_screen=True, add_history=True)
    if arg == '@ansi_alternate':
        return as_text(as_ansi=True, alternate_screen=True)
    if arg == '@ansi_alternate_scrollback':
        return as_text(as_ansi=True, alternate_screen=True, add_history=True)


class DumpCommands:  # {{{

    def __init__(self, args):
        self.draw_dump_buf = []
        if args.dump_bytes:
            self.dump_bytes_to = open(args.dump_bytes, 'wb')

    def __call__(self, *a):
        if a:
            if a[0] == 'draw':
                if a[1] is None:
                    if self.draw_dump_buf:
                        safe_print('draw', ''.join(self.draw_dump_buf))
                        self.draw_dump_buf = []
                else:
                    self.draw_dump_buf.append(a[1])
            elif a[0] == 'bytes':
                self.dump_bytes_to.write(a[1])
                self.dump_bytes_to.flush()
            else:
                if self.draw_dump_buf:
                    safe_print('draw', ''.join(self.draw_dump_buf))
                    self.draw_dump_buf = []
                safe_print(*a)
# }}}


class Boss:

    def __init__(self, os_window_id, opts, args, cached_values, new_os_window_trigger):
        set_draw_borders_options(opts)
        self.clipboard_buffers = {}
        self.update_check_process = None
        self.window_id_map = WeakValueDictionary()
        self.startup_colors = {k: opts[k] for k in opts if isinstance(opts[k], Color)}
        self.startup_cursor_text_color = opts.cursor_text_color
        self.pending_sequences = None
        self.cached_values = cached_values
        self.os_window_map = {}
        self.os_window_death_actions = {}
        self.cursor_blinking = True
        self.shutting_down = False
        talk_fd = getattr(single_instance, 'socket', None)
        talk_fd = -1 if talk_fd is None else talk_fd.fileno()
        listen_fd = -1
        if opts.allow_remote_control and args.listen_on:
            listen_fd = listen_on(args.listen_on)
        self.child_monitor = ChildMonitor(
            self.on_child_death,
            DumpCommands(args) if args.dump_commands or args.dump_bytes else None,
            talk_fd, listen_fd
        )
        set_boss(self)
        self.opts, self.args = opts, args
        startup_sessions = create_sessions(opts, args, default_session=opts.startup_session)
        self.keymap = self.opts.keymap.copy()
        if new_os_window_trigger is not None:
            self.keymap.pop(new_os_window_trigger, None)
        for startup_session in startup_sessions:
            os_window_id = self.add_os_window(startup_session, os_window_id=os_window_id)
            if args.start_as != 'normal':
                if args.start_as == 'fullscreen':
                    self.toggle_fullscreen()
                else:
                    change_os_window_state(args.start_as)
            os_window_id = None
        if is_macos:
            from .fast_data_types import cocoa_set_notification_activated_callback
            cocoa_set_notification_activated_callback(self.notification_activated)

    def add_os_window(self, startup_session, os_window_id=None, wclass=None, wname=None, opts_for_size=None, startup_id=None):
        if os_window_id is None:
            opts_for_size = opts_for_size or startup_session.os_window_size or self.opts
            cls = wclass or self.args.cls or appname
            with startup_notification_handler(do_notify=startup_id is not None, startup_id=startup_id) as pre_show_callback:
                os_window_id = create_os_window(
                        initial_window_size_func(opts_for_size, self.cached_values),
                        pre_show_callback,
                        appname, wname or self.args.name or cls, cls)
        tm = TabManager(os_window_id, self.opts, self.args, startup_session)
        self.os_window_map[os_window_id] = tm
        return os_window_id

    def list_os_windows(self):
        with cached_process_data():
            active_tab, active_window = self.active_tab, self.active_window
            active_tab_manager = self.active_tab_manager
            for os_window_id, tm in self.os_window_map.items():
                yield {
                    'id': os_window_id,
                    'is_focused': tm is active_tab_manager,
                    'tabs': list(tm.list_tabs(active_tab, active_window)),
                }

    @property
    def all_tab_managers(self):
        yield from self.os_window_map.values()

    @property
    def all_tabs(self):
        for tm in self.all_tab_managers:
            yield from tm

    @property
    def all_windows(self):
        for tab in self.all_tabs:
            yield from tab

    def match_windows(self, match):
        try:
            field, exp = match.split(':', 1)
        except ValueError:
            return
        if field == 'num':
            tab = self.active_tab
            if tab is not None:
                try:
                    w = tab.get_nth_window(int(exp))
                except Exception:
                    return
                if w is not None:
                    yield w
            return
        if field == 'env':
            kp, vp = exp.partition('=')[::2]
            if vp:
                pat = tuple(map(re.compile, (kp, vp)))
            else:
                pat = re.compile(kp), None
        else:
            pat = re.compile(exp)
        for window in self.all_windows:
            if window.matches(field, pat):
                yield window

    def tab_for_window(self, window):
        for tab in self.all_tabs:
            for w in tab:
                if w.id == window.id:
                    return tab

    def match_tabs(self, match):
        try:
            field, exp = match.split(':', 1)
        except ValueError:
            return
        pat = re.compile(exp)
        found = False
        if field in ('title', 'id'):
            for tab in self.all_tabs:
                if tab.matches(field, pat):
                    yield tab
                    found = True
        if not found:
            tabs = {self.tab_for_window(w) for w in self.match_windows(match)}
            for tab in tabs:
                if tab:
                    yield tab

    def set_active_window(self, window):
        for os_window_id, tm in self.os_window_map.items():
            for tab in tm:
                for w in tab:
                    if w.id == window.id:
                        if tab is not self.active_tab:
                            tm.set_active_tab(tab)
                        tab.set_active_window(w)
                        return os_window_id

    def _new_os_window(self, args, cwd_from=None):
        if isinstance(args, SpecialWindowInstance):
            sw = args
        else:
            sw = self.args_to_special_window(args, cwd_from) if args else None
        startup_session = next(create_sessions(self.opts, special_window=sw, cwd_from=cwd_from))
        return self.add_os_window(startup_session)

    def new_os_window(self, *args):
        self._new_os_window(args)

    @property
    def active_window_for_cwd(self):
        w = self.active_window
        if w is not None and w.overlay_for is not None and w.overlay_for in self.window_id_map:
            w = self.window_id_map[w.overlay_for]
        return w

    def new_os_window_with_cwd(self, *args):
        w = self.active_window_for_cwd
        cwd_from = w.child.pid_for_cwd if w is not None else None
        self._new_os_window(args, cwd_from)

    def new_os_window_with_wd(self, wd):
        special_window = SpecialWindow(None, cwd=wd)
        self._new_os_window(special_window)

    def add_child(self, window):
        self.child_monitor.add_child(window.id, window.child.pid, window.child.child_fd, window.screen)
        self.window_id_map[window.id] = window

    def _handle_remote_command(self, cmd, window=None):
        response = None
        if self.opts.allow_remote_control or getattr(window, 'allow_remote_control', False):
            try:
                response = handle_cmd(self, window, cmd)
            except Exception as err:
                import traceback
                response = {'ok': False, 'error': str(err)}
                if not getattr(err, 'hide_traceback', False):
                    response['tb'] = traceback.format_exc()
        else:
            response = {'ok': False, 'error': 'Remote control is disabled. Add allow_remote_control yes to your kitty.conf'}
        return response

    def peer_message_received(self, msg):
        msg = msg.decode('utf-8')
        cmd_prefix = '\x1bP@kitty-cmd'
        if msg.startswith(cmd_prefix):
            cmd = msg[len(cmd_prefix):-2]
            response = self._handle_remote_command(cmd)
            if response is not None:
                response = (cmd_prefix + json.dumps(response) + '\x1b\\').encode('utf-8')
            return response
        else:
            msg = json.loads(msg)
            if isinstance(msg, dict) and msg.get('cmd') == 'new_instance':
                startup_id = msg.get('startup_id')
                args, rest = parse_args(msg['args'][1:])
                args.args = rest
                opts = create_opts(args)
                if not os.path.isabs(args.directory):
                    args.directory = os.path.join(msg['cwd'], args.directory)
                for session in create_sessions(opts, args, respect_cwd=True):
                    os_window_id = self.add_os_window(session, wclass=args.cls, wname=args.name, opts_for_size=opts, startup_id=startup_id)
                    if msg.get('notify_on_os_window_death'):
                        self.os_window_death_actions[os_window_id] = partial(self.notify_on_os_window_death, msg['notify_on_os_window_death'])
            else:
                log_error('Unknown message received from peer, ignoring')

    def handle_remote_cmd(self, cmd, window=None):
        response = self._handle_remote_command(cmd, window)
        if response is not None:
            if window is not None:
                window.send_cmd_response(response)

    def on_child_death(self, window_id):
        window = self.window_id_map.pop(window_id, None)
        if window is None:
            return
        if window.action_on_close:
            try:
                window.action_on_close(window)
            except Exception:
                import traceback
                traceback.print_exc()
        os_window_id = window.os_window_id
        window.destroy()
        tm = self.os_window_map.get(os_window_id)
        if tm is None:
            return
        for tab in tm:
            if window in tab:
                break
        else:
            return
        tab.remove_window(window)
        if len(tab) == 0:
            tm.remove(tab)
            tab.destroy()
            if len(tm) == 0:
                if not self.shutting_down:
                    mark_os_window_for_close(os_window_id)

    def close_window(self, window=None):
        if window is None:
            window = self.active_window
        self.child_monitor.mark_for_close(window.id)

    def close_tab(self, tab=None):
        if tab is None:
            tab = self.active_tab
        for window in tab:
            self.close_window(window)

    def toggle_fullscreen(self):
        toggle_fullscreen()

    def start(self):
        if not getattr(self, 'io_thread_started', False):
            self.child_monitor.start()
            self.io_thread_started = True
        if self.opts.update_check_interval > 0 and not hasattr(self, 'update_check_started'):
            from .update_check import run_update_check
            run_update_check(self.opts.update_check_interval * 60 * 60)
            self.update_check_started = True

    def activate_tab_at(self, os_window_id, x):
        tm = self.os_window_map.get(os_window_id)
        if tm is not None:
            tm.activate_tab_at(x)

    def on_window_resize(self, os_window_id, w, h, dpi_changed):
        if dpi_changed:
            self.on_dpi_change(os_window_id)
        else:
            tm = self.os_window_map.get(os_window_id)
            if tm is not None:
                tm.resize()

    def clear_terminal(self, action, only_active):
        if only_active:
            windows = []
            w = self.active_window
            if w is not None:
                windows.append(w)
        else:
            windows = self.all_windows
        reset = action == 'reset'
        how = 3 if action == 'scrollback' else 2
        for w in windows:
            if action == 'scroll':
                w.screen.scroll_until_cursor()
                continue
            w.screen.cursor.x = w.screen.cursor.y = 0
            if reset:
                w.screen.reset()
            else:
                w.screen.erase_in_display(how, False)

    def increase_font_size(self):  # legacy
        cfs = global_font_size()
        self.set_font_size(min(self.opts.font_size * 5, cfs + 2.0))

    def decrease_font_size(self):  # legacy
        cfs = global_font_size()
        self.set_font_size(max(MINIMUM_FONT_SIZE, cfs - 2.0))

    def restore_font_size(self):  # legacy
        self.set_font_size(self.opts.font_size)

    def set_font_size(self, new_size):  # legacy
        self.change_font_size(True, None, new_size)

    def change_font_size(self, all_windows, increment_operation, amt):
        def calc_new_size(old_size):
            new_size = old_size
            if amt == 0:
                new_size = self.opts.font_size
            else:
                if increment_operation:
                    new_size += (1 if increment_operation == '+' else -1) * amt
                else:
                    new_size = amt
                new_size = max(MINIMUM_FONT_SIZE, min(new_size, self.opts.font_size * 5))
            return new_size

        if all_windows:
            current_global_size = global_font_size()
            new_size = calc_new_size(current_global_size)
            if new_size != current_global_size:
                global_font_size(new_size)
            os_windows = tuple(self.os_window_map.keys())
        else:
            os_windows = []
            w = self.active_window
            if w is not None:
                os_windows.append(w.os_window_id)
        if os_windows:
            final_windows = {}
            for wid in os_windows:
                current_size = os_window_font_size(wid)
                if current_size:
                    new_size = calc_new_size(current_size)
                    if new_size != current_size:
                        final_windows[wid] = new_size
            if final_windows:
                self._change_font_size(final_windows)

    def _change_font_size(self, sz_map):
        for os_window_id, sz in sz_map.items():
            tm = self.os_window_map.get(os_window_id)
            if tm is not None:
                os_window_font_size(os_window_id, sz)
                tm.resize()

    def on_dpi_change(self, os_window_id):
        tm = self.os_window_map.get(os_window_id)
        if tm is not None:
            sz = os_window_font_size(os_window_id)
            if sz:
                os_window_font_size(os_window_id, sz, True)
                tm.resize()

    def _set_os_window_background_opacity(self, os_window_id, opacity):
        change_background_opacity(os_window_id, max(0.1, min(opacity, 1.0)))

    def set_background_opacity(self, opacity):
        window = self.active_window
        if window is None or not opacity:
            return
        if not self.opts.dynamic_background_opacity:
            return self.show_error(
                    _('Cannot change background opacity'),
                    _('You must set the dynamic_background_opacity option in kitty.conf to be able to change background opacity'))
        os_window_id = window.os_window_id
        if opacity[0] in '+-':
            old_opacity = background_opacity_of(os_window_id)
            if old_opacity is None:
                return
            opacity = old_opacity + float(opacity)
        elif opacity == 'default':
            opacity = self.opts.background_opacity
        else:
            opacity = float(opacity)
        self._set_os_window_background_opacity(os_window_id, opacity)

    @property
    def active_tab_manager(self):
        os_window_id = current_os_window()
        return self.os_window_map.get(os_window_id)

    @property
    def active_tab(self):
        tm = self.active_tab_manager
        if tm is not None:
            return tm.active_tab

    @property
    def active_window(self):
        t = self.active_tab
        if t is not None:
            return t.active_window

    def dispatch_special_key(self, key, scancode, action, mods):
        # Handles shortcuts, return True if the key was consumed
        key_action = get_shortcut(self.keymap, mods, key, scancode)
        if key_action is None:
            sequences = get_shortcut(self.opts.sequence_map, mods, key, scancode)
            if sequences:
                self.pending_sequences = sequences
                set_in_sequence_mode(True)
                return True
        else:
            self.current_key_press_info = key, scancode, action, mods
            return self.dispatch_action(key_action)

    def process_sequence(self, key, scancode, action, mods):
        if not self.pending_sequences:
            set_in_sequence_mode(False)

        remaining = {}
        matched_action = None
        for seq, key_action in self.pending_sequences.items():
            if shortcut_matches(seq[0], mods, key, scancode):
                seq = seq[1:]
                if seq:
                    remaining[seq] = key_action
                else:
                    matched_action = key_action

        if remaining:
            self.pending_sequences = remaining
        else:
            self.pending_sequences = None
            set_in_sequence_mode(False)
            if matched_action is not None:
                self.dispatch_action(matched_action)

    def start_resizing_window(self):
        w = self.active_window
        if w is None:
            return
        overlay_window = self._run_kitten('resize_window', args=[
            '--horizontal-increment={}'.format(self.opts.window_resize_step_cells),
            '--vertical-increment={}'.format(self.opts.window_resize_step_lines)
        ])
        if overlay_window is not None:
            overlay_window.allow_remote_control = True

    def resize_layout_window(self, window, increment, is_horizontal, reset=False):
        tab = window.tabref()
        if tab is None or not increment:
            return False
        if reset:
            return tab.reset_window_sizes()
        return tab.resize_window_by(window.id, increment, is_horizontal)

    def default_bg_changed_for(self, window_id):
        w = self.window_id_map.get(window_id)
        if w is not None:
            tm = self.os_window_map.get(w.os_window_id)
            if tm is not None:
                tm.update_tab_bar_data()
                tm.mark_tab_bar_dirty()
                t = tm.tab_for_id(w.tab_id)
                if t is not None:
                    t.relayout_borders()

    def dispatch_action(self, key_action):
        if key_action is not None:
            f = getattr(self, key_action.func, None)
            if f is not None:
                if self.args.debug_keyboard:
                    print('Keypress matched action:', func_name(f))
                passthrough = f(*key_action.args)
                if passthrough is not True:
                    return True
        tab = self.active_tab
        if tab is None:
            return False
        window = self.active_window
        if window is None:
            return False
        if key_action is not None:
            f = getattr(tab, key_action.func, getattr(window, key_action.func, None))
            if f is not None:
                passthrough = f(*key_action.args)
                if self.args.debug_keyboard:
                    print('Keypress matched action:', func_name(f))
                if passthrough is not True:
                    return True
        return False

    def combine(self, *actions):
        for key_action in actions:
            self.dispatch_action(key_action)

    def on_focus(self, os_window_id, focused):
        tm = self.os_window_map.get(os_window_id)
        if tm is not None:
            w = tm.active_window
            if w is not None:
                w.focus_changed(focused)
            tm.mark_tab_bar_dirty()

    def update_tab_bar_data(self, os_window_id):
        tm = self.os_window_map.get(os_window_id)
        if tm is not None:
            tm.update_tab_bar_data()

    def on_drop(self, os_window_id, paths):
        tm = self.os_window_map.get(os_window_id)
        if tm is not None:
            w = tm.active_window
            if w is not None:
                w.paste('\n'.join(paths))

    def on_os_window_closed(self, os_window_id, viewport_width, viewport_height):
        self.cached_values['window-size'] = viewport_width, viewport_height
        tm = self.os_window_map.pop(os_window_id, None)
        if tm is not None:
            tm.destroy()
        for window_id in tuple(w.id for w in self.window_id_map.values() if getattr(w, 'os_window_id', None) == os_window_id):
            self.window_id_map.pop(window_id, None)
        action = self.os_window_death_actions.pop(os_window_id, None)
        if action is not None:
            action()

    def notify_on_os_window_death(self, address):
        import socket
        s = socket.socket(family=socket.AF_UNIX)
        try:
            s.connect(address)
            s.sendall(b'c')
            try:
                s.shutdown(socket.SHUT_RDWR)
            except EnvironmentError:
                pass
            s.close()
        except Exception:
            pass

    def display_scrollback(self, window, data, cmd):
        tab = self.active_tab
        if tab is not None and window.overlay_for is None:
            tab.new_special_window(
                SpecialWindow(
                    cmd, data, _('History'), overlay_for=window.id))

    def edit_config_file(self, *a):
        confpath = prepare_config_file_for_editing()
        # On macOS vim fails to handle SIGWINCH if it occurs early, so add a
        # small delay.
        cmd = [kitty_exe(), '+runpy', 'import os, sys, time; time.sleep(0.05); os.execvp(sys.argv[1], sys.argv[1:])'] + get_editor() + [confpath]
        self.new_os_window(*cmd)

    def get_output(self, source_window, num_lines=1):
        output = ''
        s = source_window.screen
        if num_lines is None:
            num_lines = s.lines
        for i in range(min(num_lines, s.lines)):
            output += str(s.linebuf.line(i))
        return output

    def _run_kitten(self, kitten, args=(), input_data=None, window=None):
        orig_args, args = list(args), list(args)
        from kittens.runner import create_kitten_handler
        end_kitten = create_kitten_handler(kitten, orig_args)
        if window is None:
            w = self.active_window
            tab = self.active_tab
        else:
            w = window
            tab = w.tabref()
        if end_kitten.no_ui:
            end_kitten(None, getattr(w, 'id', None), self)
            return

        if w is not None and tab is not None and w.overlay_for is None:
            args[0:0] = [config_dir, kitten]
            if input_data is None:
                type_of_input = end_kitten.type_of_input
                if type_of_input in ('text', 'history', 'ansi', 'ansi-history', 'screen', 'screen-history', 'screen-ansi', 'screen-ansi-history'):
                    data = w.as_text(
                            as_ansi='ansi' in type_of_input,
                            add_history='history' in type_of_input,
                            add_wrap_markers='screen' in type_of_input
                    ).encode('utf-8')
                elif type_of_input is None:
                    data = None
                else:
                    raise ValueError('Unknown type_of_input: {}'.format(type_of_input))
            else:
                data = input_data
            if isinstance(data, str):
                data = data.encode('utf-8')
            copts = {k: self.opts[k] for k in ('select_by_word_characters', 'open_url_with')}
            overlay_window = tab.new_special_window(
                SpecialWindow(
                    [kitty_exe(), '+runpy', 'from kittens.runner import main; main()'] + args,
                    stdin=data,
                    env={
                        'KITTY_COMMON_OPTS': json.dumps(copts),
                        'KITTY_CHILD_PID': w.child.pid,
                        'PYTHONWARNINGS': 'ignore',
                        'OVERLAID_WINDOW_LINES': str(w.screen.lines),
                        'OVERLAID_WINDOW_COLS': str(w.screen.columns),
                    },
                    cwd=w.cwd_of_child,
                    overlay_for=w.id
                ))
            overlay_window.action_on_close = partial(self.on_kitten_finish, w.id, end_kitten)
            return overlay_window

    def kitten(self, kitten, *args):
        import shlex
        cmdline = args[0] if args else ''
        args = shlex.split(cmdline) if cmdline else []
        self._run_kitten(kitten, args)

    def on_kitten_finish(self, target_window_id, end_kitten, source_window):
        output = self.get_output(source_window, num_lines=None)
        from kittens.runner import deserialize
        data = deserialize(output)
        if data is not None:
            end_kitten(data, target_window_id, self)

    def input_unicode_character(self):
        self._run_kitten('unicode_input')

    def set_tab_title(self):
        tab = self.active_tab
        if tab:
            args = ['--name=tab-title', '--message', _('Enter the new title for this tab below.'), 'do_set_tab_title', str(tab.id)]
            self._run_kitten('ask', args)

    def show_error(self, title, msg):
        self._run_kitten('show_error', ['--title', title], input_data=msg)

    def do_set_tab_title(self, title, tab_id):
        tm = self.active_tab_manager
        if tm is not None and title:
            tab_id = int(tab_id)
            for tab in tm.tabs:
                if tab.id == tab_id:
                    tab.set_title(title)
                    break

    def kitty_shell(self, window_type):
        cmd = ['@', kitty_exe(), '@']
        if window_type == 'tab':
            self._new_tab(cmd).active_window
        elif window_type == 'os_window':
            os_window_id = self._new_os_window(cmd)
            self.os_window_map[os_window_id].active_window
        elif window_type == 'overlay':
            w = self.active_window
            tab = self.active_tab
            if w is not None and tab is not None and w.overlay_for is None:
                tab.new_special_window(SpecialWindow(cmd, overlay_for=w.id))
        else:
            self._new_window(cmd)

    def switch_focus_to(self, window_idx):
        tab = self.active_tab
        tab.set_active_window_idx(window_idx)

    def open_url(self, url, program=None, cwd=None):
        if url:
            if isinstance(program, str):
                program = to_cmdline(program)
            open_url(url, program or self.opts.open_url_with, cwd=cwd)

    def open_url_lines(self, lines, program=None):
        self.open_url(''.join(lines), program)

    def destroy(self):
        self.shutting_down = True
        self.child_monitor.shutdown_monitor()
        self.set_update_check_process()
        self.update_check_process = None
        del self.child_monitor
        for tm in self.os_window_map.values():
            tm.destroy()
        self.os_window_map = {}
        destroy_global_data()

    def paste_to_active_window(self, text):
        if text:
            w = self.active_window
            if w is not None:
                w.paste(text)

    def paste_from_clipboard(self):
        text = get_clipboard_string()
        self.paste_to_active_window(text)

    def paste_from_selection(self):
        text = get_primary_selection() if supports_primary_selection else get_clipboard_string()
        self.paste_to_active_window(text)

    def set_primary_selection(self):
        w = self.active_window
        if w is not None and not w.destroyed:
            text = w.text_for_selection()
            if text:
                set_primary_selection(text)
                if self.opts.copy_on_select:
                    self.copy_to_buffer(self.opts.copy_on_select)

    def copy_to_buffer(self, buffer_name):
        w = self.active_window
        if w is not None and not w.destroyed:
            text = w.text_for_selection()
            if text:
                if buffer_name == 'clipboard':
                    set_clipboard_string(text)
                elif buffer_name == 'primary':
                    set_primary_selection(text)
                else:
                    self.clipboard_buffers[buffer_name] = text

    def paste_from_buffer(self, buffer_name):
        if buffer_name == 'clipboard':
            text = get_clipboard_string()
        elif buffer_name == 'primary':
            text = get_primary_selection()
        else:
            text = self.clipboard_buffers.get(buffer_name)
        if text:
            self.paste_to_active_window(text)

    def goto_tab(self, tab_num):
        tm = self.active_tab_manager
        if tm is not None:
            tm.goto_tab(tab_num - 1)

    def set_active_tab(self, tab):
        tm = self.active_tab_manager
        if tm is not None:
            tm.set_active_tab(tab)

    def next_tab(self):
        tm = self.active_tab_manager
        if tm is not None:
            tm.next_tab()

    def previous_tab(self):
        tm = self.active_tab_manager
        if tm is not None:
            tm.next_tab(-1)

    prev_tab = previous_tab

    def process_stdin_source(self, window=None, stdin=None):
        w = window or self.active_window
        env = None
        if stdin:
            add_wrap_markers = stdin.endswith('_wrap')
            if add_wrap_markers:
                stdin = stdin[:-len('_wrap')]
            stdin = data_for_at(w, stdin, add_wrap_markers=add_wrap_markers)
            if stdin is not None:
                pipe_data = w.pipe_data(stdin, has_wrap_markers=add_wrap_markers) if w else {}
                if pipe_data:
                    env = {
                        'KITTY_PIPE_DATA':
                        '{scrolled_by}:{cursor_x},{cursor_y}:{lines},{columns}'.format(**pipe_data)
                    }
                stdin = stdin.encode('utf-8')
        return env, stdin

    def special_window_for_cmd(self, cmd, window=None, stdin=None, cwd_from=None, as_overlay=False):
        w = window or self.active_window
        env, stdin = self.process_stdin_source(w, stdin)
        cmdline = []
        for arg in cmd:
            if arg == '@selection':
                arg = data_for_at(w, arg)
                if not arg:
                    continue
            cmdline.append(arg)
        overlay_for = w.id if as_overlay and w.overlay_for is None else None
        return SpecialWindow(cmd, stdin, cwd_from=cwd_from, overlay_for=overlay_for, env=env)

    def pipe(self, source, dest, exe, *args):
        cmd = [exe] + list(args)
        window = self.active_window
        cwd_from = window.child.pid_for_cwd if window else None

        def create_window():
            return self.special_window_for_cmd(
                cmd, stdin=source, as_overlay=dest == 'overlay', cwd_from=cwd_from)

        if dest == 'overlay' or dest == 'window':
            tab = self.active_tab
            if tab is not None:
                return tab.new_special_window(create_window())
        elif dest == 'tab':
            tm = self.active_tab_manager
            if tm is not None:
                tm.new_tab(special_window=create_window(), cwd_from=cwd_from)
        elif dest == 'os_window':
            self._new_os_window(create_window(), cwd_from=cwd_from)
        else:
            import subprocess
            env, stdin = self.process_stdin_source(stdin=source, window=window)
            if stdin:
                p = subprocess.Popen(cmd, env=env, stdin=subprocess.PIPE)
                p.communicate(stdin)
            else:
                subprocess.Popen(cmd)

    def args_to_special_window(self, args, cwd_from=None):
        args = list(args)
        stdin = None
        w = self.active_window

        if args[0].startswith('@') and args[0] != '@':
            stdin = data_for_at(w, args[0]) or None
            if stdin is not None:
                stdin = stdin.encode('utf-8')
            del args[0]

        cmd = []
        for arg in args:
            if arg == '@selection':
                arg = data_for_at(w, arg)
                if not arg:
                    continue
            cmd.append(arg)
        return SpecialWindow(cmd, stdin, cwd_from=cwd_from)

    def _new_tab(self, args, cwd_from=None, as_neighbor=False):
        special_window = None
        if args:
            if isinstance(args, SpecialWindowInstance):
                special_window = args
            else:
                special_window = self.args_to_special_window(args, cwd_from=cwd_from)
        tm = self.active_tab_manager
        if tm is not None:
            return tm.new_tab(special_window=special_window, cwd_from=cwd_from, as_neighbor=as_neighbor)

    def _create_tab(self, args, cwd_from=None):
        as_neighbor = False
        if args and args[0].startswith('!'):
            as_neighbor = 'neighbor' in args[0][1:].split(',')
            args = args[1:]
        self._new_tab(args, as_neighbor=as_neighbor, cwd_from=cwd_from)

    def new_tab(self, *args):
        self._create_tab(args)

    def new_tab_with_cwd(self, *args):
        w = self.active_window_for_cwd
        cwd_from = w.child.pid_for_cwd if w is not None else None
        self._create_tab(args, cwd_from=cwd_from)

    def new_tab_with_wd(self, wd):
        special_window = SpecialWindow(None, cwd=wd)
        self._new_tab(special_window)

    def _new_window(self, args, cwd_from=None):
        tab = self.active_tab
        if tab is not None:
            if args:
                return tab.new_special_window(self.args_to_special_window(args, cwd_from=cwd_from))
            else:
                return tab.new_window(cwd_from=cwd_from)

    def new_window(self, *args):
        self._new_window(args)

    def new_window_with_cwd(self, *args):
        w = self.active_window_for_cwd
        if w is None:
            return self.new_window(*args)
        cwd_from = w.child.pid_for_cwd if w is not None else None
        self._new_window(args, cwd_from=cwd_from)

    def move_tab_forward(self):
        tm = self.active_tab_manager
        if tm is not None:
            tm.move_tab(1)

    def move_tab_backward(self):
        tm = self.active_tab_manager
        if tm is not None:
            tm.move_tab(-1)

    def patch_colors(self, spec, cursor_text_color, configured=False):
        if configured:
            for k, v in spec.items():
                if hasattr(self.opts, k):
                    setattr(self.opts, k, color_from_int(v))
            if cursor_text_color is not False:
                if isinstance(cursor_text_color, int):
                    cursor_text_color = color_from_int(cursor_text_color)
                self.opts.cursor_text_color = cursor_text_color
        for tm in self.all_tab_managers:
            tm.tab_bar.patch_colors(spec)
        patch_global_colors(spec, configured)

    def safe_delete_temp_file(self, path):
        if is_path_in_temp_dir(path):
            try:
                os.remove(path)
            except FileNotFoundError:
                pass

    def set_update_check_process(self, process=None):
        if self.update_check_process is not None:
            try:
                if self.update_check_process.poll() is None:
                    self.update_check_process.kill()
            except Exception:
                pass
        self.update_check_process = process

    def on_monitored_pid_death(self, pid, exit_status):
        update_check_process = getattr(self, 'update_check_process', None)
        if update_check_process is not None and pid == update_check_process.pid:
            self.update_check_process = None
            from .update_check import process_current_release
            try:
                raw = update_check_process.stdout.read().decode('utf-8')
            except Exception as e:
                log_error('Failed to read data from update check process, with error: {}'.format(e))
            else:
                try:
                    process_current_release(raw)
                except Exception as e:
                    log_error('Failed to process update check data {!r}, with error: {}'.format(raw, e))

    def notification_activated(self, identifier):
        if identifier == 'new-version':
            from .update_check import notification_activated
            notification_activated()

    def dbus_notification_callback(self, activated, *args):
        from .notify import dbus_notification_created, dbus_notification_activated
        if activated:
            dbus_notification_activated(*args)
        else:
            dbus_notification_created(*args)
