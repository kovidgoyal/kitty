#!/usr/bin/env python3
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2016, Kovid Goyal <kovid at kovidgoyal.net>

import json
import os
import sys
import weakref
from collections import deque
from enum import IntEnum
from functools import partial
from gettext import gettext as _
from itertools import chain
from typing import (
    Any, Callable, Deque, Dict, Iterable, List, Optional, Pattern, Sequence,
    Tuple, Union
)

from .child import ProcessDesc
from .cli_stub import CLIOptions
from .config import build_ansi_color_table
from .constants import appname, is_macos, wakeup
from .fast_data_types import (
    BGIMAGE_PROGRAM, BLIT_PROGRAM, CELL_BG_PROGRAM, CELL_FG_PROGRAM,
    CELL_PROGRAM, CELL_SPECIAL_PROGRAM, CURSOR_BEAM, CURSOR_BLOCK,
    CURSOR_UNDERLINE, DCS, DECORATION, DIM, GLFW_MOD_CONTROL,
    GRAPHICS_ALPHA_MASK_PROGRAM, GRAPHICS_PREMULT_PROGRAM, GRAPHICS_PROGRAM,
    MARK, MARK_MASK, NO_CURSOR_SHAPE, OSC, REVERSE, SCROLL_FULL, SCROLL_LINE,
    SCROLL_PAGE, STRIKETHROUGH, TINT_PROGRAM, KeyEvent, Screen, add_timer,
    add_window, cell_size_for_window, click_mouse_url, compile_program,
    encode_key_for_tty, get_boss, get_clipboard_string, get_options,
    init_cell_program, mouse_selection, pt_to_px, set_clipboard_string,
    set_titlebar_color, set_window_padding, set_window_render_data,
    update_window_title, update_window_visibility, viewport_for_window
)
from .keys import keyboard_mode_name
from .notify import NotificationCommand, handle_notification_cmd
from .options_stub import Options
from .rgb import to_color
from .terminfo import get_capabilities
from .types import MouseEvent, ScreenGeometry, WindowGeometry
from .typing import BossType, ChildType, EdgeLiteral, TabType, TypedDict
from .utils import (
    color_as_int, get_primary_selection, load_shaders, log_error, open_cmd,
    open_url, parse_color_set, read_shell_environment, sanitize_title,
    set_primary_selection
)

MatchPatternType = Union[Pattern[str], Tuple[Pattern[str], Optional[Pattern[str]]]]


class WindowDict(TypedDict):
    id: int
    is_focused: bool
    title: str
    pid: Optional[int]
    cwd: str
    cmdline: List[str]
    env: Dict[str, str]
    foreground_processes: List[ProcessDesc]
    is_self: bool
    lines: int
    columns: int


class PipeData(TypedDict):
    input_line_number: int
    scrolled_by: int
    cursor_x: int
    cursor_y: int
    lines: int
    columns: int
    text: str


class DynamicColor(IntEnum):
    default_fg, default_bg, cursor_color, highlight_fg, highlight_bg = range(1, 6)


DYNAMIC_COLOR_CODES = {
    10: DynamicColor.default_fg,
    11: DynamicColor.default_bg,
    12: DynamicColor.cursor_color,
    17: DynamicColor.highlight_bg,
    19: DynamicColor.highlight_fg,
}
DYNAMIC_COLOR_CODES.update({k+100: v for k, v in DYNAMIC_COLOR_CODES.items()})


class Watcher:

    def __call__(self, boss: BossType, window: 'Window', data: Dict[str, Any]) -> None:
        pass


class Watchers:

    on_resize: List[Watcher]
    on_close: List[Watcher]
    on_focus_change: List[Watcher]

    def __init__(self) -> None:
        self.on_resize = []
        self.on_close = []
        self.on_focus_change = []

    def add(self, others: 'Watchers') -> None:
        def merge(base: List[Watcher], other: List[Watcher]) -> None:
            for x in other:
                if x not in base:
                    base.append(x)
        merge(self.on_resize, others.on_resize)
        merge(self.on_close, others.on_close)
        merge(self.on_focus_change, others.on_focus_change)

    def clear(self) -> None:
        del self.on_close[:], self.on_resize[:], self.on_focus_change[:]

    def copy(self) -> 'Watchers':
        ans = Watchers()
        ans.on_close = self.on_close[:]
        ans.on_resize = self.on_resize[:]
        ans.on_focus_change = self.on_focus_change
        return ans

    @property
    def has_watchers(self) -> bool:
        return bool(self.on_close or self.on_resize or self.on_focus_change)


def call_watchers(windowref: Callable[[], Optional['Window']], which: str, data: Dict[str, Any]) -> None:

    def callback(timer_id: Optional[int]) -> None:
        w = windowref()
        if w is not None:
            watchers: List[Watcher] = getattr(w.watchers, which)
            w.call_watchers(watchers, data)

    add_timer(callback, 0, False)


