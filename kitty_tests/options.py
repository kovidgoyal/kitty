#!/usr/bin/env python
# License: GPL v3 Copyright: 2018, Kovid Goyal <kovid at kovidgoyal.net>

import os
import shutil
import subprocess
import tempfile

from kitty.constants import kitty_exe
from kitty.fast_data_types import Color, test_cursor_blink_easing_function
from kitty.options.utils import DELETE_ENV_VAR, EasingFunction, build_action_aliases, to_color
from kitty.utils import log_error, shlex_split

from .base import BaseTest


class TestConfParsing(BaseTest):
    def setUp(self):
        super().setUp()
        self.error_messages = []
        log_error.redirect = self.error_messages.append
        self.tdir = tempfile.mkdtemp()

    def tearDown(self):
        del log_error.redirect
        shutil.rmtree(self.tdir)
        super().tearDown()

    def test_conf_parsing(self):
        conf_parsing(self)

    def test_launcher(self):
        launcher(self)

    def test_cli_parsing(self):
        cli_parsing(self)

    def test_font_size_clamping(self):
        font_size_clamping(self)

    def test_session_launch_option_expansion(self) -> None:
        from kitty.launch import LaunchSpec
        from kitty.options.types import defaults
        from kitty.session import parse_session

        for command in (
            '--title bash --cwd $SESSION_DIR bash $COMMAND_ARG',
            '--title=bash --cwd=$SESSION_DIR bash $COMMAND_ARG',
            '--title bash --cwd $SESSION_DIR -- bash $COMMAND_ARG',
            '--title other --cwd $SESSION_DIR bash $COMMAND_ARG',
        ):
            with self.subTest(command=command):
                (session,) = parse_session(f'launch {command}', defaults, environ={'SESSION_DIR': '/tmp/session', 'COMMAND_ARG': 'expanded'})
                spec = session.tabs[0].windows[0].launch_spec
                assert isinstance(spec, LaunchSpec)
                self.ae(spec.opts.cwd, '/tmp/session')
                self.ae(spec.args, ['bash', '$COMMAND_ARG'])

    def test_session_os_window_geometry(self) -> None:
        from types import SimpleNamespace
        from typing import cast
        from unittest.mock import patch

        from kitty.fast_data_types import WINDOW_MAXIMIZED
        from kitty.os_window_size import initial_window_size_func
        from kitty.session import default_save_as_session_opts, get_os_window_sizing_data, parse_session
        from kitty.tabs import TabManager

        opts = self.set_options({'remember_window_size': True})
        first, second = parse_session('os_window_size 1180 760\nos_window_position -1200x80\nlaunch\nnew_os_window\nlaunch', opts)
        self.ae(first.os_window_position, (-1200, 80))
        self.ae(second.os_window_position, (None, None))
        # A size specified in the session takes precedence over the remembered size
        remembered = {'window-size': (900, 600)}
        self.ae(initial_window_size_func(get_os_window_sizing_data(opts, first), remembered)(10, 20, 72, 72, 1, 1), (1180, 760))
        self.ae(initial_window_size_func(get_os_window_sizing_data(opts, second), remembered)(10, 20, 72, 72, 1, 1), (900, 600))

        tm = cast(TabManager, SimpleNamespace(os_window_id=1))
        g = {'x': -1200, 'y': 80, 'width': 1180, 'height': 760, 'state': WINDOW_MAXIMIZED}
        with patch('kitty.tabs.get_os_window_geometry', return_value=g), patch('kitty.tabs.is_wayland', return_value=False):
            geometry = TabManager.serialize_geometry_as_session(tm)
        self.ae(geometry, ['os_window_size 1180 760', 'os_window_position -1200x80', 'os_window_state maximized'])
        with patch('kitty.tabs.get_os_window_geometry', return_value=g), patch('kitty.tabs.is_wayland', return_value=True):
            self.assertNotIn(geometry[1], TabManager.serialize_geometry_as_session(tm))
        with patch('kitty.tabs.get_os_window_geometry', return_value=None):  # panels and closed OS Windows
            self.ae(TabManager.serialize_geometry_as_session(tm), [])
        (s,) = parse_session('\n'.join(geometry), opts)
        self.ae((s.os_window_size, s.os_window_position, s.os_window_state), (first.os_window_size, (-1200, 80), 'maximized'))

        # Geometry is saved only when requested
        tab = SimpleNamespace(serialize_state_as_session=lambda *a: ['', 'new_tab', 'launch'])
        tm = cast(TabManager, SimpleNamespace(tabs=[tab], active_tab=tab, wm_class='', wm_name='', serialize_geometry_as_session=lambda: geometry))
        ser_opts = default_save_as_session_opts()
        self.assertFalse(ser_opts.relaunch_full_screen_programs)
        self.assertNotIn(geometry[0], TabManager.serialize_state_as_session(tm, '', None, ser_opts, is_first=True))
        ser_opts.os_window_geometry = True
        self.ae(TabManager.serialize_state_as_session(tm, '', None, ser_opts, is_first=True)[:3], geometry)

    def test_sessions_saved_at_logout(self) -> None:
        import json
        import shlex
        import threading
        import time
        from types import SimpleNamespace
        from typing import Any, cast
        from unittest.mock import patch

        from kitty.boss import Boss
        from kitty.constants import unserialize_launch_flag
        from kitty.session import remove_sessions_saved_at_logout, save_session_at_logout, sessions_saved_at_logout
        from kitty.utils import lock_with_file
        from kitty.window import as_text

        from .base import parse_bytes

        opts = self.set_options()
        geometry = ['os_window_size 1180 760', 'os_window_position -1200x80', 'os_window_state maximized']
        # Every kitty instance saves its own session at logout, with geometry and scrollback, and they are all restored only once
        base = os.path.join(self.tdir, 'saved-at-logout')
        launch_line = shlex.join(['launch', unserialize_launch_flag + json.dumps({'id': 7})])

        def serialize(session_path, ser_opts):
            # Full screen programs are started again, other programs are not
            self.assertTrue(ser_opts.relaunch_full_screen_programs and not ser_opts.use_foreground_process)
            return iter((geometry if ser_opts.os_window_geometry else []) + [launch_line])

        def save(pid, *lines):
            screen = self.create_screen(cols=10, lines=3, scrollback=20)
            parse_bytes(screen, '\r\n'.join(lines).encode())
            windows = [SimpleNamespace(id=7, screen=screen), SimpleNamespace(id=8, screen=screen)]  # window 8 is not in the session
            with patch('kitty.session.os.getpid', return_value=pid):
                save_session_at_logout(cast(Boss, SimpleNamespace(serialize_state_as_session=serialize, all_windows=windows)))

        def restored_text(session):
            screen = self.create_screen(cols=10, lines=3, scrollback=20)
            screen.parse_child_output(session.tabs[0].windows[0].restored_scrollback)
            return as_text(screen, add_history=True).splitlines()

        with patch('kitty.session.saved_at_logout_dir', return_value=base):
            # A session saved at an earlier logout that was never restored is deleted when saving
            save(100, 'stale')
            day_ago = time.time() - 86400
            for x in os.listdir(base):
                os.utime(os.path.join(base, x), (day_ago, day_ago))
            save(111, 'one', 'two')
            save(222, 'three')
            self.ae(sorted(os.listdir(base)), ['111-scrollback', '111.kitty-session', '222-scrollback', '222.kitty-session'])
            self.ae(os.listdir(os.path.join(base, '111-scrollback')), ['7'])
            sessions = sessions_saved_at_logout(opts)
            self.ae({(s.os_window_position, s.os_window_state) for s in sessions}, {((-1200, 80), 'maximized')})
            texts = sorted(restored_text(s) for s in sessions)
            self.ae([t[:-1] for t in texts], [['one', 'two'], ['three']])
            self.assertTrue(all(t[-1].strip().startswith('Restored from ') for t in texts))
            self.assertFalse(os.path.exists(base))
            self.ae(sessions_saved_at_logout(opts), ())
            # Restoring waits for the lock, so that kitty instances started at the same time do not both restore the sessions
            save(111, 'one')
            results: list[tuple[Any, ...]] = []
            with lock_with_file(base + '.lock'):
                t = threading.Thread(target=lambda: results.append(sessions_saved_at_logout(opts)))
                t.start()
                time.sleep(0.2)
                self.assertTrue(t.is_alive())
                self.assertTrue(os.path.exists(base))
            t.join()
            self.ae((len(results[0]), os.path.exists(base)), (1, False))
            # Nothing is saved when there are no OS Windows, but sessions from an earlier logout are still deleted
            save(100, 'stale')
            for x in os.listdir(base):
                os.utime(os.path.join(base, x), (day_ago, day_ago))
            save_session_at_logout(cast(Boss, SimpleNamespace(serialize_state_as_session=lambda *a: iter(()), all_windows=[])))
            self.ae(os.listdir(base), [])
            self.ae(sessions_saved_at_logout(opts), ())
            # A broken saved session is ignored, without affecting the others, and deleted
            save(111, 'one')
            with open(os.path.join(base, '222.kitty-session'), 'wb') as f:
                f.write(b'\xff\xfe launch')
            self.ae(len(sessions_saved_at_logout(opts)), 1)
            self.assertTrue(self.error_messages)
            self.assertFalse(os.path.exists(base))
            # Leftovers are deleted when the option is disabled
            save(111, 'one')
            remove_sessions_saved_at_logout()
            self.assertFalse(os.path.exists(base))
            # Errors when restoring do not prevent kitty from starting
            open(base, 'w').close()
            del self.error_messages[:]
            self.ae(sessions_saved_at_logout(opts), ())
            self.assertTrue(self.error_messages)
            os.remove(base)

    def test_scrollback_for_restore(self) -> None:
        from kitty.session import scrollback_for_restore
        from kitty.window import as_text

        from .base import parse_bytes

        screen = self.create_screen(cols=10, lines=4, scrollback=20)
        parse_bytes(
            screen, b''.join(b'line %d\r\n' % i for i in range(8)) + b'\x1b[31mred\x1b[m 0123456789abcdef\r\n\x1b]8;;https://x.org\x1b\\link\x1b]8;;\x1b\\'
        )
        expected = as_text(screen, add_history=True).rstrip('\n')
        expected_ansi = as_text(screen, as_ansi=True, add_history=True)
        # Output on the alternate screen, such as from a full screen program, is not restored
        parse_bytes(screen, b'\x1b[?1049hfull screen program')
        data = scrollback_for_restore(screen)
        self.assertNotIn(b'full screen program', data)
        self.assertFalse(data.endswith(b'\r\n'))

        same_width = self.create_screen(cols=10, lines=4, scrollback=20)
        same_width.parse_child_output(data)
        self.ae(as_text(same_width, add_history=True), expected)
        self.ae(as_text(same_width, as_ansi=True, add_history=True), expected_ansi.rstrip('\n'))
        # Wrapped lines are re-wrapped to the width of the new screen
        wider = self.create_screen(cols=30, lines=4, scrollback=20)
        wider.parse_child_output(data)
        self.ae(as_text(wider, add_history=True).splitlines()[-2:], ['red 0123456789abcdef', 'link'])
        self.assertTrue(any(url.endswith('https://x.org') for url, hyperlink_id in wider.hyperlinks_as_set()))
        # Restored output is parsed when the window gets its actual size, before the child is allowed to run, so wide
        # lines are not wrapped at a smaller size, which would lose lines that do not fit in the scrollback
        from types import SimpleNamespace
        from typing import Any, cast
        from unittest.mock import patch

        from kitty.window import Window

        src = self.create_screen(cols=200, lines=50, scrollback=2000)
        parse_bytes(src, b''.join(b'%04d %s\r\n' % (i, b'x' * 145) for i in range(1900)))
        screen = self.create_screen(cols=80, lines=24, scrollback=2000)
        screen.resize(50, 200)
        lines_when_child_ready = []
        child = SimpleNamespace(mark_terminal_ready=lambda: lines_when_child_ready.append(len(as_text(screen, add_history=True).splitlines())))
        w = SimpleNamespace(
            id=1, screen=screen, child=child, child_is_launched=False, restored_scrollback=scrollback_for_restore(src), notify_child_of_resize=lambda: None
        )
        boss = SimpleNamespace(child_monitor=SimpleNamespace(resize_pty=lambda *a: None), args=SimpleNamespace(debug_rendering=False))
        with patch('kitty.window.get_boss', return_value=boss):
            Window.resize_child(cast(Window, w), (50, 200, 2000, 1000))
        restored = as_text(screen, add_history=True).splitlines()
        self.ae((len(restored), restored[0][:4], w.restored_scrollback), (1900, '0000', b''))
        self.ae(lines_when_child_ready, [1900])

        # Failing to parse the restored output does not prevent the child from running
        def fail(data: bytes) -> None:
            raise RuntimeError('failed')

        w.child_is_launched, w.restored_scrollback, w.screen = False, b'x', SimpleNamespace(parse_child_output=fail)
        del self.error_messages[:]
        with patch('kitty.window.get_boss', return_value=boss):
            Window.resize_child(cast(Window, w), (50, 200, 2000, 1000))
        self.ae((w.child_is_launched, w.restored_scrollback, len(lines_when_child_ready)), (True, b'', 2))
        self.assertIn('RuntimeError: failed', ''.join(self.error_messages))

        # Prompt marks in restored output are not reported as commands being run in the window
        calls: list[Any] = []
        w = SimpleNamespace(child_is_launched=False, last_cmd_cmdline='', handle_cmd_end=lambda *a: calls.append(a))
        Window.cmd_output_marking(cast(Window, w), True, 'ls')
        Window.cmd_output_marking(cast(Window, w), False)
        self.ae((calls, w.last_cmd_cmdline), ([], ''))
        w.child_is_launched = True
        Window.cmd_output_marking(cast(Window, w), False)
        self.ae(calls, [('',)])

        # The shell prompt the cursor is at is not restored, since the restored shell shows a new one
        def restored_lines(data: bytes, lines: int = 6) -> list[str]:
            src = self.create_screen(cols=20, lines=lines, scrollback=50)
            parse_bytes(src, data)
            dest = self.create_screen(cols=20, lines=lines, scrollback=50)
            dest.parse_child_output(scrollback_for_restore(src))
            return as_text(dest, add_history=True).rstrip('\n').splitlines()

        prompt, output = b'\x1b]133;A\x07', b'\x1b]133;C\x07'
        self.ae(restored_lines(prompt + b'$ ls\r\n' + output + b'a\r\nb\r\n' + prompt + b'$ partial'), ['$ ls', 'a', 'b'])
        two_line_prompt = prompt + b'~/project on main\r\n$ '
        self.ae(restored_lines(two_line_prompt + b'ls\r\n' + output + b'a\r\n' + two_line_prompt), ['~/project on main', '$ ls', 'a'])
        many = b''.join(b'%d\r\n' % i for i in range(10))
        self.ae(restored_lines(prompt + b'$ seq\r\n' + output + many + prompt + b'$ ', lines=4), ['$ seq'] + [str(i) for i in range(10)])
        # A running command is restored with all its output
        self.ae(restored_lines(prompt + b'$ tail -f log\r\n' + output + b'a\r\nb'), ['$ tail -f log', 'a', 'b'])
        # Output larger than the parser buffer
        big = self.create_screen(cols=80, lines=4, scrollback=50000)
        big.parse_child_output(b''.join(b'%05d %s\r\n' % (i, b'x' * 70) for i in range(40000)))
        self.ae(as_text(big, add_history=True).splitlines()[-1], '39999 ' + 'x' * 70)

    def test_session_discovery(self):
        from unittest.mock import patch

        from kitty.config import load_config
        from kitty.constants import config_dir
        from kitty.fast_data_types import set_options
        from kitty.session import get_all_known_sessions, seen_session_paths

        def discover(*lines):
            bad_lines = []
            opts = load_config(overrides=('clear_all_shortcuts yes', *lines), accumulate_bad_lines=bad_lines)
            self.assertFalse(bad_lines)
            set_options(opts)
            return get_all_known_sessions()

        with patch.dict(seen_session_paths, {}, clear=True):
            for args, name in (
                ('work.kitty-session', 'work'),
                ('--sort-by alphabetical work.kitty-session', 'work'),
                ('--sort-by=alphabetical work.kitty-session', 'work'),
                ('--active-only=no --sort-by recent work.kitty-session', 'work'),
                ('work.kitty-session --sort-by alphabetical', 'work'),
                ('-- "-work project.kitty-session"', '-work project'),
                ('-- -0', '-0'),
                ('', ''),
                ('--sort-by alphabetical', ''),
                ('--sort-by=alphabetical', ''),
                ('--active-only', ''),
                ('-1', ''),
                ('-- -1', ''),
                ('--sort-by alphabetical -- -2', ''),
                ('--sort-by', ''),
                ('--sort-by invalid work.kitty-session', ''),
                ('--unknown work.kitty-session', ''),
                ('--active-only=invalid work.kitty-session', ''),
            ):
                with self.subTest(args=args):
                    filename = f'{name}.kitty-session' if name != '-0' else name
                    expected = {name: os.path.join(config_dir, filename)} if name else {}
                    self.ae(discover(f'map f7 goto_session {args}'), expected)

            seen_path = os.path.join(self.tdir, 'work.kitty-session')
            seen_session_paths['work'] = seen_path
            self.ae(
                discover(
                    'action_alias project goto_session --sort-by alphabetical',
                    'map f7 project work.kitty-session',
                    'map f8 combine : goto_session --sort-by : project other.kitty-session',
                ),
                {'work': seen_path, 'other': os.path.join(config_dir, 'other.kitty-session')},
            )

    def test_launch_transparent_color_overrides(self) -> None:
        from kitty.launch import apply_colors
        from kitty.window import Window

        cases = (
            (('transparent_background_colors=#ffffff@0.5', 'foreground=red'), ((Color(255, 255, 255), 0.5),)),
            (('foreground=red', 'transparent_background_colors=#ffffff@0.5'), ((Color(255, 255, 255), 0.5),)),
            (('transparent_background_colors=#ffffff@0.5', 'foreground=red', 'transparent_background_colors='), ()),
            (('transparent_background_colors=#ffffff@0.5', 'transparent_background_colors=#000000@0.25', 'foreground=red'), ((Color(0, 0, 0), 0.25),)),
        )
        for colors, expected in cases:
            with self.subTest(colors=colors):
                window = Window.__new__(Window)
                window.screen = self.create_screen()
                apply_colors(window, colors)
                actual = window.screen.color_profile.as_dict()
                self.ae(actual.get('transparent_background_colors', ()), expected)
                self.ae(actual['foreground'], 0xFF0000)


