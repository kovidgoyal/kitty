#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2016, Kovid Goyal <kovid at kovidgoyal.net>

import json
import sys
import weakref
from collections import deque
from enum import Enum

from .config import build_ansi_color_table, parse_send_text_bytes
from .constants import (
    ScreenGeometry, WindowGeometry, appname, get_boss, wakeup
)
from .fast_data_types import (
    BLIT_PROGRAM, CELL_BG_PROGRAM, CELL_FG_PROGRAM, CELL_PROGRAM,
    CELL_SPECIAL_PROGRAM, CSI, CURSOR_PROGRAM, DCS, GRAPHICS_PREMULT_PROGRAM,
    GRAPHICS_PROGRAM, OSC, SCROLL_FULL, SCROLL_LINE, SCROLL_PAGE, Screen,
    add_window, compile_program, glfw_post_empty_event, init_cell_program,
    init_cursor_program, set_clipboard_string, set_window_render_data,
    update_window_title, update_window_visibility, viewport_for_window
)
from .keys import keyboard_mode_name
from .rgb import to_color
from .terminfo import get_capabilities
from .utils import (
    color_as_int, load_shaders, open_cmd, open_url, parse_color_set,
    sanitize_title
)


class DynamicColor(Enum):
    default_fg, default_bg, cursor_color, highlight_fg, highlight_bg = range(1, 6)


DYNAMIC_COLOR_CODES = {
    10: DynamicColor.default_fg,
    11: DynamicColor.default_bg,
    12: DynamicColor.cursor_color,
    17: DynamicColor.highlight_bg,
    19: DynamicColor.highlight_fg,
}
DYNAMIC_COLOR_CODES.update({k+100: v for k, v in DYNAMIC_COLOR_CODES.items()})


def calculate_gl_geometry(window_geometry, viewport_width, viewport_height, cell_width, cell_height):
    dx, dy = 2 * cell_width / viewport_width, 2 * cell_height / viewport_height
    xmargin = window_geometry.left / viewport_width
    ymargin = window_geometry.top / viewport_height
    xstart = -1 + 2 * xmargin
    ystart = 1 - 2 * ymargin
    return ScreenGeometry(xstart, ystart, window_geometry.xnum, window_geometry.ynum, dx, dy)


def load_shader_programs(semi_transparent=0):
    compile_program(BLIT_PROGRAM, *load_shaders('blit'))
    v, f = load_shaders('cell')
    for which, p in {
            'SIMPLE': CELL_PROGRAM,
            'BACKGROUND': CELL_BG_PROGRAM,
            'SPECIAL': CELL_SPECIAL_PROGRAM,
            'FOREGROUND': CELL_FG_PROGRAM,
    }.items():
        vv, ff = v.replace('WHICH_PROGRAM', which), f.replace('WHICH_PROGRAM', which)
        if semi_transparent:
            vv = vv.replace('#define NOT_TRANSPARENT', '#define TRANSPARENT')
            ff = ff.replace('#define NOT_TRANSPARENT', '#define TRANSPARENT')
        compile_program(p, vv, ff)
    v, f = load_shaders('graphics')
    for which, p in {
            'SIMPLE': GRAPHICS_PROGRAM,
            'PREMULT': GRAPHICS_PREMULT_PROGRAM,
    }.items():
        ff = f.replace('ALPHA_TYPE', which)
        compile_program(p, v, ff)
    init_cell_program()
    compile_program(CURSOR_PROGRAM, *load_shaders('cursor'))
    init_cursor_program()


def setup_colors(screen, opts):
    screen.color_profile.update_ansi_color_table(build_ansi_color_table(opts))
    screen.color_profile.set_configured_colors(*map(color_as_int, (
        opts.foreground, opts.background, opts.cursor, opts.selection_foreground, opts.selection_background)))


