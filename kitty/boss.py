#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2016, Kovid Goyal <kovid at kovidgoyal.net>

from collections import deque

from PyQt5.QtCore import QObject

from .data_types import Line, rewrap_lines
from .term import TerminalWidget


class Boss(QObject):

    def __init__(self, opts, parent=None):
        QObject.__init__(self, parent)
        self.linebuf = deque(maxlen=max(1000, opts.scrollback_lines))
        self.term = TerminalWidget(opts, self.linebuf, parent)
        self.term.relayout_lines.connect(self.relayout_lines)

    def apply_opts(self, opts):
        if opts.scrollback_lines != self.linebuf.maxlen:
            self.linebuf = deque(self.linebuf, maxlen=max(1000, opts.scrollback_lines))
            self.term.linebuf = self.linebuf
        self.term.apply_opts(opts)

    def relayout_lines(self, previous, cells_per_line):
        if previous == cells_per_line:
            return
        old = self.linebuf.copy()
        self.linebuf.clear()
        self.linebuf.extend(rewrap_lines(old, cells_per_line))
