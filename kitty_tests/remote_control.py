#!/usr/bin/env python
# License: GPLv3 Copyright: 2026 Kovid Goyal <kovid at kovidgoyal.net>

import os
import subprocess
import tempfile
from types import MethodType
from unittest.mock import Mock, patch

from kitty.constants import kitty_exe
from kitty.rc.base import PayloadGetter, all_command_names, command_for_name

from .base import BaseTest


class Window:
    def __init__(self, id: int, os_window_id: int):
        self.id = id
        self.os_window_id = os_window_id


class Boss:
    def __init__(self, windows: list[Window]):
        self.active_window = windows[0]
        self.all_windows = windows

    def match_windows(self, expr: str, self_window: Window | None = None):
        if expr == 'all':
            yield from self.all_windows
            return
        for window in self.all_windows:
            if str(window.id) == expr:
                yield window

    def match_tabs(self, expr: str):
        if expr == 'all':
            yield list(self.all_windows)


class TestRemoteControl(BaseTest):
    def test_set_font_size_mapping(self):
        from kitty.boss import Boss as KittyBoss
        from kitty.rc.base import RemoteControlErrorWithoutTraceback

        for all_windows in (False, True):
            for value, operation, size in (
                ('12.5', None, 12.5),
                ('0', None, 0.0),
                ('+2', '+', 2.0),
                ('-2', '-', 2.0),
                ('*1.5', '*', 1.5),
                ('/2', '/', 2.0),
            ):
                with self.subTest(all_windows=all_windows, value=value):
                    boss = Mock(spec=KittyBoss)
                    args = ('set-font-size',) + (('--all',) if all_windows else ()) + ('--', value)
                    KittyBoss.call_remote_control(boss, None, args)
                    boss.change_font_size.assert_called_once_with(all_windows, operation, size)
        for value in ('*-2', '+-2', '/0', '*0', '+0', '-0', '*nan', '/inf', 'inf', '-nan', '*', '', 'abc'):
            with self.subTest(value=value):
                boss = Mock(spec=KittyBoss)
                with self.assertRaises(Exception):
                    KittyBoss.call_remote_control(boss, None, ('set-font-size', '--', value))
                boss.change_font_size.assert_not_called()
        # payloads sent directly by kitten @ bypass message_to_kitty
        command = command_for_name('set-font-size')
        for payload in ({'size': -2, 'increment_op': '+'}, {'size': 0, 'increment_op': '/'}, {'size': -1}):
            with self.subTest(payload=payload):
                boss = Mock(spec=KittyBoss)
                with self.assertRaises(RemoteControlErrorWithoutTraceback):
                    command.response_from_kitty(boss, None, PayloadGetter(command, payload))
                boss.change_font_size.assert_not_called()

    def test_action_parse_errors(self):
        from kitty.boss import Boss as KittyBoss
        from kitty.rc.base import RemoteControlErrorWithoutTraceback
        from kitty.remote_control import handle_cmd

        self.set_options()
        for action in ('goto_tab not-a-number', 'set_font_size invalid', 'unknown_action argument', 'goto_tab 1'):
            with self.subTest(action=action):
                boss = Mock(spec=KittyBoss, active_window=None, window_for_dispatch=None, dispatch_action=Mock(return_value=True))
                boss.combine = MethodType(KittyBoss.combine, boss)
                request = {'cmd': 'action', 'version': [0, 26, 0], 'payload': {'action': action}}
                if action == 'goto_tab 1':
                    self.ae(handle_cmd(boss, None, request, 0, None), {'ok': True})
                    boss.dispatch_action.assert_called_once()
                else:
                    with self.assertRaises(RemoteControlErrorWithoutTraceback) as cm:
                        handle_cmd(boss, None, request, 0, None)
                    msg = str(cm.exception)
                    self.assertTrue(msg.startswith(f'Failed to parse action: {action}: '), msg)
                    if action == 'unknown_action argument':
                        self.ae(msg, f'Failed to parse action: {action}: Unknown action: unknown_action')
                    boss.dispatch_action.assert_not_called()
                boss.show_error.assert_not_called()

    def test_cancel_async_auth_bypass(self):
        from kitty.boss import Boss as KittyBoss
        from kitty.remote_control import handle_cmd, is_cmd_allowed

        self.set_options({'remote_control_password': {'secret': frozenset(('ls',))}})
        base = {'cmd': 'send_text', 'version': [0, 26, 0], 'payload': {'data': 'text:x'}, 'cancel_async': True}
        for extra in ({'async_id': 'x'}, {'async_id': 'x', 'password': 'wrong'}, {'async_id': 'x', 'password': 'secret'}, {'async': ''}):
            with self.subTest(extra=extra):
                self.assertIsNot(is_cmd_allowed({**base, **extra}, None, False, {}), True)
        # a genuine cancellation is allowed without a password and must only cancel
        pcmd = {**base, 'async': 'x'}
        self.assertIs(is_cmd_allowed(pcmd, None, False, {}), True)
        command = command_for_name('send_text')
        with patch.object(command, 'response_from_kitty') as rfk, patch.object(command, 'cancel_async_request') as car:
            self.assertIsNone(handle_cmd(Mock(spec=KittyBoss), None, pcmd, 0, None))
        rfk.assert_not_called()
        car.assert_called_once()

    def test_combine_parse_error_reporting(self):
        from kitty.boss import Boss as KittyBoss

        self.set_options()
        boss = Mock(spec=KittyBoss)
        self.assertTrue(KittyBoss.combine(boss, 'goto_tab not-a-number'))
        boss.show_error.assert_called_once()
        boss.dispatch_action.assert_not_called()

    def test_select_window_exclude_active(self):
        from kitty.boss import Boss as KittyBoss

        command = command_for_name('select-window')
        for exclude_active in (False, True):
            with self.subTest(exclude_active=exclude_active):
                tab = Mock(all_window_ids_except_active_window=set())
                boss = Mock(active_tab=tab)
                args = ('select-window',) + (('--exclude-active',) if exclude_active else ())
                with patch.object(command, 'create_async_responder'):
                    KittyBoss.call_remote_control(boss, None, args)
                self.ae(boss.visual_window_select_action.call_args.kwargs['only_window_ids'], set() if exclude_active else None)

    def test_visual_window_select_empty_allowed_set(self):
        from kitty.boss import Boss as KittyBoss

        self.set_options()
        for only_active_window_visible in (False, True):
            for only_window_ids, expected in ((set(), 0), (None, 1)):
                with self.subTest(only_active_window_visible=only_active_window_visible, only_window_ids=only_window_ids):
                    window = Mock(id=1)
                    tab = Mock(tab_manager_ref=Mock(return_value=None), os_window_id=1)
                    tab.current_layout.only_active_window_visible = only_active_window_visible
                    tab.windows.iter_windows_with_number.return_value = [(0, window)]
                    boss = Mock()
                    boss.select_window_in_tab_using_overlay = lambda *a: KittyBoss.select_window_in_tab_using_overlay(boss, *a)
                    with patch('kitty.boss.current_os_window', return_value=1):
                        KittyBoss.visual_window_select_action(boss, tab, Mock(), 'Choose', only_window_ids=only_window_ids)
                    boss.visual_window_select_action_trigger.assert_called_once_with(expected)
                    boss.choose_entry.assert_not_called()

    def test_run_mapping_ignores_stdin(self):
        from kitty.boss import Boss as KittyBoss

        command = command_for_name('run')
        for is_tty in (False, True):
            with self.subTest(is_tty=is_tty):
                stdin = Mock()
                stdin.isatty.return_value = is_tty
                boss = Mock()
                with patch('sys.stdin', stdin), patch.object(command, 'create_async_responder'):
                    KittyBoss.call_remote_control(boss, None, ('run', 'cat'))
                    boss.run_background_process.call_args.kwargs['notify_on_death'](0, None)
                stdin.buffer.read.assert_not_called()
                boss.run_background_process.assert_called_once()
                call = boss.run_background_process.call_args
                self.ae(call.args[0], ['cat'])
                self.ae(call.kwargs['stdin'], b'')

    def test_set_enabled_layouts_configured(self):
        from kitty.boss import Boss as KittyBoss

        for configured in (False, True):
            with self.subTest(configured=configured):
                options = self.set_options({'enabled_layouts': ['tall']})
                boss = Mock(active_tab=Mock())
                args = ('set-enabled-layouts',) + (('--configured',) if configured else ()) + ('stack',)

                KittyBoss.call_remote_control(boss, None, args)

                boss.active_tab.set_enabled_layouts.assert_called_once_with(['stack'])
                self.ae(options.enabled_layouts, ['stack'] if configured else ['tall'])

    def test_ls_self_and_output_format(self):
        from kitty.boss import Boss as KittyBoss

        self_window = Mock()
        boss = Mock(list_os_windows=Mock(return_value=[]), serialize_state_as_session=Mock(return_value=['a', 'b']))
        self.ae(KittyBoss.call_remote_control(boss, None, ('ls', '--output-format', 'session')), 'a\nb')
        boss.list_os_windows.assert_not_called()

        KittyBoss.call_remote_control(boss, self_window, ('ls', '--self'))
        window_filter = boss.list_os_windows.call_args.args[2]
        self.assertIsNotNone(window_filter)
        self.assertTrue(window_filter(self_window))
        self.assertFalse(window_filter(Mock()))

    def test_set_os_window_title_command_is_registered(self):
        self.assertIn('set_os_window_title', all_command_names())
        self.ae(command_for_name('set-os-window-title').name, 'set-os-window-title')

    def test_set_os_window_title_dedupes_os_windows(self):
        windows = [Window(1, 11), Window(2, 11), Window(3, 22)]
        boss = Boss(windows)
        cmd = command_for_name('set-os-window-title')

        with patch('kitty.rc.set_os_window_title.set_os_window_title_impl') as setter:
            cmd.response_from_kitty(boss, windows[0], PayloadGetter(cmd, {'match': 'all', 'self': True, 'title': 'repo'}))

        self.ae({call.args for call in setter.call_args_list}, {(11, 'repo'), (22, 'repo')})

    def test_set_os_window_title_without_title_resets_override(self):
        windows = [Window(1, 11)]
        boss = Boss(windows)
        cmd = command_for_name('set-os-window-title')

        with patch('kitty.rc.set_os_window_title.set_os_window_title_impl') as setter:
            cmd.response_from_kitty(boss, windows[0], PayloadGetter(cmd, {'self': True}))

        setter.assert_called_once_with(11, '')

    def test_send_key_excludes_active_window(self):
        windows = [Window(1, 11), Window(2, 11)]
        boss = Boss(windows)
        cmd = command_for_name('send-key')
        keys = ['ctrl+a', 'ctrl+b']
        # selector -> (expected recipients without --exclude-active, with --exclude-active)
        cases = {
            'all': ({'all': True}, windows, windows[1:]),
            'match': ({'match': 'all'}, windows, windows[1:]),
            'match_tab': ({'match_tab': 'all'}, windows, windows[1:]),
            'default': ({}, windows[:1], []),
        }

        for name, (selector, expected, expected_excluding_active) in cases.items():
            for exclude_active in (False, True):
                with (
                    self.subTest(selector=name, exclude_active=exclude_active),
                    patch.object(windows[0], 'send_key', create=True) as active,
                    patch.object(windows[1], 'send_key', create=True) as other,
                ):
                    cmd.response_from_kitty(boss, None, PayloadGetter(cmd, {**selector, 'exclude_active': exclude_active, 'keys': keys}))

                    recipients = expected_excluding_active if exclude_active else expected
                    for w, mock in ((windows[0], active), (windows[1], other)):
                        if w in recipients:
                            mock.assert_called_once_with(*keys)
                        else:
                            mock.assert_not_called()

    def test_set_colors_transparent_background_colors(self):
        from kitty.fast_data_types import Color
        from kitty.rc.base import RemoteControlErrorWithoutTraceback, parse_subcommand_cli
        from kitty.remote_control import parse_rc_args

        cmd = command_for_name('set-colors')

        def payload(*args: str):
            opts, items = parse_subcommand_cli(cmd, ['set-colors'] + list(args))
            return cmd.message_to_kitty(parse_rc_args([])[0], opts, items)

        # omitted means leave unchanged, explicitly empty means clear
        self.assertNotIn('transparent_background_colors', payload('foreground=red')['colors'])
        self.ae(payload('transparent_background_colors=')['colors']['transparent_background_colors'], '')
        self.ae(payload('transparent_background_colors=red@0.5')['colors']['transparent_background_colors'], '#ff0000@0.5')

        windows = [Window(1, 11)]
        boss = Boss(windows)
        boss.color_settings_at_startup = {'foreground': Color(1, 2, 3)}
        boss.transparent_background_colors_at_startup = ((Color(0, 0, 0), 0.25),)

        def response(p):
            with patch('kitty.colors.patch_colors') as patcher:
                cmd.response_from_kitty(boss, windows[0], PayloadGetter(cmd, p))
            patcher.assert_called_once()
            return patcher.call_args.args

        self.ae(response({'colors': {'foreground': 0xFF0000}}), ({'foreground': 0xFF0000}, None, False))
        colors = {'foreground': 0xFF0000, 'transparent_background_colors': 'red@0.5'}
        self.ae(response({'colors': colors, 'configured': True}), ({'foreground': 0xFF0000}, ((Color(255, 0, 0), 0.5),), True))
        self.ae(colors['transparent_background_colors'], 'red@0.5')  # payload must not be mutated
        self.ae(response({'colors': {'transparent_background_colors': ''}}), ({}, (), False))
        # reset implies configured even when the client does not set it
        self.ae(
            response({'colors': {'transparent_background_colors': 'red@0.5'}, 'reset': True}),
            ({'foreground': int(Color(1, 2, 3))}, ((Color(0, 0, 0), 0.25),), True),
        )
        for bad in (0, 'not-a-color@0.5'):
            with self.subTest(bad=bad), self.assertRaises(RemoteControlErrorWithoutTraceback):
                response({'colors': {'transparent_background_colors': bad}})


