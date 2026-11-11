#!/usr/bin/env python
# License: GPL v3

import os
import shutil
import tempfile
from types import SimpleNamespace

from .base import BaseTest


class FakeBoss:

    def __init__(self, lines: list[str]) -> None:
        self.lines = lines
        self.os_window_map = {1: object()}
        self.serialize_calls = []

    def serialize_state_as_session(self, path, ser_opts):
        self.serialize_calls.append((path, ser_opts))
        yield from self.lines


class TestLastSession(BaseTest):

    def setUp(self):
        super().setUp()
        self.tdir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tdir)
        super().tearDown()

    def test_programs_option(self):
        from kitty.options.utils import restore_last_session_programs as p

        self.ae(p('vim  less'), frozenset({'vim', 'less'}))
        self.ae(p('none'), frozenset())
        self.ae(p('*'), frozenset({'*'}))

    def test_foreground_process_allowed(self):
        from kitty.session import foreground_process_allowed

        def opts(*allowed):
            return SimpleNamespace(allow_foreground_process=list(allowed))

        q = foreground_process_allowed
        # no allowlist means everything is allowed, as for plain save_as_session
        self.assertTrue(q(opts(), 'rm -rf /tmp/x'))
        self.assertTrue(q(opts('*'), ['make', 'deploy']))
        a = opts('vim', 'less', 'ssh')
        self.assertTrue(q(a, 'vim foo.txt'))
        self.assertTrue(q(a, ['/usr/bin/vim', 'foo.txt']))
        self.assertTrue(q(a, 'EDITOR=x LANG=C vim foo'))
        self.assertTrue(q(a, 'ssh'))
        self.assertFalse(q(a, 'rm -rf /tmp/x'))
        self.assertFalse(q(a, ['make', 'deploy']))
        self.assertFalse(q(a, 'vimdiff a b'))
        self.assertFalse(q(a, ''))
        self.assertFalse(q(a, []))
        self.assertTrue(q(a, 'less "unterminated'))  # shlex failure falls back to whitespace split

    def test_save_opts_from_config(self):
        from kitty.options.types import defaults
        from kitty.session import last_session_save_opts

        so = last_session_save_opts(defaults)
        self.assertTrue(so.save_only)
        self.assertTrue(so.use_foreground_process)
        self.assertTrue(so.os_window_geometry)
        self.ae(set(so.allow_foreground_process), set(defaults.restore_last_session_programs))
        so = last_session_save_opts(defaults._replace(restore_last_session_programs=frozenset({'*'})))
        self.ae(so.allow_foreground_process, ['*'])
        # "none": nothing may match, but the list must not be empty (empty means allow all)
        so = last_session_save_opts(defaults._replace(restore_last_session_programs=frozenset()))
        self.assertTrue(so.allow_foreground_process)
        from kitty.session import foreground_process_allowed
        self.assertFalse(foreground_process_allowed(so, 'vim'))

    def test_should_restore(self):
        from kitty.options.types import defaults
        from kitty.session import should_restore_last_session

        path = os.path.join(self.tdir, 'last.kitty-session')
        with open(path, 'w') as f:
            f.write('launch\n')
        on = defaults._replace(restore_last_session=True)
        plain = SimpleNamespace(session='', args=[])
        q = should_restore_last_session
        self.assertTrue(q(on, plain, path))
        self.assertFalse(q(defaults, plain, path))
        self.assertFalse(q(on, plain, path + '-missing'))
        self.assertFalse(q(on, plain, path, is_panel=True))
        self.assertFalse(q(on, SimpleNamespace(session='work.kitty-session', args=[]), path))
        self.assertFalse(q(on, SimpleNamespace(session='', args=['vim', 'x']), path))
        self.assertFalse(q(on._replace(startup_session='/some/startup.kitty-session'), plain, path))
        self.assertTrue(q(on._replace(startup_session='none'), plain, path))
        self.assertTrue(q(on._replace(startup_session=None), plain, path))

    def test_last_session_instance(self):
        # Only instances that would restore the last session may overwrite it, so
        # a one-off "kitty some-command" does not clobber the remembered session
        from kitty.options.types import defaults
        from kitty.session import is_last_session_instance as q

        on = defaults._replace(restore_last_session=True)
        plain = SimpleNamespace(session='', args=[])
        self.assertTrue(q(on, plain))  # even when no saved file exists yet
        self.assertFalse(q(defaults, plain))
        self.assertFalse(q(on, plain, is_panel=True))
        self.assertFalse(q(on, SimpleNamespace(session='', args=['/bin/zsh', '-l'])))
        self.assertFalse(q(on, SimpleNamespace(session='work.kitty-session', args=[])))
        self.assertFalse(q(on, SimpleNamespace(session='none', args=[])))
        self.assertFalse(q(on._replace(startup_session='/x.kitty-session'), plain))

    def test_saver(self):
        from kitty.options.types import defaults
        from kitty.session import LastSessionSaver
        from kitty.fast_data_types import set_options

        set_options(defaults)
        try:
            path = os.path.join(self.tdir, 'sub', 'last.kitty-session')
            boss = FakeBoss(['new_tab', 'launch'])
            s = LastSessionSaver(path)

            def content():
                with open(path) as f:
                    return f.read()

            self.assertTrue(s.save(boss))
            self.ae(content(), 'new_tab\nlaunch')
            self.ae(boss.serialize_calls[0][0], path)
            # unchanged state is not re-written
            os.remove(path)
            self.assertFalse(s.save(boss))
            self.assertFalse(os.path.exists(path))
            # unless forced
            self.assertTrue(s.save(boss, force=True))
            self.assertTrue(os.path.exists(path))
            # changed state is written
            boss.lines = ['new_tab', 'launch vim']
            self.assertTrue(s.save(boss))
            self.ae(content(), 'new_tab\nlaunch vim')
            # never overwrite with an empty state
            boss.os_window_map = {}
            self.assertFalse(s.save(boss, force=True))
            boss.os_window_map = {1: object()}
            boss.lines = []
            self.assertFalse(s.save(boss, force=True))
            self.ae(content(), 'new_tab\nlaunch vim')
            # discard deletes the file and stops saving
            boss.lines = ['launch']
            s.discard()
            self.assertFalse(os.path.exists(path))
            self.assertFalse(s.save(boss, force=True))
            self.assertFalse(os.path.exists(path))
            s.discard()  # idempotent
            # re-enabling (new OS window on macOS) resumes saving
            s.disabled = False
            self.assertTrue(s.save(boss))
            self.ae(content(), 'launch')
        finally:
            set_options(None)