def cli_parsing(self):
    from kitty.cli import CLIOptions, Options, parse_cmdline, parse_option_spec

    seq, disabled = parse_option_spec("""\
--simple-string -s
a simple string


--list -l
type=list
a list


--choice -c
choices=a,b,c
some choices


--bool-set -1
type=bool-set
set a bool


--bool-reset -0
type=bool-reset
unset a bool


--int -i
type=int
a integer


--float -f
type=float
a float


--version -v
type=bool-set
version
""")
    oc = Options(seq, usage='xxx', message='yyy', appname='test')
    oc.do_print = False

    def t(args, leftover=(), fails=False, version_called=False, help_called=False, **expected):
        oc.help_called = oc.version_called = False
        args = list(shlex_split(args))
        ans = CLIOptions()
        if fails:
            if isinstance(fails, str):
                with self.assertRaisesRegex(SystemExit, fails):
                    parse_cmdline(oc, disabled, ans, args=args)
            else:
                with self.assertRaises(SystemExit):
                    parse_cmdline(oc, disabled, ans, args=args)
        else:
            actual_leftover = parse_cmdline(oc, disabled, ans, args=args)
            self.assertEqual(tuple(leftover), tuple(actual_leftover), f'{args}\n{ans}')
            for dest, defval in oc.values_map.items():
                val = expected.get(dest, defval)
                self.assertEqual(val, getattr(ans, dest, BaseTest), f'Failed to parse {dest} correctly for: {args}\n{ans}')
        self.assertEqual(version_called, oc.version_called, f'Failed to call version for: {args}\n{ans}')
        self.assertEqual(help_called, oc.help_called, f'Failed to call help for: {args}\n{ans}')

    t('-1', bool_set=True)
    t('-01', bool_reset=False, bool_set=True)
    t('-01=y', bool_reset=False, bool_set=True)
    t('-01=n', bool_reset=False, bool_set=False)
    t('--simple-string xx moo -1', leftover=['moo', '-1'], simple_string='xx')
    t('--si -0 -- -1', leftover=['-1'], simple_string='-0')
    t('--simple-string=-0 -- -1', leftover=['-1'], simple_string='-0')
    t('--simple-string=--help -- -1', leftover=['-1'], simple_string='--help')
    t('--simple-string --help -- -1', leftover=['-1'], simple_string='--help')
    t('-1l=a --list=b -c b --list c', bool_set=True, choice='b', list=list('abc'))
    t('-1s= -l "" --list= x', leftover=['x'], bool_set=True, simple_string='', list=['', ''])
    t('--choice moo', fails=r'moo')
    t('--bool', fails='mbiguous')
    t('-1c moo', fails=r'moo')
    t('-10c=moo', fails=r'moo')
    t('-1 -h', fails=True, help_called=True)
    t('-1 --help', fails=True, help_called=True)
    t('-1 -0v', fails=True, version_called=True)
    t('-1 -v0', fails=True, version_called=True)
    t('-1 --version', fails=True, version_called=True)
    t('-f=3.142 --int 17', float=3.142, int=17)