def calculate_gl_geometry(window_geometry: WindowGeometry, viewport_width: int, viewport_height: int, cell_width: int, cell_height: int) -> ScreenGeometry:
    dx, dy = 2 * cell_width / viewport_width, 2 * cell_height / viewport_height
    xmargin = window_geometry.left / viewport_width
    ymargin = window_geometry.top / viewport_height
    xstart = -1 + 2 * xmargin
    ystart = 1 - 2 * ymargin
    return ScreenGeometry(xstart, ystart, window_geometry.xnum, window_geometry.ynum, dx, dy)


def as_text(
    screen: Screen,
    as_ansi: bool = False,
    add_history: bool = False,
    add_wrap_markers: bool = False,
    alternate_screen: bool = False,
    add_cursor: bool = False
) -> str:
    lines: List[str] = []
    add_history = add_history and not (screen.is_using_alternate_linebuf() ^ alternate_screen)
    if alternate_screen:
        f = screen.as_text_alternate
    else:
        f = screen.as_text_non_visual if add_history else screen.as_text
    f(lines.append, as_ansi, add_wrap_markers)
    ctext = ''
    if add_cursor:
        ctext += '\x1b[?25' + ('h' if screen.cursor_visible else 'l')
        ctext += f'\x1b[{screen.cursor.y + 1};{screen.cursor.x + 1}H'
        shape = screen.cursor.shape
        if shape == NO_CURSOR_SHAPE:
            ctext += '\x1b[?12' + ('h' if screen.cursor.blink else 'l')
        else:
            code = {CURSOR_BLOCK: 1, CURSOR_UNDERLINE: 3, CURSOR_BEAM: 5}[shape]
            if not screen.cursor.blink:
                code += 1
            ctext += f'\x1b[{code} q'

    if add_history:
        h: List[str] = []
        pht = screen.historybuf.pagerhist_as_text()
        if pht:
            h.append(pht)
        if h and (not as_ansi or not add_wrap_markers):
            sanitizer = text_sanitizer(as_ansi, add_wrap_markers)
            h = list(map(sanitizer, h))
        screen.historybuf.as_text(h.append, as_ansi, add_wrap_markers)
        if h:
            if not screen.linebuf.is_continued(0):
                h[-1] += '\n'
            if as_ansi:
                h[-1] += '\x1b[m'
        ans = ''.join(chain(h, lines))
        if ctext:
            ans += ctext
        return ans
    ans = ''.join(lines)
    if ctext:
        ans += ctext
    return ans


class LoadShaderPrograms:

    use_selection_fg = True

    def __call__(self, semi_transparent: bool = False) -> None:
        compile_program(BLIT_PROGRAM, *load_shaders('blit'))
        v, f = load_shaders('cell')

        for which, p in {
                'SIMPLE': CELL_PROGRAM,
                'BACKGROUND': CELL_BG_PROGRAM,
                'SPECIAL': CELL_SPECIAL_PROGRAM,
                'FOREGROUND': CELL_FG_PROGRAM,
        }.items():
            vv, ff = v.replace('WHICH_PROGRAM', which), f.replace('WHICH_PROGRAM', which)
            for gln, pyn in {
                    'REVERSE_SHIFT': REVERSE,
                    'STRIKE_SHIFT': STRIKETHROUGH,
                    'DIM_SHIFT': DIM,
                    'DECORATION_SHIFT': DECORATION,
                    'MARK_SHIFT': MARK,
                    'MARK_MASK': MARK_MASK,
            }.items():
                vv = vv.replace('{{{}}}'.format(gln), str(pyn), 1)
            if semi_transparent:
                vv = vv.replace('#define NOT_TRANSPARENT', '#define TRANSPARENT')
                ff = ff.replace('#define NOT_TRANSPARENT', '#define TRANSPARENT')
            if not load_shader_programs.use_selection_fg:
                vv = vv.replace('#define USE_SELECTION_FG', '#define DONT_USE_SELECTION_FG')
                ff = ff.replace('#define USE_SELECTION_FG', '#define DONT_USE_SELECTION_FG')
            compile_program(p, vv, ff)

        v, f = load_shaders('graphics')
        for which, p in {
                'SIMPLE': GRAPHICS_PROGRAM,
                'PREMULT': GRAPHICS_PREMULT_PROGRAM,
                'ALPHA_MASK': GRAPHICS_ALPHA_MASK_PROGRAM,
        }.items():
            ff = f.replace('ALPHA_TYPE', which)
            compile_program(p, v, ff)

        v, f = load_shaders('bgimage')
        compile_program(BGIMAGE_PROGRAM, v, f)
        v, f = load_shaders('tint')
        compile_program(TINT_PROGRAM, v, f)
        init_cell_program()


