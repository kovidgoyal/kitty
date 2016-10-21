#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2016, Kovid Goyal <kovid at kovidgoyal.net>


from PyQt5.QtCore import Qt, QObject, QEvent

CTRL_MASK = 0b10011111

key_map = {
    Qt.Key_Up: 'OA',
    Qt.Key_Down: 'OB',
    Qt.Key_Left: 'OD',
    Qt.Key_Right: 'OC',
    Qt.Key_Home: 'OH',
    Qt.Key_End: 'OF',
    Qt.Key_Insert: '[2~',
    Qt.Key_Delete: '[3~',
    Qt.Key_PageUp: '[5~',
    Qt.Key_PageDown: '[6~',
    Qt.Key_F1: 'OP',
    Qt.Key_F2: 'OQ',
    Qt.Key_F3: 'OR',
    Qt.Key_F4: 'OS',
    Qt.Key_F5: '[15~',
    Qt.Key_F6: '[17~',
    Qt.Key_F7: '[18~',
    Qt.Key_F8: '[19~',
    Qt.Key_F9: '[20~',
    Qt.Key_F10: '[21~',
    Qt.Key_F11: '[23~',
    Qt.Key_F12: '[24~',
}


def key_event_to_data(ev, mods):
    data = bytearray()
    if mods & Qt.AltModifier:
        data.append(27)
    x = key_map.get(ev.key())
    if x is not None:
        data.extend(b'\033' + x.encode('ascii'))
    else:
        t = ev.text()
        if t:
            t = t.encode('utf-8')
            if mods & Qt.ControlModifier and len(t) == 1 and 0 < t[0] & CTRL_MASK < 33:
                data.append(t[0] & CTRL_MASK)
            else:
                data.extend(t)
    return bytes(data)


class KeyFilter(QObject):

    def __init__(self, parent=None):
        QObject.__init__(self, parent)
        self.disabled = False

    @property
    def disable_filtering(self):
        return self

    def __enter__(self):
        self.disabled = True

    def __exit__(self, *args):
        self.disabled = False

    def eventFilter(self, watched, event):
        if self.disabled:
            return False
        etype = event.type()
        if etype == QEvent.KeyPress:
            # We use a global event filter to prevent Qt from re-painting the
            # entire terminal widget on a Tab key press
            app = self.parent()
            window, fw = app.activeWindow(), app.focusWidget()
            if hasattr(window, 'boss') and fw is window.boss.term:
                window.boss.term.keyPressEvent(event)
                if event.isAccepted():
                    return True
        return False
