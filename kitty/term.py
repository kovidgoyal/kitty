#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2016, Kovid Goyal <kovid at kovidgoyal.net>

from PyQt5.QtWidgets import QWidget


class TerminalWidget(QWidget):

    def __init__(self, opts, parent=None):
        QWidget.__init__(self, parent)
