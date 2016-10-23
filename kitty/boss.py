#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2016, Kovid Goyal <kovid at kovidgoyal.net>

import os
import io
import select
import signal
import struct
from threading import Thread
from queue import Queue, Empty

import glfw
from .utils import resize_pty, create_pty


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

    def __init__(self, window, opts, args):
        Thread.__init__(self, name='ChildMonitor')
        self.window = window
        self.write_queue = Queue()
        self.write_buf = memoryview(b'')
        self.child_fd = create_pty()[0]
        self.signal_fd = handle_unix_signals()
        self.read_wakeup_fd, self.write_wakeup_fd = os.pipe2(os.O_NONBLOCK | os.O_CLOEXEC)
        self.readers = [self.child_fd, self.signal_fd, self.read_wakeup_fd]
        self.writers = [self.child_fd]
        resize_pty(80, 24)

    def on_window_resize(self, window, w, h):
        pass

    def render(self):
        pass

    def wakeup(self):
        os.write(self.write_wakeup_fd, b'1')

    def on_wakeup(self):
        try:
            os.read(self.read_wakeup_fd, 1024)
        except (EnvironmentError, BlockingIOError):
            pass
        buf = b''
        while True:
            try:
                buf += self.write_queue.get_nowait()
            except Empty:
                break
        if buf:
            self.write_buf = memoryview(self.write_buf.tobytes() + buf)

    def run(self):
        while not self.shutting_down:
            readers, writers, _ = select.select(self.readers, self.writers if self.write_buf else [], [])
            for r in readers:
                if r is self.child_fd:
                    self.read_ready()
                elif r is self.read_wakeup_fd:
                    self.on_wakeup()
                elif r is self.signal_fd:
                    self.signal_received()
            if writers:
                self.write_ready()

    def signal_received(self):
        try:
            data = os.read(self.signal_fd, 1024)
        except BlockingIOError:
            return
        if data:
            signals = struct.unpack('%uB' % len(data), data)
            if signal.SIGINT in signals or signal.SIGTERM in signals:
                self.shutdown()

    def shutdown(self):
        self.shutting_down = True
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
        if not data:
            # EOF
            self.shutdown()
            return

    def write_ready(self):
        if not self.shutting_down:
            while self.write_buf:
                n = os.write(self.child_fd, self.write_buf)
                if not n:
                    return
                self.write_buf = self.write_buf[n:]

    def write_to_child(self, data):
        self.write_queue.put(data)
        self.wakeup()
