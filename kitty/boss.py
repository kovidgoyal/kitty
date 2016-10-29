#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2016, Kovid Goyal <kovid at kovidgoyal.net>

import os
import io
import signal
import asyncio
from threading import Thread, current_thread

import glfw
from pyte.streams import Stream, DebugStream

from .char_grid import CharGrid
from .screen import Screen
from .tracker import ChangeTracker
from .utils import resize_pty, create_pty


class Boss(Thread):

    daemon = True
    shutting_down = False
    pending_title_change = pending_icon_change = None
    pending_color_changes = {}

    def __init__(self, window, window_width, window_height, opts, args):
        Thread.__init__(self, name='ChildMonitor')
        self.child_fd = create_pty()[0]
        self.loop = asyncio.get_event_loop()
        self.loop.add_signal_handler(signal.SIGINT, lambda: self.loop.call_soon_threadsafe(self.shutdown))
        self.loop.add_signal_handler(signal.SIGTERM, lambda: self.loop.call_soon_threadsafe(self.shutdown))
        self.loop.add_reader(self.child_fd, self.read_ready)
        self.queue_action = self.loop.call_soon_threadsafe
        self.window, self.opts = window, opts
        self.tracker = ChangeTracker(self.mark_dirtied)
        self.screen = Screen(self.opts, self.tracker, self)
        self.char_grid = CharGrid(self.screen, opts, window_width, window_height)
        sclass = DebugStream if args.dump_commands else Stream
        self.stream = sclass(self.screen)
        self.write_buf = memoryview(b'')
        resize_pty(80, 24)

    def on_window_resize(self, window, w, h):
        self.queue_action(self.resize_screen, w, h)

    def resize_screen(self, w, h):
        self.char_grid.resize_screen(w, h)

    def apply_opts(self, opts):
        self.opts = opts
        self.queue_action(self.apply_opts_to_screen)

    def apply_opts_to_screen(self):
        self.screen.apply_opts(self.opts)
        self.char_grid.apply_opts(self.opts)
        self.char_grid.dirty_everything()

    def render(self):
        if self.pending_title_change is not None:
            glfw.glfwSetWindowTitle(self.window, self.pending_title_change)
            self.pending_title_change = None
        if self.pending_icon_change is not None:
            self.pending_icon_change = None  # TODO: Implement this
        self.char_grid.render()

    def run(self):
        try:
            self.loop.run_forever()
        finally:
            self.loop.close()

    def shutdown(self):
        self.shutting_down = True
        self.loop.stop()
        glfw.glfwSetWindowShouldClose(self.window, True)
        glfw.glfwPostEmptyEvent()

    def read_ready(self):
        if self.shutting_down:
            return
        try:
            data = os.read(self.child_fd, io.DEFAULT_BUFFER_SIZE)
        except BlockingIOError:
            return
        except EnvironmentError:
            data = b''
        if data:
            self.stream.feed(data)
        else:  # EOF
            self.shutdown()

    def write_ready(self):
        if not self.shutting_down:
            while self.write_buf:
                try:
                    n = os.write(self.child_fd, self.write_buf)
                except BlockingIOError:
                    n = 0
                if not n:
                    return
                self.write_buf = self.write_buf[n:]
            self.loop.remove_writer(self.child_fd)

    def write_to_child(self, data):
        if data:
            if current_thread() is self:
                self.queue_write(data)
            else:
                self.queue_action(self.queue_write, data)

    def queue_write(self, data):
        self.write_buf = memoryview(self.write_buf.tobytes() + data)
        self.loop.add_writer(self.child_fd, self.write_ready)

    def mark_dirtied(self):
        self.queue_action(self.update_screen)

    def update_screen(self):
        changes = self.tracker.consolidate_changes()
        self.char_grid.update_screen(changes)
        glfw.glfwPostEmptyEvent()

    def title_changed(self, new_title):
        self.pending_title_change = new_title
        glfw.glfwPostEmptyEvent()

    def icon_changed(self, new_icon):
        self.pending_icon_change = new_icon
        glfw.glfwPostEmptyEvent()

    def change_default_color(self, which, value):
        self.pending_color_changes[which] = value
        self.queue_action(self.change_colors)

    def change_colors(self):
        self.char_grid.change_colors(self.pending_color_changes)
        self.pending_color_changes = {}
        glfw.glfwPostEmptyEvent()
