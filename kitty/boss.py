#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2016, Kovid Goyal <kovid at kovidgoyal.net>

import os
import io

from PyQt5.QtCore import QObject, QSocketNotifier

from .term import TerminalWidget
from .utils import resize_pty, hangup, create_pty


class Boss(QObject):

    def __init__(self, opts, parent, dump_commands):
        QObject.__init__(self, parent)
        self.shutting_down = False
        self.write_buf = memoryview(b'')
        self.read_notifier = QSocketNotifier(create_pty()[0], QSocketNotifier.Read, self)
        self.read_notifier.activated.connect(self.read_ready)
        self.write_notifier = QSocketNotifier(create_pty()[0], QSocketNotifier.Write, self)
        self.write_notifier.setEnabled(False)
        self.write_notifier.activated.connect(self.write_ready)
        self.term = TerminalWidget(opts, parent, dump_commands)
        self.term.relayout_lines.connect(self.relayout_lines)
        self.term.send_data_to_child.connect(self.write_to_child)
        self.term.write_to_child.connect(self.write_to_child)
        resize_pty(80, 24)

    def apply_opts(self, opts):
        self.term.apply_opts(opts)

    def read_ready(self, read_fd):
        if self.shutting_down:
            return
        try:
            data = os.read(read_fd, io.DEFAULT_BUFFER_SIZE)
        except EnvironmentError:
            data = b''
        if not data:
            # EOF
            self.read_notifier.setEnabled(False)
            self.parent().child_process_died()
            return
        self.term.feed(data)

    def write_ready(self, write_fd):
        if not self.shutting_down:
            while self.write_buf:
                n = os.write(write_fd, self.write_buf)
                if not n:
                    return
                self.write_buf = self.write_buf[n:]
        self.write_notifier.setEnabled(False)

    def write_to_child(self, data):
        self.write_buf = memoryview(self.write_buf.tobytes() + data)
        self.write_notifier.setEnabled(True)

    def relayout_lines(self, cells_per_line, lines_per_screen):
        resize_pty(cells_per_line, lines_per_screen)

    def shutdown(self):
        self.shutting_down = True
        self.read_notifier.setEnabled(False)
        hangup()
