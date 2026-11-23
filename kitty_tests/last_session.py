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

    def write_claude_registry(self, config_dir, file_pid, **fields):
        import json

        d = {'pid': file_pid, 'sessionId': '0d6f3f2e-5b8a-4c1e-9f00-1234567890ab', 'cwd': '/x', 'kind': 'interactive'}
        d.update(fields)
        os.makedirs(os.path.join(config_dir, 'sessions'), exist_ok=True)
        with open(os.path.join(config_dir, 'sessions', f'{file_pid}.json'), 'w') as f:
            json.dump(d, f)

    def test_is_claude_cmdline(self):
        from kitty.session import is_claude_cmdline as q

        self.assertTrue(q(['claude']))
        self.assertTrue(q(['claude', '--resume']))
        self.assertTrue(q(['/Users/x/.local/bin/claude', '--model', 'opus']))
        self.assertTrue(q(['node', '/usr/local/bin/claude']))
        self.assertTrue(q(['/opt/homebrew/bin/node', '/opt/homebrew/lib/node_modules/@anthropic-ai/claude-code/cli.js']))
        self.assertFalse(q([]))
        self.assertFalse(q(None))
        self.assertFalse(q(['vim', 'claude']))
        self.assertFalse(q(['node', 'server.js']))
        self.assertFalse(q(['claude-monitor']))

    def test_claude_session_id_for_pid(self):
        from kitty.session import claude_session_id_for_pid as q

        cdir = os.path.join(self.tdir, 'claude-config')
        self.write_claude_registry(cdir, 101)
        self.ae(q(101, cdir), '0d6f3f2e-5b8a-4c1e-9f00-1234567890ab')
        self.ae(q(102, cdir), '')  # no registry file
        self.write_claude_registry(cdir, 103, pid=999)  # file not written by this process
        self.ae(q(103, cdir), '')
        self.write_claude_registry(cdir, 104, kind='bg')  # background agents are not panes to resume
        self.ae(q(104, cdir), '')
        self.write_claude_registry(cdir, 105, sessionId='x; rm -rf ~')  # must be safe to run in a shell
        self.ae(q(105, cdir), '')
        self.write_claude_registry(cdir, 106, sessionId=7)
        self.ae(q(106, cdir), '')
        with open(os.path.join(cdir, 'sessions', '107.json'), 'w') as f:
            f.write('{not json')
        self.ae(q(107, cdir), '')
        self.write_claude_registry(cdir, 108)
        os.remove(os.path.join(cdir, 'sessions', '108.json'))
        os.makedirs(os.path.join(cdir, 'sessions', '108.json'))  # not a file
        self.ae(q(108, cdir), '')
        # CLAUDE_CONFIG_DIR is honoured when no directory is given
        from unittest.mock import patch

        with patch.dict(os.environ, {'CLAUDE_CONFIG_DIR': cdir}):
            self.ae(q(101), '0d6f3f2e-5b8a-4c1e-9f00-1234567890ab')

    def test_claude_resume_cmdline(self):
        from kitty.session import claude_resume_cmdline as q

        cdir = os.path.join(self.tdir, 'claude-config')
        self.write_claude_registry(cdir, 201, sessionId='aaaa-1111')
        self.write_claude_registry(cdir, 202, sessionId='bbbb-2222')
        procs = [
            {'pid': 200, 'cmdline': ['less', 'x'], 'cwd': '/x'},
            {'pid': 201, 'cmdline': ['claude', '--model', 'opus', 'fix the bug'], 'cwd': '/x'},
        ]
        # Only the session is resumed, other arguments such as a prompt are not re-run
        self.ae(q(procs, cdir), ['claude', '--resume', 'aaaa-1111'])
        self.ae(q([{'pid': 202, 'cmdline': ['/usr/bin/node', '/usr/lib/node_modules/@anthropic-ai/claude-code/cli.js'], 'cwd': '/x'}], cdir),
                ['claude', '--resume', 'bbbb-2222'])
        self.ae(q(procs[:1], cdir), [])
        self.ae(q([{'pid': 203, 'cmdline': ['claude'], 'cwd': '/x'}], cdir), [])  # claude without a registered session
        self.ae(q([{'pid': 201, 'cmdline': None, 'cwd': None}], cdir), [])
        # the default allowlist restarts claude
        from kitty.options.types import defaults
        from kitty.session import foreground_process_allowed, last_session_save_opts

        self.assertIn('claude', defaults.restore_last_session_programs)
        self.assertTrue(foreground_process_allowed(last_session_save_opts(defaults), ['claude', '--resume', 'aaaa-1111']))
