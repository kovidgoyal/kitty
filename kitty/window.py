#!/usr/bin/env python3
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2016, Kovid Goyal <kovid at kovidgoyal.net>

import json
import os
import sys
import weakref
from collections import deque
from enum import IntEnum
from itertools import chain
from typing import (
    Any, Callable, Deque, Dict, Iterable, List, Optional, Pattern, Sequence,
    Tuple, Union
)

from .child import ProcessDesc
from .cli_stub import CLIOptions
from .config import build_ansi_color_table
from .constants import ScreenGeometry, WindowGeometry, appname, wakeup
from .fast_data_types import (
    BGIMAGE_PROGRAM, BLIT_PROGRAM, CELL_BG_PROGRAM, CELL_FG_PROGRAM,
    CELL_PROGRAM, CELL_SPECIAL_PROGRAM, CSI, DCS, DECORATION, DIM,
    GRAPHICS_ALPHA_MASK_PROGRAM, GRAPHICS_PREMULT_PROGRAM, GRAPHICS_PROGRAM,
    MARK, MARK_MASK, OSC, REVERSE, SCROLL_FULL, SCROLL_LINE, SCROLL_PAGE,
    STRIKETHROUGH, TINT_PROGRAM, Screen, add_window, cell_size_for_window,
    compile_program, get_boss, get_clipboard_string, init_cell_program,
    set_clipboard_string, set_titlebar_color, set_window_render_data,
    update_window_title, update_window_visibility, viewport_for_window
)
from .keys import defines, extended_key_event, keyboard_mode_name
from .options_stub import Options
from .rgb import to_color
from .terminfo import get_capabilities
from .typing import BossType, ChildType, TabType, TypedDict
from .utils import (
    color_as_int, get_primary_selection, load_shaders, open_cmd, open_url,
    parse_color_set, read_shell_environment, sanitize_title,
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

    def __init__(self) -> None:
        self.on_resize: List[Watcher] = []
        self.on_close: List[Watcher] = []


def calculate_gl_geometry(window_geometry: WindowGeometry, viewport_width: int, viewport_height: int, cell_width: int, cell_height: int) -> ScreenGeometry:
    dx, dy = 2 * cell_width / viewport_width, 2 * cell_height / viewport_height
    xmargin = window_geometry.left / viewport_width
    ymargin = window_geometry.top / viewport_height
    xstart = -1 + 2 * xmargin
    ystart = 1 - 2 * ymargin
    return ScreenGeometry(xstart, ystart, window_geometry.xnum, window_geometry.ynum, dx, dy)


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
        pat = re.compile(r'\033\[.+?m')
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


class Window:

    def __init__(
        self,
        tab: TabType,
        child: ChildType,
        opts: Options,
        args: CLIOptions,
        override_title: Optional[str] = None,
        copy_colors_from: Optional['Window'] = None,
        watchers: Optional[Watchers] = None
    ):
        self.watchers = watchers or Watchers()
        self.action_on_close: Optional[Callable] = None
        self.action_on_removal: Optional[Callable] = None
        self.current_marker_spec: Optional[Tuple[str, Union[str, Tuple[Tuple[int, str], ...]]]] = None
        self.pty_resized_once = False
        self.needs_attention = False
        self.override_title = override_title
        self.overlay_window_id: Optional[int] = None
        self.overlay_for: Optional[int] = None
        self.default_title = os.path.basename(child.argv[0] or appname)
        self.child_title = self.default_title
        self.title_stack: Deque[str] = deque(maxlen=10)
        self.allow_remote_control = child.allow_remote_control
        self.id = add_window(tab.os_window_id, tab.id, self.title)
        if not self.id:
            raise Exception('No tab with id: {} in OS Window: {} was found, or the window counter wrapped'.format(tab.id, tab.os_window_id))
        self.tab_id = tab.id
        self.os_window_id = tab.os_window_id
        self.tabref: Callable[[], Optional[TabType]] = weakref.ref(tab)
        self.clipboard_control_buffers = {'p': '', 'c': ''}
        self.destroyed = False
        self.geometry = WindowGeometry(0, 0, 0, 0, 0, 0)
        self.needs_layout = True
        self.is_visible_in_layout = True
        self.child, self.opts = child, opts
        cell_width, cell_height = cell_size_for_window(self.os_window_id)
        self.screen = Screen(self, 24, 80, opts.scrollback_lines, cell_width, cell_height, self.id)
        if copy_colors_from is not None:
            self.screen.copy_colors_from(copy_colors_from.screen)
        else:
            setup_colors(self.screen, opts)

    def change_tab(self, tab: TabType) -> None:
        self.tab_id = tab.id
        self.os_window_id = tab.os_window_id
        self.tabref = weakref.ref(tab)

    @property
    def title(self) -> str:
        return self.override_title or self.child_title

    def __repr__(self) -> str:
        return 'Window(title={}, id={}, overlay_for={}, overlay_window_id={})'.format(
                self.title, self.id, self.overlay_for, self.overlay_window_id)

    def as_dict(self, is_focused: bool = False) -> WindowDict:
        return dict(
            id=self.id,
            is_focused=is_focused,
            title=self.override_title or self.title,
            pid=self.child.pid,
            cwd=self.child.current_cwd or self.child.cwd,
            cmdline=self.child.cmdline,
            env=self.child.environ,
            foreground_processes=self.child.foreground_processes
        )

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

        if field == 'id':
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

    def set_visible_in_layout(self, window_idx: int, val: bool) -> None:
        val = bool(val)
        if val is not self.is_visible_in_layout:
            self.is_visible_in_layout = val
            update_window_visibility(self.os_window_id, self.tab_id, self.id, window_idx, val)
            if val:
                self.refresh()

    def refresh(self) -> None:
        self.screen.mark_as_dirty()
        wakeup()

    def update_position(self, window_geometry: WindowGeometry) -> ScreenGeometry:
        central, tab_bar, vw, vh, cw, ch = viewport_for_window(self.os_window_id)
        self.screen_geometry = sg = calculate_gl_geometry(window_geometry, vw, vh, cw, ch)
        return sg

    def set_geometry(self, window_idx: int, new_geometry: WindowGeometry) -> None:
        if self.destroyed:
            return
        if self.needs_layout or new_geometry.xnum != self.screen.columns or new_geometry.ynum != self.screen.lines:
            boss = get_boss()
            self.screen.resize(new_geometry.ynum, new_geometry.xnum)
            current_pty_size = (
                self.screen.lines, self.screen.columns,
                max(0, new_geometry.right - new_geometry.left), max(0, new_geometry.bottom - new_geometry.top))
            sg = self.update_position(new_geometry)
            self.needs_layout = False
            boss.child_monitor.resize_pty(self.id, *current_pty_size)
            if not self.pty_resized_once:
                self.pty_resized_once = True
                self.child.mark_terminal_ready()
            self.call_watchers(self.watchers.on_resize, {'old_geometry': self.geometry, 'new_geometry': new_geometry})
        else:
            sg = self.update_position(new_geometry)
        self.geometry = g = new_geometry
        set_window_render_data(self.os_window_id, self.tab_id, self.id, window_idx, sg.xstart, sg.ystart, sg.dx, sg.dy, self.screen, *g[:4])

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
                print('Failed to write to child %d as it does not exist' % self.id, file=sys.stderr)

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

    # screen callbacks {{{
    def use_utf8(self, on: bool) -> None:
        get_boss().child_monitor.set_iutf8_winid(self.id, on)

    def focus_changed(self, focused: bool) -> None:
        if focused:
            self.needs_attention = False
            if self.screen.focus_tracking_enabled:
                self.screen.send_escape_code_to_child(CSI, 'I')
        else:
            if self.screen.focus_tracking_enabled:
                self.screen.send_escape_code_to_child(CSI, 'O')

    def title_changed(self, new_title: Optional[str]) -> None:
        self.child_title = sanitize_title(new_title or self.default_title)
        if self.override_title is None:
            self.title_updated()

    def icon_changed(self, new_icon: object) -> None:
        pass  # TODO: Implement this

    @property
    def is_active(self) -> bool:
        return get_boss().active_window is self

    def on_bell(self) -> None:
        if self.opts.command_on_bell and self.opts.command_on_bell != ['none']:
            import subprocess
            import shlex
            env = self.child.final_env
            env['KITTY_CHILD_CMDLINE'] = ' '.join(map(shlex.quote, self.child.cmdline))
            subprocess.Popen(self.opts.command_on_bell, env=env, cwd=self.child.foreground_cwd)
        if not self.is_active:
            self.needs_attention = True
            tab = self.tabref()
            if tab is not None:
                tab.on_bell(self)

    def change_titlebar_color(self) -> None:
        val = self.opts.macos_titlebar_color
        if val:
            if (val & 0xff) == 1:
                val = self.screen.color_profile.default_bg
            else:
                val = val >> 8
            set_titlebar_color(self.os_window_id, val)

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
        self.screen.send_escape_code_to_child(DCS, get_capabilities(q))

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
        if text == '?':
            response = None
            if 's' in where or 'c' in where:
                response = get_clipboard_string() if 'read-clipboard' in self.opts.clipboard_control else ''
                loc = 'c'
            elif 'p' in where:
                response = get_primary_selection() if 'read-primary' in self.opts.clipboard_control else ''
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
                    if ('no-append' in self.opts.clipboard_control or
                            len(self.clipboard_control_buffers[key]) > 1024*1024):
                        self.clipboard_control_buffers[key] = ''
                    self.clipboard_control_buffers[key] += text
                else:
                    self.clipboard_control_buffers[key] = ''
                func(self.clipboard_control_buffers[key])

            if 's' in where or 'c' in where:
                if 'write-clipboard' in self.opts.clipboard_control:
                    write('c', set_clipboard_string)
            if 'p' in where:
                if self.opts.copy_on_select == 'clipboard':
                    if 'write-clipboard' in self.opts.clipboard_control:
                        write('c', set_clipboard_string)
                if 'write-primary' in self.opts.clipboard_control:
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

    def text_for_selection(self) -> str:
        lines = self.screen.text_for_selection()
        if self.opts.strip_trailing_spaces == 'always' or (
                self.opts.strip_trailing_spaces == 'smart' and not self.screen.is_rectangle_select()):
            return ''.join((l.rstrip() or '\n') for l in lines)
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
        alternate_screen: bool = False
    ) -> str:
        lines: List[str] = []
        add_history = add_history and not (self.screen.is_using_alternate_linebuf() ^ alternate_screen)
        if alternate_screen:
            f = self.screen.as_text_alternate
        else:
            f = self.screen.as_text_non_visual if add_history else self.screen.as_text
        f(lines.append, as_ansi, add_wrap_markers)
        if add_history:
            h: List[str] = []
            self.screen.historybuf.pagerhist_as_text(h.append)
            if h and (not as_ansi or not add_wrap_markers):
                sanitizer = text_sanitizer(as_ansi, add_wrap_markers)
                h = list(map(sanitizer, h))
            self.screen.historybuf.as_text(h.append, as_ansi, add_wrap_markers)
            if h:
                if not self.screen.linebuf.is_continued(0):
                    h[-1] += '\n'
                if as_ansi:
                    h[-1] += '\x1b[m'
            return ''.join(chain(h, lines))
        return ''.join(lines)

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
        cmd = [x.replace('INPUT_LINE_NUMBER', str(data['input_line_number'])) for x in self.opts.scrollback_pager]
        if not os.path.isabs(cmd[0]):
            import shutil
            exe = shutil.which(cmd[0])
            if not exe:
                env = read_shell_environment(self.opts)
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

    def copy_or_interrupt(self) -> None:
        text = self.text_for_selection()
        if text:
            set_clipboard_string(text)
        else:
            mode = keyboard_mode_name(self.screen)
            data = extended_key_event(defines.GLFW_KEY_C, defines.GLFW_MOD_CONTROL, defines.GLFW_PRESS) if mode == 'kitty' else b'\x03'
            self.write_to_child(data)

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
        from .config import toggle_marker, parse_marker_spec
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
    # }}}
