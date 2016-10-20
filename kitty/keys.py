#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2016, Kovid Goyal <kovid at kovidgoyal.net>


from PyQt5.QtCore import Qt

CTRL_MASK = 0b10011111


def key_event_to_data(ev, mods):
    data = bytearray()
    if mods & Qt.AltModifier:
        data.append(27)
    t = ev.text()
    if t:
        t = t.encode('utf-8')
        if mods & Qt.ControlModifier and len(t) == 1 and 0 < t[0] & CTRL_MASK < 33:
            data.append(t[0] & CTRL_MASK)
        else:
            data.extend(t)
    return bytes(data)
