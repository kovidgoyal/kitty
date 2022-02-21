#!/usr/bin/env python3
# License: GPL v3 Copyright: 2016, Kovid Goyal <kovid at kovidgoyal.net>

import json
import os
import re
import sys
import weakref
from collections import deque
from enum import IntEnum
from functools import partial
from gettext import gettext as _
from itertools import chain
from time import monotonic
from typing import (
    TYPE_CHECKING, Any, Callable, Deque, Dict, Iterable, List, NamedTuple,
    Optional, Pattern, Sequence, Tuple, Union
)

from .child import ProcessDesc
from .cli_stub import CLIOptions
from .config import build_ansi_color_table
from .constants import appname, is_macos, wakeup
from .fast_data_types import (
    BGIMAGE_PROGRAM, BLIT_PROGRAM, CELL_BG_PROGRAM, CELL_FG_PROGRAM,
    CELL_PROGRAM, CELL_SPECIAL_PROGRAM, CURSOR_BEAM, CURSOR_BLOCK,
    CURSOR_UNDERLINE, DCS, DECORATION, DECORATION_MASK, DIM, GLFW_MOD_CONTROL,
    GRAPHICS_ALPHA_MASK_PROGRAM, GRAPHICS_PREMULT_PROGRAM, GRAPHICS_PROGRAM,
    MARK, MARK_MASK, NO_CURSOR_SHAPE, NUM_UNDERLINE_STYLES, OSC, REVERSE,
    SCROLL_FULL, SCROLL_LINE, SCROLL_PAGE, STRIKETHROUGH, TINT_PROGRAM, Color,
    KeyEvent, Screen, add_timer, add_window, cell_size_for_window,
    click_mouse_cmd_output, click_mouse_url, compile_program,
    current_os_window, encode_key_for_tty, get_boss, get_click_interval,
    get_clipboard_string, get_options, init_cell_program, mark_os_window_dirty,
    mouse_selection, move_cursor_to_mouse_if_in_prompt, pt_to_px,
    set_clipboard_string, set_titlebar_color, set_window_logo,
    set_window_padding, set_window_render_data, update_ime_position_for_window,
    update_window_title, update_window_visibility
)
from .keys import keyboard_mode_name, mod_mask
from .notify import NotificationCommand, handle_notification_cmd
from .options.types import Options
from .rgb import to_color
from .terminfo import get_capabilities
from .types import MouseEvent, WindowGeometry, ac
from .typing import BossType, ChildType, EdgeLiteral, TabType, TypedDict
from .utils import (
    get_primary_selection, kitty_ansi_sanitizer_pat, load_shaders, log_error,
    open_cmd, open_url, parse_color_set, resolve_custom_file, sanitize_title,
    set_primary_selection
)

MatchPatternType = Union[Pattern[str], Tuple[Pattern[str], Optional[Pattern[str]]]]


if TYPE_CHECKING:
    from .file_transmission import FileTransmission


def process_title_from_child(title: str, is_base64: bool) -> str:
    if is_base64:
        from base64 import standard_b64decode
        try:
            title = standard_b64decode(title).decode('utf-8', 'replace')
        except Exception:
            title = 'undecodeable title'
    return sanitize_title(title)


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


class ClipboardPending(NamedTuple):
    where: str
    data: str
    truncated: bool = False


class DynamicColor(IntEnum):
    default_fg, default_bg, cursor_color, highlight_fg, highlight_bg = range(1, 6)


class CommandOutput(IntEnum):
    last_run, first_on_screen, last_visited = 0, 1, 2


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
        ans.on_focus_change = self.on_focus_change[:]
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


def pagerhist(screen: Screen, as_ansi: bool = False, add_wrap_markers: bool = True, upto_output_start: bool = False) -> str:
    pht = screen.historybuf.pagerhist_as_text(upto_output_start)
    if pht and (not as_ansi or not add_wrap_markers):
        sanitizer = text_sanitizer(as_ansi, add_wrap_markers)
        pht = sanitizer(pht)
    return pht


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
        pht = pagerhist(screen, as_ansi, add_wrap_markers)
        h: List[str] = [pht] if pht else []
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


def multi_replace(src: str, **replacements: Any) -> str:
    r = {k: str(v) for k, v in replacements.items()}

    def sub(m: 're.Match[str]') -> str:
        return r.get(m.group(1), m.group(1))

    return re.sub(r'\{([A-Z_]+)\}', sub, src)


