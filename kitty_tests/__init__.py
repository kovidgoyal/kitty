#!/usr/bin/env python3
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2016, Kovid Goyal <kovid at kovidgoyal.net>

import os
from unittest import TestCase

from kitty.config import (
    Options, defaults, finalize_keys, finalize_mouse_mappings, merge_configs
)
from kitty.fast_data_types import (
    Cursor, HistoryBuf, LineBuf, Screen, set_options
)
from kitty.types import MouseEvent


class Callbacks:

    def __init__(self, opts) -> None:
        self.clear()
        self.opts = opts

    def write(self, data) -> None:
        self.wtcbuf += data

    def title_changed(self, data) -> None:
        self.titlebuf += data

    def icon_changed(self, data) -> None:
        self.iconbuf += data

    def set_dynamic_color(self, code, data) -> None:
        self.colorbuf += data or ''

    def set_color_table_color(self, code, data) -> None:
        self.ctbuf += ''

    def request_capabilities(self, q) -> None:
        from kitty.terminfo import get_capabilities
        for c in get_capabilities(q, None):
            self.write(c.encode('ascii'))

    def use_utf8(self, on) -> None:
        self.iutf8 = on

    def desktop_notify(self, osc_code: int, raw_data: str) -> None:
        self.notifications.append((osc_code, raw_data))

    def open_url(self, url: str, hyperlink_id: int) -> None:
        self.open_urls.append((url, hyperlink_id))

    def clear(self) -> None:
        self.wtcbuf = b''
        self.iconbuf = self.titlebuf = self.colorbuf = self.ctbuf = ''
        self.iutf8 = True
        self.notifications = []
        self.open_urls = []

    def on_activity_since_last_focus(self) -> None:
        pass

    def on_mouse_event(self, event):
        ev = MouseEvent(**event)
        action = self.opts.mousemap.get(ev)
        if action is None:
            return False
        self.current_mouse_button = ev.button
        getattr(self, action.func)(*action.args)
        self.current_mouse_button = 0
        return True


def filled_line_buf(ynum=5, xnum=5, cursor=Cursor()):
    ans = LineBuf(ynum, xnum)
    cursor.x = 0
    for i in range(ynum):
        t = ('{}'.format(i)) * xnum
        ans.line(i).set_text(t, 0, xnum, cursor)
    return ans


def filled_cursor():
    ans = Cursor()
    ans.bold = ans.italic = ans.reverse = ans.strikethrough = ans.dim = True
    ans.fg = 0x101
    ans.bg = 0x201
    ans.decoration_fg = 0x301
    return ans


def filled_history_buf(ynum=5, xnum=5, cursor=Cursor()):
    lb = filled_line_buf(ynum, xnum, cursor)
    ans = HistoryBuf(ynum, xnum)
    for i in range(ynum):
        ans.push(lb.line(i))
    return ans


class BaseTest(TestCase):

    ae = TestCase.assertEqual
    maxDiff = 2000
    is_ci = os.environ.get('CI') == 'true'

    def set_options(self, options=None):
        final_options = {'scrollback_pager_history_size': 1024, 'click_interval': 0.5}
        if options:
            final_options.update(options)
        options = Options(merge_configs(defaults._asdict(), final_options))
        finalize_keys(options)
        finalize_mouse_mappings(options)
        set_options(options)
        return options

    def create_screen(self, cols=5, lines=5, scrollback=5, cell_width=10, cell_height=20, options=None):
        opts = self.set_options(options)
        c = Callbacks(opts)
        s = Screen(c, lines, cols, scrollback, cell_width, cell_height, 0, c)
        return s

    def assertEqualAttributes(self, c1, c2):
        x1, y1, c1.x, c1.y = c1.x, c1.y, 0, 0
        x2, y2, c2.x, c2.y = c2.x, c2.y, 0, 0
        try:
            self.assertEqual(c1, c2)
        finally:
            c1.x, c1.y, c2.x, c2.y = x1, y1, x2, y2
