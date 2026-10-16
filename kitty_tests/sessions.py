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

    def test_session_os_window_geometry(self) -> None:
        from kitty.fast_data_types import WINDOW_FULLSCREEN, WINDOW_MAXIMIZED, WINDOW_NORMAL
        from kitty.tabs import os_window_geometry_as_session

        opts = self.set_options()
        first, second = parse_session('os_window_position -1200x80\nlaunch\nnew_os_window\nlaunch', opts)
        self.ae((first.os_window_position, second.os_window_position), ((-1200, 80), None))
        with self.assertRaises(ValueError):
            tuple(parse_session('os_window_position 100\nlaunch', opts))

        g = {'x': -1200, 'y': 80, 'width': 1180, 'height': 760, 'state': WINDOW_MAXIMIZED}
        lines = os_window_geometry_as_session(g)
        self.ae(lines, ['os_window_size 1180 760', 'os_window_position -1200x80', 'os_window_state maximized'])
        self.ae(os_window_geometry_as_session(g, include_position=False), [lines[0], lines[2]])
        (s,) = parse_session('\n'.join(lines + ['launch']), opts)
        size = WindowSizes(WindowSize(1180, 'px'), WindowSize(760, 'px'))
        self.ae((s.os_window_size, s.os_window_position, s.os_window_state), (size, (-1200, 80), 'maximized'))
        for state, name in ((WINDOW_FULLSCREEN, 'fullscreen'), (WINDOW_NORMAL, 'normal')):
            self.ae(os_window_geometry_as_session({**g, 'state': state})[-1], f'os_window_state {name}')