def font_size_clamping(self: 'BaseTest') -> None:
    from kitty.options.utils import MAXIMUM_FONT_SIZE, MINIMUM_FONT_SIZE, clamp_font_size

    # the floor applies whatever the configured size
    self.ae(clamp_font_size(0, 11), MINIMUM_FONT_SIZE)
    self.ae(clamp_font_size(-100, 11), MINIMUM_FONT_SIZE)

    # sizes inside the range come back untouched
    self.ae(clamp_font_size(11, 11), 11)
    self.ae(clamp_font_size(64, 11), 64)

    # the ceiling is the larger of the multiple and the absolute maximum, so a
    # small configured size no longer implies a small maximum zoom
    self.ae(clamp_font_size(1e6, 4), MAXIMUM_FONT_SIZE)
    self.ae(clamp_font_size(1e6, 11), MAXIMUM_FONT_SIZE)
    self.ae(clamp_font_size(200, 4), 200)

    # a large configured size keeps its proportional ceiling
    self.ae(clamp_font_size(1e6, 40), 400)
    self.ae(clamp_font_size(1e6, 100), 1000)

    # and the ceiling is never below the absolute maximum
    for configured in (1, 4, 11, 25.6, 40, 100):
        self.assertGreaterEqual(clamp_font_size(1e6, configured), MAXIMUM_FONT_SIZE)