class LoadShaderPrograms:

    def __call__(self, semi_transparent: bool = False) -> None:
        compile_program(BLIT_PROGRAM, *load_shaders('blit'))
        v, f = load_shaders('cell')

        for which, p in {
                'SIMPLE': CELL_PROGRAM,
                'BACKGROUND': CELL_BG_PROGRAM,
                'SPECIAL': CELL_SPECIAL_PROGRAM,
                'FOREGROUND': CELL_FG_PROGRAM,
        }.items():
            ff = f.replace('{WHICH_PROGRAM}', which)
            vv = multi_replace(
                v,
                WHICH_PROGRAM=which,
                REVERSE_SHIFT=REVERSE,
                STRIKE_SHIFT=STRIKETHROUGH,
                DIM_SHIFT=DIM,
                DECORATION_SHIFT=DECORATION,
                MARK_SHIFT=MARK,
                MARK_MASK=MARK_MASK,
                DECORATION_MASK=DECORATION_MASK,
                STRIKE_SPRITE_INDEX=NUM_UNDERLINE_STYLES + 1,
            )
            if semi_transparent:
                vv = vv.replace('#define NOT_TRANSPARENT', '#define TRANSPARENT')
                ff = ff.replace('#define NOT_TRANSPARENT', '#define TRANSPARENT')
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

    def s(c: Optional[Color]) -> int:
        return 0 if c is None else (0xff000000 | int(c))
    screen.color_profile.set_configured_colors(
        s(opts.foreground), s(opts.background),
        s(opts.cursor), s(opts.cursor_text_color),
        s(opts.selection_foreground), s(opts.selection_background),
        s(opts.visual_bell_color)
    )


def text_sanitizer(as_ansi: bool, add_wrap_markers: bool) -> Callable[[str], str]:
    pat = kitty_ansi_sanitizer_pat()
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


def cmd_output(screen: Screen, which: CommandOutput = CommandOutput.last_run, as_ansi: bool = False, add_wrap_markers: bool = False) -> str:
    lines: List[str] = []
    search_in_pager_hist = screen.cmd_output(which, lines.append, as_ansi, add_wrap_markers)
    if search_in_pager_hist:
        pht = pagerhist(screen, as_ansi, add_wrap_markers, True)
        if pht:
            lines.insert(0, pht)
    return ''.join(lines)


def process_remote_print(msg: bytes) -> str:
    from base64 import standard_b64decode
    from .cli import green
    text = standard_b64decode(msg).decode('utf-8', 'replace')
    return text.replace('\x1b', green(r'\e')).replace('\a', green(r'\a')).replace('\0', green(r'\0'))


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


class GlobalWatchers:

    def __init__(self) -> None:
        self.options_spec: Optional[Dict[str, str]] = None
        self.ans = Watchers()
        self.extra = ''

    def __call__(self) -> Watchers:
        spec = get_options().watcher
        if spec == self.options_spec:
            return self.ans
        from .launch import load_watch_modules
        if self.extra:
            spec = spec.copy()
            spec[self.extra] = self.extra
        self.ans = load_watch_modules(spec.keys()) or self.ans
        self.options_spec = spec.copy()
        return self.ans

    def set_extra(self, extra: str) -> None:
        self.extra = extra


