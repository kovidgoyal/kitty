#!/usr/bin/env python
# License: GPLv3 Copyright: 2026, kitty contributors

from functools import partial
from types import SimpleNamespace
from unittest.mock import Mock, patch

from kitty.boss import Boss
from kitty.launch import load_watch_modules
from kitty.tabs import SpecialWindow

from .base import BaseTest


class IterableArgumentsTest(BaseTest):
    def test_window_creation_with_iterable_arguments(self):
        for method in ('_new_os_window', '_new_tab'):
            for container in (list, tuple, iter):
                for values in ((), ('/bin/echo', 'hello')):
                    with self.subTest(method=method, container=container, values=values):
                        tm = SimpleNamespace(new_tab=Mock())
                        boss = SimpleNamespace(active_window=None, os_window_map={1: tm}, active_tab_manager=tm, add_os_window=Mock(return_value=1))
                        boss.args_to_special_window = partial(Boss.args_to_special_window, boss)
                        with (
                            patch('kitty.boss.get_options'),
                            patch('kitty.boss.create_sessions', return_value=iter((SimpleNamespace(),))) as sessions,
                        ):
                            getattr(Boss, method)(boss, container(values))
                        call = sessions.call_args if method == '_new_os_window' else tm.new_tab.call_args
                        special = call.kwargs['special_window']
                        if values:
                            self.ae(special.cmd, list(values))
                        else:
                            self.assertIsNone(special)

    def test_special_window_arguments_are_preserved(self):
        special = SpecialWindow(['/bin/echo', 'hello'])
        tm = SimpleNamespace(new_tab=Mock())
        boss = SimpleNamespace(os_window_map={1: tm}, active_tab_manager=tm, add_os_window=Mock(return_value=1))
        with (
            patch('kitty.boss.get_options'),
            patch('kitty.boss.create_sessions', return_value=iter((SimpleNamespace(),))) as sessions,
        ):
            Boss._new_os_window(boss, special)
        Boss._new_tab(boss, special)
        self.assertIs(sessions.call_args.kwargs['special_window'], special)
        self.assertIs(tm.new_tab.call_args.kwargs['special_window'], special)

    def test_config_error_iterable(self):
        for container in (list, tuple, iter):
            for values in ((), ('configuration error',)):
                with self.subTest(container=container, values=values):
                    boss = SimpleNamespace(show_error=Mock())
                    Boss.show_bad_config_lines(boss, (), container(values))
                    message = boss.show_error.call_args.args[1]
                    self.ae(message, 'In final effective configuration:\nconfiguration error' if values else '')

    def test_watcher_iterable(self):
        for container in (list, tuple, iter):
            for values in ((), ('watcher.py',)):
                with self.subTest(container=container, values=values):
                    on_load, on_close = Mock(), Mock()
                    with (
                        patch('kitty.launch.get_boss', return_value=None),
                        patch('kitty.launch.resolve_custom_file', side_effect=lambda path: path),
                        patch.dict('kitty.launch.watcher_modules', {}, clear=True),
                        patch('runpy.run_path', return_value={'on_load': on_load, 'on_close': on_close}) as load,
                    ):
                        watchers = load_watch_modules(container(values))
                    if values:
                        self.ae(watchers.on_close, [on_close])
                        load.assert_called_once_with('watcher.py', run_name='__kitty_watcher__')
                        on_load.assert_called_once_with(None, {})
                    else:
                        self.assertIsNone(watchers)
                        load.assert_not_called()