def launcher(self):
    import tempfile

    from kitty.constants import is_macos

    kexe = kitty_exe()
    cfgdir = None

    def get_report(cmdline: str, launch_services=False, config_dir: str = ''):
        nonlocal cfgdir
        args = list(shlex_split(cmdline))
        env = dict(os.environ)
        if launch_services:
            env['KITTY_LAUNCHED_BY_LAUNCH_SERVICES'] = '1'
        if config_dir:
            env['KITTY_CONFIG_DIRECTORY'] = config_dir
        cp = subprocess.run([kexe, '+testing-launcher-code'] + args, env=env, stdout=subprocess.PIPE)
        self.assertEqual(cp.returncode, 0)
        ans = {}
        for line in cp.stdout.decode().split('\n'):
            if not line:
                continue
            try:
                key, val = line.split(':')
            except ValueError:
                raise AssertionError(f'Unexpected output from launcher: {line!r}\n{cp.stdout.decode()}')
            if '\x1e' in val:
                val = [x for x in val.split('\x1e') if x]
            else:
                val = val.strip()
            ans[key] = val
            if key == 'config_dir':
                cfgdir = val
        return ans, cp.stdout.decode().replace('\x1e', ' ')

    def test(cmdline, assertions):
        r, output = get_report(cmdline, launch_services=assertions.get('launched_by_launch_services', '0') != '0')
        for key, expected in assertions.items():
            self.assertEqual(expected, r.get(key), f'Failed for {key} with command line: {cmdline}\nOutput:\n{output}')
        return output

    def t(cmdline, **assertions):
        assertions['is_quick_access_terminal'] = '0'
        if cfgdir:
            assertions['config_dir'] = cfgdir
        assertions.setdefault('launched_by_launch_services', '0')
        test(cmdline, assertions)

    def si(cmdline, **assertions):
        assertions['single_instance'] = '1'
        test(cmdline, assertions)

    def dt(cmdline, **assertions):
        assertions['detach'] = 'true'
        test(cmdline, assertions)

    def k(cmdline):
        assertions = {}
        assertions['argv'] = ['kitten'] + cmdline.split()
        for prefix in ('+kitten', '+ kitten'):
            output = test(prefix + ' ' + cmdline, assertions)
            self.assertIn('kitten_exe:', output)

    def pn(cmdline, **assertions):
        ig = assertions.get('instance_group')
        assertions['instance_group'] = f'panel-{ig}' if ig else 'panel'
        assertions['single_instance'] = '1'
        assertions['session'] = ''
        test(cmdline, assertions)

    t('', original_argv=[kexe], argv=[])
    t(
        '--title=xxx --start-as maximized -c=a -c b cat',
        title='xxx',
        start_as='maximized',
        config=['a', 'b'],
        original_argv=[kexe, '--title=xxx', '--start-as', 'maximized', '-c=a', '-c', 'b', 'cat'],
        argv=['cat'],
    )
    k('icat abc xyz')
    t('+kitten unwrapped xyz', argv=['+kitten', 'unwrapped', 'xyz'])
    t('+ kitten unwrapped xyz', original_argv=[kexe, '+', 'kitten', 'unwrapped', 'xyz'])
    si('--single-instance --instance-group=g -T 3', argv=[kexe, '--single-instance', '--instance-group=g', '-T', '3'])
    t('+open --help', argv=['+open', '--help'])
    t('+open -1 --help', argv=['+open', '-1', '--help'])
    si('+open -1 moose', argv=[kexe, '+open', '-1', 'moose'], open_urls=['moose'])
    si('+open -1 --instance-group=g x y', instance_group='g', open_urls=['x', 'y'])
    dt('--detach --session=moose --detached-log=xyz', detached_log='xyz', session='moose')
    pn('+kitten panel -1 --edge=left', edge='left')

    if is_macos:
        with tempfile.TemporaryDirectory() as tdir:
            with open(tdir + '/macos-launch-services-cmdline', 'w') as f:
                f.write('kitty --title from-file\n')
            # File args are used when launched by launch services
            r, output = get_report('', launch_services=True, config_dir=tdir)
            self.assertEqual(r.get('title'), 'from-file', f'Expected title=from-file in:\n{output}')
            # User args passed via open --args are appended after file args (and override them)
            r, output = get_report('--title from-args', launch_services=True, config_dir=tdir)
            self.assertEqual(r.get('title'), 'from-args', f'Expected title=from-args to override from-file in:\n{output}')


