#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2016, Kovid Goyal <kovid at kovidgoyal.net>


from PyQt5.QtCore import pyqtSignal, QTimer, Qt
from PyQt5.QtGui import QPainter
from PyQt5.QtWidgets import QWidget, QApplication

from .config import Options
from .tracker import ChangeTracker
from .keys import key_event_to_data
from .screen import Screen
from .render import Renderer
from pyte.streams import Stream, DebugStream
from pyte import modes as mo


class TerminalWidget(QWidget):

    relayout_lines = pyqtSignal(object, object)
    write_to_child = pyqtSignal(object)
    title_changed = pyqtSignal(object)
    icon_changed = pyqtSignal(object)
    send_data_to_child = pyqtSignal(object)

    def __init__(self, opts: Options, parent: QWidget=None, dump_commands: bool=False):
        QWidget.__init__(self, parent)
        self.setAttribute(Qt.WA_OpaquePaintEvent, True)
        self.setAutoFillBackground(False)
        self.setFocusPolicy(Qt.WheelFocus)
        self.debounce_resize_timer = t = QTimer(self)
        t.setSingleShot(True)
        t.setInterval(50)
        t.timeout.connect(self.do_layout)

        self.tracker = ChangeTracker(self)
        sclass = DebugStream if dump_commands else Stream
        self.screen = Screen(opts, self.tracker, parent=self)
        for s in 'write_to_child title_changed icon_changed'.split():
            getattr(self.screen, s).connect(getattr(self, s))
        self.stream = sclass(self.screen)
        self.feed = self.stream.feed
        self.renderer = Renderer(self.screen, self.logicalDpiX(), self.logicalDpiY(), self)
        self.tracker.dirtied.connect(self.renderer.update_screen)
        self.renderer.update_required.connect(self.update_required)
        self.renderer.relayout_lines.connect(self.relayout_lines)
        self.apply_opts(opts)

    def update_required(self):
        self.update()

    def apply_opts(self, opts):
        self.screen.apply_opts(opts)
        self.opts = opts
        self.renderer.apply_opts(opts)
        self.do_layout()

    def do_layout(self):
        self.renderer.resize(self.size())
        self.update()

    def resizeEvent(self, ev):
        self.debounce_resize_timer.start()

    def paintEvent(self, ev):
        if self.size() != self.renderer.size():
            return
        p = QPainter(self)
        self.renderer.render(p)
        p.end()

    def keyPressEvent(self, ev):
        mods = ev.modifiers()
        if mods & Qt.ControlModifier and mods & Qt.ShiftModifier:
            ev.accept()
            return  # Terminal shortcuts
        data = key_event_to_data(ev, mods)
        if data:
            self.send_data_to_child.emit(data)
            ev.accept()
            return
        return QWidget.keyPressEvent(self, ev)

    def mousePressEvent(self, ev):
        if ev.button() == Qt.MiddleButton:
            c = QApplication.clipboard()
            if c.supportsSelection():
                text = c.text(c.Selection)
                if text:
                    text = text.encode('utf-8')
                    if self.screen.in_bracketed_paste_mode:
                        text = mo.BRACKETED_PASTE_START + text + mo.BRACKETED_PASTE_END
                    self.send_data_to_child.emit(text)
                ev.accept()
                return
        return QWidget.mousePressEvent(self, ev)

    def focusInEvent(self, ev):
        if self.screen.enable_focus_tracking:
            self.send_data_to_child.emit(b'\x1b[I')
        self.renderer.set_has_focus(True)
        return QWidget.focusInEvent(self, ev)

    def focusOutEvent(self, ev):
        if self.screen.enable_focus_tracking:
            self.send_data_to_child.emit(b'\x1b[O')
        self.renderer.set_has_focus(False)
        return QWidget.focusOutEvent(self, ev)
