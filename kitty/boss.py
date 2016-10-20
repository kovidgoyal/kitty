#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2016, Kovid Goyal <kovid at kovidgoyal.net>

import os
import io

from PyQt5.QtCore import QObject, QSocketNotifier

from .screen import Screen
from .term import TerminalWidget
from .utils import resize_pty, hangup, create_pty
from .tracker import ChangeTracker
from pyte.streams import Stream


class Boss(QObject):

    def __init__(self, opts, parent):
        QObject.__init__(self, parent)
        self.write_buf = memoryview(b'')
        self.read_notifier = QSocketNotifier(create_pty()[0], QSocketNotifier.Read, self)
        self.read_notifier.activated.connect(self.read_ready)
        self.write_notifier = QSocketNotifier(create_pty()[0], QSocketNotifier.Write, self)
        self.write_notifier.setEnabled(False)
        self.write_notifier.activated.connect(self.write_ready)
        self.tracker = ChangeTracker(self)
        self.screen = s = Screen(opts, self.tracker, parent=self)
        self.stream = Stream(s)
        s.write_to_child.connect(self.write_to_child)
        self.term = TerminalWidget(opts, self.tracker, self.screen.linebuf, parent)
        self.term.relayout_lines.connect(self.relayout_lines)
        resize_pty(self.screen.columns, self.screen.lines)

    def apply_opts(self, opts):
        self.screen.apply_opts(opts)
        self.term.apply_opts(opts)

    def read_ready(self, read_fd):
        data = os.read(read_fd, io.DEFAULT_BUFFER_SIZE)
        if not data:
            # EOF
            self.parent().child_process_died()
            return
        self.stream.feed(data)

    def write_ready(self, write_fd):
        while self.write_buf:
            n = os.write(write_fd, io.DEFAULT_BUFFER_SIZE)
            if not n:
                return
            self.write_buf = self.write_buf[n:]
        self.write_notifier.setEnabled(False)

    def write_to_child(self, data):
        self.write_buf = memoryview(self.write_buf.tobytes() + data)
        self.write_notifier.setEnabled(True)

    def relayout_lines(self, previous, cells_per_line, previousl, lines_per_screen):
        self.screen.resize(lines_per_screen, cells_per_line)
        resize_pty(cells_per_line, lines_per_screen)

    def shutdown(self):
        del self.master_fd
        del self.slave_fd
        hangup()