def conf_parsing(self):
    from kitty.config import defaults, load_config
    from kitty.constants import is_macos
    from kitty.fast_data_types import LEFT_EDGE, RIGHT_EDGE
    from kitty.fonts import FontModification, ModificationType, ModificationUnit, ModificationValue
    from kitty.options.utils import to_modifiers

    bad_lines = []

    def p(*lines, bad_line_num=0, num_err=None):
        del bad_lines[:]
        del self.error_messages[:]
        ans = load_config(overrides=lines, accumulate_bad_lines=bad_lines)
        if bad_line_num:
            self.ae(len(bad_lines), bad_line_num)
        else:
            self.assertFalse(bad_lines)
        if num_err is not None:
            self.ae(len(self.error_messages), num_err, '\n'.join(self.error_messages))
        return ans

    def keys_for_func(opts, name):
        for key, defns in opts.keyboard_modes[''].keymap.items():
            for action in opts.alias_map.resolve_aliases(defns[0].definition):
                if action.func == name:
                    yield key

    opts = p('font_size 11.37', 'clear_all_shortcuts y', 'color23 red')
    self.ae(opts.font_size, 11.37)
    radius_opts = p('window_border_radius 7px')
    self.ae(radius_opts.window_border_radius, (7.0, 'px'))
    radius_opts = p('window_border_radius -2')
    self.ae(radius_opts.window_border_radius, (0.0, 'pt'))
    self.ae(opts.mouse_hide_wait[0], 0 if is_macos else 3)
    self.ae(opts.mouse_hide_wait[1], 0)
    self.ae(opts.mouse_hide_wait[2], 40)
    self.ae(opts.mouse_hide_wait[3], True)
    self.ae(opts.color23, Color(255, 0, 0))
    self.assertFalse(opts.keyboard_modes[''].keymap)
    opts = p("url_excluded_characters '''")
    self.ae(opts.url_excluded_characters, "'''")
    opts = p("url_excluded_characters abc'")
    self.ae(opts.url_excluded_characters, "abc'")
    opts = p('tab_bar_edge left')
    self.ae(opts.tab_bar_edge, LEFT_EDGE)
    opts = p('tab_bar_edge right')
    self.ae(opts.tab_bar_edge, RIGHT_EDGE)
    opts = p('tab_bar_align start')
    self.ae(opts.tab_bar_align, 'start')
    opts = p('tab_bar_align end')
    self.ae(opts.tab_bar_align, 'end')
    opts = p('tab_bar_align left')
    self.ae(opts.tab_bar_align, 'left')
    opts = p('tab_bar_align right')
    self.ae(opts.tab_bar_align, 'right')
    opts = p('clear_all_shortcuts y', 'map f1 next_window')
    self.ae(len(opts.keyboard_modes[''].keymap), 1)
    opts = p('clear_all_mouse_actions y', 'mouse_map left click ungrabbed mouse_click_url_or_select')
    self.ae(len(opts.mousemap), 1)
    opts = p('strip_trailing_spaces always')
    self.ae(opts.strip_trailing_spaces, 'always')
    self.assertFalse(bad_lines)
    opts = p('pointer_shape_when_grabbed XXX', bad_line_num=1)
    self.ae(opts.pointer_shape_when_grabbed, defaults.pointer_shape_when_grabbed)
    opts = p('modify_font underline_position -2', 'modify_font underline_thickness 150%', 'modify_font size Test -1px')
    self.ae(
        opts.modify_font,
        {
            'underline_position': FontModification(ModificationType.underline_position, ModificationValue(-2.0, ModificationUnit.pt)),
            'underline_thickness': FontModification(ModificationType.underline_thickness, ModificationValue(150, ModificationUnit.percent)),
            'size:Test': FontModification(ModificationType.size, ModificationValue(-1.0, ModificationUnit.pixel), 'Test'),
        },
    )

    # test the aliasing options
    opts = p('env A=1', 'env B=x$A', 'env C=', 'env D', 'clear_all_shortcuts y', 'kitten_alias a b --moo', 'map f1 kitten a arg')
    self.ae(opts.env, {'A': '1', 'B': 'x1', 'C': '', 'D': DELETE_ENV_VAR})

    def ac(which=0):
        ka = tuple(opts.keyboard_modes[''].keymap.values())[0][0]
        acs = opts.alias_map.resolve_aliases(ka.definition)
        return acs[which]

    ka = ac()
    self.ae(ka.func, 'kitten')
    self.ae(ka.args, ('b', '--moo', 'arg'))

    opts = p('clear_all_shortcuts y', 'kitten_alias hints hints --hi', 'map f1 kitten hints XXX')
    ka = ac()
    self.ae(ka.func, 'kitten')
    self.ae(ka.args, ('hints', '--hi', 'XXX'))

    opts = p('clear_all_shortcuts y', 'action_alias la launch --moo', 'map f1 la XXX')
    ka = ac()
    self.ae(ka.func, 'launch')
    self.ae(ka.args, ('--moo', 'XXX'))

    opts = p('clear_all_shortcuts y', 'action_alias one launch --moo', 'action_alias two one recursive', 'map f1 two XXX')
    ka = ac()
    self.ae(ka.func, 'launch')
    self.ae(ka.args, ('--moo', 'recursive', 'XXX'))

    opts = p('clear_all_shortcuts y', 'action_alias launch two 1', 'action_alias two launch 2', 'map f1 launch 3')
    ka = ac()
    self.ae(ka.func, 'launch')
    self.ae(ka.args, ('2', '1', '3'))

    opts = p('clear_all_shortcuts y', 'action_alias launch launch --moo', 'map f1 launch XXX')
    ka = ac()
    self.ae(ka.func, 'launch')
    self.ae(ka.args, ('--moo', 'XXX'))

    opts = p('clear_all_shortcuts y', 'action_alias cfs change_font_size current', 'map f1 cfs +2')
    ka = ac()
    self.ae(ka.func, 'change_font_size')
    self.ae(ka.args, (False, '+', 2.0))

    opts = p('clear_all_shortcuts y', 'action_alias la launch --moo', 'map f1 combine : new_window : la ')
    self.ae((ac().func, ac(1).func), ('new_window', 'launch'))

    opts = p('clear_all_shortcuts y', 'action_alias cc combine : new_window : launch --moo', 'map f1 cc XXX')
    self.ae((ac().func, ac(1).func), ('new_window', 'launch'))
    self.ae(ac(1).args, ('--moo', 'XXX'))

    opts = p('clear_all_shortcuts y', 'action_alias ss kitten "space 1"', 'map f1 ss "space 2"')
    self.ae(ac().args, ('space 1', 'space 2'))

    am = build_action_aliases({'la': 'launch --moo'})
    self.ae(am.resolve_aliases('la XXX')[0].args, ('--moo', 'XXX'))
    am.update(build_action_aliases({'la': 'launch --baa'}))
    self.ae(am.resolve_aliases('la XXX')[0].args, ('--baa', 'XXX'))

    opts = p('kitty_mod alt')
    self.ae(opts.kitty_mod, to_modifiers('alt'))
    self.ae(next(keys_for_func(opts, 'next_layout')).mods, opts.kitty_mod)

    opts = p('inactive_text_alpha 0.25')
    self.ae(opts.inactive_text_alpha, 0.25)
    opts = p('inactive_text_alpha -0.25')
    self.ae(opts.inactive_text_alpha, -0.25)
    opts = p('inactive_text_alpha 2')
    self.ae(opts.inactive_text_alpha, 1.0)
    opts = p('inactive_text_alpha -2')
    self.ae(opts.inactive_text_alpha, -1.0)

    # deprecation handling
    opts = p('clear_all_shortcuts y', 'send_text all f1 hello')
    self.ae(len(opts.keyboard_modes[''].keymap), 1)
    opts = p('macos_hide_titlebar y' if is_macos else 'x11_hide_window_decorations y')
    self.assertTrue(opts.hide_window_decorations)
    self.ae(len(self.error_messages), 1)

    # line breaks
    opts = p('    font', ' \t  \t    \\_size', '    \\ 12', '\\.35', 'col', '\\o', '\t \t\\r', '\\25', ' \\ blue')
    self.ae(opts.font_size, 12.35)
    self.ae(opts.color25, Color(0, 0, 255))

    # cursor_blink_interval
    def cb(src, interval=-1, first=EasingFunction(), second=EasingFunction()):
        opts = p('cursor_blink_interval ' + src)
        self.ae((float(interval), first, second), (float(opts.cursor_blink_interval[0]), opts.cursor_blink_interval[1], opts.cursor_blink_interval[2]))

    cb('3', 3)
    cb('-2.3', -2.3)
    cb('linear', first=EasingFunction('cubic-bezier', cubic_bezier_points=(0, 0.0, 1.0, 1.0)))
    cb('linear 19', 19, EasingFunction('cubic-bezier', cubic_bezier_points=(0, 0.0, 1.0, 1.0)))
    cb(
        'ease-in-out cubic-bezier(0.1, 0.2, 0.3, 0.4) 11',
        11,
        EasingFunction('cubic-bezier', cubic_bezier_points=(0.42, 0, 0.58, 1)),
        EasingFunction('cubic-bezier', cubic_bezier_points=(0.1, 0.2, 0.3, 0.4)),
    )
    cb('step-start', first=EasingFunction('steps', num_steps=1, jump_type='start'))
    cb('steps(7, jump-none)', first=EasingFunction('steps', num_steps=7, jump_type='none'))
    cb('linear(0, 0.25, 1)', first=EasingFunction('linear', linear_x=(0.0, 0.5, 1.0), linear_y=(0, 0.25, 1.0)))
    cb('linear(0, 0.25 75%, 1)', first=EasingFunction('linear', linear_x=(0.0, 0.75, 1.0), linear_y=(0, 0.25, 1.0)))
    cb('linear(0, 0.25 25% 75%, 1)', first=EasingFunction('linear', linear_x=(0.0, 0.25, 0.75, 1.0), linear_y=(0, 0.25, 0.25, 1.0)))

    # test that easing functions give expected values
    def ef(spec, tests, only_single=True, duration=0.5, accuracy=0):
        cfv = p('cursor_blink_interval ' + spec).cursor_blink_interval
        self.set_options({'cursor_blink_interval': cfv})
        for t, expected in tests.items():
            actual = test_cursor_blink_easing_function(t, only_single, duration)
            if abs(actual - expected) > accuracy:
                self.ae(expected, actual, f'Failed for {spec=} with {t=}: {expected} != {actual}')

    ef('linear', {0: 1, 0.25: 0.5, 0.5: 0, 0.75: 0.5, 1: 1}, only_single=False)

    ef('linear(0, 0.25 25% 75%, 1)', {0: 0, 0.25: 0.25, 0.3: 0.25, 0.75: 0.25, 1: 1})
    linear_vals = {0: 0, 1: 1, 0.1234: 0.1234, 0.6453: 0.6453}
    for spec in ('linear', 'linear(0, 1)', 'cubic-bezier(0, 0, 1, 1)', 'cubic-bezier(0.2, 0.2, 0.7, 0.7)'):
        ef(spec, linear_vals)
    # test an almost linear function to test cubic bezier implementation
    ef('cubic-bezier(0.2, 0.2, 0.7, 0.71)', linear_vals, accuracy=0.01)
    ef('cubic-bezier(0.23, 0.2, 0.7, 0.71)', linear_vals, accuracy=0.01)

    ef('steps(5)', {0: 0, 0.1: 0, 0.3: 0.2, 0.9: 0.8})
    ef('steps(5, start)', {0: 0.2, 0.1: 0.2, 0.3: 0.4, 0.9: 1})
    ef('steps(4, jump-both)', {0: 0.2, 0.1: 0.2, 0.3: 0.4, 0.9: 1})
    ef('steps(6, jump-none)', {0: 0, 0.1: 0.0, 0.3: 0.2, 0.9: 1})

    # test various include modes
    base = os.path.join(self.tdir, 'glob')
    os.mkdir(base)
    with open(os.path.join(base, 'fg'), 'w') as f:
        print('foreground red', file=f)
    opts = p(f'include {f.name}', num_err=0)
    self.ae(opts.foreground, to_color('red'))
    with open(os.path.join(self.tdir, 'bg'), 'w') as f:
        print('background white', file=f)
        print('globinclude glob/*', file=f)
        print('envinclude ENVINCLUDE', file=f)
        print('geninclude g.py', file=f)
        print('geninclude g', file=f)
    with open(os.path.join(self.tdir, 'g.py'), 'w') as g:
        print('print("background_opacity .77")', file=g)
        print('print("background_blur 77")', file=g)
    with open(os.path.join(self.tdir, 'g'), 'w') as g:
        print('#!/bin/sh', file=g)
        print('echo background_image_linear y', file=g)
        print('echo background_image_layout clamped', file=g)
        os.chmod(g.fileno(), 0o700)
    os.environ['ENVINCLUDE'] = 'cursor yellow'
    opts = p(f'include {f.name}', num_err=0)
    os.environ.pop('ENVINCLUDE')
    self.ae(opts.foreground, to_color('red'))
    self.ae(opts.background, to_color('white'))
    self.ae(opts.cursor, to_color('yellow'))
    self.ae(opts.background_opacity, 0.77)
    self.ae(opts.background_blur, 77)
    self.ae(opts.background_image_linear, True)
    self.ae(opts.background_image_layout, 'clamped')
    with open(os.path.join(self.tdir, 'a'), 'w') as a:
        print('background red', file=a)
        print('include b', file=a)
    with open(os.path.join(self.tdir, 'b'), 'w') as a:
        print('foreground red', file=a)
        print('include a', file=a)
    opts = p(f'include {a.name}', num_err=0, bad_line_num=1)
    self.ae(opts.foreground, to_color('red'))
    self.ae(opts.background, to_color('red'))

    # remap_modifier. NOTE: parsing only. Whether the permutation is applied
    # simultaneously rather than sequentially is a property of
    # apply_modifier_remap() in C and is NOT observable from this dict - a
    # sequential implementation would produce an identical one. That property is
    # covered end to end by tests/test-remap-e2e.sh, which asserts that the
    # encoded bytes actually exchange.
    self.ae(p().remap_modifiers, {})
    ctrl, hyper, sup = to_modifiers('ctrl'), to_modifiers('hyper'), to_modifiers('super')
    self.ae(p('remap_modifiers ctrl:hyper').remap_modifiers, {ctrl: hyper})
    # both directions of a swap are recorded
    self.ae(p('remap_modifiers ctrl:hyper hyper:ctrl').remap_modifiers, {ctrl: hyper, hyper: ctrl})
    # the last declaration for a given source wins, wherever it appears
    self.ae(p('remap_modifiers ctrl:hyper', 'kitty_mod ctrl', 'remap_modifiers ctrl:super').remap_modifiers, {ctrl: sup})
    # the destination may name more than one modifier
    self.ae(p('remap_modifiers ctrl:ctrl+shift').remap_modifiers, {ctrl: to_modifiers('ctrl+shift')})
    # every rejection must be REPORTED, never silently ignored: wrong arity, unknown
    # or non-remappable modifier names, a source naming more than one modifier, and
    # a mapping that does nothing
    for bad in (
        'remap_modifiers ctrl',
        'remap_modifiers ctrl:hyper super',
        'remap_modifiers ctrl:nosuchmod',
        'remap_modifiers nosuchmod:ctrl',
        'remap_modifiers ctrl+shift:hyper',
        'remap_modifiers ctrl:none',
        'remap_modifiers none:ctrl',
        'remap_modifiers ctrl:kitty_mod',
        'remap_modifiers kitty_mod:ctrl',
        'remap_modifiers caps_lock:ctrl',
        'remap_modifiers ctrl:num_lock',
        'remap_modifiers ctrl:ctrl',
    ):
        self.ae(p(bad, num_err=1).remap_modifiers, {}, f'not rejected: {bad}')
