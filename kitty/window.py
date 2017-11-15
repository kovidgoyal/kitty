#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2016, Kovid Goyal <kovid at kovidgoyal.net>

import sys
import weakref
from collections import deque
from enum import Enum

from .config import build_ansi_color_table, parse_send_text_bytes
from .constants import (
    ScreenGeometry, WindowGeometry, appname, get_boss, wakeup
)
from .fast_data_types import (
    BRACKETED_PASTE_END, BRACKETED_PASTE_START, CELL_BACKGROUND_PROGRAM,
    CELL_FOREGROUND_PROGRAM, CELL_PROGRAM, CELL_SPECIAL_PROGRAM,
    CURSOR_PROGRAM, GRAPHICS_PROGRAM, SCROLL_FULL, SCROLL_LINE, SCROLL_PAGE,
    Screen, add_window, compile_program, glfw_post_empty_event,
    init_cell_program, init_cursor_program, set_clipboard_string,
    set_window_render_data, update_window_title, update_window_visibility,
    viewport_for_window
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


def load_shader_programs():
    v, f = load_shaders('cell')
    compile_program(GRAPHICS_PROGRAM, *load_shaders('graphics'))
    for which, p in {
            'ALL': CELL_PROGRAM, 'BACKGROUND': CELL_BACKGROUND_PROGRAM, 'SPECIAL': CELL_SPECIAL_PROGRAM,
            'FOREGROUND': CELL_FOREGROUND_PROGRAM
    }.items():
        vv, ff = v.replace('WHICH_PROGRAM', which), f.replace('WHICH_PROGRAM', which)
        compile_program(p, vv, ff)
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
        self.title = self.override_title or appname
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

    def __repr__(self):
        return 'Window(title={}, id={})'.format(self.title, self.id)

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
        self.screen_geometry = sg = calculate_gl_geometry(window_geometry, *viewport_for_window(self.os_window_id))
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

    def on_child_death(self):
        if self.destroyed:
            return
        self.destroyed = True
        # Remove cycles so that screen is de-allocated immediately
        boss = get_boss()
        self.screen.reset_callbacks()
        boss.gui_close_window(self)
        self.screen = None

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

    # screen callbacks {{{
    def use_utf8(self, on):
        get_boss().child_monitor.set_iutf8(self.window_id, on)

    def focus_changed(self, focused):
        if focused:
            if self.screen.focus_tracking_enabled:
                self.write_to_child(b'\x1b[I')
        else:
            if self.screen.focus_tracking_enabled:
                self.write_to_child(b'\x1b[O')

    def title_changed(self, new_title):
        if self.override_title is None:
            self.title = sanitize_title(new_title or appname)
            update_window_title(self.os_window_id, self.tab_id, self.id, self.title)
            t = self.tabref()
            if t is not None:
                t.title_changed(self)
            glfw_post_empty_event()

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

    def set_dynamic_color(self, code, value):
        if isinstance(value, bytes):
            value = value.decode('utf-8')
        color_changes = {}
        for val in value.split(';'):
            w = DYNAMIC_COLOR_CODES.get(code)
            if w is not None:
                if code >= 110:
                    val = None
                color_changes[w] = val
            code += 1
        self.change_colors(color_changes)
        glfw_post_empty_event()

    def set_color_table_color(self, code, value):
        cp = self.screen.color_profile
        if code == 4:
            for c, val in parse_color_set(value):
                cp.set_color(c, val)
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
        self.write_to_child(get_capabilities(q))

    # }}}

    def text_for_selection(self):
        return ''.join(self.screen.text_for_selection())

    def destroy(self):
        pass

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
                bpe = BRACKETED_PASTE_END.encode('ascii')
                text = BRACKETED_PASTE_START.encode('ascii') + text.replace(bpe, b'') + bpe
            self.write_to_child(text)

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
