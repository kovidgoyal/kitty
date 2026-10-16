#!/usr/bin/env python
# License: GPL v3 Copyright: 2026, Kovid Goyal <kovid at kovidgoyal.net>


from kitty.os_window_size import WindowSize, WindowSizes, initial_window_size_func
from kitty.session import get_os_window_sizing_data, parse_session

from .base import BaseTest


class TestSessions(BaseTest):

    def test_session_size_overrides_remembered_size(self) -> None:
        opts = self.set_options({'remember_window_size': True})
        with_size, without_size = parse_session('os_window_size 1180 760\nlaunch\nnew_os_window\nlaunch', opts)
        remembered = {'window-size': (900, 600)}
        sd = get_os_window_sizing_data(opts, with_size)
        self.ae((sd.remember_window_size, sd.initial_window_sizes), (False, WindowSizes(WindowSize(1180, 'px'), WindowSize(760, 'px'))))
        for session in (without_size, None):
            sd = get_os_window_sizing_data(opts, session)
            self.assertTrue(sd.remember_window_size)
            self.ae(initial_window_size_func(sd, remembered)(10, 20, 72, 72, 1, 1), (900, 600))
