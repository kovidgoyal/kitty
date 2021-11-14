#!/usr/bin/env python3
# License: GPL v3 Copyright: 2016, Kovid Goyal <kovid at kovidgoyal.net>

import atexit
import json
import os
import re
from contextlib import suppress
from functools import partial
from gettext import gettext as _
from typing import (
    Any, Callable, Container, Dict, Iterable, Iterator, List, Optional, Tuple,
    Union, cast
)
from weakref import WeakValueDictionary

from .child import (
    cached_process_data, cwd_of_process, default_env, set_default_env
)
from .cli import create_opts, parse_args
from .cli_stub import CLIOptions
from .conf.utils import BadLine, KeyAction, to_cmdline
from .config import common_opts_as_dict, prepare_config_file_for_editing
from .constants import (
    appname, config_dir, is_macos, is_wayland, kitty_exe,
    supports_primary_selection, website_url
)
from .fast_data_types import (
    CLOSE_BEING_CONFIRMED, GLFW_MOD_ALT, GLFW_MOD_CONTROL, GLFW_MOD_SHIFT,
    GLFW_MOD_SUPER, GLFW_MOUSE_BUTTON_LEFT, GLFW_PRESS,
    IMPERATIVE_CLOSE_REQUESTED, NO_CLOSE_REQUESTED, ChildMonitor, Color,
    KeyEvent, add_timer, apply_options_update, background_opacity_of,
    change_background_opacity, change_os_window_state, cocoa_set_menubar_title,
    create_os_window, current_application_quit_request, current_os_window,
    destroy_global_data, focus_os_window, get_boss, get_clipboard_string,
    get_options, get_os_window_size, global_font_size,
    mark_os_window_for_close, os_window_font_size, patch_global_colors,
    redirect_mouse_handling, ring_bell, safe_pipe,
    set_application_quit_request, set_background_image, set_boss,
    set_clipboard_string, set_in_sequence_mode, set_options,
    set_os_window_size, set_os_window_title, thread_write, toggle_fullscreen,
    toggle_maximized
)
from .key_encoding import get_name_to_functional_number_map
from .keys import get_shortcut, shortcut_matches
from .layout.base import set_layout_options
from .notify import notification_activated
from .options.types import Options
from .options.utils import MINIMUM_FONT_SIZE, SubSequenceMap
from .os_window_size import initial_window_size_func
from .rgb import color_from_int
from .session import Session, create_sessions, get_os_window_sizing_data
from .tabs import (
    SpecialWindow, SpecialWindowInstance, Tab, TabDict, TabManager
)
from .types import _T, AsyncResponse, SingleKey, WindowSystemMouseEvent, ac
from .typing import PopenType, TypedDict
from .utils import (
    func_name, get_editor, get_new_os_window_size, get_primary_selection,
    is_path_in_temp_dir, log_error, open_url, parse_address_spec,
    parse_uri_list, platform_window_id, read_shell_environment,
    remove_socket_file, safe_print, set_primary_selection, single_instance,
    startup_notification_handler
)
from .window import MatchPatternType, Window


class OSWindowDict(TypedDict):
    id: int
    platform_window_id: Optional[int]
    is_focused: bool
    tabs: List[TabDict]
    wm_class: str
    wm_name: str


def listen_on(spec: str) -> int:
    import socket
    family, address, socket_path = parse_address_spec(spec)
    s = socket.socket(family)
    atexit.register(remove_socket_file, s, socket_path)
    s.bind(address)
    s.listen()
    return s.fileno()


def data_for_at(w: Optional[Window], arg: str, add_wrap_markers: bool = False) -> Optional[str]:
    if not w:
        return None

    def as_text(**kw: bool) -> str:
        kw['add_wrap_markers'] = add_wrap_markers
        return w.as_text(**kw) if w else ''

    if arg == '@selection':
        return w.text_for_selection()
    if arg in ('@ansi', '@ansi_screen_scrollback'):
        return as_text(as_ansi=True, add_history=True)
    if arg in ('@text', '@screen_scrollback'):
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
    if arg == '@first_cmd_output_on_screen':
        return w.first_cmd_output_on_screen(add_wrap_markers=add_wrap_markers)
    if arg == '@ansi_first_cmd_output_on_screen':
        return w.first_cmd_output_on_screen(as_ansi=True, add_wrap_markers=add_wrap_markers)
    if arg == '@last_cmd_output':
        return w.last_cmd_output(add_wrap_markers=add_wrap_markers)
    if arg == '@ansi_last_cmd_output':
        return w.last_cmd_output(as_ansi=True, add_wrap_markers=add_wrap_markers)
    if arg == '@last_visited_cmd_output':
        return w.last_visited_cmd_output(add_wrap_markers=add_wrap_markers)
    if arg == '@ansi_last_visited_cmd_output':
        return w.last_visited_cmd_output(as_ansi=True, add_wrap_markers=add_wrap_markers)
    return None


class DumpCommands:  # {{{

    def __init__(self, args: CLIOptions):
        self.draw_dump_buf: List[str] = []
        if args.dump_bytes:
            self.dump_bytes_to = open(args.dump_bytes, 'wb')

    def __call__(self, *a: Any) -> None:
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


class VisualSelect:

    def __init__(
        self,
        tab_id: int,
        os_window_id: int,
        prev_tab_id: Optional[int],
        prev_os_window_id: Optional[int],
        title: str,
        callback: Callable[[Optional[Tab], Optional[Window]], None],
        reactivate_prev_tab: bool
    ) -> None:
        self.tab_id = tab_id
        self.os_window_id = os_window_id
        self.prev_tab_id = prev_tab_id
        self.prev_os_window_id = prev_os_window_id
        self.callback = callback
        self.window_ids: List[int] = []
        self.window_used_for_selection_id = 0
        self.reactivate_prev_tab = reactivate_prev_tab
        set_os_window_title(self.os_window_id, title)

    def cancel(self) -> None:
        self.clear_global_state()
        self.activate_prev_tab()
        self.callback(None, None)

    def trigger(self, window_id: int) -> None:
        boss = self.clear_global_state()
        self.activate_prev_tab()
        w = boss.window_id_map.get(window_id)
        if w is None:
            self.callback(None, None)
        else:
            tab = w.tabref()
            if tab is None:
                self.callback(None, None)
            else:
                self.callback(tab, w)

    def clear_global_state(self) -> 'Boss':
        set_os_window_title(self.os_window_id, '')
        boss = get_boss()
        redirect_mouse_handling(False)
        boss.clear_pending_sequences()
        for wid in self.window_ids:
            w = boss.window_id_map.get(wid)
            if w is not None:
                w.screen.set_window_char()
        if self.window_used_for_selection_id:
            w = boss.window_id_map.get(self.window_used_for_selection_id)
            if w is not None:
                boss.mark_window_for_close(w)
        return boss

    def activate_prev_tab(self) -> None:
        if not self.reactivate_prev_tab or self.prev_tab_id is None:
            return None
        boss = get_boss()
        tm = boss.os_window_map.get(self.os_window_id)
        if tm is not None:
            t = tm.tab_for_id(self.prev_tab_id)
            if t is not tm.active_tab and t is not None:
                tm.set_active_tab(t)
        if current_os_window() != self.prev_os_window_id and self.prev_os_window_id is not None:
            focus_os_window(self.prev_os_window_id, True)


