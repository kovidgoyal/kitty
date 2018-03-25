#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2016, Kovid Goyal <kovid at kovidgoyal.net>

import atexit
import json
import re
import socket
from functools import partial
from gettext import gettext as _
from weakref import WeakValueDictionary

from .cli import create_opts, parse_args
from .config import (
    MINIMUM_FONT_SIZE, initial_window_size, prepare_config_file_for_editing
)
from .constants import appname, editor, set_boss
from .fast_data_types import (
    ChildMonitor, create_os_window, current_os_window, destroy_global_data,
    destroy_sprite_map, get_clipboard_string, glfw_post_empty_event,
    layout_sprite_map, mark_os_window_for_close, set_clipboard_string,
    set_dpi_from_os_window, show_window, toggle_fullscreen,
    viewport_for_window
)
from .fonts.render import prerender, resize_fonts, set_font_family
from .keys import get_shortcut
from .remote_control import handle_cmd
from .session import create_session
from .tabs import SpecialWindow, SpecialWindowInstance, TabManager
from .utils import (
    end_startup_notification, get_primary_selection, init_startup_notification,
    log_error, open_url, parse_address_spec, remove_socket_file, safe_print,
    set_primary_selection, single_instance
)


def initialize_renderer():
    layout_sprite_map()
    prerender()


