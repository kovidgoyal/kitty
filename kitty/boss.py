#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2016, Kovid Goyal <kovid at kovidgoyal.net>

import os
import fcntl
import termios
import struct

from PyQt5.QtCore import QObject

from .screen import Screen
from .term import TerminalWidget


class Boss(QObject):

    def __init__(self, opts, parent=None):
        QObject.__init__(self, parent)
        self.screen = Screen(opts, parent=self)
        self.term = TerminalWidget(opts, self.screen.linebuf, parent)
        self.term.relayout_lines.connect(self.relayout_lines)
        self.master_fd, self.slave_fd = os.openpty()

    def apply_opts(self, opts):
        self.screen.apply_opts(opts)
        self.term.apply_opts(opts)

    def relayout_lines(self, previous, cells_per_line, previousl, lines_per_screen):
        self.screen.resize(lines_per_screen, cells_per_line)
        fcntl.ioctl(self.master_fd, termios.TIOCSWINSZ, struct.pack('4H', cells_per_line, lines_per_screen, 0, 0))

    def shutdown(self):
        os.close(self.slave_fd), os.close(self.master_fd)
        del self.master_fd
        del self.slave_fd
