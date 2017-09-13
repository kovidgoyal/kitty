#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2016, Kovid Goyal <kovid at kovidgoyal.net>

import re
import sys
import weakref
from collections import deque
from enum import Enum
from itertools import count
from time import monotonic

from .config import build_ansi_color_table
from .constants import (
    ScreenGeometry, WindowGeometry, appname, cell_size, get_boss,
    is_key_pressed, mouse_button_pressed, viewport_size, wakeup
)
from .fast_data_types import (
    ANY_MODE, BRACKETED_PASTE_END, BRACKETED_PASTE_START, CELL_PROGRAM,
    CURSOR_PROGRAM, GLFW_KEY_DOWN, GLFW_KEY_LEFT_SHIFT, GLFW_KEY_RIGHT_SHIFT,
    GLFW_KEY_UP, GLFW_MOD_SHIFT, GLFW_MOUSE_BUTTON_1, GLFW_MOUSE_BUTTON_4,
    GLFW_MOUSE_BUTTON_5, GLFW_MOUSE_BUTTON_MIDDLE, GLFW_PRESS, GLFW_RELEASE,
    MOTION_MODE, SCROLL_FULL, SCROLL_LINE, SCROLL_PAGE, Screen,
    compile_program, create_cell_vao, glfw_post_empty_event, init_cell_program,
    init_cursor_program, remove_vao, set_window_render_data,
    update_window_title, update_window_visibility
)
from .keys import get_key_map
from .mouse import DRAG, MOVE, PRESS, RELEASE, encode_mouse_event
from .rgb import to_color
from .terminfo import get_capabilities
from .utils import (
    color_as_int, get_primary_selection, load_shaders, open_url,
    parse_color_set, sanitize_title, set_primary_selection
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
window_counter = count()
next(window_counter)


def calculate_gl_geometry(window_geometry, viewport_width, viewport_height, cell_width, cell_height):
    dx, dy = 2 * cell_width / viewport_width, 2 * cell_height / viewport_height
    xmargin = window_geometry.left / viewport_width
    ymargin = window_geometry.top / viewport_height
    xstart = -1 + 2 * xmargin
    ystart = 1 - 2 * ymargin
    return ScreenGeometry(xstart, ystart, window_geometry.xnum, window_geometry.ynum, dx, dy)


def load_shader_programs():
    compile_program(CELL_PROGRAM, *load_shaders('cell'))
    init_cell_program()
    compile_program(CURSOR_PROGRAM, *load_shaders('cursor'))
    init_cursor_program()


class Window:

    def __init__(self, tab, child, opts, args):
        self.id = next(window_counter)
        self.vao_id = create_cell_vao()
        self.tab_id = tab.id
        self.tabref = weakref.ref(tab)
        self.override_title = None
        self.last_mouse_cursor_pos = 0, 0
        self.destroyed = False
        self.click_queue = deque(maxlen=3)
        self.geometry = WindowGeometry(0, 0, 0, 0, 0, 0)
        self.needs_layout = True
        self.title = appname
        self.is_visible_in_layout = True
        self.child, self.opts = child, opts
        self.screen = Screen(self, 24, 80, opts.scrollback_lines)
        self.screen.color_profile.update_ansi_color_table(build_ansi_color_table(opts))
        self.screen.color_profile.set_configured_colors(*map(color_as_int, (
            opts.foreground, opts.background, opts.cursor, opts.selection_foreground, opts.selection_background)))

    def __repr__(self):
        return 'Window(title={}, id={})'.format(self.title, self.id)

    def set_visible_in_layout(self, window_idx, val):
        val = bool(val)
        if val is not self.is_visible_in_layout:
            self.is_visible_in_layout = val
            update_window_visibility(self.tab_id, window_idx, val)
            if val:
                self.refresh()

    def refresh(self):
        self.screen.mark_as_dirty()
        wakeup()

    def update_position(self, window_geometry):
        self.screen_geometry = sg = calculate_gl_geometry(window_geometry, viewport_size.width, viewport_size.height, cell_size.width, cell_size.height)
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
        set_window_render_data(self.tab_id, window_idx, self.vao_id, sg.xstart, sg.ystart, sg.dx, sg.dy, self.screen)
        self.geometry = new_geometry

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

    def write_to_child(self, data):
        if data:
            if get_boss().child_monitor.needs_write(self.id, data) is True:
                wakeup()
            else:
                print('Failed to write to child %d as it does not exist' % self.id, file=sys.stderr)

    # screen callbacks {{{
    def bell(self):
        boss = get_boss()
        boss.request_attention()
        glfw_post_empty_event()

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
            update_window_title(self.tab_id, self.id, self.title)
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
            cp.dirty = True
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
            cp.dirty = True
            self.refresh()

    def request_capabilities(self, q):
        self.write_to_child(get_capabilities(q))

    def buf_toggled(self, is_main_linebuf):
        self.screen.scroll(SCROLL_FULL, False)
    # }}}

    # mouse handling {{{
    def multi_click(self, count, x, y):
        x, y = self.cell_for_pos(x, y)
        if x is not None:
            line = self.screen.visual_line(y)
            if line is not None and count in (2, 3):
                if count == 2:
                    start_x, xlimit = self.screen.selection_range_for_word(x, y, self.opts.select_by_word_characters)
                    end_x = max(start_x, xlimit - 1)
                elif count == 3:
                    start_x, xlimit = self.screen.selection_range_for_line(y)
                    end_x = max(start_x, xlimit - 1)
                self.screen.start_selection(start_x, y)
                self.screen.update_selection(end_x, y, True)
            ps = self.text_for_selection()
            if ps:
                set_primary_selection(ps)

    def cell_for_pos(self, x, y):
        x, y = int(x // cell_size.width), int(y // cell_size.height)
        if 0 <= x < self.screen.columns and 0 <= y < self.screen.lines:
            return x, y
        return None, None

    def dispatch_multi_click(self, x, y):
        if len(self.click_queue) > 2 and self.click_queue[-1] - self.click_queue[-3] <= 2 * self.opts.click_interval:
            self.multi_click(3, x, y)
            glfw_post_empty_event()
        elif len(self.click_queue) > 1 and self.click_queue[-1] - self.click_queue[-2] <= self.opts.click_interval:
            self.multi_click(2, x, y)
            glfw_post_empty_event()

    def update_drag(self, is_press, mx, my):
        x, y = self.cell_for_pos(mx, my)
        if x is None:
            x = 0 if mx <= cell_size.width else self.screen.columns - 1
            y = 0 if my <= cell_size.height else self.screen.lines - 1
        ps = None
        if is_press:
            self.screen.start_selection(x, y)
        elif self.screen.is_selection_in_progress():
            ended = is_press is False
            self.screen.update_selection(x, y, ended)
            if ended:
                ps = self.text_for_selection()
        if ps and ps.strip():
            set_primary_selection(ps)

    def has_url_at(self, x, y):
        x, y = self.cell_for_pos(x, y)
        if x is not None:
            l = self.screen.visual_line(y)
            if l is not None:
                text = str(l)
                for m in self.url_pat.finditer(text):
                    if m.start() <= x < m.end():
                        return True
        return False

    def click_url(self, x, y):
        x, y = self.cell_for_pos(x, y)
        if x is not None:
            l = self.screen.visual_line(y)
            if l is not None:
                text = str(l)
                for m in self.url_pat.finditer(text):
                    if m.start() <= x < m.end():
                        url = ''.join(l[i] for i in range(*m.span())).rstrip('.')
                        # Remove trailing "] and similar
                        url = re.sub(r'''["'][)}\]]$''', '', url)
                        # Remove closing trailing character if it is matched by it's
                        # corresponding opening character before the url
                        if m.start() > 0:
                            before = l[m.start() - 1]
                            closing = {'(': ')', '[': ']', '{': '}', '<': '>', '"': '"', "'": "'", '`': '`', '|': '|', ':': ':'}.get(before)
                            if closing is not None and url.endswith(closing):
                                url = url[:-1]
                        if url:
                            open_url(url, self.opts.open_url_with)

    def text_for_selection(self):
        return ''.join(self.screen.text_for_selection())

    def on_mouse_button(self, button, action, mods):
        mode = self.screen.mouse_tracking_mode()
        handle_event = mods == GLFW_MOD_SHIFT or mode == 0 or button == GLFW_MOUSE_BUTTON_MIDDLE or (
            mods == self.opts.open_url_modifiers and button == GLFW_MOUSE_BUTTON_1)
        x, y = self.last_mouse_cursor_pos
        if handle_event:
            if button == GLFW_MOUSE_BUTTON_1:
                self.update_drag(action == GLFW_PRESS, x, y)
                if action == GLFW_RELEASE:
                    if mods == self.opts.open_url_modifiers:
                        self.click_url(x, y)
                    self.click_queue.append(monotonic())
                    self.dispatch_multi_click(x, y)
            elif button == GLFW_MOUSE_BUTTON_MIDDLE:
                if action == GLFW_RELEASE:
                    self.paste_from_selection()
        else:
            x, y = self.cell_for_pos(x, y)
            if x is not None:
                ev = encode_mouse_event(mode, self.screen.mouse_tracking_protocol(),
                                        button, PRESS if action == GLFW_PRESS else RELEASE, mods, x, y)
                if ev:
                    self.write_to_child(ev)

    def on_mouse_move(self, x, y):
        button = None
        for b in range(0, GLFW_MOUSE_BUTTON_5 + 1):
            if mouse_button_pressed[b]:
                button = b
                break
        action = MOVE if button is None else DRAG
        mode = self.screen.mouse_tracking_mode()
        send_event = (mode == ANY_MODE or (mode == MOTION_MODE and button is not None)) and not (
            is_key_pressed[GLFW_KEY_LEFT_SHIFT] or is_key_pressed[GLFW_KEY_RIGHT_SHIFT])
        x, y = max(0, x - self.geometry.left), max(0, y - self.geometry.top)
        self.last_mouse_cursor_pos = x, y
        get_boss().change_mouse_cursor(self.has_url_at(x, y))
        if send_event:
            x, y = self.cell_for_pos(x, y)
            if x is not None:
                ev = encode_mouse_event(mode, self.screen.mouse_tracking_protocol(),
                                        button, action, 0, x, y)
                if ev:
                    self.write_to_child(ev)
        else:
            if self.screen.is_selection_in_progress():
                self.update_drag(None, x, y)
                margin = cell_size.height // 2
                if y <= margin or y >= self.geometry.bottom - margin:
                    get_boss().ui_timers.add(0.02, self.drag_scroll)

    def drag_scroll(self):
        x, y = self.last_mouse_cursor_pos
        margin = cell_size.height // 2
        if y <= margin or y >= self.geometry.bottom - margin:
            self.scroll_line_up() if y < 50 else self.scroll_line_down()
            self.update_drag(None, x, y)
            return 0.02  # causes the timer to be re-added

    def on_mouse_scroll(self, x, y):
        s = int(round(y * self.opts.wheel_scroll_multiplier))
        if abs(s) < 0:
            return
        upwards = s > 0
        if self.screen.is_main_linebuf():
            self.screen.scroll(abs(s), upwards)
            glfw_post_empty_event()
        else:
            mode = self.screen.mouse_tracking_mode()
            send_event = mode > 0
            if send_event:
                x, y = self.last_mouse_cursor_pos
                x, y = self.cell_for_pos(x, y)
                if x is not None:
                    ev = encode_mouse_event(mode, self.screen.mouse_tracking_protocol(),
                                            GLFW_MOUSE_BUTTON_4 if upwards else GLFW_MOUSE_BUTTON_5, PRESS, 0, x, y)
                    if ev:
                        self.write_to_child(ev)
            else:
                k = get_key_map(self.screen)[GLFW_KEY_UP if upwards else GLFW_KEY_DOWN]
                self.write_to_child(k * abs(s))
    # }}}

    def destroy(self):
        if self.vao_id is not None:
            remove_vao(self.vao_id)
            self.vao_id = None

    # actions {{{

    def show_scrollback(self):
        data = []
        self.screen.historybuf.as_ansi(data.append)
        self.screen.linebuf.as_ansi(data.append)
        data = ''.join(data).encode('utf-8')
        get_boss().display_scrollback(data)

    def paste(self, text):
        if text and not self.destroyed:
            if isinstance(text, str):
                text = text.encode('utf-8')
            if self.screen.in_bracketed_paste_mode:
                text = BRACKETED_PASTE_START.encode('ascii') + text + BRACKETED_PASTE_END.encode('ascii')
            self.write_to_child(text)

    def paste_from_selection(self):
        text = get_primary_selection()
        if text:
            if isinstance(text, bytes):
                text = text.decode('utf-8')
            self.paste(text)

    def copy_to_clipboard(self):
        text = self.text_for_selection()
        if text:
            get_boss().glfw_window.set_clipboard_string(text)

    def scroll_line_up(self):
        if self.screen.is_main_linebuf():
            self.screen.scroll(SCROLL_LINE, True)
            glfw_post_empty_event()

    def scroll_line_down(self):
        if self.screen.is_main_linebuf():
            self.screen.scroll(SCROLL_LINE, False)
            glfw_post_empty_event()

    def scroll_page_up(self):
        if self.screen.is_main_linebuf():
            self.screen.scroll(SCROLL_PAGE, True)
            glfw_post_empty_event()

    def scroll_page_down(self):
        if self.screen.is_main_linebuf():
            self.screen.scroll(SCROLL_PAGE, False)
            glfw_post_empty_event()

    def scroll_home(self):
        if self.screen.is_main_linebuf():
            self.screen.scroll(SCROLL_FULL, True)
            glfw_post_empty_event()

    def scroll_end(self):
        if self.screen.is_main_linebuf():
            self.screen.scroll(SCROLL_FULL, False)
            glfw_post_empty_event()
    # }}}