TALK_THREAD_SURVIVES_ACCEPT_ERROR = """
import os, socket, sys, time
from kitty.fast_data_types import ChildMonitor
ls = socket.socket(socket.AF_UNIX)
ls.bind(sys.argv[1])
ls.listen(8)
cm = ChildMonitor(lambda *a: None, None, -1, ls.fileno())
a, b = socket.socketpair()
cm.inject_peer(os.dup(a.fileno()))
cm.fail_next_accepts(2)
c = socket.socket(socket.AF_UNIX)
c.connect(sys.argv[1])
deadline = time.monotonic() + 10
while cm.fail_next_accepts(-1) and time.monotonic() < deadline:
    time.sleep(0.01)
assert cm.fail_next_accepts(-1) == 0, 'injected accept errors not consumed'
cm.inject_peer(os.dup(b.fileno()))
print('ok', flush=True)
os._exit(0)
"""


TALK_THREAD_STALLED_PEER = """
import os, socket
from kitty.fast_data_types import ChildMonitor, send_data_to_peer
cm = ChildMonitor(lambda *a: None, None)
a, a_remote = socket.socketpair()
b, b_remote = socket.socketpair()
big = os.urandom(8 * 1024 * 1024)
pa = cm.inject_peer(os.dup(a.fileno()))
send_data_to_peer(pa, big)
pb = cm.inject_peer(os.dup(b.fileno()))
send_data_to_peer(pb, b'hello')
b_remote.settimeout(10)
assert b_remote.recv(16) == b'hello'
a_remote.settimeout(10)
got = bytearray()
while len(got) < len(big):
    got += a_remote.recv(1024 * 1024)
assert got == big, 'stalled peer response corrupted'
print('ok', flush=True)
os._exit(0)
"""


class TestTalkThread(BaseTest):
    def test_talk_thread_not_blocked_by_stalled_peer(self):
        p = subprocess.run([kitty_exe(), '+runpy', TALK_THREAD_STALLED_PEER], capture_output=True, text=True, timeout=30)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn('ok', p.stdout, p.stderr)

    def test_talk_thread_survives_accept_errors(self):
        with tempfile.TemporaryDirectory() as tdir:
            p = subprocess.run([kitty_exe(), '+runpy', TALK_THREAD_SURVIVES_ACCEPT_ERROR, os.path.join(tdir, 's')], capture_output=True, text=True, timeout=30)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn('ok', p.stdout, p.stderr)
        self.assertEqual(p.stderr.count('accept() on talk socket failed'), 1, p.stderr)
