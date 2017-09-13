#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2016, Kovid Goyal <kovid at kovidgoyal.net>

import sys
import weakref
from collections import deque
from itertools import count
from time import monotonic

from .char_grid import CharGrid, DynamicColor
from .constants import (
    WindowGeometry, appname, cell_size, get_boss, is_key_pressed,
    mouse_button_pressed, wakeup
)
from .fast_data_types import (
    ANY_MODE, BRACKETED_PASTE_END, BRACKETED_PASTE_START, GLFW_KEY_DOWN,
    GLFW_KEY_LEFT_SHIFT, GLFW_KEY_RIGHT_SHIFT, GLFW_KEY_UP, GLFW_MOD_SHIFT,
    GLFW_MOUSE_BUTTON_1, GLFW_MOUSE_BUTTON_4, GLFW_MOUSE_BUTTON_5,
    GLFW_MOUSE_BUTTON_MIDDLE, GLFW_PRESS, GLFW_RELEASE, MOTION_MODE,
    SCROLL_FULL, SCROLL_LINE, SCROLL_PAGE, Screen, create_cell_vao,
    glfw_post_empty_event, remove_vao, set_window_render_data,
    update_window_title, update_window_visibility
)
from .keys import get_key_map
from .mouse import DRAG, MOVE, PRESS, RELEASE, encode_mouse_event
from .terminfo import get_capabilities
from .utils import get_primary_selection, parse_color_set, sanitize_title

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
        self.char_grid = CharGrid(self.screen, opts)

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

    def set_geometry(self, window_idx, new_geometry):
        if self.destroyed:
            return
        if self.needs_layout or new_geometry.xnum != self.screen.columns or new_geometry.ynum != self.screen.lines:
            boss = get_boss()
            self.screen.resize(new_geometry.ynum, new_geometry.xnum)
            current_pty_size = (
                self.screen.lines, self.screen.columns,
                max(0, new_geometry.right - new_geometry.left), max(0, new_geometry.bottom - new_geometry.top))
            sg = self.char_grid.update_position(new_geometry)
            self.needs_layout = False
            boss.child_monitor.resize_pty(self.id, *current_pty_size)
        else:
            sg = self.char_grid.update_position(new_geometry)
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
        self.screen = self.char_grid.screen = None
        self.char_grid = None

    def write_to_child(self, data):
        if data:
            if get_boss().child_monitor.needs_write(self.id, data) is True:
                wakeup()
            else:
                print('Failed to write to child %d as it does not exist' % self.id, file=sys.stderr)

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
        self.char_grid.change_colors(color_changes)
        glfw_post_empty_event()

    def set_color_table_color(self, code, value):
        cp = self.char_grid.screen.color_profile
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

    def dispatch_multi_click(self, x, y):
        if len(self.click_queue) > 2 and self.click_queue[-1] - self.click_queue[-3] <= 2 * self.opts.click_interval:
            self.char_grid.multi_click(3, x, y)
            glfw_post_empty_event()
        elif len(self.click_queue) > 1 and self.click_queue[-1] - self.click_queue[-2] <= self.opts.click_interval:
            self.char_grid.multi_click(2, x, y)
            glfw_post_empty_event()

    def on_mouse_button(self, button, action, mods):
        mode = self.screen.mouse_tracking_mode()
        handle_event = mods == GLFW_MOD_SHIFT or mode == 0 or button == GLFW_MOUSE_BUTTON_MIDDLE or (
            mods == self.opts.open_url_modifiers and button == GLFW_MOUSE_BUTTON_1)
        x, y = self.last_mouse_cursor_pos
        if handle_event:
            if button == GLFW_MOUSE_BUTTON_1:
                self.char_grid.update_drag(action == GLFW_PRESS, x, y)
                if action == GLFW_RELEASE:
                    if mods == self.char_grid.opts.open_url_modifiers:
                        self.char_grid.click_url(x, y)
                    self.click_queue.append(monotonic())
                    self.dispatch_multi_click(x, y)
            elif button == GLFW_MOUSE_BUTTON_MIDDLE:
                if action == GLFW_RELEASE:
                    self.paste_from_selection()
        else:
            x, y = self.char_grid.cell_for_pos(x, y)
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
        get_boss().change_mouse_cursor(self.char_grid.has_url_at(x, y))
        if send_event:
            x, y = self.char_grid.cell_for_pos(x, y)
            if x is not None:
                ev = encode_mouse_event(mode, self.screen.mouse_tracking_protocol(),
                                        button, action, 0, x, y)
                if ev:
                    self.write_to_child(ev)
        else:
            if self.screen.is_selection_in_progress():
                self.char_grid.update_drag(None, x, y)
                margin = cell_size.height // 2
                if y <= margin or y >= self.geometry.bottom - margin:
                    get_boss().ui_timers.add(0.02, self.drag_scroll)

    def drag_scroll(self):
        x, y = self.last_mouse_cursor_pos
        margin = cell_size.height // 2
        if y <= margin or y >= self.geometry.bottom - margin:
            self.scroll_line_up() if y < 50 else self.scroll_line_down()
            self.char_grid.update_drag(None, x, y)
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
                x, y = self.char_grid.cell_for_pos(x, y)
                if x is not None:
                    ev = encode_mouse_event(mode, self.screen.mouse_tracking_protocol(),
                                            GLFW_MOUSE_BUTTON_4 if upwards else GLFW_MOUSE_BUTTON_5, PRESS, 0, x, y)
                    if ev:
                        self.write_to_child(ev)
            else:
                k = get_key_map(self.screen)[GLFW_KEY_UP if upwards else GLFW_KEY_DOWN]
                self.write_to_child(k * abs(s))

    def buf_toggled(self, is_main_linebuf):
        self.screen.scroll(SCROLL_FULL, False)

    def destroy(self):
        if self.vao_id is not None:
            remove_vao(self.vao_id)
            self.vao_id = None

    # actions {{{

    def show_scrollback(self):
        data = self.char_grid.get_scrollback_as_ansi()
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
        text = self.char_grid.text_for_selection()
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
