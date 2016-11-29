#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2016, Kovid Goyal <kovid at kovidgoyal.net>

import os
import weakref
from collections import deque
from functools import partial
from time import monotonic

import glfw
from .char_grid import CharGrid
from .constants import wakeup, tab_manager, appname, WindowGeometry
from .fast_data_types import (
    BRACKETED_PASTE_START, BRACKETED_PASTE_END, Screen, read_bytes_dump,
    read_bytes, GLFW_MOD_SHIFT, GLFW_MOUSE_BUTTON_1, GLFW_PRESS,
    GLFW_MOUSE_BUTTON_MIDDLE, GLFW_RELEASE, GLFW_KEY_LEFT_SHIFT,
    GLFW_KEY_RIGHT_SHIFT
)
from .terminfo import get_capabilities
from .utils import sanitize_title, get_primary_selection


class Window:

    def __init__(self, tab, child, opts, args):
        self.tabref = weakref.ref(tab)
        self.click_queue = deque(maxlen=3)
        self.geometry = WindowGeometry(0, 0, 0, 0, 0, 0)
        self.needs_layout = True
        self.title = appname
        self.is_visible_in_layout = True
        self.child, self.opts = child, opts
        self.child_fd = child.child_fd
        self.screen = Screen(self, 24, 80, opts.scrollback_lines)
        self.read_bytes = partial(read_bytes_dump, self.dump_commands) if args.dump_commands else read_bytes
        self.draw_dump_buf = []
        self.write_buf = memoryview(b'')
        self.char_grid = CharGrid(self.screen, opts)

    def refresh(self):
        self.screen.mark_as_dirty()
        wakeup()

    def set_geometry(self, new_geometry):
        if self.needs_layout or new_geometry.xnum != self.screen.columns or new_geometry.ynum != self.screen.lines:
            self.screen.resize(new_geometry.ynum, new_geometry.xnum)
            self.child.resize_pty(self.screen.columns, self.screen.lines)
            self.char_grid.resize(new_geometry)
            self.needs_layout = False
        else:
            self.char_grid.update_position(new_geometry)
        self.geometry = new_geometry

    def contains(self, x, y):
        g = self.geometry
        return g.left <= x <= g.right and g.top <= y <= g.bottom

    def close(self):
        tab_manager().close_window(self)

    def destroy(self):
        self.child.hangup()
        self.child.get_child_status()  # Ensure child does not become zombie

    def read_ready(self):
        if self.read_bytes(self.screen, self.child_fd) is False:
            self.close()  # EOF

    def write_ready(self):
        while self.write_buf:
            try:
                n = os.write(self.child_fd, self.write_buf)
            except BlockingIOError:
                n = 0
            if not n:
                return
            self.write_buf = self.write_buf[n:]

    def write_to_child(self, data):
        self.write_buf = memoryview(self.write_buf.tobytes() + data)
        wakeup()

    def update_screen(self):
        self.char_grid.update_cell_data()
        glfw.glfwPostEmptyEvent()

    def focus_changed(self, focused):
        if focused:
            if self.screen.focus_tracking_enabled():
                self.write_to_child(b'\x1b[I')
        else:
            if self.screen.focus_tracking_enabled():
                self.write_to_child(b'\x1b[O')

    def title_changed(self, new_title):
        self.title = sanitize_title(new_title or appname)
        glfw.glfwPostEmptyEvent()

    def icon_changed(self, new_icon):
        pass  # TODO: Implement this

    def set_dynamic_color(self, code, value):
        wmap = {10: 'fg', 11: 'bg', 110: 'fg', 111: 'bg'}
        if isinstance(value, bytes):
            value = value.decode('utf-8')
        color_changes = {}
        for val in value.split(';'):
            w = wmap.get(code)
            if w is not None:
                if code >= 110:
                    val = None
                color_changes[w] = val
            code += 1
        self.char_grid.change_colors(color_changes)
        glfw.glfwPostEmptyEvent()

    def request_capabilities(self, q):
        self.write_to_child(get_capabilities(q))

    def dispatch_multi_click(self, x, y):
        if len(self.click_queue) > 2 and self.click_queue[-1] - self.click_queue[-3] <= 2 * self.opts.click_interval:
            self.char_grid.multi_click(3, x, y)
            glfw.glfwPostEmptyEvent()
        elif len(self.click_queue) > 1 and self.click_queue[-1] - self.click_queue[-2] <= self.opts.click_interval:
            self.char_grid.multi_click(2, x, y)
            glfw.glfwPostEmptyEvent()

    def on_mouse_button(self, window, button, action, mods):
        handle_event = mods == GLFW_MOD_SHIFT or not self.screen.mouse_button_tracking_enabled()
        if handle_event:
            if button == GLFW_MOUSE_BUTTON_1:
                x, y = glfw.glfwGetCursorPos(window)
                x, y = max(0, x - self.geometry.left), max(0, y - self.geometry.top)
                self.char_grid.update_drag(action == GLFW_PRESS, x, y)
                if action == GLFW_RELEASE:
                    self.click_queue.append(monotonic())
                    self.dispatch_multi_click(x, y)
            elif button == GLFW_MOUSE_BUTTON_MIDDLE:
                if action == GLFW_RELEASE:
                    self.paste_from_selection()
        else:
            x, y = glfw.glfwGetCursorPos(window)
            x, y = max(0, x - self.geometry.left), max(0, y - self.geometry.top)
            x, y = self.char_grid.cell_for_pos(x, y)

    def on_mouse_move(self, window, x, y):
        if self.char_grid.current_selection.in_progress:
            self.char_grid.update_drag(None, max(0, x - self.geometry.left), max(0, y - self.geometry.top))

    def on_mouse_scroll(self, window, x, y):
        handle_event = (
            glfw.glfwGetKey(window, GLFW_KEY_LEFT_SHIFT) == GLFW_PRESS or
            glfw.glfwGetKey(window, GLFW_KEY_RIGHT_SHIFT) == GLFW_PRESS or
            not self.screen.mouse_button_tracking_enabled())
        if handle_event:
            s = int(round(y * self.opts.wheel_scroll_multiplier))
            if abs(s) > 0:
                self.char_grid.scroll(abs(s), s > 0)
                glfw.glfwPostEmptyEvent()

    # actions {{{

    def paste(self, text):
        if text:
            if isinstance(text, str):
                text = text.encode('utf-8')
            if self.screen.in_bracketed_paste_mode():
                text = BRACKETED_PASTE_START.encode('ascii') + text + BRACKETED_PASTE_END.encode('ascii')
            self.write_to_child(text)

    def paste_from_clipboard(self):
        text = glfw.glfwGetClipboardString(tab_manager().glfw_window)
        if text:
            self.paste(text.decode('utf-8'))

    def paste_from_selection(self):
        text = get_primary_selection()
        if text:
            if isinstance(text, bytes):
                text = text.decode('utf-8')
            self.paste(text)

    def scroll_line_up(self):
        self.char_grid.scroll('line', True)
        glfw.glfwPostEmptyEvent()

    def scroll_line_down(self):
        self.char_grid.scroll('line', False)
        glfw.glfwPostEmptyEvent()

    def scroll_page_up(self):
        self.char_grid.scroll('page', True)
        glfw.glfwPostEmptyEvent()

    def scroll_page_down(self):
        self.char_grid.scroll('page', False)
        glfw.glfwPostEmptyEvent()

    def scroll_home(self):
        self.char_grid.scroll('full', True)
        glfw.glfwPostEmptyEvent()

    def scroll_end(self):
        self.char_grid.scroll('full', False)
        glfw.glfwPostEmptyEvent()
    # }}}

    def dump_commands(self, *a):
        if a:
            if a[0] == 'draw':
                if a[1] is None:
                    if self.draw_dump_buf:
                        print('draw', ''.join(self.draw_dump_buf))
                        self.draw_dump_buf = []
                else:
                    self.draw_dump_buf.append(a[1])
            else:
                if self.draw_dump_buf:
                    print('draw', ''.join(self.draw_dump_buf))
                    self.draw_dump_buf = []
                print(*a)
