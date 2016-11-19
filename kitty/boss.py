#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2016, Kovid Goyal <kovid at kovidgoyal.net>

import os
import io
import signal
import select
import subprocess
import struct
from itertools import repeat
from functools import partial
from time import monotonic
from threading import Thread, current_thread
from queue import Queue, Empty

import glfw

from .constants import appname
from .char_grid import CharGrid
from .keys import interpret_text_event, interpret_key_event
from .utils import resize_pty, create_pty, sanitize_title
from .fast_data_types import (
    BRACKETED_PASTE_START, BRACKETED_PASTE_END, Screen, read_bytes_dump, read_bytes
)


def handle_unix_signals():
    read_fd, write_fd = os.pipe2(os.O_NONBLOCK | os.O_CLOEXEC)
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda x, y: None)
        signal.siginterrupt(sig, False)
    signal.set_wakeup_fd(write_fd)
    return read_fd


class Boss(Thread):

    daemon = True
    shutting_down = False
    pending_title_change = pending_icon_change = None
    pending_color_changes = {}
    SCREEN_UPDATE_DELAY = 1 / 100  # seconds

    def __init__(self, window, window_width, window_height, opts, args):
        Thread.__init__(self, name='ChildMonitor')
        self.pending_update_screen = None
        self.action_queue = Queue()
        self.child_fd = create_pty()[0]
        self.read_wakeup_fd, self.write_wakeup_fd = os.pipe2(os.O_NONBLOCK | os.O_CLOEXEC)
        self.signal_fd = handle_unix_signals()
        self.readers = [self.child_fd, self.signal_fd, self.read_wakeup_fd]
        self.writers = [self.child_fd]
        self.queue_action(self.initialize)
        self.profile = args.profile
        self.window, self.opts = window, opts
        self.screen = Screen(self)
        self.char_grid = CharGrid(self.screen, opts, window_width, window_height)
        self.read_bytes = partial(read_bytes_dump, print) if args.dump_commands else read_bytes
        self.write_buf = memoryview(b'')
        glfw.glfwSetCharModsCallback(window, self.on_text_input)
        glfw.glfwSetKeyCallback(window, self.on_key)
        glfw.glfwSetMouseButtonCallback(window, self.on_mouse_button)
        glfw.glfwSetWindowFocusCallback(window, self.on_focus)

    def queue_action(self, func, *args):
        self.action_queue.put((func, args))
        self.wakeup()

    def wakeup(self):
        os.write(self.write_wakeup_fd, b'1')

    def on_wakeup(self):
        try:
            os.read(self.read_wakeup_fd, io.DEFAULT_BUFFER_SIZE)
        except (EnvironmentError, BlockingIOError):
            pass
        while not self.shutting_down:
            try:
                func, args = self.action_queue.get_nowait()
            except Empty:
                break
            func(*args)

    def signal_received(self):
        try:
            data = os.read(self.signal_fd, io.DEFAULT_BUFFER_SIZE)
        except BlockingIOError:
            return
        if data:
            signals = struct.unpack('%uB' % len(data), data)
            if signal.SIGINT in signals or signal.SIGTERM in signals:
                self.shutdown()

    def initialize(self):
        self.char_grid.initialize()
        glfw.glfwPostEmptyEvent()

    def on_focus(self, window, focused):
        if focused:
            if self.screen.enable_focus_tracking():
                self.write_to_child(b'\x1b[I')
        else:
            if self.screen.enable_focus_tracking():
                self.write_to_child(b'\x1b[O')

    def on_mouse_button(self, window, button, action, mods):
        if action == glfw.GLFW_RELEASE:
            if button == glfw.GLFW_MOUSE_BUTTON_MIDDLE:
                # glfw has no way to get the primary selection
                # text = glfw.glfwGetClipboardString(window)
                text = subprocess.check_output(['xsel'])
                if text:
                    if self.screen.in_bracketed_paste_mode():
                        text = BRACKETED_PASTE_START.encode('ascii') + text + BRACKETED_PASTE_END.encode('ascii')
                    self.write_to_child(text)

    def on_key(self, window, key, scancode, action, mods):
        if action == glfw.GLFW_PRESS or action == glfw.GLFW_REPEAT:
            data = interpret_key_event(key, scancode, mods)
            if data:
                self.write_to_child(data)

    def on_text_input(self, window, codepoint, mods):
        data = interpret_text_event(codepoint, mods)
        if data:
            self.write_to_child(data)

    def on_window_resize(self, window, w, h):
        self.queue_action(self.apply_resize_screen, w, h)

    def apply_resize_screen(self, w, h):
        self.char_grid.resize_screen(w, h)
        sg = self.char_grid.screen_geometry
        resize_pty(sg.xnum, sg.ynum)
        glfw.glfwPostEmptyEvent()

    def apply_opts(self, opts):
        self.opts = opts
        self.queue_action(self.apply_opts_to_screen)

    def apply_opts_to_screen(self):
        self.char_grid.apply_opts(self.opts)
        self.char_grid.dirty_everything()

    def render(self):
        if self.pending_title_change is not None:
            t, self.pending_title_change = sanitize_title(self.pending_title_change or appname), None
            glfw.glfwSetWindowTitle(self.window, t)
        if self.pending_icon_change is not None:
            self.pending_icon_change = None  # TODO: Implement this
        self.char_grid.render()

    def run(self):
        if self.profile:
            import cProfile
            import pstats
            pr = cProfile.Profile()
            pr.enable()
        self.loop()
        if self.profile:
            pr.disable()
            pr.create_stats()
            s = pstats.Stats(pr)
            s.dump_stats(self.profile)

    def loop(self):
        all_readers, all_writers = self.readers, self.writers
        dispatch = list(repeat(None, max(all_readers) + 1))
        dispatch[self.child_fd] = self.read_ready
        dispatch[self.read_wakeup_fd] = self.on_wakeup
        dispatch[self.signal_fd] = self.signal_received
        while not self.shutting_down:
            timeout = None if self.pending_update_screen is None else max(0, self.pending_update_screen - monotonic())
            readers, writers, _ = select.select(all_readers, all_writers if self.write_buf else [], [], timeout)
            for r in readers:
                dispatch[r]()
            if writers:
                self.write_ready()
            if self.pending_update_screen is not None:
                if monotonic() > self.pending_update_screen:
                    self.apply_update_screen()
            elif self.screen.is_dirty():
                self.pending_update_screen = monotonic() + self.SCREEN_UPDATE_DELAY

    def close(self):
        if not self.shutting_down:
            self.queue_action(self.shutdown)

    def destroy(self):
        # Must be called in the main thread as it manipulates signal handlers
        signal.signal(signal.SIGINT, signal.SIG_DFL)
        signal.signal(signal.SIGTERM, signal.SIG_DFL)
        self.char_grid.destroy()

    def shutdown(self):
        self.shutting_down = True
        glfw.glfwSetWindowShouldClose(self.window, True)
        glfw.glfwPostEmptyEvent()

    def read_ready(self):
        if self.shutting_down:
            return
        if self.read_bytes(self.screen, self.child_fd) is False:
            self.shutdown()  # EOF

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

    def write_to_child(self, data):
        if data:
            if current_thread() is self:
                self.queue_write(data)
            else:
                self.queue_action(self.queue_write, data)

    def queue_write(self, data):
        self.write_buf = memoryview(self.write_buf.tobytes() + data)

    def apply_update_screen(self):
        self.pending_update_screen = None
        self.char_grid.update_cell_data()
        glfw.glfwPostEmptyEvent()

    def title_changed(self, new_title):
        self.pending_title_change = new_title
        glfw.glfwPostEmptyEvent()

    def icon_changed(self, new_icon):
        self.pending_icon_change = new_icon
        glfw.glfwPostEmptyEvent()

    def set_dynamic_color(self, code, value):
        wmap = {10: 'fg', 11: 'bg', 110: 'fg', 111: 'bg'}
        for val in value.decode('utf-8').split(';'):
            w = wmap.get(code)
            if w is not None:
                if code >= 110:
                    val = None
                self.pending_color_changes[w] = val
            code += 1
        self.queue_action(self.apply_change_colors)

    def apply_change_colors(self):
        self.char_grid.change_colors(self.pending_color_changes)
        self.pending_color_changes = {}
        glfw.glfwPostEmptyEvent()
