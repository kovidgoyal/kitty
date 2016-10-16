#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2016, Kovid Goyal <kovid at kovidgoyal.net>

from PyQt5.QtCore import QObject

from .screen import Screen
from .term import TerminalWidget


class Boss(QObject):

    def __init__(self, opts, parent=None):
        QObject.__init__(self, parent)
        self.screen = Screen(opts, parent=self)
        self.term = TerminalWidget(opts, self.screen.linebuf, parent)
        self.term.relayout_lines.connect(self.relayout_lines)

    def apply_opts(self, opts):
        self.screen.apply_opts(opts)
        self.term.apply_opts(opts)

    def relayout_lines(self, previous, cells_per_line, previousl, lines_per_screen):
        self.screen.resize(lines_per_screen, cells_per_line)
