#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2016, Kovid Goyal <kovid at kovidgoyal.net>

from PyQt5.QtCore import QObject

from .screen import Screen
from .term import TerminalWidget
from .utils import resize_pty, hangup


class Boss(QObject):

    def __init__(self, opts, parent=None):
        QObject.__init__(self, parent)
        self.screen = Screen(opts, parent=self)
        self.term = TerminalWidget(opts, self.screen.linebuf, parent)
        self.term.relayout_lines.connect(self.relayout_lines)
        resize_pty(self.screen.columns, self.screen.lines)

    def apply_opts(self, opts):
        self.screen.apply_opts(opts)
        self.term.apply_opts(opts)

    def relayout_lines(self, previous, cells_per_line, previousl, lines_per_screen):
        self.screen.resize(lines_per_screen, cells_per_line)
        resize_pty(cells_per_line, lines_per_screen)

    def shutdown(self):
        del self.master_fd
        del self.slave_fd
        hangup()
