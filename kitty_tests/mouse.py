#!/usr/bin/env python3
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2016, Kovid Goyal <kovid at kovidgoyal.net>

from functools import partial

from kitty.fast_data_types import (
    create_mock_window, send_mock_mouse_event_to_window, GLFW_MOUSE_BUTTON_LEFT
)

from . import BaseTest


def send_mouse_event(window, button=-1, modifiers=0, is_release=False, x=0, y=0):
    send_mock_mouse_event_to_window(window, button, modifiers, is_release, x, y)


class TestMouse(BaseTest):

    def test_mouse_selection(self):
        s = self.create_screen()
        w = create_mock_window(s)
        ev = partial(send_mouse_event, w)

        def sel():
            return s.text_for_selection()[0]

        def init():
            s.reset()
            s.draw('12345')
            s.draw('67890')
            s.draw('abcde')
            s.draw('fghij')
            s.draw('klmno')

        init()
        ev(GLFW_MOUSE_BUTTON_LEFT)
        ev(x=3)
        self.ae(sel(), '1234')
        ev(GLFW_MOUSE_BUTTON_LEFT, x=3, is_release=True)
        self.ae(sel(), '1234')