global_watchers = GlobalWatchers()


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
        if watchers:
            self.watchers = watchers
            self.watchers.add(global_watchers())
        else:
            self.watchers = global_watchers().copy()
        self.last_focused_at = 0.
        self.started_at = monotonic()
        self.current_mouse_event_button = 0
        self.current_clipboard_read_ask: Optional[bool] = None
        self.prev_osc99_cmd = NotificationCommand()
        self.actions_on_close: List[Callable[['Window'], None]] = []
        self.actions_on_removal: List[Callable[['Window'], None]] = []
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
            raise Exception(f'No tab with id: {tab.id} in OS Window: {tab.os_window_id} was found, or the window counter wrapped')
        self.tab_id = tab.id
        self.os_window_id = tab.os_window_id
        self.tabref: Callable[[], Optional[TabType]] = weakref.ref(tab)
        self.clipboard_pending: Optional[ClipboardPending] = None
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

    @property
    def file_transmission_control(self) -> 'FileTransmission':
        ans: Optional['FileTransmission'] = getattr(self, '_file_transmission', None)
        if ans is None:
            from .file_transmission import FileTransmission
            ans = self._file_transmission = FileTransmission(self.id)
        return ans

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

    def apply_options(self) -> None:
        opts = get_options()
        self.update_effective_padding()
        self.change_titlebar_color()
        setup_colors(self.screen, opts)

    @property
    def title(self) -> str:
        return self.override_title or self.child_title

    def __repr__(self) -> str:
        return f'Window(title={self.title}, id={self.id})'

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
    def current_colors(self) -> Dict[str, Optional[int]]:
        return self.screen.color_profile.as_dict()

    @property
    def at_prompt(self) -> bool:
        return self.screen.cursor_at_prompt()

    @property
    def has_running_program(self) -> bool:
        return not self.at_prompt

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

    def set_geometry(self, new_geometry: WindowGeometry) -> None:
        if self.destroyed:
            return
        if self.needs_layout or new_geometry.xnum != self.screen.columns or new_geometry.ynum != self.screen.lines:
            self.screen.resize(new_geometry.ynum, new_geometry.xnum)
            self.needs_layout = False
            call_watchers(weakref.ref(self), 'on_resize', {'old_geometry': self.geometry, 'new_geometry': new_geometry})
        current_pty_size = (
            self.screen.lines, self.screen.columns,
            max(0, new_geometry.right - new_geometry.left), max(0, new_geometry.bottom - new_geometry.top))
        update_ime_position = False
        if current_pty_size != self.last_reported_pty_size:
            get_boss().child_monitor.resize_pty(self.id, *current_pty_size)
            if not self.pty_resized_once:
                self.pty_resized_once = True
                self.child.mark_terminal_ready()
                update_ime_position = True
            self.last_reported_pty_size = current_pty_size
        else:
            mark_os_window_dirty(self.os_window_id)

        self.geometry = g = new_geometry
        set_window_render_data(self.os_window_id, self.tab_id, self.id, self.screen, *g[:4])
        self.update_effective_padding()
        if update_ime_position:
            update_ime_position_for_window(self.id, True)

    def contains(self, x: int, y: int) -> bool:
        g = self.geometry
        return g.left <= x <= g.right and g.top <= y <= g.bottom

    def close(self) -> None:
        get_boss().mark_window_for_close(self)

    @ac('misc', '''
        Send the specified text to the active window

        See :sc:`send_text <send_text>` for details.
        ''')
    def send_text(self, *args: str) -> bool:
        mode = keyboard_mode_name(self.screen)
        required_mode_, text = args[-2:]
        required_mode = frozenset(required_mode_.split(','))
        if not required_mode & {mode, 'all'}:
            return True
        if not text:
            return True
        self.write_to_child(text)
        return False

    @ac('debug', 'Show a dump of the current lines in the scrollback + screen with their line attributes')
    def dump_lines_with_attrs(self) -> None:
        strings: List[str] = []
        self.screen.dump_lines_with_attrs(strings.append)
        text = ''.join(strings)
        get_boss().display_scrollback(self, text, title='Dump of lines', report_cursor=False)

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
        if osc_code == 777:
            if not raw_data.startswith('notify;'):
                log_error(f'Ignoring unknown OSC 777: {raw_data}')
                return  # unknown OSC 777
            raw_data = raw_data[len('notify;'):]
        cmd = handle_notification_cmd(osc_code, raw_data, self.id, self.prev_osc99_cmd)
        if cmd is not None and osc_code == 99:
            self.prev_osc99_cmd = cmd

    # screen callbacks {{{
    def use_utf8(self, on: bool) -> None:
        get_boss().child_monitor.set_iutf8_winid(self.id, on)

    def on_mouse_event(self, event: Dict[str, Any]) -> bool:
        event['mods'] = event.get('mods', 0) & mod_mask
        ev = MouseEvent(**event)
        self.current_mouse_event_button = ev.button
        action = get_options().mousemap.get(ev)
        if action is None:
            return False
        return get_boss().combine(action, window_for_dispatch=self, dispatch_type='MouseEvent')

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
                get_boss().choose(
                    'What would you like to do with this URL:\n' + styled(unquote(url), fg='yellow'),
                    partial(self.hyperlink_open_confirmed, url, cwd),
                    'o:Open', 'c:Copy to clipboard', 'n;red:Nothing', default='o',
                    window=self,
                )
                return
        get_boss().open_url(url, cwd=cwd)

    def hyperlink_open_confirmed(self, url: str, cwd: Optional[str], q: str) -> None:
        if q == 'o':
            get_boss().open_url(url, cwd=cwd)
        elif q == 'c':
            set_clipboard_string(url)

    def handle_remote_file(self, netloc: str, remote_path: str) -> None:
        from kittens.ssh.main import get_connection_data
        args = self.child.foreground_cmdline
        conn_data = get_connection_data(args, self.child.foreground_cwd or self.child.current_cwd or '')
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
            self.last_focused_at = monotonic()
            update_ime_position_for_window(self.id)
            changed = self.needs_attention
            self.needs_attention = False
            if changed:
                tab = self.tabref()
                if tab is not None:
                    tab.relayout_borders()
        elif self.os_window_id == current_os_window():
            # Cancel IME composition after loses focus
            update_ime_position_for_window(self.id, False, True)

    def title_changed(self, new_title: Optional[str], is_base64: bool = False) -> None:
        self.child_title = process_title_from_child(new_title or self.default_title, is_base64)
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
        if val > 0:
            if (val & 0xff) == 1:
                val = self.screen.color_profile.default_bg
            else:
                val = val >> 8
            set_titlebar_color(self.os_window_id, val)
        else:
            set_titlebar_color(self.os_window_id, 0, True, -val)

    def change_colors(self, changes: Dict[DynamicColor, Optional[str]]) -> None:
        dirtied = default_bg_changed = False

        def item(raw: Optional[str]) -> int:
            if raw is None:
                return 0
            v = to_color(raw)
            if v is None:
                return 0
            return 0xff000000 | int(v)

        for which, val_ in changes.items():
            val = item(val_)
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
        self.screen.send_escape_code_to_child(OSC, f'{code};rgb:{r:04x}/{g:04x}/{b:04x}')

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
                    qc = self.screen.color_profile.as_color((c << 8) | 1)
                    assert qc is not None
                    self.report_color(f'4;{c}', qc.red, qc.green, qc.blue)
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

    def handle_remote_echo(self, msg: bytes) -> None:
        from base64 import standard_b64decode
        data = standard_b64decode(msg)
        self.write_to_child(data)

    def handle_remote_print(self, msg: bytes) -> None:
        text = process_remote_print(msg)
        print(text, end='', file=sys.stderr)
        sys.stderr.flush()

    def send_cmd_response(self, response: Any) -> None:
        self.screen.send_escape_code_to_child(DCS, '@kitty-cmd' + json.dumps(response))

    def file_transmission(self, data: str) -> None:
        self.file_transmission_control.handle_serialized_command(data)

    def clipboard_control(self, data: str, is_partial: bool = False) -> None:
        where, text = data.partition(';')[::2]
        if is_partial:
            if self.clipboard_pending is None:
                self.clipboard_pending = ClipboardPending(where, text)
            else:
                self.clipboard_pending = self.clipboard_pending._replace(data=self.clipboard_pending[1] + text)
                limit = get_options().clipboard_max_size
                if limit and len(self.clipboard_pending.data) > limit * 1024 * 1024:
                    log_error('Discarding part of too large OSC 52 paste request')
                    self.clipboard_pending = self.clipboard_pending._replace(data='', truncated=True)
            return

        if not where:
            if self.clipboard_pending is not None:
                text = self.clipboard_pending.data + text
                where = self.clipboard_pending.where
                try:
                    if self.clipboard_pending.truncated:
                        return
                finally:
                    self.clipboard_pending = None
            else:
                where = 's0'
        cc = get_options().clipboard_control
        if text == '?':
            response = None
            if 's' in where or 'c' in where:
                if 'read-clipboard-ask' in cc:
                    return self.ask_to_read_clipboard(False)
                response = get_clipboard_string() if 'read-clipboard' in cc else ''
                loc = 'c'
            elif 'p' in where:
                if 'read-primary-ask' in cc:
                    return self.ask_to_read_clipboard(True)
                response = get_primary_selection() if 'read-primary' in cc else ''
                loc = 'p'
            response = response or ''
            self.send_osc52(loc, response or '')

        else:
            from base64 import standard_b64decode
            try:
                text = standard_b64decode(text).decode('utf-8')
            except Exception:
                text = ''

            if 's' in where or 'c' in where:
                if 'write-clipboard' in cc:
                    set_clipboard_string(text)
            if 'p' in where:
                if 'write-primary' in cc:
                    set_primary_selection(text)
        self.clipboard_pending = None

    def send_osc52(self, loc: str, response: str) -> None:
        from base64 import standard_b64encode
        self.screen.send_escape_code_to_child(OSC, '52;{};{}'.format(
            loc, standard_b64encode(response.encode('utf-8')).decode('ascii')))

    def ask_to_read_clipboard(self, primary: bool = False) -> None:
        if self.current_clipboard_read_ask is not None:
            self.current_clipboard_read_ask = primary
            return
        self.current_clipboard_read_ask = primary
        get_boss().confirm(_(
            'A program running in this window wants to read from the system clipboard.'
            ' Allow it do so, once?'),
            self.handle_clipboard_confirmation, window=self,
        )

    def handle_clipboard_confirmation(self, confirmed: bool) -> None:
        try:
            loc = 'p' if self.current_clipboard_read_ask else 'c'
            response = ''
            if confirmed:
                response = get_primary_selection() if self.current_clipboard_read_ask else get_clipboard_string()
            self.send_osc52(loc, response)
        finally:
            self.current_clipboard_read_ask = None

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
    @ac('mouse', '''
        Handle a mouse click

        Try to perform the specified actions one after the other till one of them is successful.
        Supported actions are::

            selection - check for a selection and if one exists abort processing
            link - if a link exists under the mouse, click it
            prompt - if the mouse click happens at a shell prompt move the cursor to the mouse location

        For examples, see :ref:`conf-kitty-mouse.mousemap`
        ''')
    def mouse_handle_click(self, *actions: str) -> None:
        for a in actions:
            if a == 'selection':
                if self.screen.has_selection():
                    break
            if a == 'link':
                if click_mouse_url(self.os_window_id, self.tab_id, self.id):
                    break
            if a == 'prompt':
                # Do not send move cursor events too soon after the window is
                # focused, this is because there are people that click on
                # windows and start typing immediately and the cursor event
                # can interfere with that. See https://github.com/kovidgoyal/kitty/issues/4128
                if monotonic() - self.last_focused_at < 1.5 * get_click_interval():
                    return
                if move_cursor_to_mouse_if_in_prompt(self.os_window_id, self.tab_id, self.id):
                    self.screen.ignore_bells_for(1)
                    break

    @ac('mouse', 'Click the URL under the mouse')
    def mouse_click_url(self) -> None:
        self.mouse_handle_click('link')

    @ac('mouse', 'Click the URL under the mouse only if the screen has no selection')
    def mouse_click_url_or_select(self) -> None:
        self.mouse_handle_click('selection', 'link')

    @ac('mouse', '''
        Manipulate the selection based on the current mouse position

        For examples, see :ref:`conf-kitty-mouse.mousemap`
        ''')
    def mouse_selection(self, code: int) -> None:
        mouse_selection(self.os_window_id, self.tab_id, self.id, code, self.current_mouse_event_button)

    @ac('mouse', 'Paste the current primary selection')
    def paste_selection(self) -> None:
        txt = get_boss().current_primary_selection()
        if txt:
            self.paste(txt)

    @ac('mouse', 'Paste the current primary selection or the clipboard if no selection is present')
    def paste_selection_or_clipboard(self) -> None:
        txt = get_boss().current_primary_selection_or_clipboard()
        if txt:
            self.paste(txt)

    @ac('mouse', '''
        Select clicked command output

        Requires :ref:`shell_integration` to work
        ''')
    def mouse_select_command_output(self) -> None:
        click_mouse_cmd_output(self.os_window_id, self.tab_id, self.id, True)

    @ac('mouse', '''
        Show clicked command output in a pager like less

        Requires :ref:`shell_integration` to work
        ''')
    def mouse_show_command_output(self) -> None:
        if click_mouse_cmd_output(self.os_window_id, self.tab_id, self.id, False):
            self.show_cmd_output(CommandOutput.last_visited, 'Clicked command output')
    # }}}

    def text_for_selection(self, as_ansi: bool = False) -> str:
        sts = get_options().strip_trailing_spaces
        strip_trailing_spaces = sts == 'always' or (sts == 'smart' and not self.screen.is_rectangle_select())
        lines = self.screen.text_for_selection(as_ansi, strip_trailing_spaces)
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
            if self.is_active and self.os_window_id == current_os_window():
                # Cancel IME composition when window is destroyed
                update_ime_position_for_window(self.id, False, True)
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

    def cmd_output(self, which: CommandOutput = CommandOutput.last_run, as_ansi: bool = False, add_wrap_markers: bool = False) -> str:
        return cmd_output(self.screen, which, as_ansi, add_wrap_markers)

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

    def set_logo(self, path: str, position: str = '', alpha: float = -1) -> None:
        path = resolve_custom_file(path) if path else ''
        set_window_logo(self.os_window_id, self.tab_id, self.id, path, position or '', alpha)

    # actions {{{

    @ac('cp', 'Show scrollback in a pager like less')
    def show_scrollback(self) -> None:
        text = self.as_text(as_ansi=True, add_history=True, add_wrap_markers=True)
        data = self.pipe_data(text, has_wrap_markers=True)
        cursor_on_screen = self.screen.scrolled_by < self.screen.lines - self.screen.cursor.y
        get_boss().display_scrollback(self, data['text'], data['input_line_number'], report_cursor=cursor_on_screen)

    def show_cmd_output(self, which: CommandOutput, title: str = 'Command output', as_ansi: bool = True, add_wrap_markers: bool = True) -> None:
        text = self.cmd_output(which, as_ansi=as_ansi, add_wrap_markers=add_wrap_markers)
        text = text.replace('\r\n', '\n').replace('\r', '\n')
        get_boss().display_scrollback(self, text, title=title, report_cursor=False)

    @ac('cp', '''
        Show output from the first shell command on screen in a pager like less

        Requires :ref:`shell_integration` to work
        ''')
    def show_first_command_output_on_screen(self) -> None:
        self.show_cmd_output(CommandOutput.first_on_screen, 'First command output on screen')

    @ac('cp', '''
        Show output from the last shell command in a pager like less

        Requires :ref:`shell_integration` to work
        ''')
    def show_last_command_output(self) -> None:
        self.show_cmd_output(CommandOutput.last_run, 'Last command output')

    @ac('cp', '''
        Show the first command output below the last scrolled position via scroll_to_prompt
        or the last mouse clicked command output in a pager like less

        Requires :ref:`shell_integration` to work
        ''')
    def show_last_visited_command_output(self) -> None:
        self.show_cmd_output(CommandOutput.last_visited, 'Last visited command output')

    def paste_bytes(self, text: Union[str, bytes]) -> None:
        # paste raw bytes without any processing
        if isinstance(text, str):
            text = text.encode('utf-8')
        self.screen.paste_bytes(text)

    @ac('cp', 'Paste the specified text into the current window')
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

    @ac('cp', 'Copy the selected text from the active window to the clipboard')
    def copy_to_clipboard(self) -> None:
        text = self.text_for_selection()
        if text:
            set_clipboard_string(text)

    @ac('cp', 'Copy the selected text from the active window to the clipboard with ANSI formatting codes')
    def copy_ansi_to_clipboard(self) -> None:
        text = self.text_for_selection(as_ansi=True)
        if text:
            set_clipboard_string(text)

    def encoded_key(self, key_event: KeyEvent) -> bytes:
        return encode_key_for_tty(
            key=key_event.key, shifted_key=key_event.shifted_key, alternate_key=key_event.alternate_key,
            mods=key_event.mods, action=key_event.action, text=key_event.text,
            key_encoding_flags=self.screen.current_key_encoding_flags(),
            cursor_key_mode=self.screen.cursor_key_mode,
        ).encode('ascii')

    @ac('cp', 'Copy the selected text from the active window to the clipboard, if no selection, send SIGINT (aka :kbd:`ctrl+c`)')
    def copy_or_interrupt(self) -> None:
        text = self.text_for_selection()
        if text:
            set_clipboard_string(text)
        else:
            self.write_to_child(self.encoded_key(KeyEvent(key=ord('c'), mods=GLFW_MOD_CONTROL)))

    @ac('cp', 'Copy the selected text from the active window to the clipboard and clear selection, if no selection, send SIGINT (aka :kbd:`ctrl+c`)')
    def copy_and_clear_or_interrupt(self) -> None:
        self.copy_or_interrupt()
        self.screen.clear_selection()

    @ac('cp', 'Pass the selected text from the active window to the specified program')
    def pass_selection_to_program(self, *args: str) -> None:
        cwd = self.cwd_of_child
        text = self.text_for_selection()
        if text:
            if args:
                open_cmd(args, text, cwd=cwd)
            else:
                open_url(text, cwd=cwd)

    @ac('cp', 'Clear the current selection')
    def clear_selection(self) -> None:
        self.screen.clear_selection()

    @ac('sc', 'Scroll up by one line')
    def scroll_line_up(self) -> None:
        if self.screen.is_main_linebuf():
            self.screen.scroll(SCROLL_LINE, True)

    @ac('sc', 'Scroll down by one line')
    def scroll_line_down(self) -> None:
        if self.screen.is_main_linebuf():
            self.screen.scroll(SCROLL_LINE, False)

    @ac('sc', 'Scroll up by one page')
    def scroll_page_up(self) -> None:
        if self.screen.is_main_linebuf():
            self.screen.scroll(SCROLL_PAGE, True)

    @ac('sc', 'Scroll down by one page')
    def scroll_page_down(self) -> None:
        if self.screen.is_main_linebuf():
            self.screen.scroll(SCROLL_PAGE, False)

    @ac('sc', 'Scroll to the top of the scrollback buffer')
    def scroll_home(self) -> None:
        if self.screen.is_main_linebuf():
            self.screen.scroll(SCROLL_FULL, True)

    @ac('sc', 'Scroll to the bottom of the scrollback buffer')
    def scroll_end(self) -> None:
        if self.screen.is_main_linebuf():
            self.screen.scroll(SCROLL_FULL, False)

    @ac('sc', '''
        Scroll to the previous/next shell command prompt
        Allows easy jumping from one command to the next. Requires working
        :ref:`shell_integration`. Takes a single, optional, number as argument which is
        the number of prompts to jump, negative values jump up and positive values jump down.
        A value of zero will jump to the last prompt visited by this action.
        For example::

            map ctrl+p scroll_to_prompt -1  # jump to previous
            map ctrl+n scroll_to_prompt 1   # jump to next
            map ctrl+o scroll_to_prompt 0   # jump to last visited
        ''')
    def scroll_to_prompt(self, num_of_prompts: int = -1) -> None:
        if self.screen.is_main_linebuf():
            self.screen.scroll_to_prompt(num_of_prompts)

    @ac('sc', 'Scroll prompt to the bottom of the screen, filling in extra lines form the scrollback buffer')
    def scroll_prompt_to_bottom(self) -> None:
        self.screen.scroll_prompt_to_bottom()

    @ac('mk', 'Toggle the current marker on/off')
    def toggle_marker(self, ftype: str, spec: Union[str, Tuple[Tuple[int, str], ...]], flags: int) -> None:
        from .marks import marker_from_spec
        key = ftype, spec
        if key == self.current_marker_spec:
            self.remove_marker()
            return
        self.screen.set_marker(marker_from_spec(ftype, spec, flags))
        self.current_marker_spec = key

    def set_marker(self, spec: Union[str, Sequence[str]]) -> None:
        from .marks import marker_from_spec
        from .options.utils import parse_marker_spec, toggle_marker
        if isinstance(spec, str):
            func, (ftype, spec_, flags) = toggle_marker('toggle_marker', spec)
        else:
            ftype, spec_, flags = parse_marker_spec(spec[0], spec[1:])
        key = ftype, spec_
        self.screen.set_marker(marker_from_spec(ftype, spec_, flags))
        self.current_marker_spec = key

    @ac('mk', 'Remove a previously created marker')
    def remove_marker(self) -> None:
        if self.current_marker_spec is not None:
            self.screen.set_marker()
            self.current_marker_spec = None

    @ac('mk', 'Scroll to the next or previous mark of the specified type')
    def scroll_to_mark(self, prev: bool = True, mark: int = 0) -> None:
        self.screen.scroll_to_next_mark(mark, prev)

    @ac('misc', '''
        Send the specified SIGNAL to the foreground process in the active window

        For example::

            map F1 signal_child SIGTERM
        ''')
    def signal_child(self, *signals: int) -> None:
        pid = self.child.pid_for_cwd
        if pid is not None:
            for sig in signals:
                os.kill(pid, sig)
    # }}}