class Boss:

    def __init__(
        self,
        opts: Options,
        args: CLIOptions,
        cached_values: Dict[str, Any],
        global_shortcuts: Dict[str, SingleKey]
    ):
        set_layout_options(opts)
        self.cocoa_application_launched = False
        self.clipboard_buffers: Dict[str, str] = {}
        self.update_check_process: Optional['PopenType[bytes]'] = None
        self.window_id_map: WeakValueDictionary[int, Window] = WeakValueDictionary()
        self.startup_colors = {k: opts[k] for k in opts if isinstance(opts[k], Color)}
        self.current_visual_select: Optional[VisualSelect] = None
        self.startup_cursor_text_color = opts.cursor_text_color
        self.pending_sequences: Optional[SubSequenceMap] = None
        self.default_pending_action: Optional[KeyAction] = None
        self.cached_values = cached_values
        self.os_window_map: Dict[int, TabManager] = {}
        self.os_window_death_actions: Dict[int, Callable[[], None]] = {}
        self.cursor_blinking = True
        self.shutting_down = False
        talk_fd = getattr(single_instance, 'socket', None)
        talk_fd = -1 if talk_fd is None else talk_fd.fileno()
        listen_fd = -1
        # we dont allow reloading the config file to change
        # allow_remote_control
        self.allow_remote_control = opts.allow_remote_control
        if args.listen_on and (self.allow_remote_control in ('y', 'socket-only')):
            listen_fd = listen_on(args.listen_on)
        self.child_monitor = ChildMonitor(
            self.on_child_death,
            DumpCommands(args) if args.dump_commands or args.dump_bytes else None,
            talk_fd, listen_fd
        )
        set_boss(self)
        self.args = args
        self.global_shortcuts_map = {v: KeyAction(k) for k, v in global_shortcuts.items()}
        self.global_shortcuts = global_shortcuts
        self.mouse_handler: Optional[Callable[[WindowSystemMouseEvent], None]] = None
        self.update_keymap()
        if is_macos:
            from .fast_data_types import (
                cocoa_set_notification_activated_callback
            )
            cocoa_set_notification_activated_callback(notification_activated)

    def update_keymap(self) -> None:
        self.keymap = get_options().keymap.copy()
        for sc in self.global_shortcuts.values():
            self.keymap.pop(sc, None)

    def startup_first_child(self, os_window_id: Optional[int]) -> None:
        startup_sessions = create_sessions(get_options(), self.args, default_session=get_options().startup_session)
        for startup_session in startup_sessions:
            self.add_os_window(startup_session, os_window_id=os_window_id)
            os_window_id = None
            if self.args.start_as != 'normal':
                if self.args.start_as == 'fullscreen':
                    self.toggle_fullscreen()
                else:
                    change_os_window_state(self.args.start_as)

    def add_os_window(
        self,
        startup_session: Optional[Session] = None,
        os_window_id: Optional[int] = None,
        wclass: Optional[str] = None,
        wname: Optional[str] = None,
        opts_for_size: Optional[Options] = None,
        startup_id: Optional[str] = None,
        override_title: Optional[str] = None,
    ) -> int:
        if os_window_id is None:
            size_data = get_os_window_sizing_data(opts_for_size or get_options(), startup_session)
            wclass = wclass or getattr(startup_session, 'os_window_class', None) or self.args.cls or appname
            wname = wname or self.args.name or wclass
            wtitle = override_title or self.args.title
            with startup_notification_handler(do_notify=startup_id is not None, startup_id=startup_id) as pre_show_callback:
                os_window_id = create_os_window(
                        initial_window_size_func(size_data, self.cached_values),
                        pre_show_callback,
                        wtitle or appname, wname, wclass, disallow_override_title=bool(wtitle))
        else:
            wname = self.args.name or self.args.cls or appname
            wclass = self.args.cls or appname
        tm = TabManager(os_window_id, self.args, wclass, wname, startup_session)
        self.os_window_map[os_window_id] = tm
        return os_window_id

    def list_os_windows(self, self_window: Optional[Window] = None) -> Iterator[OSWindowDict]:
        with cached_process_data():
            active_tab, active_window = self.active_tab, self.active_window
            active_tab_manager = self.active_tab_manager
            for os_window_id, tm in self.os_window_map.items():
                yield {
                    'id': os_window_id,
                    'platform_window_id': platform_window_id(os_window_id),
                    'is_focused': tm is active_tab_manager,
                    'tabs': list(tm.list_tabs(active_tab, active_window, self_window)),
                    'wm_class': tm.wm_class,
                    'wm_name': tm.wm_name
                }

    @property
    def all_tab_managers(self) -> Iterator[TabManager]:
        yield from self.os_window_map.values()

    @property
    def all_tabs(self) -> Iterator[Tab]:
        for tm in self.all_tab_managers:
            yield from tm

    @property
    def all_windows(self) -> Iterator[Window]:
        for tab in self.all_tabs:
            yield from tab

    def match_windows(self, match: str) -> Iterator[Window]:
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
        if field == 'recent':
            tab = self.active_tab
            if tab is not None:
                try:
                    num = int(exp)
                except Exception:
                    return
                w = self.window_id_map.get(tab.nth_active_window_id(num))
                if w is not None:
                    yield w
            return
        if field != 'env':
            pat: MatchPatternType = re.compile(exp)
        else:
            kp, vp = exp.partition('=')[::2]
            if vp:
                pat = re.compile(kp), re.compile(vp)
            else:
                pat = re.compile(kp), None
        for window in self.all_windows:
            if window.matches(field, pat):
                yield window

    def tab_for_window(self, window: Window) -> Optional[Tab]:
        for tab in self.all_tabs:
            for w in tab:
                if w.id == window.id:
                    return tab
        return None

    def match_tabs(self, match: str) -> Iterator[Tab]:
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
        elif field in ('window_id', 'window_title'):
            wf = field.split('_')[1]
            tabs = {self.tab_for_window(w) for w in self.match_windows(f'{wf}:{exp}')}
            for q in tabs:
                if q:
                    found = True
                    yield q
        elif field == 'index':
            tm = self.active_tab_manager
            if tm is not None and len(tm.tabs) > 0:
                idx = (int(pat.pattern) + len(tm.tabs)) % len(tm.tabs)
                found = True
                yield tm.tabs[idx]
        elif field == 'recent':
            tm = self.active_tab_manager
            if tm is not None and len(tm.tabs) > 0:
                try:
                    num = int(exp)
                except Exception:
                    return
                q = tm.nth_active_tab(num)
                if q is not None:
                    found = True
                    yield q
        if not found:
            tabs = {self.tab_for_window(w) for w in self.match_windows(match)}
            for q in tabs:
                if q:
                    yield q

    def set_active_window(self, window: Window, switch_os_window_if_needed: bool = False) -> Optional[int]:
        for os_window_id, tm in self.os_window_map.items():
            for tab in tm:
                for w in tab:
                    if w.id == window.id:
                        if tab is not self.active_tab:
                            tm.set_active_tab(tab)
                        tab.set_active_window(w)
                        if switch_os_window_if_needed and current_os_window() != os_window_id:
                            focus_os_window(os_window_id, True)
                        return os_window_id
        return None

    def _new_os_window(self, args: Union[SpecialWindowInstance, Iterable[str]], cwd_from: Optional[int] = None) -> int:
        if isinstance(args, SpecialWindowInstance):
            sw: Optional[SpecialWindowInstance] = args
        else:
            sw = self.args_to_special_window(args, cwd_from) if args else None
        startup_session = next(create_sessions(get_options(), special_window=sw, cwd_from=cwd_from))
        return self.add_os_window(startup_session)

    @ac('win', 'New OS Window')
    def new_os_window(self, *args: str) -> None:
        self._new_os_window(args)

    @property
    def active_window_for_cwd(self) -> Optional[Window]:
        t = self.active_tab
        if t is not None:
            return t.active_window_for_cwd
        return None

    @ac('win', 'New OS Window with the same working directory as the currently active window')
    def new_os_window_with_cwd(self, *args: str) -> None:
        w = self.active_window_for_cwd
        cwd_from = w.child.pid_for_cwd if w is not None else None
        self._new_os_window(args, cwd_from)

    def new_os_window_with_wd(self, wd: str) -> None:
        special_window = SpecialWindow(None, cwd=wd)
        self._new_os_window(special_window)

    def add_child(self, window: Window) -> None:
        assert window.child.pid is not None and window.child.child_fd is not None
        self.child_monitor.add_child(window.id, window.child.pid, window.child.child_fd, window.screen)
        self.window_id_map[window.id] = window

    def _handle_remote_command(self, cmd: str, window: Optional[Window] = None, peer_id: int = 0) -> Union[Dict[str, Any], None, AsyncResponse]:
        from .remote_control import handle_cmd
        response = None
        window = window or None
        if self.allow_remote_control == 'y' or peer_id > 0 or getattr(window, 'allow_remote_control', False):
            try:
                response = handle_cmd(self, window, cmd, peer_id)
            except Exception as err:
                import traceback
                response = {'ok': False, 'error': str(err)}
                if not getattr(err, 'hide_traceback', False):
                    response['tb'] = traceback.format_exc()
        else:
            no_response = False
            try:
                no_response = json.loads(cmd).get('no_response')
            except Exception:
                pass
            if not no_response:
                response = {'ok': False, 'error': 'Remote control is disabled. Add allow_remote_control to your kitty.conf'}
        return response

    @ac('misc', '''
        Run a remote control command

        For example::

            map F1 remote_control set-spacing margin=30

        See :ref:`rc_mapping` for details.
        ''')
    def remote_control(self, *args: str) -> None:
        from .rc.base import (
            PayloadGetter, command_for_name, parse_subcommand_cli
        )
        from .remote_control import parse_rc_args
        try:
            global_opts, items = parse_rc_args(['@'] + list(args))
            if not items:
                return
            cmd = items[0]
            c = command_for_name(cmd)
            opts, items = parse_subcommand_cli(c, items)
            payload = c.message_to_kitty(global_opts, opts, items)
            import types
            if isinstance(cast(types.GeneratorType, payload), types.GeneratorType):
                payloads = cast(types.GeneratorType, payload)
                for x in payloads:
                    c.response_from_kitty(self, self.active_window, PayloadGetter(c, x if isinstance(x, dict) else {}))
            else:
                c.response_from_kitty(self, self.active_window, PayloadGetter(c, payload if isinstance(payload, dict) else {}))
        except (Exception, SystemExit):
            import traceback
            tb = traceback.format_exc()
            self.show_error(_('remote_control mapping failed'), tb)

    def peer_message_received(self, msg_bytes: bytes, peer_id: int) -> Union[bytes, bool, None]:
        cmd_prefix = b'\x1bP@kitty-cmd'
        terminator = b'\x1b\\'
        if msg_bytes.startswith(cmd_prefix) and msg_bytes.endswith(terminator):
            cmd = msg_bytes[len(cmd_prefix):-len(terminator)].decode('utf-8')
            response = self._handle_remote_command(cmd, peer_id=peer_id)
            if response is None:
                return None
            if isinstance(response, AsyncResponse):
                return True
            from kitty.remote_control import encode_response_for_peer
            return encode_response_for_peer(response)

        data = json.loads(msg_bytes.decode('utf-8'))
        if isinstance(data, dict) and data.get('cmd') == 'new_instance':
            from .cli_stub import CLIOptions
            startup_id = data.get('startup_id')
            args, rest = parse_args(data['args'][1:], result_class=CLIOptions)
            args.args = rest
            opts = create_opts(args)
            if args.session == '-':
                from .session import PreReadSession
                args.session = PreReadSession(data['stdin'])
            if not os.path.isabs(args.directory):
                args.directory = os.path.join(data['cwd'], args.directory)
            for session in create_sessions(opts, args, respect_cwd=True):
                os_window_id = self.add_os_window(
                    session, wclass=args.cls, wname=args.name, opts_for_size=opts, startup_id=startup_id,
                    override_title=args.title or None)
                if opts.background_opacity != get_options().background_opacity:
                    self._set_os_window_background_opacity(os_window_id, opts.background_opacity)
                if data.get('notify_on_os_window_death'):
                    self.os_window_death_actions[os_window_id] = partial(self.notify_on_os_window_death, data['notify_on_os_window_death'])
        else:
            log_error('Unknown message received from peer, ignoring')
        return None

    def handle_remote_cmd(self, cmd: str, window: Optional[Window] = None) -> None:
        response = self._handle_remote_command(cmd, window)
        if response is not None and not isinstance(response, AsyncResponse) and window is not None:
            window.send_cmd_response(response)

    def mark_os_window_for_close(self, os_window_id: int, request_type: int = IMPERATIVE_CLOSE_REQUESTED) -> None:
        if self.current_visual_select is not None and self.current_visual_select.os_window_id == os_window_id and request_type == IMPERATIVE_CLOSE_REQUESTED:
            self.cancel_current_visual_select()
        mark_os_window_for_close(os_window_id, request_type)

    def _cleanup_tab_after_window_removal(self, src_tab: Tab) -> None:
        if len(src_tab) < 1:
            tm = src_tab.tab_manager_ref()
            if tm is not None:
                tm.remove(src_tab)
                src_tab.destroy()
                if len(tm) == 0:
                    if not self.shutting_down:
                        self.mark_os_window_for_close(src_tab.os_window_id)

    def on_child_death(self, window_id: int) -> None:
        prev_active_window = self.active_window
        window = self.window_id_map.pop(window_id, None)
        if window is None:
            return
        for close_action in window.actions_on_close:
            try:
                close_action(window)
            except Exception:
                import traceback
                traceback.print_exc()
        os_window_id = window.os_window_id
        window.destroy()
        tm = self.os_window_map.get(os_window_id)
        tab = None
        if tm is not None:
            for q in tm:
                if window in q:
                    tab = q
                    break
        if tab is not None:
            tab.remove_window(window)
            self._cleanup_tab_after_window_removal(tab)
        for removal_action in window.actions_on_removal:
            try:
                removal_action(window)
            except Exception:
                import traceback
                traceback.print_exc()
        del window.actions_on_close[:], window.actions_on_removal[:]
        window = self.active_window
        if window is not prev_active_window:
            if prev_active_window is not None:
                prev_active_window.focus_changed(False)
            if window is not None:
                window.focus_changed(True)

    def mark_window_for_close(self, q: Union[Window, None, int] = None) -> None:
        if isinstance(q, int):
            window = self.window_id_map.get(q)
            if window is None:
                return
        else:
            window = q or self.active_window
        if window:
            self.child_monitor.mark_for_close(window.id)

    @ac('win', 'Close the currently active window')
    def close_window(self) -> None:
        self.mark_window_for_close()

    @ac('win', '''
    Close window with confirmation

    Asks for confirmation before closing the window. If you don't want the
    confirmation when the window is sitting at a shell prompt
    (requires :ref:`shell_integration`), use::

        map f1 close_window_with_confirmation ignore-shell
    ''')
    def close_window_with_confirmation(self, ignore_shell: bool = False) -> None:
        window = self.active_window
        if window is None:
            return
        if not ignore_shell or window.has_running_program:
            msg = _('Are you sure you want to close this window?')
            if window.has_running_program:
                msg += ' ' + _('It is running a program.')
            self._run_kitten(
                'ask', ['--type=yesno', '--message', msg],
                window=window,
                custom_callback=partial(self.handle_close_window_confirmation, window.id)
            )
        else:
            self.mark_window_for_close(window)

    def handle_close_window_confirmation(self, window_id: int, data: Dict[str, Any], *a: Any) -> None:
        if data['response'] != 'y':
            return
        self.mark_window_for_close(window_id)

    @ac('tab', 'Close the current tab')
    def close_tab(self, tab: Optional[Tab] = None) -> None:
        tab = tab or self.active_tab
        if tab:
            self.confirm_tab_close(tab)

    def confirm_tab_close(self, tab: Tab) -> None:
        x = get_options().confirm_os_window_close
        num = tab.number_of_windows_with_running_programs if x < 0 else len(tab)
        needs_confirmation = x != 0 and num >= abs(x)
        if not needs_confirmation:
            self.close_tab_no_confirm(tab)
            return
        if tab is not self.active_tab:
            tm = tab.tab_manager_ref()
            if tm is not None:
                tm.set_active_tab(tab)
        self._run_kitten('ask', ['--type=yesno', '--message', _(
            'Are you sure you want to close this tab, it has {}'
            ' windows running?').format(num)],
            window=tab.active_window,
            custom_callback=partial(self.handle_close_tab_confirmation, tab.id)
        )

    def handle_close_tab_confirmation(self, tab_id: int, data: Dict[str, Any], *a: Any) -> None:
        if data['response'] != 'y':
            return
        for tab in self.all_tabs:
            if tab.id == tab_id:
                break
        else:
            return
        self.close_tab_no_confirm(tab)

    def close_tab_no_confirm(self, tab: Tab) -> None:
        if self.current_visual_select is not None and self.current_visual_select.tab_id == tab.id:
            self.cancel_current_visual_select()
        for window in tab:
            self.mark_window_for_close(window)

    @ac('win', 'Toggle the fullscreen status of the active OS Window')
    def toggle_fullscreen(self, os_window_id: int = 0) -> None:
        toggle_fullscreen(os_window_id)

    @ac('win', 'Toggle the maximized status of the active OS Window')
    def toggle_maximized(self, os_window_id: int = 0) -> None:
        toggle_maximized(os_window_id)

    def start(self, first_os_window_id: int) -> None:
        if not getattr(self, 'io_thread_started', False):
            self.child_monitor.start()
            self.io_thread_started = True
            self.startup_first_child(first_os_window_id)

        if get_options().update_check_interval > 0 and not hasattr(self, 'update_check_started'):
            from .update_check import run_update_check
            run_update_check(get_options().update_check_interval * 60 * 60)
            self.update_check_started = True

    def handle_click_on_tab(self, os_window_id: int, x: int, button: int, modifiers: int, action: int) -> None:
        tm = self.os_window_map.get(os_window_id)
        if tm is not None:
            tm.handle_click_on_tab(x, button, modifiers, action)

    def on_window_resize(self, os_window_id: int, w: int, h: int, dpi_changed: bool) -> None:
        if dpi_changed:
            self.on_dpi_change(os_window_id)
        else:
            tm = self.os_window_map.get(os_window_id)
            if tm is not None:
                tm.resize()

    @ac('misc', '''
        Clear the terminal

        See :sc:`reset_terminal` for details. For example::

            # Reset the terminal
            map kitty_mod+f9 clear_terminal reset active
            # Clear the terminal screen by erasing all contents
            map kitty_mod+f10 clear_terminal clear active
            # Clear the terminal scrollback by erasing it
            map kitty_mod+f11 clear_terminal scrollback active
            # Scroll the contents of the screen into the scrollback
            map kitty_mod+f12 clear_terminal scroll active

        ''')
    def clear_terminal(self, action: str, only_active: bool) -> None:
        if only_active:
            windows = []
            w = self.active_window
            if w is not None:
                windows.append(w)
        else:
            windows = list(self.all_windows)
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

    def increase_font_size(self) -> None:  # legacy
        cfs = global_font_size()
        self.set_font_size(min(get_options().font_size * 5, cfs + 2.0))

    def decrease_font_size(self) -> None:  # legacy
        cfs = global_font_size()
        self.set_font_size(max(MINIMUM_FONT_SIZE, cfs - 2.0))

    def restore_font_size(self) -> None:  # legacy
        self.set_font_size(get_options().font_size)

    def set_font_size(self, new_size: float) -> None:  # legacy
        self.change_font_size(True, None, new_size)

    @ac('win', '''
        Change the font size for the current or all OS Windows

        See :ref:`conf-kitty-shortcuts.fonts` for details.
        ''')
    def change_font_size(self, all_windows: bool, increment_operation: Optional[str], amt: float) -> None:
        def calc_new_size(old_size: float) -> float:
            new_size = old_size
            if amt == 0:
                new_size = get_options().font_size
            else:
                if increment_operation:
                    new_size += (1 if increment_operation == '+' else -1) * amt
                else:
                    new_size = amt
                new_size = max(MINIMUM_FONT_SIZE, min(new_size, get_options().font_size * 5))
            return new_size

        if all_windows:
            current_global_size = global_font_size()
            new_size = calc_new_size(current_global_size)
            if new_size != current_global_size:
                global_font_size(new_size)
            os_windows = list(self.os_window_map.keys())
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

    def _change_font_size(self, sz_map: Dict[int, float]) -> None:
        for os_window_id, sz in sz_map.items():
            tm = self.os_window_map.get(os_window_id)
            if tm is not None:
                os_window_font_size(os_window_id, sz)
                tm.resize()

    def on_dpi_change(self, os_window_id: int) -> None:
        tm = self.os_window_map.get(os_window_id)
        if tm is not None:
            sz = os_window_font_size(os_window_id)
            if sz:
                os_window_font_size(os_window_id, sz, True)
                for tab in tm:
                    for window in tab:
                        window.on_dpi_change(sz)
                tm.resize()

    def _set_os_window_background_opacity(self, os_window_id: int, opacity: float) -> None:
        change_background_opacity(os_window_id, max(0.1, min(opacity, 1.0)))

    @ac('win', '''
        Set the background opacity for the active OS Window

        For example::

            map f1 set_background_opacity +0.1
            map f2 set_background_opacity -0.1
            map f3 set_background_opacity 0.5
        ''')
    def set_background_opacity(self, opacity: str) -> None:
        window = self.active_window
        if window is None or not opacity:
            return
        if not get_options().dynamic_background_opacity:
            self.show_error(
                    _('Cannot change background opacity'),
                    _('You must set the dynamic_background_opacity option in kitty.conf to be able to change background opacity'))
            return
        os_window_id = window.os_window_id
        if opacity[0] in '+-':
            old_opacity = background_opacity_of(os_window_id)
            if old_opacity is None:
                return
            fin_opacity = old_opacity + float(opacity)
        elif opacity == 'default':
            fin_opacity = get_options().background_opacity
        else:
            fin_opacity = float(opacity)
        self._set_os_window_background_opacity(os_window_id, fin_opacity)

    @property
    def active_tab_manager(self) -> Optional[TabManager]:
        os_window_id = current_os_window()
        return None if os_window_id is None else self.os_window_map.get(os_window_id)

    @property
    def active_tab(self) -> Optional[Tab]:
        tm = self.active_tab_manager
        return None if tm is None else tm.active_tab

    @property
    def active_window(self) -> Optional[Window]:
        t = self.active_tab
        return None if t is None else t.active_window

    def set_pending_sequences(self, sequences: SubSequenceMap, default_pending_action: Optional[KeyAction] = None) -> None:
        self.pending_sequences = sequences
        self.default_pending_action = default_pending_action
        set_in_sequence_mode(True)

    def dispatch_possible_special_key(self, ev: KeyEvent) -> bool:
        # Handles shortcuts, return True if the key was consumed
        key_action = get_shortcut(self.keymap, ev)
        if key_action is None:
            sequences = get_shortcut(get_options().sequence_map, ev)
            if sequences and not isinstance(sequences, KeyAction):
                self.set_pending_sequences(sequences)
                return True
            if self.global_shortcuts_map and get_shortcut(self.global_shortcuts_map, ev):
                return True
        elif isinstance(key_action, KeyAction):
            return self.dispatch_action(key_action)
        return False

    def clear_pending_sequences(self) -> None:
        self.pending_sequences = self.default_pending_action = None
        set_in_sequence_mode(False)

    def process_sequence(self, ev: KeyEvent) -> None:
        if not self.pending_sequences:
            set_in_sequence_mode(False)
            return

        remaining = {}
        matched_action = None
        for seq, key_action in self.pending_sequences.items():
            if shortcut_matches(seq[0], ev):
                seq = seq[1:]
                if seq:
                    remaining[seq] = key_action
                else:
                    matched_action = key_action

        if remaining:
            self.pending_sequences = remaining
        else:
            matched_action = matched_action or self.default_pending_action
            self.clear_pending_sequences()
            if matched_action is not None:
                self.dispatch_action(matched_action)

    def cancel_current_visual_select(self) -> None:
        if self.current_visual_select:
            self.current_visual_select.cancel()
            self.current_visual_select = None

    def visual_window_select_action(
        self, tab: Tab,
        callback: Callable[[Optional[Tab], Optional[Window]], None],
        choose_msg: str,
        only_window_ids: Container[int] = (),
        reactivate_prev_tab: bool = False
    ) -> None:
        import string
        self.cancel_current_visual_select()
        initial_tab_id: Optional[int] = None
        initial_os_window_id = current_os_window()
        tm = tab.tab_manager_ref()
        if tm is not None:
            if tm.active_tab is not None:
                initial_tab_id = tm.active_tab.id
            tm.set_active_tab(tab)
        if initial_os_window_id != tab.os_window_id:
            focus_os_window(tab.os_window_id, True)
        self.current_visual_select = VisualSelect(tab.id, tab.os_window_id, initial_tab_id, initial_os_window_id, choose_msg, callback, reactivate_prev_tab)
        if tab.current_layout.only_active_window_visible:
            w = self.select_window_in_tab_using_overlay(tab, choose_msg, only_window_ids)
            self.current_visual_select.window_used_for_selection_id = 0 if w is None else w.id
            return
        pending_sequences: SubSequenceMap = {}
        fmap = get_name_to_functional_number_map()
        alphanumerics = get_options().visual_window_select_characters
        for idx, window in tab.windows.iter_windows_with_number(only_visible=True):
            if only_window_ids and window.id not in only_window_ids:
                continue
            ac = KeyAction('visual_window_select_action_trigger', (window.id,))
            if idx >= len(alphanumerics):
                break
            ch = alphanumerics[idx]
            window.screen.set_window_char(ch)
            self.current_visual_select.window_ids.append(window.id)
            for mods in (0, GLFW_MOD_CONTROL, GLFW_MOD_CONTROL | GLFW_MOD_SHIFT, GLFW_MOD_SUPER, GLFW_MOD_ALT, GLFW_MOD_SHIFT):
                pending_sequences[(SingleKey(mods=mods, key=ord(ch.lower())),)] = ac
                if ch in string.digits:
                    pending_sequences[(SingleKey(mods=mods, key=fmap[f'KP_{ch}']),)] = ac
        if len(self.current_visual_select.window_ids) > 1:
            self.set_pending_sequences(pending_sequences, default_pending_action=KeyAction('visual_window_select_action_trigger', (0,)))
            redirect_mouse_handling(True)
            self.mouse_handler = self.visual_window_select_mouse_handler
        else:
            self.visual_window_select_action_trigger(self.current_visual_select.window_ids[0] if self.current_visual_select.window_ids else 0)
            if get_options().enable_audio_bell:
                ring_bell()

    def visual_window_select_action_trigger(self, window_id: int = 0) -> None:
        if self.current_visual_select:
            self.current_visual_select.trigger(window_id)
        self.current_visual_select = None

    def visual_window_select_mouse_handler(self, ev: WindowSystemMouseEvent) -> None:
        tab = self.active_tab
        if ev.button == GLFW_MOUSE_BUTTON_LEFT and ev.action == GLFW_PRESS and ev.window_id:
            w = self.window_id_map.get(ev.window_id)
            if w is not None and tab is not None and w in tab:
                if self.current_visual_select and self.current_visual_select.tab_id == tab.id:
                    self.visual_window_select_action_trigger(w.id)
                else:
                    self.visual_window_select_action_trigger()
                return
        if ev.button > -1 and tab is not None:
            self.visual_window_select_action_trigger()

    def mouse_event(
        self, in_tab_bar: bool, window_id: int, action: int, modifiers: int, button: int,
        currently_pressed_button: int, x: float, y: float
    ) -> None:
        if self.mouse_handler is not None:
            ev = WindowSystemMouseEvent(in_tab_bar, window_id, action, modifiers, button, currently_pressed_button, x, y)
            self.mouse_handler(ev)

    def select_window_in_tab_using_overlay(self, tab: Tab, msg: str, only_window_ids: Container[int] = ()) -> Optional[Window]:
        windows = tuple((w.id, w.title) for i, w in tab.windows.iter_windows_with_number(only_visible=False)
                        if not only_window_ids or w.id in only_window_ids)
        if len(windows) < 1:
            self.visual_window_select_action_trigger(windows[0][0] if windows else 0)
            if get_options().enable_audio_bell:
                ring_bell()
            return None
        cvs = self.current_visual_select

        def chosen(ans: Union[None, int, str]) -> None:
            q = self.current_visual_select
            self.current_visual_select = None
            if cvs and q is cvs:
                q.trigger(ans if isinstance(ans, int) else 0)
        return self.choose_entry(msg, windows, chosen)

    @ac('win', '''
        Resize the active window interactively

        See :ref:`window_resizing` for details.
        ''')
    def start_resizing_window(self) -> None:
        w = self.active_window
        if w is None:
            return
        overlay_window = self._run_kitten('resize_window', args=[
            f'--horizontal-increment={get_options().window_resize_step_cells}',
            f'--vertical-increment={get_options().window_resize_step_lines}'
        ])
        if overlay_window is not None:
            overlay_window.allow_remote_control = True

    def resize_layout_window(self, window: Window, increment: float, is_horizontal: bool, reset: bool = False) -> Union[bool, None, str]:
        tab = window.tabref()
        if tab is None or not increment:
            return False
        if reset:
            tab.reset_window_sizes()
            return None
        return tab.resize_window_by(window.id, increment, is_horizontal)

    def resize_os_window(self, os_window_id: int, width: int, height: int, unit: str, incremental: bool = False) -> None:
        if not incremental and (width < 0 or height < 0):
            return
        metrics = get_os_window_size(os_window_id)
        if metrics is None:
            return
        has_window_scaling = is_macos or is_wayland()
        w, h = get_new_os_window_size(metrics, width, height, unit, incremental, has_window_scaling)
        set_os_window_size(os_window_id, w, h)

    def default_bg_changed_for(self, window_id: int) -> None:
        w = self.window_id_map.get(window_id)
        if w is not None:
            tm = self.os_window_map.get(w.os_window_id)
            if tm is not None:
                tm.update_tab_bar_data()
                tm.mark_tab_bar_dirty()
                t = tm.tab_for_id(w.tab_id)
                if t is not None:
                    t.relayout_borders()

    def dispatch_action(
        self,
        key_action: KeyAction,
        window_for_dispatch: Optional[Window] = None,
        dispatch_type: str = 'KeyPress'
    ) -> bool:

        def report_match(f: Callable[..., Any]) -> None:
            if self.args.debug_keyboard:
                prefix = '\n' if dispatch_type == 'KeyPress' else ''
                print(f'{prefix}\x1b[35m{dispatch_type}\x1b[m matched action:', func_name(f), flush=True)

        if key_action is not None:
            f = getattr(self, key_action.func, None)
            if f is not None:
                report_match(f)
                passthrough = f(*key_action.args)
                if passthrough is not True:
                    return True
        if window_for_dispatch is None:
            tab = self.active_tab
            window = self.active_window
        else:
            window = window_for_dispatch
            tab = window.tabref()
        if tab is None or window is None:
            return False
        if key_action is not None:
            f = getattr(tab, key_action.func, getattr(window, key_action.func, None))
            if f is not None:
                passthrough = f(*key_action.args)
                report_match(f)
                if passthrough is not True:
                    return True
        return False

    @ac('misc', '''
        Combine multiple actions and map to a single keypress

        The syntax is::

            map key combine <separator> action1 <separator> action2 <separator> action3 ...

        For example::

            map kitty_mod+e combine : new_window : next_layout
        ''')
    def combine(self, *actions: KeyAction) -> None:
        for key_action in actions:
            self.dispatch_action(key_action)

    def on_focus(self, os_window_id: int, focused: bool) -> None:
        tm = self.os_window_map.get(os_window_id)
        if tm is not None:
            w = tm.active_window
            if w is not None:
                w.focus_changed(focused)
                if is_macos and focused:
                    cocoa_set_menubar_title(w.title or '')
            tm.mark_tab_bar_dirty()

    def on_activity_since_last_focus(self, window: Window) -> None:
        os_window_id = window.os_window_id
        tm = self.os_window_map.get(os_window_id)
        if tm is not None:
            tm.mark_tab_bar_dirty()

    def update_tab_bar_data(self, os_window_id: int) -> None:
        tm = self.os_window_map.get(os_window_id)
        if tm is not None:
            tm.update_tab_bar_data()

    def on_drop(self, os_window_id: int, mime: str, data: bytes) -> None:
        tm = self.os_window_map.get(os_window_id)
        if tm is not None:
            w = tm.active_window
            if w is not None:
                text = data.decode('utf-8', 'replace')
                if mime == 'text/uri-list':
                    text = '\n'.join(parse_uri_list(text))
                w.paste(text)

    @ac('win', 'Close the currently active OS Window')
    def close_os_window(self) -> None:
        tm = self.active_tab_manager
        if tm is not None:
            self.confirm_os_window_close(tm.os_window_id)

    def confirm_os_window_close(self, os_window_id: int) -> None:
        tm = self.os_window_map.get(os_window_id)
        q = get_options().confirm_os_window_close
        num = 0 if tm is None else (tm.number_of_windows_with_running_programs if q < 0 else tm.number_of_windows)
        needs_confirmation = tm is not None and q != 0 and num >= abs(q)
        if not needs_confirmation:
            self.mark_os_window_for_close(os_window_id)
            return
        if tm is not None:
            w = tm.active_window
            self._run_kitten('ask', ['--type=yesno', '--message', _(
                'Are you sure you want to close this OS window, it has {}'
                ' windows running?').format(num)],
                window=w,
                custom_callback=partial(self.handle_close_os_window_confirmation, os_window_id)
            )

    def handle_close_os_window_confirmation(self, os_window_id: int, data: Dict[str, Any], *a: Any) -> None:
        if data['response'] == 'y':
            self.mark_os_window_for_close(os_window_id)
        else:
            self.mark_os_window_for_close(os_window_id, NO_CLOSE_REQUESTED)

    def on_os_window_closed(self, os_window_id: int, viewport_width: int, viewport_height: int) -> None:
        self.cached_values['window-size'] = viewport_width, viewport_height
        tm = self.os_window_map.pop(os_window_id, None)
        if tm is not None:
            tm.destroy()
        for window_id in tuple(w.id for w in self.window_id_map.values() if getattr(w, 'os_window_id', None) == os_window_id):
            self.window_id_map.pop(window_id, None)
        if not self.os_window_map and is_macos:
            cocoa_set_menubar_title('')
        action = self.os_window_death_actions.pop(os_window_id, None)
        if action is not None:
            action()

    @ac('win', 'Quit, closing all windows')
    def quit(self, *args: Any) -> None:
        tm = self.active_tab
        num = 0
        x = get_options().confirm_os_window_close
        for q in self.os_window_map.values():
            num += q.number_of_windows_with_running_programs if x < 0 else q.number_of_windows
        needs_confirmation = tm is not None and x != 0 and num >= abs(x)
        if not needs_confirmation:
            set_application_quit_request(IMPERATIVE_CLOSE_REQUESTED)
            return
        if current_application_quit_request() == CLOSE_BEING_CONFIRMED:
            return
        assert tm is not None
        self._run_kitten('ask', ['--type=yesno', '--message', _(
            'Are you sure you want to quit kitty, it has {} windows running?').format(num)],
            window=tm.active_window,
            custom_callback=self.handle_quit_confirmation
        )
        set_application_quit_request(CLOSE_BEING_CONFIRMED)

    def handle_quit_confirmation(self, data: Dict[str, Any], *a: Any) -> None:
        set_application_quit_request(IMPERATIVE_CLOSE_REQUESTED if data['response'] == 'y' else NO_CLOSE_REQUESTED)

    def notify_on_os_window_death(self, address: str) -> None:
        import socket
        s = socket.socket(family=socket.AF_UNIX)
        with suppress(Exception):
            s.connect(address)
            s.sendall(b'c')
            with suppress(OSError):
                s.shutdown(socket.SHUT_RDWR)
            s.close()

    def display_scrollback(self, window: Window, data: Union[bytes, str], input_line_number: int = 0, title: str = '', report_cursor: bool = True) -> None:
        def prepare_arg(x: str) -> str:
            x = x.replace('INPUT_LINE_NUMBER', str(input_line_number))
            x = x.replace('CURSOR_LINE', str(window.screen.cursor.y + 1) if report_cursor else '0')
            x = x.replace('CURSOR_COLUMN', str(window.screen.cursor.x + 1) if report_cursor else '0')
            return x

        cmd = list(map(prepare_arg, get_options().scrollback_pager))
        if not os.path.isabs(cmd[0]):
            import shutil
            exe = shutil.which(cmd[0])
            if not exe:
                env = read_shell_environment(get_options())
                if env and 'PATH' in env:
                    exe = shutil.which(cmd[0], path=env['PATH'])
                    if exe:
                        cmd[0] = exe

        if os.path.basename(cmd[0]) == 'less':
            cmd.append('-+F')  # reset --quit-if-one-screen
        tab = self.active_tab
        if tab is not None:
            bdata = data.encode('utf-8') if isinstance(data, str) else data
            tab.new_special_window(
                SpecialWindow(cmd, bdata, title or _('History'), overlay_for=window.id, cwd=window.cwd_of_child),
                copy_colors_from=self.active_window
                )

    @ac('misc', 'Edit the kitty.conf config file in your favorite text editor')
    def edit_config_file(self, *a: Any) -> None:
        confpath = prepare_config_file_for_editing()
        # On macOS vim fails to handle SIGWINCH if it occurs early, so add a
        # small delay.
        cmd = [kitty_exe(), '+runpy', 'import os, sys, time; time.sleep(0.05); os.execvp(sys.argv[1], sys.argv[1:])'] + get_editor(get_options()) + [confpath]
        self.new_os_window(*cmd)

    def get_output(self, source_window: Window, num_lines: Optional[int] = 1) -> str:
        output = ''
        s = source_window.screen
        if num_lines is None:
            num_lines = s.lines
        for i in range(min(num_lines, s.lines)):
            output += str(s.linebuf.line(i))
        return output

    def _run_kitten(
        self,
        kitten: str,
        args: Iterable[str] = (),
        input_data: Optional[Union[bytes, str]] = None,
        window: Optional[Window] = None,
        custom_callback: Optional[Callable[[Dict[str, Any], int, 'Boss'], None]] = None,
        action_on_removal: Optional[Callable[[int, 'Boss'], None]] = None
    ) -> Any:
        orig_args, args = list(args), list(args)
        from kittens.runner import create_kitten_handler
        end_kitten = create_kitten_handler(kitten, orig_args)
        if window is None:
            w = self.active_window
            tab = self.active_tab
        else:
            w = window
            tab = w.tabref() if w else None
        if end_kitten.no_ui:
            return end_kitten(None, getattr(w, 'id', None), self)

        if w is not None and tab is not None:
            args[0:0] = [config_dir, kitten]
            if input_data is None:
                type_of_input = end_kitten.type_of_input
                if type_of_input in ('text', 'history', 'ansi', 'ansi-history', 'screen', 'screen-history', 'screen-ansi', 'screen-ansi-history'):
                    data: Optional[bytes] = w.as_text(
                            as_ansi='ansi' in type_of_input,
                            add_history='history' in type_of_input,
                            add_wrap_markers='screen' in type_of_input
                    ).encode('utf-8')
                elif type_of_input == 'selection':
                    sel = self.data_for_at(which='@selection', window=w)
                    data = sel.encode('utf-8') if sel else None
                elif type_of_input is None:
                    data = None
                elif type_of_input in ('first-output', 'first-output-screen', 'first-output-screen-ansi', 'first-output-ansi'):
                    q = type_of_input.split('-')
                    data = w.first_cmd_output_on_screen(as_ansi='ansi' in q, add_wrap_markers='screen' in q).encode('utf-8')
                elif type_of_input in ('output', 'output-screen', 'output-screen-ansi', 'output-ansi'):
                    q = type_of_input.split('-')
                    data = w.last_cmd_output(as_ansi='ansi' in q, add_wrap_markers='screen' in q).encode('utf-8')
                elif type_of_input in ('last-visited-output', 'last-visited-output-screen', 'last-visited-output-screen-ansi', 'last-visited-output-ansi'):
                    q = type_of_input.split('-')
                    data = w.last_visited_cmd_output(as_ansi='ansi' in q, add_wrap_markers='screen' in q).encode('utf-8')
                else:
                    raise ValueError(f'Unknown type_of_input: {type_of_input}')
            else:
                data = input_data if isinstance(input_data, bytes) else input_data.encode('utf-8')
            copts = common_opts_as_dict(get_options())
            final_args: List[str] = []
            for x in args:
                if x == '@selection':
                    sel = self.data_for_at(which='@selection', window=w)
                    if sel:
                        x = sel
                final_args.append(x)
            overlay_window = tab.new_special_window(
                SpecialWindow(
                    [kitty_exe(), '+runpy', 'from kittens.runner import main; main()'] + final_args,
                    stdin=data,
                    env={
                        'KITTY_COMMON_OPTS': json.dumps(copts),
                        'KITTY_CHILD_PID': str(w.child.pid),
                        'PYTHONWARNINGS': 'ignore',
                        'OVERLAID_WINDOW_LINES': str(w.screen.lines),
                        'OVERLAID_WINDOW_COLS': str(w.screen.columns),
                    },
                    cwd=w.cwd_of_child,
                    overlay_for=w.id
                ),
                copy_colors_from=w
            )
            wid = w.id
            overlay_window.actions_on_close.append(partial(self.on_kitten_finish, wid, custom_callback or end_kitten))
            if action_on_removal is not None:

                def callback_wrapper(*a: Any) -> None:
                    if action_on_removal is not None:
                        action_on_removal(wid, self)
                overlay_window.actions_on_removal.append(callback_wrapper)
            return overlay_window

    @ac('misc', 'Run the specified kitten. See :doc:`/kittens/custom` for details')
    def kitten(self, kitten: str, *args: str) -> None:
        import shlex
        cmdline = args[0] if args else ''
        kargs = shlex.split(cmdline) if cmdline else []
        self._run_kitten(kitten, kargs)

    def run_kitten(self, kitten: str, *args: str) -> None:
        self._run_kitten(kitten, args)

    def on_kitten_finish(self, target_window_id: int, end_kitten: Callable[[Dict[str, Any], int, 'Boss'], None], source_window: Window) -> None:
        output = self.get_output(source_window, num_lines=None)
        from kittens.runner import deserialize
        data = deserialize(output)
        if data is not None:
            end_kitten(data, target_window_id, self)

    @ac('misc', 'Input an arbitrary unicode character. See :doc:`/kittens/unicode-input` for details.')
    def input_unicode_character(self) -> None:
        self._run_kitten('unicode_input')

    @ac('tab', 'Change the title of the active tab')
    def set_tab_title(self) -> None:
        tab = self.active_tab
        if tab:
            args = ['--name=tab-title', '--message', _('Enter the new title for this tab below.'), 'do_set_tab_title', str(tab.id)]
            self._run_kitten('ask', args)

    def do_set_tab_title(self, title: str, tab_id: int) -> None:
        tm = self.active_tab_manager
        if tm is not None and title:
            tab_id = int(tab_id)
            for tab in tm.tabs:
                if tab.id == tab_id:
                    tab.set_title(title)
                    break

    def show_error(self, title: str, msg: str) -> None:
        self._run_kitten('show_error', args=['--title', title], input_data=msg)

    @ac('mk', 'Create a new marker')
    def create_marker(self) -> None:
        w = self.active_window
        if w:
            spec = None

            def done(data: Dict[str, Any], target_window_id: int, self: Boss) -> None:
                nonlocal spec
                spec = data['response']

            def done2(target_window_id: int, self: Boss) -> None:
                w = self.window_id_map.get(target_window_id)
                if w is not None and spec:
                    try:
                        w.set_marker(spec)
                    except Exception as err:
                        self.show_error(_('Invalid marker specification'), str(err))

            self._run_kitten('ask', [
                '--name=create-marker', '--message',
                _('Create marker, for example:\ntext 1 ERROR\nSee {}\n').format(website_url('marks'))
                ],
                custom_callback=done, action_on_removal=done2)

    @ac('misc', 'Run the kitty shell to control kitty with commands')
    def kitty_shell(self, window_type: str = 'window') -> None:
        kw: Dict[str, Any] = {}
        cmd = [kitty_exe(), '@']
        aw = self.active_window
        if aw is not None:
            kw['env'] = {'KITTY_SHELL_ACTIVE_WINDOW_ID': str(aw.id)}
        if window_type == 'tab':
            tab = self._new_tab(SpecialWindow(cmd, **kw))
            if tab is not None:
                for w in tab:
                    w.allow_remote_control = True
        elif window_type == 'os_window':
            os_window_id = self._new_os_window(SpecialWindow(cmd, **kw))
            for tab in self.os_window_map[os_window_id]:
                for w in tab:
                    w.allow_remote_control = True
        elif window_type == 'overlay':
            tab = self.active_tab
            if aw is not None and tab is not None:
                kw['overlay_for'] = aw.id
                tab.new_special_window(SpecialWindow(cmd, **kw), allow_remote_control=True)
        else:
            tab = self.active_tab
            if tab is not None:
                tab.new_special_window(SpecialWindow(cmd, **kw), allow_remote_control=True)

    def switch_focus_to(self, window_id: int) -> None:
        tab = self.active_tab
        if tab:
            tab.set_active_window(window_id)

    def open_url(self, url: str, program: Optional[Union[str, List[str]]] = None, cwd: Optional[str] = None) -> None:
        if not url:
            return
        if isinstance(program, str):
            program = to_cmdline(program)
        found_action = False
        if program is None:
            from .open_actions import actions_for_url
            actions = list(actions_for_url(url))
            if actions:
                found_action = True
                self.dispatch_action(actions.pop(0))
                if actions:
                    self.drain_actions(actions)
        if not found_action:
            open_url(url, program or get_options().open_url_with, cwd=cwd)

    @ac('misc', 'Click a URL using the keyboard')
    def open_url_with_hints(self) -> None:
        self._run_kitten('hints')

    def drain_actions(self, actions: List[KeyAction]) -> None:

        def callback(timer_id: Optional[int]) -> None:
            self.dispatch_action(actions.pop(0))
            if actions:
                self.drain_actions(actions)
        add_timer(callback, 0, False)

    def destroy(self) -> None:
        self.shutting_down = True
        self.child_monitor.shutdown_monitor()
        self.set_update_check_process()
        self.update_check_process = None
        del self.child_monitor
        for tm in self.os_window_map.values():
            tm.destroy()
        self.os_window_map = {}
        destroy_global_data()

    def paste_to_active_window(self, text: str) -> None:
        if text:
            w = self.active_window
            if w is not None:
                w.paste(text)

    @ac('cp', 'Paste from the clipboard to the active window')
    def paste_from_clipboard(self) -> None:
        text = get_clipboard_string()
        self.paste_to_active_window(text)

    def current_primary_selection(self) -> str:
        return get_primary_selection() if supports_primary_selection else ''

    def current_primary_selection_or_clipboard(self) -> str:
        return get_primary_selection() if supports_primary_selection else get_clipboard_string()

    @ac('cp', 'Paste from the clipboard to the active window')
    def paste_from_selection(self) -> None:
        text = self.current_primary_selection_or_clipboard()
        self.paste_to_active_window(text)

    def set_primary_selection(self) -> None:
        w = self.active_window
        if w is not None and not w.destroyed:
            text = w.text_for_selection()
            if text:
                set_primary_selection(text)
                if get_options().copy_on_select:
                    self.copy_to_buffer(get_options().copy_on_select)

    @ac('cp', '''
        Copy the selection from the active window to the specified buffer

        See :ref:`cpbuf` for details.
        ''')
    def copy_to_buffer(self, buffer_name: str) -> None:
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

    @ac('cp', '''
        Paste from the specified buffer to the active window

        See :ref:`cpbuf` for details.
        ''')
    def paste_from_buffer(self, buffer_name: str) -> None:
        if buffer_name == 'clipboard':
            text: Optional[str] = get_clipboard_string()
        elif buffer_name == 'primary':
            text = get_primary_selection()
        else:
            text = self.clipboard_buffers.get(buffer_name)
        if text:
            self.paste_to_active_window(text)

    @ac('tab', '''
        Go to the specified tab, by number, starting with 1

        Zero and negative numbers go to previously active tabs
        ''')
    def goto_tab(self, tab_num: int) -> None:
        tm = self.active_tab_manager
        if tm is not None:
            tm.goto_tab(tab_num - 1)

    def set_active_tab(self, tab: Tab) -> bool:
        tm = self.active_tab_manager
        if tm is not None:
            return tm.set_active_tab(tab)
        return False

    @ac('tab', 'Make the next tab active')
    def next_tab(self) -> None:
        tm = self.active_tab_manager
        if tm is not None:
            tm.next_tab()

    @ac('tab', 'Make the previous tab active')
    def previous_tab(self) -> None:
        tm = self.active_tab_manager
        if tm is not None:
            tm.next_tab(-1)

    prev_tab = previous_tab

    def process_stdin_source(
        self, window: Optional[Window] = None,
        stdin: Optional[str] = None, copy_pipe_data: Optional[Dict[str, Any]] = None
    ) -> Tuple[Optional[Dict[str, str]], Optional[bytes]]:
        w = window or self.active_window
        if not w:
            return None, None
        env = None
        input_data = None
        if stdin:
            add_wrap_markers = stdin.endswith('_wrap')
            if add_wrap_markers:
                stdin = stdin[:-len('_wrap')]
            stdin = data_for_at(w, stdin, add_wrap_markers=add_wrap_markers)
            if stdin is not None:
                pipe_data = w.pipe_data(stdin, has_wrap_markers=add_wrap_markers) if w else None
                if pipe_data:
                    if copy_pipe_data is not None:
                        copy_pipe_data.update(pipe_data)
                    env = {
                        'KITTY_PIPE_DATA':
                        '{scrolled_by}:{cursor_x},{cursor_y}:{lines},{columns}'.format(**pipe_data)
                    }
                input_data = stdin.encode('utf-8')
        return env, input_data

    def data_for_at(self, which: str, window: Optional[Window] = None, add_wrap_markers: bool = False) -> Optional[str]:
        window = window or self.active_window
        if not window:
            return None
        return data_for_at(window, which, add_wrap_markers=add_wrap_markers)

    def special_window_for_cmd(
        self, cmd: List[str],
        window: Optional[Window] = None,
        stdin: Optional[str] = None,
        cwd_from: Optional[int] = None,
        as_overlay: bool = False
    ) -> SpecialWindowInstance:
        w = window or self.active_window
        env, input_data = self.process_stdin_source(w, stdin)
        cmdline = []
        for arg in cmd:
            if arg == '@selection' and w:
                q = data_for_at(w, arg)
                if not q:
                    continue
                arg = q
            cmdline.append(arg)
        overlay_for = w.id if w and as_overlay else None
        return SpecialWindow(cmd, input_data, cwd_from=cwd_from, overlay_for=overlay_for, env=env)

    def run_background_process(
        self,
        cmd: List[str],
        cwd: Optional[str] = None,
        env: Optional[Dict[str, str]] = None,
        stdin: Optional[bytes] = None,
        cwd_from: Optional[int] = None
    ) -> None:
        import subprocess
        env = env or None
        if env:
            env_ = default_env().copy()
            env_.update(env)
            env = env_
        if cwd_from:
            with suppress(Exception):
                cwd = cwd_of_process(cwd_from)

        if stdin:
            r, w = safe_pipe(False)
            try:
                subprocess.Popen(cmd, env=env, stdin=r, cwd=cwd)
            except Exception:
                os.close(w)
            else:
                thread_write(w, stdin)
            finally:
                os.close(r)
        else:
            subprocess.Popen(cmd, env=env, cwd=cwd)

    def pipe(self, source: str, dest: str, exe: str, *args: str) -> Optional[Window]:
        cmd = [exe] + list(args)
        window = self.active_window
        cwd_from = window.child.pid_for_cwd if window else None

        def create_window() -> SpecialWindowInstance:
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
        elif dest in ('clipboard', 'primary'):
            env, stdin = self.process_stdin_source(stdin=source, window=window)
            if stdin:
                if dest == 'clipboard':
                    set_clipboard_string(stdin)
                else:
                    set_primary_selection(stdin)
        else:
            env, stdin = self.process_stdin_source(stdin=source, window=window)
            self.run_background_process(cmd, cwd_from=cwd_from, stdin=stdin, env=env)
        return None

    def args_to_special_window(self, args: Iterable[str], cwd_from: Optional[int] = None) -> SpecialWindowInstance:
        args = list(args)
        stdin = None
        w = self.active_window

        if args[0].startswith('@') and args[0] != '@':
            q = data_for_at(w, args[0]) or None
            if q is not None:
                stdin = q.encode('utf-8')
            del args[0]

        cmd = []
        for arg in args:
            if arg == '@selection':
                q = data_for_at(w, arg)
                if not q:
                    continue
                arg = q
            cmd.append(arg)
        return SpecialWindow(cmd, stdin, cwd_from=cwd_from)

    def _new_tab(self, args: Union[SpecialWindowInstance, Iterable[str]], cwd_from: Optional[int] = None, as_neighbor: bool = False) -> Optional[Tab]:
        special_window = None
        if args:
            if isinstance(args, SpecialWindowInstance):
                special_window = args
            else:
                special_window = self.args_to_special_window(args, cwd_from=cwd_from)
        tm = self.active_tab_manager
        if tm is not None:
            return tm.new_tab(special_window=special_window, cwd_from=cwd_from, as_neighbor=as_neighbor)
        return None

    def _create_tab(self, args: List[str], cwd_from: Optional[int] = None) -> None:
        as_neighbor = False
        if args and args[0].startswith('!'):
            as_neighbor = 'neighbor' in args[0][1:].split(',')
            args = args[1:]
        self._new_tab(args, as_neighbor=as_neighbor, cwd_from=cwd_from)

    @ac('tab', 'Create a new tab')
    def new_tab(self, *args: str) -> None:
        self._create_tab(list(args))

    @ac('tab', 'Create a new tab with working directory for the window in it set to the same as the active window')
    def new_tab_with_cwd(self, *args: str) -> None:
        w = self.active_window_for_cwd
        cwd_from = w.child.pid_for_cwd if w is not None else None
        self._create_tab(list(args), cwd_from=cwd_from)

    def new_tab_with_wd(self, wd: str) -> None:
        special_window = SpecialWindow(None, cwd=wd)
        self._new_tab(special_window)

    def _new_window(self, args: List[str], cwd_from: Optional[int] = None) -> Optional[Window]:
        tab = self.active_tab
        if tab is None:
            return None
        allow_remote_control = False
        location = None
        if args and args[0].startswith('!'):
            location = args[0][1:].lower()
            args = args[1:]
        if args and args[0] == '@':
            args = args[1:]
            allow_remote_control = True
        if args:
            return tab.new_special_window(
                self.args_to_special_window(args, cwd_from=cwd_from),
                location=location, allow_remote_control=allow_remote_control)
        else:
            return tab.new_window(cwd_from=cwd_from, location=location, allow_remote_control=allow_remote_control)

    @ac('win', 'Create a new window')
    def new_window(self, *args: str) -> None:
        self._new_window(list(args))

    @ac('win', 'Create a new window with working directory same as that of the active window')
    def new_window_with_cwd(self, *args: str) -> None:
        w = self.active_window_for_cwd
        if w is None:
            return self.new_window(*args)
        cwd_from = w.child.pid_for_cwd
        self._new_window(list(args), cwd_from=cwd_from)

    @ac('misc', '''
        Launch the specified program in a new window/tab/etc.

        See :doc:`launch` for details
        ''')
    def launch(self, *args: str) -> None:
        from kitty.launch import launch, parse_launch_args
        opts, args_ = parse_launch_args(args)
        launch(self, opts, args_)

    @ac('tab', 'Move the active tab forward')
    def move_tab_forward(self) -> None:
        tm = self.active_tab_manager
        if tm is not None:
            tm.move_tab(1)

    @ac('tab', 'Move the active tab backward')
    def move_tab_backward(self) -> None:
        tm = self.active_tab_manager
        if tm is not None:
            tm.move_tab(-1)

    @ac('misc', '''
        Turn on/off ligatures in the specified window

        See :opt:`disable_ligatures` for details
        ''')
    def disable_ligatures_in(self, where: Union[str, Iterable[Window]], strategy: int) -> None:
        if isinstance(where, str):
            windows: List[Window] = []
            if where == 'active':
                if self.active_window is not None:
                    windows = [self.active_window]
            elif where == 'all':
                windows = list(self.all_windows)
            elif where == 'tab':
                if self.active_tab is not None:
                    windows = list(self.active_tab)
        else:
            windows = list(where)
        for window in windows:
            window.screen.disable_ligatures = strategy
            window.refresh()

    def patch_colors(self, spec: Dict[str, Optional[int]], configured: bool = False) -> None:
        from kitty.rc.set_colors import nullable_colors
        opts = get_options()
        if configured:
            for k, v in spec.items():
                if hasattr(opts, k):
                    if v is None:
                        if k in nullable_colors:
                            setattr(opts, k, None)
                    else:
                        setattr(opts, k, color_from_int(v))
        for tm in self.all_tab_managers:
            tm.tab_bar.patch_colors(spec)
            tm.tab_bar.layout()
            tm.mark_tab_bar_dirty()
            t = tm.active_tab
            if t is not None:
                t.relayout_borders()
        patch_global_colors(spec, configured)

    def apply_new_options(self, opts: Options) -> None:
        from .fonts.box_drawing import set_scale

        # Update options storage
        set_options(opts, is_wayland(), self.args.debug_rendering, self.args.debug_font_fallback)
        apply_options_update()
        set_layout_options(opts)
        set_default_env(opts.env.copy())
        # Update font data
        set_scale(opts.box_drawing_scale)
        from .fonts.render import set_font_family
        set_font_family(opts, debug_font_matching=self.args.debug_font_fallback)
        for os_window_id, tm in self.os_window_map.items():
            if tm is not None:
                os_window_font_size(os_window_id, opts.font_size, True)
                tm.resize()
        # Update key bindings
        self.update_keymap()
        # Update misc options
        for tm in self.all_tab_managers:
            tm.apply_options()
        # Update colors
        for w in self.all_windows:
            self.default_bg_changed_for(w.id)
            w.refresh()

    @ac('misc', '''
        Reload the config file

        If mapped without arguments reloads the default config file, otherwise loads
        the specified config files, in order. Loading a config file *replaces* all
        config options. For example::

            map f5 load_config_file /path/to/some/kitty.conf
        ''')
    def load_config_file(self, *paths: str, apply_overrides: bool = True) -> None:
        from .config import load_config
        old_opts = get_options()
        paths = paths or old_opts.config_paths
        bad_lines: List[BadLine] = []
        opts = load_config(*paths, overrides=old_opts.config_overrides if apply_overrides else None, accumulate_bad_lines=bad_lines)
        if bad_lines:
            self.show_bad_config_lines(bad_lines)
        self.apply_new_options(opts)
        from .open_actions import load_open_actions
        load_open_actions.clear_cached()

    def safe_delete_temp_file(self, path: str) -> None:
        if is_path_in_temp_dir(path):
            with suppress(FileNotFoundError):
                os.remove(path)

    def set_update_check_process(self, process: Optional['PopenType[bytes]'] = None) -> None:
        if self.update_check_process is not None:
            with suppress(Exception):
                if self.update_check_process.poll() is None:
                    self.update_check_process.kill()
        self.update_check_process = process

    def on_monitored_pid_death(self, pid: int, exit_status: int) -> None:
        update_check_process = self.update_check_process
        if update_check_process is not None and pid == update_check_process.pid:
            self.update_check_process = None
            from .update_check import process_current_release
            try:
                assert update_check_process.stdout is not None
                raw = update_check_process.stdout.read().decode('utf-8')
            except Exception as e:
                log_error(f'Failed to read data from update check process, with error: {e}')
            else:
                try:
                    process_current_release(raw)
                except Exception as e:
                    log_error(f'Failed to process update check data {raw!r}, with error: {e}')

    def dbus_notification_callback(self, activated: bool, a: int, b: Union[int, str]) -> None:
        from .notify import (
            dbus_notification_activated, dbus_notification_created
        )
        if activated:
            assert isinstance(b, str)
            dbus_notification_activated(a, b)
        else:
            assert isinstance(b, int)
            dbus_notification_created(a, b)

    def show_bad_config_lines(self, bad_lines: Iterable[BadLine]) -> None:

        def format_bad_line(bad_line: BadLine) -> str:
            return f'{bad_line.number}:{bad_line.exception} in line: {bad_line.line}\n'

        msg = '\n'.join(map(format_bad_line, bad_lines)).rstrip()
        self.show_error(_('Errors in kitty.conf'), msg)

    @ac('misc', '''
        Change colors in the specified windows

        For details, see :ref:`at_set-colors`. For example::

            map f5 set_colors --configured /path/to/some/config/file/colors.conf
        ''')
    def set_colors(self, *args: str) -> None:
        from kitty.rc.base import (
            PayloadGetter, command_for_name, parse_subcommand_cli
        )
        from kitty.remote_control import parse_rc_args
        c = command_for_name('set_colors')
        try:
            opts, items = parse_subcommand_cli(c, ['set-colors'] + list(args))
        except (Exception, SystemExit) as err:
            self.show_error('Invalid set_colors mapping', str(err))
            return
        try:
            payload = c.message_to_kitty(parse_rc_args([])[0], opts, items)
        except (Exception, SystemExit) as err:
            self.show_error('Failed to set colors', str(err))
            return
        c.response_from_kitty(self, self.active_window, PayloadGetter(c, payload if isinstance(payload, dict) else {}))

    def _move_window_to(
        self,
        window: Optional[Window] = None,
        target_tab_id: Optional[Union[str, int]] = None,
        target_os_window_id: Optional[Union[str, int]] = None
    ) -> None:
        window = window or self.active_window
        if not window:
            return
        src_tab = self.tab_for_window(window)
        if src_tab is None:
            return
        if target_os_window_id == 'new':
            target_os_window_id = self.add_os_window()
            tm = self.os_window_map[target_os_window_id]
            target_tab = tm.new_tab(empty_tab=True)
        else:
            target_os_window_id = target_os_window_id or current_os_window()
            if isinstance(target_tab_id, str):
                if not isinstance(target_os_window_id, int):
                    q = self.active_tab_manager
                    assert q is not None
                    tm = q
                else:
                    tm = self.os_window_map[target_os_window_id]
                if target_tab_id == 'new':
                    target_tab = tm.new_tab(empty_tab=True)
                else:
                    target_tab = tm.tab_at_location(target_tab_id) or tm.new_tab(empty_tab=True)
            else:
                for tab in self.all_tabs:
                    if tab.id == target_tab_id:
                        target_tab = tab
                        target_os_window_id = tab.os_window_id
                        break
                else:
                    return

        for detached_window in src_tab.detach_window(window):
            target_tab.attach_window(detached_window)
        self._cleanup_tab_after_window_removal(src_tab)
        target_tab.make_active()

    def _move_tab_to(self, tab: Optional[Tab] = None, target_os_window_id: Optional[int] = None) -> None:
        tab = tab or self.active_tab
        if tab is None:
            return
        if target_os_window_id is None:
            target_os_window_id = self.add_os_window()
        tm = self.os_window_map[target_os_window_id]
        target_tab = tm.new_tab(empty_tab=True)
        target_tab.take_over_from(tab)
        self._cleanup_tab_after_window_removal(tab)
        target_tab.make_active()

    def choose_entry(
        self, title: str, entries: Iterable[Tuple[Union[_T, str, None], str]],
        callback: Callable[[Union[_T, str, None]], None]
    ) -> Optional[Window]:
        lines = [title, '']
        idx_map: List[Union[_T, str]] = []
        ans: Union[str, _T, None] = None
        fmt = ': {1}'

        for obj, text in entries:
            if obj is None:
                lines.append(text)
            else:
                idx_map.append(obj)
                lines.append(fmt.format(len(idx_map), text))

        def done(data: Dict[str, Any], target_window_id: int, self: Boss) -> None:
            nonlocal ans
            ans = idx_map[int(data['groupdicts'][0]['index'])]

        def done2(target_window_id: int, self: Boss) -> None:
            callback(ans)

        q = self._run_kitten(
            'hints', args=(
                '--ascending', '--customize-processing=::import::kitty.choose_entry',
                r'--regex=(?m)^:\s+.+$', '--window-title', title,
            ), input_data='\r\n'.join(lines).encode('utf-8'), custom_callback=done, action_on_removal=done2
        )
        return q if isinstance(q, Window) else None

    @ac('tab', 'Interactively select a tab to switch to')
    def select_tab(self) -> None:

        def chosen(ans: Union[None, str, int]) -> None:
            if isinstance(ans, int):
                for tab in self.all_tabs:
                    if tab.id == ans:
                        self.set_active_tab(tab)

        ct = self.active_tab
        self.choose_entry('Choose a tab to switch to', ((t.id, t.title) for t in self.all_tabs if t is not ct), chosen)

    @ac('win', '''
        Detach a window, moving it to another tab or OS Window

        See :ref:`detaching windows <detach_window>` for details.
        ''')
    def detach_window(self, *args: str) -> None:
        if not args or args[0] == 'new':
            return self._move_window_to(target_os_window_id='new')
        if args[0] in ('new-tab', 'tab-prev', 'tab-left', 'tab-right'):
            where = 'new' if args[0] == 'new-tab' else args[0][4:]
            return self._move_window_to(target_tab_id=where)
        ct = self.active_tab
        items: List[Tuple[Union[str, int], str]] = [(t.id, t.title) for t in self.all_tabs if t is not ct]
        items.append(('new_tab', 'New tab'))
        items.append(('new_os_window', 'New OS Window'))
        target_window = self.active_window

        def chosen(ans: Union[None, str, int]) -> None:
            if ans is not None:
                if isinstance(ans, str):
                    if ans == 'new_os_window':
                        self._move_window_to(target_os_window_id='new')
                    elif ans == 'new_tab':
                        self._move_window_to(target_tab_id=ans)
                else:
                    self._move_window_to(target_window, target_tab_id=ans)

        self.choose_entry('Choose a tab to move the window to', items, chosen)

    @ac('tab', '''
        Detach a tab, moving it to another OS Window

        See :ref:`detaching windows <detach_window>` for details.
        ''')
    def detach_tab(self, *args: str) -> None:
        if not args or args[0] == 'new':
            return self._move_tab_to()

        items: List[Tuple[Union[str, int], str]] = []
        ct = self.active_tab_manager
        for osw_id, tm in self.os_window_map.items():
            if tm is not ct and tm.active_tab:
                items.append((osw_id, tm.active_tab.title))
        items.append(('new', 'New OS Window'))
        target_tab = self.active_tab

        def chosen(ans: Union[None, int, str]) -> None:
            if ans is not None:
                os_window_id = None if isinstance(ans, str) else ans
                self._move_tab_to(tab=target_tab, target_os_window_id=os_window_id)

        self.choose_entry('Choose an OS window to move the tab to', items, chosen)

    def set_background_image(self, path: Optional[str], os_windows: Tuple[int, ...], configured: bool, layout: Optional[str], anchor: Optional[str]) -> None:
        set_background_image(path, os_windows, configured, layout, anchor)
        for os_window_id in os_windows:
            self.default_bg_changed_for(os_window_id)

    # Can be called with kitty -o "map f1 send_test_notification"
    def send_test_notification(self) -> None:
        from time import monotonic

        from .notify import notify
        now = monotonic()
        ident = f'test-notify-{now}'
        notify(f'Test {now}', f'At: {now}', identifier=ident, subtitle=f'Test subtitle {now}')

    def notification_activated(self, identifier: str, window_id: int, focus: bool, report: bool) -> None:
        w = self.window_id_map.get(window_id)
        if w is None:
            return
        if focus:
            self.set_active_window(w, switch_os_window_if_needed=True)
        if report:
            w.report_notification_activated(identifier)

    @ac('debug', 'Show the environment variables that the kitty process sees')
    def show_kitty_env_vars(self) -> None:
        w = self.active_window
        if w:
            output = '\n'.join(f'{k}={v}' for k, v in os.environ.items())
            self.display_scrollback(w, output, title=_('Current kitty env vars'), report_cursor=False)

    def open_file(self, path: str) -> None:
        if path == ":cocoa::application launched::":
            self.cocoa_application_launched = True
            return

        def new_os_window() -> None:
            self.new_os_window(path)

        if self.cocoa_application_launched or not self.os_window_map:
            return new_os_window()
        tab = self.active_tab
        if tab is None:
            return new_os_window()
        w = tab.active_window
        self.new_window(path)
        if w is not None:
            tab.remove_window(w)

    @ac('debug', 'Show the effective configuration kitty is running with')
    def debug_config(self) -> None:
        from .debug_config import debug_config
        w = self.active_window
        if w is not None:
            output = debug_config(get_options())
            set_clipboard_string(re.sub(r'\x1b.+?m', '', output))
            output += '\n\x1b[35mThis debug output has been copied to the clipboard\x1b[m'
            self.display_scrollback(w, output, title=_('Current kitty options'), report_cursor=False)

    @ac('misc', 'Discard this event completely ignoring it')
    def discard_event(self) -> None:
        pass
    mouse_discard_event = discard_event