load_shader_programs = LoadShaderPrograms()


def setup_colors(screen: Screen, opts: Options) -> None:
    screen.color_profile.update_ansi_color_table(build_ansi_color_table(opts))
    cursor_text_color = opts.cursor_text_color or (12, 12, 12)
    cursor_text_color_as_bg = 3 if opts.cursor_text_color is None else 1
    sfg = (0, 0, 0) if opts.selection_foreground is None else opts.selection_foreground
    screen.color_profile.set_configured_colors(*map(color_as_int, (
        opts.foreground, opts.background, opts.cursor,
        cursor_text_color, (0, 0, cursor_text_color_as_bg),
        sfg, opts.selection_background)
    ))


def text_sanitizer(as_ansi: bool, add_wrap_markers: bool) -> Callable[[str], str]:
    pat = getattr(text_sanitizer, 'pat', None)
    if pat is None:
        import re
        pat = re.compile('\033\\[.*?m')
        setattr(text_sanitizer, 'pat', pat)

    ansi, wrap_markers = not as_ansi, not add_wrap_markers

    def remove_wrap_markers(line: str) -> str:
        return line.replace('\r', '')

    def remove_sgr(line: str) -> str:
        return str(pat.sub('', line))

    def remove_both(line: str) -> str:
        return str(pat.sub('', line.replace('\r', '')))

    if ansi:
        return remove_both if wrap_markers else remove_sgr
    return remove_wrap_markers


class EdgeWidths:
    left: Optional[float]
    top: Optional[float]
    right: Optional[float]
    bottom: Optional[float]

    def __init__(self, serialized: Optional[Dict[str, Optional[float]]] = None):
        if serialized is not None:
            self.left = serialized['left']
            self.right = serialized['right']
            self.top = serialized['top']
            self.bottom = serialized['bottom']
        else:
            self.left = self.top = self.right = self.bottom = None

    def serialize(self) -> Dict[str, Optional[float]]:
        return {'left': self.left, 'right': self.right, 'top': self.top, 'bottom': self.bottom}


