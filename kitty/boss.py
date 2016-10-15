#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2016, Kovid Goyal <kovid at kovidgoyal.net>

from collections import deque

from PyQt5.QtCore import QObject

from .term import TerminalWidget

class Boss(QObject):

    def __init__(self, opts, parent=None):
        self.linebuf = deque(maxlen=max(1000, opts.scrollback_lines))
        self.term = TerminalWidget(opts, self.linebuf, parent)
        self.term.relayout_lines.connect(self.relayout_lines)

    def apply_opts(self, opts):
        if opts.scrollback_lines != self.linebuf.maxlen:
            self.linebuf, old = deque(maxlen=max(1000, opts.scrollback_lines)), self.linebuf
            self.linebuf.extend(old)
        self.term.apply_opts(opts)

    def relayout_lines(self):
        pass