def listen_on(spec):
    family, address, socket_path = parse_address_spec(spec)
    s = socket.socket(family)
    atexit.register(remove_socket_file, s, socket_path)
    s.bind(address)
    s.listen()
    return s.fileno()


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

    def __init__(self, os_window_id, opts, args, cached_values):
        self.window_id_map = WeakValueDictionary()
        self.cached_values = cached_values
        self.os_window_map = {}
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
        self.current_font_size = opts.font_size
        set_font_family(opts)
        self.opts, self.args = opts, args
        initialize_renderer()
        startup_session = create_session(opts, args)
        self.add_os_window(startup_session, os_window_id=os_window_id)

    def add_os_window(self, startup_session, os_window_id=None, wclass=None, wname=None, size=None, startup_id=None):
        dpi_changed = False
        if os_window_id is None:
            w, h = initial_window_size(self.opts, self.cached_values) if size is None else size
            cls = wclass or self.args.cls or appname
            os_window_id = create_os_window(w, h, appname, wname or self.args.name or cls, cls)
            if startup_id:
                ctx = init_startup_notification(os_window_id, startup_id)
            dpi_changed = show_window(os_window_id)
            if startup_id:
                end_startup_notification(ctx)
        tm = TabManager(os_window_id, self.opts, self.args, startup_session)
        self.os_window_map[os_window_id] = tm
        if dpi_changed:
            self.on_dpi_change(os_window_id)

    def list_os_windows(self):
        for os_window_id, tm in self.os_window_map.items():
            yield {
                'id': os_window_id,
                'tabs': list(tm.list_tabs()),
            }

    def match_windows(self, match):
        try:
            field, exp = match.split(':', 1)
        except ValueError:
            return
        pat = re.compile(exp)
        for tm in self.os_window_map.values():
            for tab in tm:
                for window in tab:
                    if window.matches(field, pat):
                        yield window

    def tab_for_window(self, window):
        for tm in self.os_window_map.values():
            for tab in tm:
                for w in tab:
                    if w.id == window.id:
                        return tab

    def match_tabs(self, match):
        try:
            field, exp = match.split(':', 1)
        except ValueError:
            return
        pat = re.compile(exp)
        tms = tuple(self.os_window_map.values())
        found = False
        if field in ('title', 'id'):
            for tm in tms:
                for tab in tm:
                    if tab.matches(field, pat):
                        yield tab
                        found = True
        if not found:
            tabs = {self.tab_for_window(w) for w in self.match_windows(match)}
            for tab in tabs:
                if tab:
                    yield tab

    def set_active_window(self, window):
        for tm in self.os_window_map.values():
            for tab in tm:
                for w in tab:
                    if w.id == window.id:
                        if tab is not self.active_tab:
                            tm.set_active_tab(tab)
                        tab.set_active_window(w)
                        return

    def _new_os_window(self, args, cwd_from=None):
        sw = self.args_to_special_window(args, cwd_from) if args else None
        startup_session = create_session(self.opts, special_window=sw, cwd_from=cwd_from)
        self.add_os_window(startup_session)

    def new_os_window(self, *args):
        self._new_os_window(args)

    def new_os_window_with_cwd(self, *args):
        w = self.active_window
        cwd_from = w.child.pid if w is not None else None
        self._new_os_window(args, cwd_from)

    def add_child(self, window):
        self.child_monitor.add_child(window.id, window.child.pid, window.child.child_fd, window.screen)
        self.window_id_map[window.id] = window

    def _handle_remote_command(self, cmd, window=None):
        response = None
        if self.opts.allow_remote_control:
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
                session = create_session(opts, args)
                self.add_os_window(session, wclass=args.cls, wname=args.name, size=initial_window_size(opts, self.cached_values), startup_id=startup_id)
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
                    glfw_post_empty_event()

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

    def activate_tab_at(self, os_window_id, x):
        tm = self.os_window_map.get(os_window_id)
        if tm is not None:
            tm.activate_tab_at(x)

    def on_window_resize(self, os_window_id, w, h, dpi_changed):
        tm = self.os_window_map.get(os_window_id)
        if tm is not None:
            if dpi_changed:
                if set_dpi_from_os_window(os_window_id):
                    self.on_dpi_change(os_window_id)
                else:
                    tm.resize()
            else:
                tm.resize()

    def increase_font_size(self):
        self.set_font_size(
            min(
                self.opts.font_size * 5, self.current_font_size +
                self.opts.font_size_delta))

    def decrease_font_size(self):
        self.set_font_size(self.current_font_size - self.opts.font_size_delta)

    def restore_font_size(self):
        self.set_font_size(self.opts.font_size)

    def _change_font_size(self, new_size=None, on_dpi_change=False):
        if new_size is not None:
            self.current_font_size = new_size
        old_cell_width, old_cell_height = viewport_for_window()[-2:]
        windows = tuple(filter(None, self.window_id_map.values()))
        resize_fonts(self.current_font_size, on_dpi_change=on_dpi_change)
        layout_sprite_map()
        prerender()
        for window in windows:
            window.screen.rescale_images(old_cell_width, old_cell_height)
            window.screen.refresh_sprite_positions()
        for tm in self.os_window_map.values():
            tm.resize()
            tm.refresh_sprite_positions()
        glfw_post_empty_event()

    def set_font_size(self, new_size):
        new_size = max(MINIMUM_FONT_SIZE, new_size)
        if new_size == self.current_font_size:
            return
        self._change_font_size(new_size)

    def on_dpi_change(self, os_window_id):
        self._change_font_size()

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
        key_action = get_shortcut(self.opts.keymap, mods, key, scancode)
        self.current_key_press_info = key, scancode, action, mods
        return self.dispatch_action(key_action)

    def default_bg_changed_for(self, window_id):
        w = self.window_id_map.get(window_id)
        if w is not None:
            tm = self.os_window_map.get(w.os_window_id)
            if tm is not None:
                t = tm.tab_for_id(w.tab_id)
                if t is not None:
                    t.relayout_borders()

    def dispatch_action(self, key_action):
        if key_action is not None:
            f = getattr(self, key_action.func, None)
            if f is not None:
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

    def display_scrollback(self, window, data):
        tab = self.active_tab
        if tab is not None and window.overlay_for is None:
            tab.new_special_window(
                SpecialWindow(
                    self.opts.scrollback_pager, data, _('History'), overlay_for=window.id))

    def edit_config_file(self, *a):
        confpath = prepare_config_file_for_editing()
        # On macOS vim fails to handle SIGWINCH if it occurs early, so add a
        # small delay.
        cmd = ['kitty', '+runpy', 'import os, sys, time; time.sleep(0.05); os.execvp(sys.argv[1], sys.argv[1:])'] + editor + [confpath]
        self.new_os_window(*cmd)

    def input_unicode_character(self):
        w = self.active_window
        tab = self.active_tab
        if w is not None and tab is not None and w.overlay_for is None:
            overlay_window = tab.new_special_window(
                SpecialWindow(
                    ['kitty', '+runpy', 'from kittens.unicode_input.main import main; main()'],
                    overlay_for=w.id))
            overlay_window.action_on_close = partial(self.send_unicode_character, w.id)

    def get_output(self, source_window, num_lines=1):
        output = ''
        s = source_window.screen
        for i in range(min(num_lines, s.lines)):
            output += str(s.linebuf.line(i))
        return output

    def send_unicode_character(self, target_window_id, source_window):
        w = self.window_id_map.get(target_window_id)
        if w is not None:
            output = self.get_output(source_window)
            if output.startswith('OK: '):
                try:
                    text = chr(int(output.partition(' ')[2], 16))
                except Exception:
                    import traceback
                    traceback.print_exc()
                else:
                    w.paste(text)

    def set_tab_title(self):
        w = self.active_window
        tab = self.active_tab
        if w is not None and tab is not None and w.overlay_for is None:
            args = ['--name=tab-title', '--message', _('Enter the new title for this tab below.')]
            overlay_window = tab.new_special_window(
                SpecialWindow(
                    ['kitty', '+runpy', 'from kittens.ask.main import main; main()'] + args,
                    overlay_for=w.id))
            overlay_window.action_on_close = partial(self.do_set_tab_title, tab.id)

    def do_set_tab_title(self, tab_id, source_window):
        output = self.get_output(source_window)
        if output.startswith('OK: '):
            title = json.loads(output.partition(' ')[2].strip())
            tm = self.active_tab_manager
            if tm is not None and title:
                for tab in tm.tabs:
                    if tab.id == tab_id:
                        tab.set_title(title)
                        break

    def run_simple_kitten(self, type_of_input, kitten, *args):
        import shlex
        w = self.active_window
        tab = self.active_tab
        if w is not None and tab is not None and w.overlay_for is None:
            cmdline = args[0] if args else ''
            args = shlex.split(cmdline) if cmdline else []
            if '--program' not in cmdline:
                args.extend(('--program', self.opts.open_url_with))
            if type_of_input in ('text', 'history', 'ansi', 'ansi-history'):
                data = w.as_text(as_ansi='ansi' in type_of_input, add_history='history' in type_of_input).encode('utf-8')
            elif type_of_input == 'none':
                data = None
            else:
                raise ValueError('Unknown type_of_input: {}'.format(type_of_input))
            tab.new_special_window(
                SpecialWindow(
                    ['kitty', '+runpy', 'from kittens.{}.main import main; main()'.format(kitten)] + args,
                    stdin=data,
                    overlay_for=w.id))

    def switch_focus_to(self, window_idx):
        tab = self.active_tab
        tab.set_active_window_idx(window_idx)
        old_focus = tab.active_window
        if not old_focus.destroyed:
            old_focus.focus_changed(False)
        tab.active_window.focus_changed(True)

    def open_url(self, url):
        if url:
            open_url(url, self.opts.open_url_with)

    def open_url_lines(self, lines):
        self.open_url(''.join(lines))

    def destroy(self):
        self.shutting_down = True
        self.child_monitor.shutdown_monitor()
        del self.child_monitor
        for tm in self.os_window_map.values():
            tm.destroy()
        self.os_window_map = {}
        destroy_sprite_map()
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
        text = get_primary_selection()
        self.paste_to_active_window(text)

    def set_primary_selection(self):
        w = self.active_window
        if w is not None and not w.destroyed:
            text = w.text_for_selection()
            if text:
                set_primary_selection(text)
                if self.opts.copy_on_select:
                    set_clipboard_string(text)

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

    def args_to_special_window(self, args, cwd_from=None):
        args = list(args)
        stdin = None
        w = self.active_window

        def data_for_at(arg):
            if arg == '@selection':
                return w.text_for_selection()
            if arg == '@ansi':
                return w.as_text(as_ansi=True, add_history=True)
            if arg == '@text':
                return w.as_text(add_history=True)
            if arg == '@screen':
                return w.as_text()
            if arg == '@ansi_screen':
                return w.as_text(as_ansi=True)

        if args[0].startswith('@'):
            stdin = data_for_at(args[0]) or None
            if stdin is not None:
                stdin = stdin.encode('utf-8')
            del args[0]

        cmd = []
        for arg in args:
            if arg == '@selection':
                arg = data_for_at(arg)
                if not arg:
                    continue
            cmd.append(arg)
        return SpecialWindow(cmd, stdin, cwd_from=cwd_from)

    def _new_tab(self, args, cwd_from=None):
        special_window = None
        if args:
            if isinstance(args, SpecialWindowInstance):
                special_window = args
            else:
                special_window = self.args_to_special_window(args, cwd_from=cwd_from)
        tm = self.active_tab_manager
        if tm is not None:
            tm.new_tab(special_window=special_window, cwd_from=cwd_from)

    def new_tab(self, *args):
        self._new_tab(args)

    def new_tab_with_cwd(self, *args):
        w = self.active_window
        cwd_from = w.child.pid if w is not None else None
        self._new_tab(args, cwd_from=cwd_from)

    def _new_window(self, args, cwd_from=None):
        tab = self.active_tab
        if tab is not None:
            if args:
                tab.new_special_window(self.args_to_special_window(args, cwd_from=cwd_from))
            else:
                tab.new_window(cwd_from=cwd_from)

    def new_window(self, *args):
        self._new_window(args)

    def new_window_with_cwd(self, *args):
        w = self.active_window
        if w is None:
            return self.new_window(*args)
        cwd_from = w.child.pid if w is not None else None
        self._new_window(args, cwd_from=cwd_from)

    def move_tab_forward(self):
        tm = self.active_tab_manager
        if tm is not None:
            tm.move_tab(1)

    def move_tab_backward(self):
        tm = self.active_tab_manager
        if tm is not None:
            tm.move_tab(-1)
