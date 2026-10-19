#!/usr/bin/env python
# License: GPL v3 Copyright: 2026, Kovid Goyal <kovid at kovidgoyal.net>


from kitty.fast_data_types import Screen
from kitty.os_window_size import WindowSize, WindowSizes, initial_window_size_func
from kitty.session import get_os_window_sizing_data, parse_session

from .base import BaseTest, parse_bytes


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

    def test_scrollback_for_restore(self) -> None:
        from kitty.logout_session import sanitize_restored_output, scrollback_for_restore
        from kitty.window import as_text

        def restore(data: bytes, cols: int = 10, lines: int = 4, scrollback: int = 20) -> Screen:
            s = self.create_screen(cols=cols, lines=lines, scrollback=scrollback)
            s.restore_scrollback(sanitize_restored_output(data.decode()).encode())
            return s

        def text(s: Screen) -> list[str]:
            return as_text(s, add_history=True).rstrip('\n').splitlines()

        src = self.create_screen(cols=10, lines=4, scrollback=20)
        parse_bytes(
            src, b''.join(b'line %d\r\n' % i for i in range(8)) + b'\x1b[31mred\x1b[m 0123456789abcdef\r\n\x1b]8;;https://x.org\x1b\\link\x1b]8;;\x1b\\'
        )
        expected, expected_ansi = text(src), as_text(src, as_ansi=True, add_history=True).rstrip('\n')
        # Output on the alternate screen, such as from a full screen program, is not restored
        parse_bytes(src, b'\x1b[?1049hfull screen program')
        data = scrollback_for_restore(src)
        self.assertNotIn(b'full screen program', data)
        self.assertFalse(data.endswith(b'\r\n'))
        same_width = restore(data)
        self.ae(text(same_width), expected)
        self.ae(as_text(same_width, as_ansi=True, add_history=True).rstrip('\n'), expected_ansi)
        # Wrapped lines are re-wrapped to the width of the new screen
        wider = restore(data, cols=30)
        self.ae(text(wider)[-2:], ['red 0123456789abcdef', 'link'])
        self.assertTrue(any(url.endswith('https://x.org') for url, hyperlink_id in wider.hyperlinks_as_set()))

        # The scrollback pager history is not saved, so at most scrollback + lines lines are restored
        src = self.create_screen(cols=10, lines=4, scrollback=5)
        parse_bytes(src, b'\r\n'.join(b'%d' % i for i in range(30)))
        self.ae(text(restore(scrollback_for_restore(src), scrollback=50)), [str(i) for i in range(21, 30)])

        # The shell prompt the cursor is at is not restored, since the restored shell shows a new one
        def restored_lines(data: bytes, lines: int = 6) -> list[str]:
            src = self.create_screen(cols=20, lines=lines, scrollback=50)
            parse_bytes(src, data)
            return text(restore(scrollback_for_restore(src), cols=20, lines=lines, scrollback=50))

        prompt, output = b'\x1b]133;A\x07', b'\x1b]133;C\x07'
        self.ae(restored_lines(prompt + b'$ ls\r\n' + output + b'a\r\nb\r\n' + prompt + b'$ partial'), ['$ ls', 'a', 'b'])
        two_line_prompt = prompt + b'~/project on main\r\n$ '
        self.ae(restored_lines(two_line_prompt + b'ls\r\n' + output + b'a\r\n' + two_line_prompt), ['~/project on main', '$ ls', 'a'])
        many = b''.join(b'%d\r\n' % i for i in range(10))
        self.ae(restored_lines(prompt + b'$ seq\r\n' + output + many + prompt + b'$ ', lines=4), ['$ seq'] + [str(i) for i in range(10)])
        # A running command is restored with all its output
        self.ae(restored_lines(prompt + b'$ tail -f log\r\n' + output + b'a\r\nb'), ['$ tail -f log', 'a', 'b'])

        # Shell integration marks are not restored, so restored output is not treated as the output of a command
        src = self.create_screen(cols=20, lines=6, scrollback=50)
        parse_bytes(src, prompt + b'$ ls\r\n' + output + b'a\r\n' + prompt + b'$ ')
        data = scrollback_for_restore(src)
        self.assertIn(b'\x1b]133;C', data)
        self.assertNotIn('\x1b]133;', sanitize_restored_output(data.decode()))

        # Output larger than the parser buffer
        big = self.create_screen(cols=80, lines=4, scrollback=20)
        big.restore_scrollback(b''.join(b'%05d %s\r\n' % (i, b'x' * 70) for i in range(16000)))
        self.ae(text(big)[-1], '15999 ' + 'x' * 70)

        # Restoring scrollback while the child is writing to the screen raises instead of crashing
        s = self.create_screen()
        s.test_create_write_buffer()
        with self.assertRaises(RuntimeError):
            s.restore_scrollback(b'x')

    def test_sanitize_restored_output(self) -> None:
        from kitty.logout_session import sanitize_restored_output as s

        sgr, link, link_end, sized = '\x1b[1;38:2:1:2:3m', '\x1b]8;id=1;https://x.org\x1b\\', '\x1b]8;;\x07', '\x1b]66;s=2;big\x1b\\'
        text = f'{sgr}bold\x1b[m {link}link{link_end} {sized}\ttab\r\n'
        self.ae(s(text), text)
        for unsafe, expected in (
            ('\x1b]52;c;aGVsbG8=\x07', 'ab'),
            ('\x1b]133;A\x1b\\', 'ab'),
            ('\x1b]99;;notification\x1b\\', 'ab'),
            ('\x1bP@kitty-cmd{"cmd":"ls"}\x1b\\', 'ab'),
            ('\x1b_Gf=100;AAAA\x1b\\', 'ab'),
            ('\x1b[2J', 'ab'),
            ('\x1b[?1049h', 'ab'),
            ('\x1bc', 'ab'),
            ('\x07\x08\x0c', 'ab'),
            ('\x1b', 'a'),  # ESC followed by a character is an escape code
            ('\x9b2J', 'a2Jb'),  # C1 control codes are removed, leaving harmless text
            ('\x1b]0;title', 'a'),  # an unterminated OSC consumes the rest of the text
        ):
            with self.subTest(unsafe=unsafe):
                self.ae(s(f'a{unsafe}b'), expected)

    def test_logout_snapshots(self) -> None:
        from .crypto import is_rlimit_memlock_too_low

        if is_rlimit_memlock_too_low():
            self.skipTest('RLIMIT_MEMLOCK is too low')
        import json
        import os
        import shlex
        import shutil
        import stat
        import tempfile
        import time
        from unittest.mock import patch

        from kitty.constants import unserialize_launch_flag
        from kitty.fast_data_types import Secret
        from kitty.logout_session import (
            LOGOUT_CONFIRMATION_TIMEOUT,
            ProcessState,
            claim_snapshots,
            delete_snapshot,
            finish_restore,
            is_logout_in_progress,
            load_snapshot,
            lock_snapshot_for_saver,
            new_key_id,
            read_key_id,
            release_saver_lock,
            remove_all_snapshots,
            remove_orphaned_keys,
            remove_stale_snapshots,
            restore_snapshots,
            save_snapshot,
        )
        from kitty.utils import log_error

        class FakeKeyStore:
            def __init__(self) -> None:
                self.keys: dict[str, Secret] = {}
                self.fail = False

            def store(self, key_id: str, key: Secret) -> None:
                if self.fail:
                    raise OSError('User interaction is not allowed')
                self.keys[key_id] = key

            def read(self, key_id: str) -> Secret | None:
                if self.fail:
                    raise OSError('User interaction is not allowed')
                return self.keys.get(key_id)

            def delete(self, key_id: str) -> None:
                self.keys.pop(key_id, None)

            def list_ids(self) -> list[str]:
                if self.fail:
                    raise OSError('User interaction is not allowed')
                return list(self.keys)

        errors: list[str] = []
        log_error.redirect = errors.append
        self.addCleanup(delattr, log_error, 'redirect')
        opts = self.set_options()
        tdir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tdir, True)
        base = os.path.join(tdir, 'saved-at-logout')
        state = ProcessState(('--config', 'other.conf'), tdir, {'SECRET_VAR': 'value'}, 0)
        session = shlex.join(['launch', unserialize_launch_flag + json.dumps({'id': 7})])
        ks = FakeKeyStore()

        def save(pid: int, argv: tuple[str, ...] = state.argv) -> str:
            return save_snapshot(base, pid, session, {7: b'\x1b]52;c;eA==\x07seven', 8: b'eight'}, state._replace(argv=argv), ks)

        def mode(path: str) -> int:
            return stat.S_IMODE(os.stat(path).st_mode)

        def raw(path: str, name: str) -> bytes:
            with open(os.path.join(path, name), 'rb') as f:
                return f.read()

        # The saved state is readable only by the user and is encrypted with a key in the key store
        path = save(11)
        self.ae((mode(base), mode(path), mode(os.path.join(path, 'scrollback', '7')), mode(os.path.join(path, 'process.json'))), (0o700, 0o700, 0o600, 0o600))
        self.ae(list(ks.keys), [read_key_id(path)])
        for name, plaintext in (('process.json', b'SECRET_VAR'), ('session.kitty-session', b'launch'), ('scrollback/7', b'seven')):
            self.assertNotIn(plaintext, raw(path, name))
        # Snapshots from before this instance was started are from an earlier logout and were never restored, their keys are deleted
        stale = save(10)
        day_ago = time.time() - 86400
        os.utime(stale, (day_ago, day_ago))
        remove_stale_snapshots(base, time.time() - 3600, ks)
        self.ae((os.listdir(base), list(ks.keys)), (['11'], [read_key_id(path)]))
        # Nothing is saved if the key cannot be stored, for example because the keychain needs user interaction
        ks.fail = True
        with self.assertRaises(OSError):
            save(12)
        ks.fail = False
        self.ae(os.listdir(base), ['11'])

        # Snapshots claimed by a running kitty instance are not claimed again, but those claimed by an instance that died are
        alive = {99}
        os.rename(path, os.path.join(base, '11.claimed-by-99'))
        self.ae(claim_snapshots(base, 1, ks, alive.__contains__), [])
        alive.clear()
        (snapshot,) = claim_snapshots(base, 1, ks, alive.__contains__)
        self.ae((snapshot.path, snapshot.process_state[:3]), (os.path.join(base, '11.claimed-by-1'), state[:3]))
        (s,) = load_snapshot(snapshot.path, opts, ks)
        # The scrollback is restored, without unsafe escape codes, followed by a line showing when it was saved
        restored = s.tabs[0].windows[0].restored_scrollback
        self.assertTrue(restored.startswith(b'seven\r\n'), restored)
        self.assertIn(b'Restored from', restored)
        # A snapshot that repeatedly fails to be restored, for example, because kitty crashes, is deleted, with its key
        self.ae(len(claim_snapshots(base, 2, ks, alive.__contains__)), 1)
        self.ae(claim_snapshots(base, 3, ks, alive.__contains__), [])
        self.ae((os.listdir(base), ks.keys), ([], {}))
        self.assertTrue(errors)

        # Snapshots that cannot be decrypted are deleted: key not in the keychain, keychain needs user interaction, modified or
        # swapped files
        def modify(path: str) -> None:
            data = bytearray(raw(path, 'process.json'))
            data[-1] ^= 1
            with open(os.path.join(path, 'process.json'), 'wb') as f:
                f.write(data)

        def swap(path: str) -> None:
            os.replace(os.path.join(path, 'session.kitty-session'), os.path.join(path, 'process.json'))

        for name, damage, num_errors in (
            ('missing key', lambda path: ks.keys.clear(), 1),
            # both reading the key and listing keys to remove orphans fail
            ('keychain needs interaction', lambda path: setattr(ks, 'fail', True), 2),
            ('modified', modify, 1),
            ('swapped', swap, 1),
        ):
            with self.subTest(name):
                errors.clear()
                damage(save(13))
                self.ae(claim_snapshots(base, 1, ks, alive.__contains__), [])
                ks.fail = False
                self.ae((os.listdir(base), len(errors)), ([], num_errors))

        # Keys of snapshots deleted by something other than kitty are deleted, but not the keys of existing snapshots or keys
        # not created by kitty
        path = save(15)
        orphan, foreign = new_key_id(), 'some-other-item'
        ks.keys[orphan] = ks.keys[foreign] = ks.keys[read_key_id(path)]
        remove_orphaned_keys(base, ks)
        self.ae(sorted(ks.keys), sorted((read_key_id(path), foreign)))
        # Orphans are removed when saving and claiming, and all keys when all snapshots are removed
        ks.keys[orphan] = ks.keys[foreign]
        remove_stale_snapshots(base, 0, ks)
        self.assertNotIn(orphan, ks.keys)
        ks.keys[orphan] = ks.keys[foreign]
        self.ae(len(claim_snapshots(base, 1, ks, alive.__contains__)), 1)
        self.assertNotIn(orphan, ks.keys)
        # Failing to list the keys is logged, not raised
        errors.clear()
        ks.fail = True
        remove_orphaned_keys(base, ks)
        ks.fail = False
        self.ae(len(errors), 1)
        shutil.rmtree(base)
        ks.keys.clear()

        # Files are bound to their names, so swapping the scrollback of two windows is detected
        path = save(14)
        os.rename(os.path.join(path, 'scrollback', '7'), os.path.join(path, 'scrollback', 'x'))
        os.rename(os.path.join(path, 'scrollback', '8'), os.path.join(path, 'scrollback', '7'))
        with self.assertRaises(Exception):
            load_snapshot(path, opts, ks)
        shutil.rmtree(base)
        ks.keys.clear()

        # The snapshot of a kitty instance that is still running, for example, because the logout was cancelled, is not claimed,
        # even if a process with its pid is running, since pids are reused
        import kitty.logout_session as ls

        path = save(16)
        lock_snapshot_for_saver(path)
        alive.add(16)
        self.ae(claim_snapshots(base, 1, ks, alive.__contains__), [])
        release_saver_lock(os.path.join(base, 'other'))
        self.ae(claim_snapshots(base, 1, ks, alive.__contains__), [])
        release_saver_lock(path)
        self.ae(len(claim_snapshots(base, 1, ks, alive.__contains__)), 1)
        alive.clear()
        # Deleting the snapshot of this instance, as when the logout is cancelled, releases its lock
        path = save(17)
        lock_snapshot_for_saver(path)
        delete_snapshot(path)
        self.assertIsNone(ls.saver_lock)
        shutil.rmtree(base)
        ks.keys.clear()

        # Without a key store, as on Linux, snapshots are not encrypted and are readable only by the user
        path = save_snapshot(base, 31, session, {7: b'seven'}, state, None)
        self.ae((read_key_id(path), mode(path), mode(os.path.join(path, 'process.json'))), ('', 0o700, 0o600))
        self.assertIn(b'SECRET_VAR', raw(path, 'process.json'))
        (snapshot,) = claim_snapshots(base, 1, None, alive.__contains__)
        self.ae(snapshot.process_state[:3], state[:3])
        (s,) = load_snapshot(snapshot.path, opts, None)
        self.assertTrue(s.tabs[0].windows[0].restored_scrollback.startswith(b'seven\r\n'))
        finish_restore(snapshot.path)
        # An encrypted snapshot cannot be read without a key store and an unencrypted one is not accepted when there is a key store
        errors.clear()
        save_snapshot(base, 32, session, {}, state, None)
        self.ae(claim_snapshots(base, 1, ks, alive.__contains__), [])
        save(33)
        self.ae(claim_snapshots(base, 1, None, alive.__contains__), [])
        self.ae((os.listdir(base), len(errors)), ([], 2))
        remove_orphaned_keys(base, ks)
        self.ae(ks.keys, {})
        shutil.rmtree(base)
        ks.keys.clear()

        # The snapshot of the kitty instance with the same command line is restored in this instance, others in new instances
        save(21, ('a',)), save(22, ('b',))
        started: list[str] = []
        with (
            patch('kitty.logout_session.snapshots_dir', return_value=base),
            patch('kitty.logout_session.get_key_store', return_value=ks),
            patch('kitty.logout_session.start_instance_for_snapshot', side_effect=lambda s: started.append(s.path)),
        ):
            r = restore_snapshots(opts, ('b',))
            assert r is not None
            self.ae((os.path.basename(r.path), len(r.sessions)), (f'22.claimed-by-{os.getpid()}', 1))
            self.ae([os.path.basename(x) for x in started], [f'21.claimed-by-{os.getpid()}'])
            # Snapshots and their keys are deleted only once they have been restored
            self.assertTrue(os.path.exists(r.path))
            self.ae(len(ks.keys), 2)
            finish_restore(r.path)
            self.ae((os.listdir(base), list(ks.keys)), ([os.path.basename(started[0])], [read_key_id(started[0])]))
            self.assertIsNone(restore_snapshots(opts, ('b',)))
            remove_all_snapshots()
            self.assertFalse(os.path.exists(base))
            self.ae(ks.keys, {})
            self.assertIsNone(restore_snapshots(opts, ('b',)))

        # On Linux, the snapshot is saved when the desktop portal says the session is about to end and is deleted if the logout is
        # cancelled
        from types import SimpleNamespace

        from kitty.boss import Boss
        from kitty.logout_session import DESKTOP_SESSION_ENDING, DESKTOP_SESSION_QUERY_END, DESKTOP_SESSION_RUNNING

        boss = SimpleNamespace(snapshot_saved_for_logout='', save_session_at_logout=lambda: save_snapshot(base, 41, session, {}, state, None))
        for new_state, expected in (
            (DESKTOP_SESSION_QUERY_END, ['41']),
            (DESKTOP_SESSION_RUNNING, []),
            (DESKTOP_SESSION_QUERY_END, ['41']),
            (DESKTOP_SESSION_ENDING, ['41']),
        ):
            Boss.on_desktop_session_state_changed(boss, new_state)  # type: ignore[arg-type]
            self.ae(os.listdir(base), expected)
        shutil.rmtree(base)

        # Restored instances get variables that refer to the login session, such as the display, from the current login session and
        # never get single use startup tokens
        from kitty.logout_session import environment_for_snapshot

        self.ae(
            environment_for_snapshot(
                {'HOME': '/h', 'WAYLAND_DISPLAY': 'wayland-1', 'XAUTHORITY': '/old', 'DISPLAY': ':1', 'XDG_ACTIVATION_TOKEN': 'x'},
                {'HOME': '/other', 'DISPLAY': ':0', 'XAUTHORITY': '/new', 'XDG_ACTIVATION_TOKEN': 'y'},
            ),
            {'HOME': '/h', 'DISPLAY': ':0', 'XAUTHORITY': '/new'},
        )

        # A quit confirmed long after the OS asked kitty to quit for a logout is an ordinary quit
        for requested_at, now, expected in ((-1, 10, False), (5, 10, True), (5, 6 + LOGOUT_CONFIRMATION_TIMEOUT, False)):
            with (
                patch('kitty.logout_session.application_logout_requested_at', return_value=requested_at),
                patch('kitty.logout_session.monotonic', return_value=now),
            ):
                self.ae(is_logout_in_progress(), expected)