class Window:

    def __init__(self, tab, child, opts, args, override_title=None):
        self.override_title = override_title
        self.child_title = appname
        self.id = add_window(tab.os_window_id, tab.id, self.title)
        if not self.id:
            raise Exception('No tab with id: {} in OS Window: {} was found, or the window counter wrapped'.format(tab.id, tab.os_window_id))
        self.tab_id = tab.id
        self.os_window_id = tab.os_window_id
        self.tabref = weakref.ref(tab)
        self.destroyed = False
        self.click_queue = deque(maxlen=3)
        self.geometry = WindowGeometry(0, 0, 0, 0, 0, 0)
        self.needs_layout = True
        self.is_visible_in_layout = True
        self.child, self.opts = child, opts
        self.screen = Screen(self, 24, 80, opts.scrollback_lines, self.id)
        setup_colors(self.screen, opts)

    @property
    def title(self):
        return self.override_title or self.child_title

    def __repr__(self):
        return 'Window(title={}, id={})'.format(self.title, self.id)

    def as_dict(self):
        return dict(
            id=self.id,
            title=self.override_title or self.title,
            pid=self.child.pid,
            cwd=self.child.current_cwd or self.child.cwd, cmdline=self.child.cmdline
        )

    def matches(self, field, pat):
        if field == 'id':
            return pat.pattern == str(self.id)
        if field == 'pid':
            return pat.pattern == str(self.child.pid)
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

    def set_visible_in_layout(self, window_idx, val):
        val = bool(val)
        if val is not self.is_visible_in_layout:
            self.is_visible_in_layout = val
            update_window_visibility(self.os_window_id, self.tab_id, window_idx, val)
            if val:
                self.refresh()

    def refresh(self):
        self.screen.mark_as_dirty()
        wakeup()

    def update_position(self, window_geometry):
        vw, vh, ah, cw, ch = viewport_for_window(self.os_window_id)
        self.screen_geometry = sg = calculate_gl_geometry(window_geometry, vw, vh, cw, ch)
        return sg

    def set_geometry(self, window_idx, new_geometry):
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
        else:
            sg = self.update_position(new_geometry)
        self.geometry = g = new_geometry
        set_window_render_data(self.os_window_id, self.tab_id, window_idx, sg.xstart, sg.ystart, sg.dx, sg.dy, self.screen, *g[:4])

    def contains(self, x, y):
        g = self.geometry
        return g.left <= x <= g.right and g.top <= y <= g.bottom

    def close(self):
        get_boss().close_window(self)

    def send_text(self, *args):
        mode = keyboard_mode_name(self.screen)
        required_mode, text = args[-2:]
        required_mode = frozenset(required_mode.split(','))
        if not required_mode & {mode, 'all'}:
            return True
        data = parse_send_text_bytes(text)
        if not data:
            return True
        self.write_to_child(data)

    def write_to_child(self, data):
        if data:
            if get_boss().child_monitor.needs_write(self.id, data) is not True:
                print('Failed to write to child %d as it does not exist' % self.id, file=sys.stderr)

    def title_updated(self):
        update_window_title(self.os_window_id, self.tab_id, self.id, self.title)
        t = self.tabref()
        if t is not None:
            t.title_changed(self)
        glfw_post_empty_event()

    def set_title(self, title):
        self.override_title = title or None
        self.title_updated()

    # screen callbacks {{{
    def use_utf8(self, on):
        get_boss().child_monitor.set_iutf8(self.window_id, on)

    def focus_changed(self, focused):
        if focused:
            if self.screen.focus_tracking_enabled:
                self.screen.send_escape_code_to_child(CSI, 'I')
        else:
            if self.screen.focus_tracking_enabled:
                self.screen.send_escape_code_to_child(CSI, 'O')

    def title_changed(self, new_title):
        self.child_title = sanitize_title(new_title or appname)
        if self.override_title is None:
            self.title_updated()

    def icon_changed(self, new_icon):
        pass  # TODO: Implement this

    def change_colors(self, changes):
        dirtied = False

        def item(raw):
            if raw is None:
                return 0
            val = to_color(raw)
            return None if val is None else (color_as_int(val) << 8) | 2

        for which, val in changes.items():
            val = item(val)
            if val is None:
                continue
            dirtied = True
            setattr(self.screen.color_profile, which.name, val)
        if dirtied:
            self.screen.mark_as_dirty()

    def report_color(self, code, r, g, b):
        r |= r << 8
        g |= g << 8
        b |= b << 8
        self.screen.send_escape_code_to_child(OSC, '{};rgb:{:04x}/{:04x}/{:04x}'.format(code, r, g, b))

    def set_dynamic_color(self, code, value):
        if isinstance(value, bytes):
            value = value.decode('utf-8')
        color_changes = {}
        for val in value.split(';'):
            w = DYNAMIC_COLOR_CODES.get(code)
            if w is not None:
                if val == '?':
                    col = getattr(self.screen.color_profile, w.name)
                    self.report_color(str(code), col >> 16, (col >> 8) & 0xff, col & 0xff)
                else:
                    if code >= 110:
                        val = None
                    color_changes[w] = val
            code += 1
        if color_changes:
            self.change_colors(color_changes)
            glfw_post_empty_event()

    def set_color_table_color(self, code, value):
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
                for c in value.split(';'):
                    try:
                        c = int(c)
                    except Exception:
                        continue
                    if 0 <= c <= 255:
                        cp.reset_color(c)
            self.refresh()

    def request_capabilities(self, q):
        self.screen.send_escape_code_to_child(DCS, get_capabilities(q))

    def handle_remote_cmd(self, cmd):
        get_boss().handle_remote_cmd(cmd, self)

    def send_cmd_response(self, response):
        self.screen.send_escape_code_to_child(DCS, '@kitty-cmd' + json.dumps(response))

    # }}}

    def text_for_selection(self):
        return ''.join(self.screen.text_for_selection())

    def destroy(self):
        self.destroyed = True
        if self.screen is not None:
            # Remove cycles so that screen is de-allocated immediately
            self.screen.reset_callbacks()
        self.screen = None

    def buffer_as_ansi(self):
        data = []
        self.screen.historybuf.as_ansi(data.append)
        self.screen.linebuf.as_ansi(data.append)
        return ''.join(data)

    def buffer_as_text(self):
        return str(self.screen.historybuf) + '\n' + str(self.screen.linebuf)

    # actions {{{

    def show_scrollback(self):
        get_boss().display_scrollback(self.buffer_as_ansi().encode('utf-8'))

    def paste(self, text):
        if text and not self.destroyed:
            if isinstance(text, str):
                text = text.encode('utf-8')
            if self.screen.in_bracketed_paste_mode:
                text = text.replace(b'\033[201~', b'').replace(b'\x9b201~', b'')
            self.screen.paste(text)

    def copy_to_clipboard(self):
        text = self.text_for_selection()
        if text:
            set_clipboard_string(text)

    def pass_selection_to_program(self, *args):
        text = self.text_for_selection()
        if text:
            if args:
                open_cmd(args, text)
            else:
                open_url(text)

    def scroll_line_up(self):
        if self.screen.is_main_linebuf():
            self.screen.scroll(SCROLL_LINE, True)

    def scroll_line_down(self):
        if self.screen.is_main_linebuf():
            self.screen.scroll(SCROLL_LINE, False)

    def scroll_page_up(self):
        if self.screen.is_main_linebuf():
            self.screen.scroll(SCROLL_PAGE, True)

    def scroll_page_down(self):
        if self.screen.is_main_linebuf():
            self.screen.scroll(SCROLL_PAGE, False)

    def scroll_home(self):
        if self.screen.is_main_linebuf():
            self.screen.scroll(SCROLL_FULL, True)

    def scroll_end(self):
        if self.screen.is_main_linebuf():
            self.screen.scroll(SCROLL_FULL, False)
    # }}}
