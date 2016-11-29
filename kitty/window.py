#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2016, Kovid Goyal <kovid at kovidgoyal.net>

import os
import weakref
import subprocess
from functools import partial

import glfw
import glfw_constants
from .char_grid import CharGrid
from .constants import wakeup, tab_manager, appname, WindowGeometry, queue_action
from .fast_data_types import (
    BRACKETED_PASTE_START, BRACKETED_PASTE_END, Screen, read_bytes_dump, read_bytes
)
from .terminfo import get_capabilities
from .utils import sanitize_title


class Window:

    def __init__(self, tab, child, opts, args):
        self.tabref = weakref.ref(tab)
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

    def on_mouse_button(self, window, button, action, mods):
        ignore_mouse_mode = mods == glfw_constants.GLFW_MOD_SHIFT or not self.screen.mouse_button_tracking_enabled()
        if button == glfw_constants.GLFW_MOUSE_BUTTON_1 and ignore_mouse_mode:
            x, y = glfw.glfwGetCursorPos(window)
            self.char_grid.update_drag(action == glfw_constants.GLFW_PRESS, max(0, x - self.geometry.left), max(0, y - self.geometry.top))
        if action == glfw_constants.GLFW_RELEASE:
            if button == glfw_constants.GLFW_MOUSE_BUTTON_MIDDLE:
                self.paste_from_selection()
                return

    def on_mouse_move(self, x, y):
        if self.char_grid.current_selection.in_progress:
            self.char_grid.update_drag(None, max(0, x - self.geometry.left), max(0, y - self.geometry.top))

    def on_mouse_scroll(self, x, y):
        pass

    # actions {{{

    def paste(self, text):
        if text:
            if self.screen.in_bracketed_paste_mode():
                text = BRACKETED_PASTE_START.encode('ascii') + text + BRACKETED_PASTE_END.encode('ascii')
            self.write_to_child(text)

    def paste_from_clipboard(self):
        text = glfw.glfwGetClipboardString(self.window)
        self.paste(text)

    def paste_from_selection(self):
        # glfw has no way to get the primary selection
        # https://github.com/glfw/glfw/issues/894
        text = subprocess.check_output(['xsel'])
        self.paste(text)

    def scroll_line_up(self):
        queue_action(self.char_grid.scroll, 'line', True)

    def scroll_line_down(self):
        queue_action(self.char_grid.scroll, 'line', False)

    def scroll_page_up(self):
        queue_action(self.char_grid.scroll, 'page', True)

    def scroll_page_down(self):
        queue_action(self.char_grid.scroll, 'page', False)

    def scroll_home(self):
        queue_action(self.char_grid.scroll, 'full', True)

    def scroll_end(self):
        queue_action(self.char_grid.scroll, 'full', False)
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