class Window:

    def __init__(
        self,
        tab: TabType,
        child: ChildType,
        args: CLIOptions,
        override_title: Optional[str] = None,
        copy_colors_from: Optional['Window'] = None,
        watchers: Optional[Watchers] = None
    ):
        self.watchers = watchers or Watchers()
        self.current_mouse_event_button = 0
        self.prev_osc99_cmd = NotificationCommand()
        self.action_on_close: Optional[Callable] = None
        self.action_on_removal: Optional[Callable] = None
        self.current_marker_spec: Optional[Tuple[str, Union[str, Tuple[Tuple[int, str], ...]]]] = None
        self.pty_resized_once = False
        self.last_reported_pty_size = (-1, -1, -1, -1)
        self.needs_attention = False
        self.override_title = override_title
        self.default_title = os.path.basename(child.argv[0] or appname)
        self.child_title = self.default_title
        self.title_stack: Deque[str] = deque(maxlen=10)
        self.allow_remote_control = child.allow_remote_control
        self.id: int = add_window(tab.os_window_id, tab.id, self.title)
        self.margin = EdgeWidths()
        self.padding = EdgeWidths()
        if not self.id:
            raise Exception('No tab with id: {} in OS Window: {} was found, or the window counter wrapped'.format(tab.id, tab.os_window_id))
        self.tab_id = tab.id
        self.os_window_id = tab.os_window_id
        self.tabref: Callable[[], Optional[TabType]] = weakref.ref(tab)
        self.clipboard_control_buffers = {'p': '', 'c': ''}
        self.destroyed = False
        self.geometry: WindowGeometry = WindowGeometry(0, 0, 0, 0, 0, 0)
        self.needs_layout = True
        self.is_visible_in_layout: bool = True
        self.child = child
        cell_width, cell_height = cell_size_for_window(self.os_window_id)
        opts = get_options()
        self.screen: Screen = Screen(self, 24, 80, opts.scrollback_lines, cell_width, cell_height, self.id)
        if copy_colors_from is not None:
            self.screen.copy_colors_from(copy_colors_from.screen)
        else:
            setup_colors(self.screen, opts)

    def on_dpi_change(self, font_sz: float) -> None:
        self.update_effective_padding()

    def change_tab(self, tab: TabType) -> None:
        self.tab_id = tab.id
        self.os_window_id = tab.os_window_id
        self.tabref = weakref.ref(tab)

    def effective_margin(self, edge: EdgeLiteral, is_single_window: bool = False) -> int:
        q = getattr(self.margin, edge)
        if q is not None:
            return pt_to_px(q, self.os_window_id)
        opts = get_options()
        if is_single_window:
            q = getattr(opts.single_window_margin_width, edge)
            if q > -0.1:
                return pt_to_px(q, self.os_window_id)
        q = getattr(opts.window_margin_width, edge)
        return pt_to_px(q, self.os_window_id)

    def effective_padding(self, edge: EdgeLiteral) -> int:
        q = getattr(self.padding, edge)
        if q is not None:
            return pt_to_px(q, self.os_window_id)
        q = getattr(get_options().window_padding_width, edge)
        return pt_to_px(q, self.os_window_id)

    def update_effective_padding(self) -> None:
        set_window_padding(
            self.os_window_id, self.tab_id, self.id,
            self.effective_padding('left'), self.effective_padding('top'),
            self.effective_padding('right'), self.effective_padding('bottom'))

    def patch_edge_width(self, which: str, edge: EdgeLiteral, val: Optional[float]) -> None:
        q = self.padding if which == 'padding' else self.margin
        setattr(q, edge, val)
        if q is self.padding:
            self.update_effective_padding()

    def effective_border(self) -> int:
        val, unit = get_options().window_border_width
        if unit == 'pt':
            val = max(1 if val > 0 else 0, pt_to_px(val, self.os_window_id))
        else:
            val = round(val)
        return int(val)

    @property
    def title(self) -> str:
        return self.override_title or self.child_title

    def __repr__(self) -> str:
        return 'Window(title={}, id={})'.format(
                self.title, self.id)

    def as_dict(self, is_focused: bool = False, is_self: bool = False) -> WindowDict:
        return dict(
            id=self.id,
            is_focused=is_focused,
            title=self.override_title or self.title,
            pid=self.child.pid,
            cwd=self.child.current_cwd or self.child.cwd,
            cmdline=self.child.cmdline,
            env=self.child.environ,
            foreground_processes=self.child.foreground_processes,
            is_self=is_self,
            lines=self.screen.lines,
            columns=self.screen.columns,
        )

    def serialize_state(self) -> Dict[str, Any]:
        return {
            'version': 1,
            'id': self.id,
            'child_title': self.child_title,
            'override_title': self.override_title,
            'default_title': self.default_title,
            'title_stack': list(self.title_stack),
            'allow_remote_control': self.allow_remote_control,
            'cwd': self.child.current_cwd or self.child.cwd,
            'env': self.child.environ,
            'cmdline': self.child.cmdline,
            'margin': self.margin.serialize(),
            'padding': self.padding.serialize(),
        }

    @property
    def current_colors(self) -> Dict:
        return self.screen.color_profile.as_dict()

    def matches(self, field: str, pat: MatchPatternType) -> bool:
        if not pat:
            return False
        if field == 'env':
            assert isinstance(pat, tuple)
            key_pat, val_pat = pat
            for key, val in self.child.environ.items():
                if key_pat.search(key) is not None and (
                        val_pat is None or val_pat.search(val) is not None):
                    return True
            return False
        assert not isinstance(pat, tuple)

        if field in ('id', 'window_id'):
            return True if pat.pattern == str(self.id) else False
        if field == 'pid':
            return True if pat.pattern == str(self.child.pid) else False
        if field == 'title':
            return pat.search(self.override_title or self.title) is not None
        if field in 'cwd':
            return pat.search(self.child.current_cwd or self.child.cwd) is not None
        if field == 'cmdline':
            for x in self.child.cmdline:
                if pat.search(x) is not None:
                    return True
            return False
        return False

    def set_visible_in_layout(self, val: bool) -> None:
        val = bool(val)
        if val is not self.is_visible_in_layout:
            self.is_visible_in_layout = val
            update_window_visibility(self.os_window_id, self.tab_id, self.id, val)
            if val:
                self.refresh()

    def refresh(self) -> None:
        self.screen.mark_as_dirty()
        wakeup()

    def update_position(self, window_geometry: WindowGeometry) -> ScreenGeometry:
        central, tab_bar, vw, vh, cw, ch = viewport_for_window(self.os_window_id)
        self.screen_geometry = sg = calculate_gl_geometry(window_geometry, vw, vh, cw, ch)
        return sg

    def set_geometry(self, new_geometry: WindowGeometry) -> None:
        if self.destroyed:
            return
        if self.needs_layout or new_geometry.xnum != self.screen.columns or new_geometry.ynum != self.screen.lines:
            self.screen.resize(new_geometry.ynum, new_geometry.xnum)
            sg = self.update_position(new_geometry)
            self.needs_layout = False
            call_watchers(weakref.ref(self), 'on_resize', {'old_geometry': self.geometry, 'new_geometry': new_geometry})
        else:
            sg = self.update_position(new_geometry)
        current_pty_size = (
            self.screen.lines, self.screen.columns,
            max(0, new_geometry.right - new_geometry.left), max(0, new_geometry.bottom - new_geometry.top))
        if current_pty_size != self.last_reported_pty_size:
            get_boss().child_monitor.resize_pty(self.id, *current_pty_size)
            if not self.pty_resized_once:
                self.pty_resized_once = True
                self.child.mark_terminal_ready()
            self.last_reported_pty_size = current_pty_size

        self.geometry = g = new_geometry
        set_window_render_data(self.os_window_id, self.tab_id, self.id, sg.xstart, sg.ystart, sg.dx, sg.dy, self.screen, *g[:4])
        self.update_effective_padding()

    def contains(self, x: int, y: int) -> bool:
        g = self.geometry
        return g.left <= x <= g.right and g.top <= y <= g.bottom

    def close(self) -> None:
        get_boss().close_window(self)

    def send_text(self, *args: str) -> bool:
        mode = keyboard_mode_name(self.screen)
        required_mode_, text = args[-2:]
        required_mode = frozenset(required_mode_.split(','))
        if not required_mode & {mode, 'all'}:
            return True
        if not text:
            return True
        self.write_to_child(text)

    def write_to_child(self, data: Union[str, bytes]) -> None:
        if data:
            if get_boss().child_monitor.needs_write(self.id, data) is not True:
                log_error(f'Failed to write to child {self.id} as it does not exist')

    def title_updated(self) -> None:
        update_window_title(self.os_window_id, self.tab_id, self.id, self.title)
        t = self.tabref()
        if t is not None:
            t.title_changed(self)

    def set_title(self, title: Optional[str]) -> None:
        if title:
            title = sanitize_title(title)
        self.override_title = title or None
        self.title_updated()

    def desktop_notify(self, osc_code: int, raw_data: str) -> None:
        cmd = handle_notification_cmd(osc_code, raw_data, self.id, self.prev_osc99_cmd)
        if cmd is not None and osc_code == 99:
            self.prev_osc99_cmd = cmd

    # screen callbacks {{{
    def use_utf8(self, on: bool) -> None:
        get_boss().child_monitor.set_iutf8_winid(self.id, on)

    def on_mouse_event(self, event: Dict[str, Any]) -> bool:
        ev = MouseEvent(**event)
        self.current_mouse_event_button = ev.button
        action = get_options().mousemap.get(ev)
        if action is None:
            return False
        return get_boss().dispatch_action(action, window_for_dispatch=self, dispatch_type='MouseEvent')

    def open_url(self, url: str, hyperlink_id: int, cwd: Optional[str] = None) -> None:
        opts = get_options()
        if hyperlink_id:
            if not opts.allow_hyperlinks:
                return
            from urllib.parse import unquote, urlparse, urlunparse
            try:
                purl = urlparse(url)
            except Exception:
                return
            if (not purl.scheme or purl.scheme == 'file'):
                if purl.netloc:
                    from socket import gethostname
                    try:
                        hostname = gethostname()
                    except Exception:
                        hostname = ''
                    remote_hostname = purl.netloc.partition(':')[0]
                    if remote_hostname and remote_hostname != hostname and remote_hostname != 'localhost':
                        self.handle_remote_file(purl.netloc, unquote(purl.path))
                        return
                    url = urlunparse(purl._replace(netloc=''))
            if opts.allow_hyperlinks & 0b10:
                from kittens.tui.operations import styled
                get_boss()._run_kitten('ask', ['--type=choices', '--message', _(
                    'What would you like to do with this URL:\n') +
                    styled(unquote(url), fg='yellow'),
                    '--choice=o:Open', '--choice=c:Copy to clipboard', '--choice=n;red:Nothing'
                    ],
                    window=self,
                    custom_callback=partial(self.hyperlink_open_confirmed, url, cwd)
                )
                return
        get_boss().open_url(url, cwd=cwd)

    def hyperlink_open_confirmed(self, url: str, cwd: Optional[str], data: Dict[str, Any], *a: Any) -> None:
        q = data['response']
        if q == 'o':
            get_boss().open_url(url, cwd=cwd)
        elif q == 'c':
            set_clipboard_string(url)

    def handle_remote_file(self, netloc: str, remote_path: str) -> None:
        from kittens.ssh.main import get_connection_data
        args = self.child.foreground_cmdline
        conn_data = get_connection_data(args)
        if conn_data is None:
            get_boss().show_error('Could not handle remote file', 'No SSH connection data found in: {args}')
            return
        get_boss().run_kitten(
            'remote_file', '--hostname', netloc.partition(':')[0], '--path', remote_path,
            '--ssh-connection-data', json.dumps(conn_data)
        )

    def focus_changed(self, focused: bool) -> None:
        if self.destroyed:
            return
        call_watchers(weakref.ref(self), 'on_focus_change', {'focused': focused})
        self.screen.focus_changed(focused)
        if focused:
            changed = self.needs_attention
            self.needs_attention = False
            if changed:
                tab = self.tabref()
                if tab is not None:
                    tab.relayout_borders()

    def title_changed(self, new_title: Optional[str]) -> None:
        self.child_title = sanitize_title(new_title or self.default_title)
        if self.override_title is None:
            self.title_updated()

    def icon_changed(self, new_icon: object) -> None:
        pass  # TODO: Implement this

    @property
    def is_active(self) -> bool:
        return get_boss().active_window is self

    @property
    def has_activity_since_last_focus(self) -> bool:
        return self.screen.has_activity_since_last_focus()

    def on_activity_since_last_focus(self) -> None:
        if get_options().tab_activity_symbol:
            get_boss().on_activity_since_last_focus(self)

    def on_bell(self) -> None:
        cb = get_options().command_on_bell
        if cb and cb != ['none']:
            import shlex
            import subprocess
            env = self.child.final_env
            env['KITTY_CHILD_CMDLINE'] = ' '.join(map(shlex.quote, self.child.cmdline))
            subprocess.Popen(cb, env=env, cwd=self.child.foreground_cwd)
        if not self.is_active:
            changed = not self.needs_attention
            self.needs_attention = True
            tab = self.tabref()
            if tab is not None:
                if changed:
                    tab.relayout_borders()
                tab.on_bell(self)

    def change_titlebar_color(self) -> None:
        opts = get_options()
        val = opts.macos_titlebar_color if is_macos else opts.wayland_titlebar_color
        if val:
            if (val & 0xff) == 1:
                val = self.screen.color_profile.default_bg
            else:
                val = val >> 8
            set_titlebar_color(self.os_window_id, val)
        else:
            set_titlebar_color(self.os_window_id, 0, True)

    def change_colors(self, changes: Dict[DynamicColor, Optional[str]]) -> None:
        dirtied = default_bg_changed = False

        def item(raw: Optional[str]) -> Optional[int]:
            if raw is None:
                return 0
            val = to_color(raw)
            return None if val is None else (color_as_int(val) << 8) | 2

        for which, val_ in changes.items():
            val = item(val_)
            if val is None:
                continue
            dirtied = True
            setattr(self.screen.color_profile, which.name, val)
            if which.name == 'default_bg':
                default_bg_changed = True
        if dirtied:
            self.screen.mark_as_dirty()
        if default_bg_changed:
            get_boss().default_bg_changed_for(self.id)

    def report_color(self, code: str, r: int, g: int, b: int) -> None:
        r |= r << 8
        g |= g << 8
        b |= b << 8
        self.screen.send_escape_code_to_child(OSC, '{};rgb:{:04x}/{:04x}/{:04x}'.format(code, r, g, b))

    def report_notification_activated(self, identifier: str) -> None:
        self.screen.send_escape_code_to_child(OSC, f'99;i={identifier};')

    def set_dynamic_color(self, code: int, value: Union[str, bytes]) -> None:
        if isinstance(value, bytes):
            value = value.decode('utf-8')
        color_changes: Dict[DynamicColor, Optional[str]] = {}
        for val in value.split(';'):
            w = DYNAMIC_COLOR_CODES.get(code)
            if w is not None:
                if val == '?':
                    col = getattr(self.screen.color_profile, w.name)
                    self.report_color(str(code), col >> 16, (col >> 8) & 0xff, col & 0xff)
                else:
                    q = None if code >= 100 else val
                    color_changes[w] = q
            code += 1
        if color_changes:
            self.change_colors(color_changes)

    def set_color_table_color(self, code: int, value: str) -> None:
        cp = self.screen.color_profile
        if code == 4:
            changed = False
            for c, val in parse_color_set(value):
                if val is None:  # color query
                    self.report_color('4;{}'.format(c), *self.screen.color_profile.as_color((c << 8) | 1))
                else:
                    changed = True
                    cp.set_color(c, val)
            if changed:
                self.refresh()
        elif code == 104:
            if not value.strip():
                cp.reset_color_table()
            else:
                for x in value.split(';'):
                    try:
                        y = int(x)
                    except Exception:
                        continue
                    if 0 <= y <= 255:
                        cp.reset_color(y)
            self.refresh()

    def request_capabilities(self, q: str) -> None:
        for result in get_capabilities(q, get_options()):
            self.screen.send_escape_code_to_child(DCS, result)

    def handle_remote_cmd(self, cmd: str) -> None:
        get_boss().handle_remote_cmd(cmd, self)

    def handle_remote_print(self, msg: bytes) -> None:
        from base64 import standard_b64decode
        text = standard_b64decode(msg).decode('utf-8')
        print(text, end='', file=sys.stderr)
        sys.stderr.flush()

    def send_cmd_response(self, response: Any) -> None:
        self.screen.send_escape_code_to_child(DCS, '@kitty-cmd' + json.dumps(response))

    def clipboard_control(self, data: str) -> None:
        where, text = data.partition(';')[::2]
        if not where:
            where = 's0'
        cc = get_options().clipboard_control
        if text == '?':
            response = None
            if 's' in where or 'c' in where:
                response = get_clipboard_string() if 'read-clipboard' in cc else ''
                loc = 'c'
            elif 'p' in where:
                response = get_primary_selection() if 'read-primary' in cc else ''
                loc = 'p'
            response = response or ''
            from base64 import standard_b64encode
            self.screen.send_escape_code_to_child(OSC, '52;{};{}'.format(
                loc, standard_b64encode(response.encode('utf-8')).decode('ascii')))

        else:
            from base64 import standard_b64decode
            try:
                text = standard_b64decode(text).decode('utf-8')
            except Exception:
                text = ''

            def write(key: str, func: Callable[[str], None]) -> None:
                if text:
                    if ('no-append' in cc or
                            len(self.clipboard_control_buffers[key]) > 1024*1024):
                        self.clipboard_control_buffers[key] = ''
                    self.clipboard_control_buffers[key] += text
                else:
                    self.clipboard_control_buffers[key] = ''
                func(self.clipboard_control_buffers[key])

            if 's' in where or 'c' in where:
                if 'write-clipboard' in cc:
                    write('c', set_clipboard_string)
            if 'p' in where:
                if cc == 'clipboard':
                    if 'write-clipboard' in cc:
                        write('c', set_clipboard_string)
                if 'write-primary' in cc:
                    write('p', set_primary_selection)

    def manipulate_title_stack(self, pop: bool, title: str, icon: Any) -> None:
        if title:
            if pop:
                if self.title_stack:
                    self.child_title = self.title_stack.pop()
                    self.title_updated()
            else:
                if self.child_title:
                    self.title_stack.append(self.child_title)
    # }}}

    # mouse actions {{{
    def mouse_click_url(self) -> None:
        click_mouse_url(self.os_window_id, self.tab_id, self.id)

    def mouse_click_url_or_select(self) -> None:
        if not self.screen.has_selection():
            self.mouse_click_url()

    def mouse_selection(self, code: int) -> None:
        mouse_selection(self.os_window_id, self.tab_id, self.id, code, self.current_mouse_event_button)

    def paste_selection(self) -> None:
        txt = get_boss().current_primary_selection()
        if txt:
            self.paste(txt)

    def paste_selection_or_clipboard(self) -> None:
        txt = get_boss().current_primary_selection_or_clipboard()
        if txt:
            self.paste(txt)
    # }}}

    def text_for_selection(self) -> str:
        lines = self.screen.text_for_selection()
        sts = get_options().strip_trailing_spaces
        if sts == 'always' or (
                sts == 'smart' and not self.screen.is_rectangle_select()):
            return ''.join((ln.rstrip() or '\n') for ln in lines)
        return ''.join(lines)

    def call_watchers(self, which: Iterable[Watcher], data: Dict[str, Any]) -> None:
        boss = get_boss()
        for w in which:
            try:
                w(boss, self, data)
            except Exception:
                import traceback
                traceback.print_exc()

    def destroy(self) -> None:
        self.call_watchers(self.watchers.on_close, {})
        self.destroyed = True
        if hasattr(self, 'screen'):
            # Remove cycles so that screen is de-allocated immediately
            self.screen.reset_callbacks()
            del self.screen

    def as_text(
        self,
        as_ansi: bool = False,
        add_history: bool = False,
        add_wrap_markers: bool = False,
        alternate_screen: bool = False,
        add_cursor: bool = False
    ) -> str:
        return as_text(self.screen, as_ansi, add_history, add_wrap_markers, alternate_screen, add_cursor)

    @property
    def cwd_of_child(self) -> Optional[str]:
        return self.child.foreground_cwd or self.child.current_cwd

    def pipe_data(self, text: str, has_wrap_markers: bool = False) -> PipeData:
        text = text or ''
        if has_wrap_markers:
            text = text.replace('\r\n', '\n').replace('\r', '\n')
        lines = text.count('\n')
        input_line_number = (lines - (self.screen.lines - 1) - self.screen.scrolled_by)
        return {
            'input_line_number': input_line_number,
            'scrolled_by': self.screen.scrolled_by,
            'cursor_x': self.screen.cursor.x + 1,
            'cursor_y': self.screen.cursor.y + 1,
            'lines': self.screen.lines,
            'columns': self.screen.columns,
            'text': text
        }

    # actions {{{

    def show_scrollback(self) -> None:
        text = self.as_text(as_ansi=True, add_history=True, add_wrap_markers=True)
        data = self.pipe_data(text, has_wrap_markers=True)

        def prepare_arg(x: str) -> str:
            x = x.replace('INPUT_LINE_NUMBER', str(data['input_line_number']))
            x = x.replace('CURSOR_LINE', str(data['cursor_y']))
            x = x.replace('CURSOR_COLUMN', str(data['cursor_x']))
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
        bdata: Union[str, bytes, None] = data['text']
        if isinstance(bdata, str):
            bdata = bdata.encode('utf-8')
        get_boss().display_scrollback(self, bdata, cmd)

    def paste_bytes(self, text: Union[str, bytes]) -> None:
        # paste raw bytes without any processing
        if isinstance(text, str):
            text = text.encode('utf-8')
        self.screen.paste_bytes(text)

    def paste(self, text: Union[str, bytes]) -> None:
        if text and not self.destroyed:
            if isinstance(text, str):
                text = text.encode('utf-8')
            if self.screen.in_bracketed_paste_mode:
                while True:
                    new_text = text.replace(b'\033[201~', b'').replace(b'\x9b201~', b'')
                    if len(text) == len(new_text):
                        break
                    text = new_text
            else:
                # Workaround for broken editors like nano that cannot handle
                # newlines in pasted text see https://github.com/kovidgoyal/kitty/issues/994
                text = text.replace(b'\r\n', b'\n').replace(b'\n', b'\r')
            self.screen.paste(text)

    def copy_to_clipboard(self) -> None:
        text = self.text_for_selection()
        if text:
            set_clipboard_string(text)

    def encoded_key(self, key_event: KeyEvent) -> bytes:
        return encode_key_for_tty(
            key=key_event.key, shifted_key=key_event.shifted_key, alternate_key=key_event.alternate_key,
            mods=key_event.mods, action=key_event.action, text=key_event.text,
            key_encoding_flags=self.screen.current_key_encoding_flags(),
            cursor_key_mode=self.screen.cursor_key_mode,
        ).encode('ascii')

    def copy_or_interrupt(self) -> None:
        text = self.text_for_selection()
        if text:
            set_clipboard_string(text)
        else:
            self.write_to_child(self.encoded_key(KeyEvent(key=ord('c'), mods=GLFW_MOD_CONTROL)))

    def copy_and_clear_or_interrupt(self) -> None:
        self.copy_or_interrupt()
        self.screen.clear_selection()

    def pass_selection_to_program(self, *args: str) -> None:
        cwd = self.cwd_of_child
        text = self.text_for_selection()
        if text:
            if args:
                open_cmd(args, text, cwd=cwd)
            else:
                open_url(text, cwd=cwd)

    def scroll_line_up(self) -> None:
        if self.screen.is_main_linebuf():
            self.screen.scroll(SCROLL_LINE, True)

    def scroll_line_down(self) -> None:
        if self.screen.is_main_linebuf():
            self.screen.scroll(SCROLL_LINE, False)

    def scroll_page_up(self) -> None:
        if self.screen.is_main_linebuf():
            self.screen.scroll(SCROLL_PAGE, True)

    def scroll_page_down(self) -> None:
        if self.screen.is_main_linebuf():
            self.screen.scroll(SCROLL_PAGE, False)

    def scroll_home(self) -> None:
        if self.screen.is_main_linebuf():
            self.screen.scroll(SCROLL_FULL, True)

    def scroll_end(self) -> None:
        if self.screen.is_main_linebuf():
            self.screen.scroll(SCROLL_FULL, False)

    def toggle_marker(self, ftype: str, spec: Union[str, Tuple[Tuple[int, str], ...]], flags: int) -> None:
        from .marks import marker_from_spec
        key = ftype, spec
        if key == self.current_marker_spec:
            self.remove_marker()
            return
        self.screen.set_marker(marker_from_spec(ftype, spec, flags))
        self.current_marker_spec = key

    def set_marker(self, spec: Union[str, Sequence[str]]) -> None:
        from .config import parse_marker_spec, toggle_marker
        from .marks import marker_from_spec
        if isinstance(spec, str):
            func, (ftype, spec_, flags) = toggle_marker('toggle_marker', spec)
        else:
            ftype, spec_, flags = parse_marker_spec(spec[0], spec[1:])
        key = ftype, spec_
        self.screen.set_marker(marker_from_spec(ftype, spec_, flags))
        self.current_marker_spec = key

    def remove_marker(self) -> None:
        if self.current_marker_spec is not None:
            self.screen.set_marker()
            self.current_marker_spec = None

    def scroll_to_mark(self, prev: bool = True, mark: int = 0) -> None:
        self.screen.scroll_to_next_mark(mark, prev)

    def signal_child(self, *signals: int) -> None:
        pid = self.child.pid_for_cwd
        if pid is not None:
            for sig in signals:
                os.kill(pid, sig)
    # }}}
