#!/usr/bin/env python
# License: GPLv3 Copyright: 2022, Kovid Goyal <kovid at kovidgoyal.net>


import errno
import os
import shlex
import shutil
import subprocess
import tempfile
import unittest
from contextlib import contextmanager
from functools import lru_cache, partial

from kitty.bash import decode_ansi_c_quoted_string
from kitty.constants import is_macos, kitten_exe, kitty_base_dir, shell_integration_dir, terminfo_dir
from kitty.fast_data_types import CURSOR_BEAM, CURSOR_BLOCK, CURSOR_UNDERLINE
from kitty.shell_integration import setup_bash_env, setup_fish_env, setup_zsh_env

from . import BaseTest


@lru_cache
def bash_ok():
    v = shutil.which('bash')
    if not v:
        return False
    o = subprocess.check_output([v, '-c', 'echo "${BASH_VERSINFO[0]}\n${BASH_VERSINFO[4]}"']).decode('utf-8').splitlines()
    if not o:
        return False
    major_ver, relstatus = o[0], o[-1]
    return int(major_ver) >= 5 and relstatus == 'release'


def basic_shell_env(home_dir):
    ans = {
        'PATH': os.environ.get('PATH', '/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin'),
        'HOME': home_dir,
        'TERM': 'xterm-kitty',
        'TERMINFO': terminfo_dir,
        'KITTY_SHELL_INTEGRATION': 'enabled',
        'KITTY_INSTALLATION_DIR': kitty_base_dir,
        'BASH_SILENCE_DEPRECATION_WARNING': '1',
        'PYTHONDONTWRITEBYTECODE': '1',
        'WEZTERM_SHELL_SKIP_ALL': '1',  # dont fail if WezTerm's system wide, default on (why?) shell integration is installed
    }
    for x in ('USER', 'LANG'):
        if os.environ.get(x):
            ans[x] = os.environ[x]
    return ans


def safe_env_for_running_shell(argv, home_dir, rc='', shell='zsh', with_kitten=False):
    ans = basic_shell_env(home_dir)
    if shell == 'zsh':
        argv.insert(1, '--noglobalrcs')
        with open(os.path.join(home_dir, '.zshrc'), 'w') as f:
            print(rc + '\nZLE_RPROMPT_INDENT=0', file=f)
        setup_zsh_env(ans, argv)
    elif shell == 'fish':
        conf_dir = os.path.join(home_dir, '.config', 'fish')
        os.makedirs(conf_dir, exist_ok=True)
        # Avoid generating unneeded completion scripts
        os.makedirs(os.path.join(home_dir, '.local', 'share', 'fish', 'generated_completions'), exist_ok=True)
        with open(os.path.join(conf_dir, 'config.fish'), 'w') as f:
            print(rc + '\n', file=f)
        setup_fish_env(ans, argv)
    elif shell == 'bash':
        bashrc = os.path.join(home_dir, '.bashrc')
        if with_kitten:
            ans['KITTY_RUNNING_BASH_INTEGRATION_TEST'] = bashrc
        else:
            setup_bash_env(ans, argv)
            ans['KITTY_BASH_INJECT'] += ' posix'
            ans['KITTY_BASH_POSIX_ENV'] = bashrc
        with open(bashrc, 'w') as f:
            # ensure LINES and COLUMNS are kept up to date
            print('shopt -s checkwinsize', file=f)
            if rc:
                print(rc, file=f)
    return ans


class ShellIntegration(BaseTest):

    with_kitten = False

    @contextmanager
    def run_shell(self, shell='zsh', rc='', cmd='', setup_env=None):
        home_dir = self.home_dir = os.path.realpath(tempfile.mkdtemp())
        cmd = cmd or shell
        cmd = shlex.split(cmd.format(**locals()))
        env = (setup_env or safe_env_for_running_shell)(cmd, home_dir, rc=rc, shell=shell, with_kitten=self.with_kitten)
        env['KITTY_RUNNING_SHELL_INTEGRATION_TEST'] = '1'
        try:
            if self.with_kitten:
                cmd = [kitten_exe(), 'run-shell', '--shell', shlex.join(cmd)]
            pty = self.create_pty(cmd, cwd=home_dir, env=env, cols=180)
            i = 10
            while i > 0 and not pty.screen_contents().strip():
                pty.process_input_from_child()
                i -= 1
            yield pty
        finally:
            while os.path.exists(home_dir):
                try:
                    shutil.rmtree(home_dir)
                except OSError as e:
                    # As of fish 4 fish runs a background daemon generating
                    # completions.
                    if e.errno == errno.ENOTEMPTY:
                        continue
                    raise

    @unittest.skipUnless(shutil.which('zsh'), 'zsh not installed')
    def test_zsh_integration(self):
        ps1, rps1 = 'left>', '<right'
        with self.run_shell(
            rc=f'''
PS1="{ps1}"
RPS1="{rps1}"
''') as pty:
            q = ps1 + ' ' * (pty.screen.columns - len(ps1) - len(rps1)) + rps1
            try:
                pty.wait_till(lambda: pty.screen.cursor.shape == CURSOR_BEAM)
            except TimeoutError as e:
                raise AssertionError(f'Cursor was not changed to beam. Screen contents: {repr(pty.screen_contents())}') from e
            pty.wait_till(lambda: pty.screen_contents() == q)
            self.ae(pty.callbacks.titlebuf[-1], '~')
            pty.callbacks.clear()
            pty.send_cmd_to_child('mkdir test && ls -a')
            self.assert_command(pty)
            pty.wait_till(lambda: pty.screen_contents().count(rps1) == 2)
            self.ae(pty.callbacks.titlebuf[-2:], ['mkdir test && ls -a', '~'])
            q = '\n'.join(str(pty.screen.line(i)) for i in range(1, pty.screen.cursor.y))
            self.ae(pty.last_cmd_output(), q)
            # shrink the screen
            pty.write_to_child(r'echo $COLUMNS')
            pty.set_window_size(rows=20, columns=40)
            q = ps1 + 'echo $COLUMNS' + ' ' * (40 - len(ps1) - len(rps1) - len('echo $COLUMNS')) + rps1
            pty.process_input_from_child()

            def redrawn():
                q = pty.screen_contents()
                return '$COLUMNS' in q and q.count(rps1) == 2 and q.count(ps1) == 2

            pty.wait_till(redrawn)
            self.ae(q, str(pty.screen.line(pty.screen.cursor.y)))
            pty.write_to_child('\r')
            self.assert_command(pty, 'echo $COLUMNS')
            pty.wait_till(lambda: pty.screen_contents().count(rps1) == 3)
            self.ae('40', str(pty.screen.line(pty.screen.cursor.y - 1)))
            self.ae(q, str(pty.screen.line(pty.screen.cursor.y - 2)))
            pty.send_cmd_to_child('clear')
            self.assert_command(pty)
            q = ps1 + ' ' * (pty.screen.columns - len(ps1) - len(rps1)) + rps1
            pty.wait_till(lambda: pty.screen_contents() == q)
            pty.wait_till(lambda: pty.screen.cursor.shape == CURSOR_BEAM)
            pty.send_cmd_to_child('cat')
            pty.wait_till(lambda: pty.screen.cursor.shape == 0)
            pty.write_to_child('\x04')
            pty.wait_till(lambda: pty.screen.cursor.shape == CURSOR_BEAM)
            self.assert_command(pty)
            # Check escaping of inputs
            pty.send_cmd_to_child("-f-this-command-must-not-exist")
            self.assert_command(pty, exit_status=127)
        with self.run_shell(rc=f'''PS1="{ps1}"''') as pty:
            pty.callbacks.clear()
            pty.send_cmd_to_child('printf "%s\x16\a%s" "a" "b"')
            pty.wait_till(lambda: 'ab' in pty.screen_contents())
            self.assertTrue(pty.screen.last_reported_cwd.decode().endswith(self.home_dir))
            self.assertIn('%s^G%s', pty.screen_contents())
            q = os.path.join(self.home_dir, 'testing-cwd-notification-🐱')
            os.mkdir(q)
            pty.send_cmd_to_child(f'cd {q}')
            pty.wait_till(lambda: pty.screen.last_reported_cwd.decode().endswith(q))
            if not is_macos:  # Fails on older macOS like the one used to build kitty binary because of unicode encoding issues
                self.assert_command(pty)
        with self.run_shell(rc=f'''PS1="{ps1}"\nexport ES="a\n b c\nd"''') as pty:
            pty.callbacks.clear()
            pty.send_cmd_to_child('clone-in-kitty')
            pty.wait_till(lambda: len(pty.callbacks.clone_cmds) == 1)
            self.assert_command(pty)
            env = pty.callbacks.clone_cmds[0].env
            self.ae(env.get('ES'), 'a\n b c\nd')

    @unittest.skipUnless(shutil.which('fish'), 'fish not installed')
    def test_fish_integration(self):
        fish_prompt, right_prompt = 'left>', '<right'
        completions_dir = os.path.join(kitty_base_dir, 'shell-integration', 'fish', 'vendor_completions.d')
        with self.run_shell(
            shell='fish',
            rc=f'''
set -g fish_greeting
function fish_prompt; echo -n "{fish_prompt}"; end
function fish_right_prompt; echo -n "{right_prompt}"; end
function _test_comp_path; contains "{completions_dir}" $fish_complete_path; and echo ok; end
function _set_key; set -g fish_key_bindings fish_$argv[1]_key_bindings; end
function _set_status_prompt; function fish_prompt; echo -n "$pipestatus $status {fish_prompt}"; end; end
''') as pty:
            q = fish_prompt + ' ' * (pty.screen.columns - len(fish_prompt) - len(right_prompt)) + right_prompt
            pty.wait_till(lambda: pty.screen_contents().count(right_prompt) == 1)
            self.ae(pty.screen_contents(), q)

            # shell integration dir must not be in XDG_DATA_DIRS
            cmd = f'string match -q -- "*{shell_integration_dir}*" "$XDG_DATA_DIRS" || echo "XDD_OK"'
            pty.send_cmd_to_child(cmd)
            pty.wait_till(lambda: 'XDD_OK' in pty.screen_contents())
            # self.assert_command(pty, cmd)

            # CWD reporting
            self.assertTrue(pty.screen.last_reported_cwd.decode().endswith(self.home_dir))
            q = os.path.join(self.home_dir, 'testing-cwd-notification-🐱')
            os.mkdir(q)
            pty.send_cmd_to_child(f'cd {q}')
            # self.assert_command(pty)
            pty.wait_till(lambda: pty.screen.last_reported_cwd.decode().endswith(q))
            pty.send_cmd_to_child('cd -')
            pty.wait_till(lambda: pty.screen.last_reported_cwd.decode().endswith(self.home_dir))

            # completion and prompt marking
            pty.wait_till(lambda: 'cd -' not in pty.screen_contents().splitlines()[-1])
            pty.send_cmd_to_child('clear')
            pty.wait_till(lambda: pty.screen_contents().count(right_prompt) == 1)
            pty.send_cmd_to_child('_test_comp_path')
            # self.assert_command(pty)
            pty.wait_till(lambda: pty.screen_contents().count(right_prompt) == 2)
            q = '\n'.join(str(pty.screen.line(i)) for i in range(1, pty.screen.cursor.y))
            self.ae(q, 'ok')
            self.ae(pty.last_cmd_output(), q)

            # resize and redraw (fish_handle_reflow)
            pty.write_to_child(r'echo $COLUMNS')
            pty.set_window_size(rows=20, columns=40)
            q = fish_prompt + 'echo $COLUMNS' + ' ' * (40 - len(fish_prompt) - len(right_prompt) - len('echo $COLUMNS')) + right_prompt
            pty.process_input_from_child()

            def redrawn():
                q = pty.screen_contents()
                return '$COLUMNS' in q and q.count(right_prompt) == 2 and q.count(fish_prompt) == 2

            pty.wait_till(redrawn)
            self.ae(q, str(pty.screen.line(pty.screen.cursor.y)))
            pty.write_to_child('\r')
            pty.wait_till(lambda: pty.screen_contents().count(right_prompt) == 3)
            # self.assert_command(pty, 'echo $COLUMNS')
            self.ae('40', str(pty.screen.line(pty.screen.cursor.y - 1)))
            self.ae(q, str(pty.screen.line(pty.screen.cursor.y - 2)))

            # cursor shapes
            pty.send_cmd_to_child('clear')
            q = fish_prompt + ' ' * (pty.screen.columns - len(fish_prompt) - len(right_prompt)) + right_prompt
            pty.wait_till(lambda: pty.screen_contents() == q)
            pty.wait_till(lambda: pty.screen.cursor.shape == CURSOR_BEAM)
            pty.send_cmd_to_child('echo; cat')
            pty.wait_till(lambda: pty.screen.cursor.shape == 0 and pty.screen.cursor.y > 1)
            pty.write_to_child('\x04')
            pty.wait_till(lambda: pty.screen.cursor.shape == CURSOR_BEAM)
            pty.send_cmd_to_child('_set_key vi')
            pty.wait_till(lambda: pty.screen_contents().count(right_prompt) == 3)
            pty.wait_till(lambda: pty.screen.cursor.shape == CURSOR_BEAM)
            pty.write_to_child('\x1b')
            pty.wait_till(lambda: pty.screen.cursor.shape == CURSOR_BLOCK)
            pty.write_to_child('r')
            pty.wait_till(lambda: pty.screen.cursor.shape == CURSOR_UNDERLINE)
            pty.write_to_child('\x1b')
            pty.wait_till(lambda: pty.screen.cursor.shape == CURSOR_BLOCK)
            pty.write_to_child('i')
            pty.wait_till(lambda: pty.screen.cursor.shape == CURSOR_BEAM)
            pty.send_cmd_to_child('_set_key default')
            # self.assert_command(pty)
            pty.wait_till(lambda: pty.screen_contents().count(right_prompt) == 4)
            pty.wait_till(lambda: pty.screen.cursor.shape == CURSOR_BEAM)

            pty.send_cmd_to_child('exit')

    def assert_command(self, pty, cmd='', exit_status=0):
        cmd = cmd or pty.last_cmd
        pty.wait_till(lambda: pty.callbacks.last_cmd_exit_status == exit_status, timeout_msg=lambda: f'{pty.callbacks.last_cmd_exit_status=} != {exit_status}')
        pty.wait_till(lambda: pty.callbacks.last_cmd_cmdline == cmd, timeout_msg=lambda: f'{pty.callbacks.last_cmd_cmdline=!r} != {cmd!r}')

    @unittest.skipUnless(bash_ok(), 'bash not installed, too old, or debug build')
    def test_bash_integration(self):
        ps1 = 'prompt> '
        with self.run_shell(
            shell='bash', rc=f'''
PS1="{ps1}"
''') as pty:
            try:
                pty.wait_till(lambda: pty.screen.cursor.shape == CURSOR_BEAM)
            except TimeoutError as e:
                raise AssertionError(f'Cursor was not changed to beam. Screen contents: {repr(pty.screen_contents())}') from e
            pty.wait_till(lambda: pty.screen_contents().count(ps1) == 1)
            self.ae(pty.screen_contents(), ps1)
            pty.wait_till(lambda: pty.callbacks.titlebuf[-1:] == ['~'])
            self.ae(pty.callbacks.titlebuf[-1], '~')
            pty.callbacks.clear()
            cmd = 'mkdir test && ls -a'
            pty.send_cmd_to_child(cmd)
            pty.wait_till(lambda: pty.callbacks.titlebuf[-2:] == [cmd, '~'])
            pty.wait_till(lambda: pty.screen_contents().count(ps1) == 2)
            self.assert_command(pty, cmd)
            q = '\n'.join(str(pty.screen.line(i)) for i in range(1, pty.screen.cursor.y))
            self.ae(pty.last_cmd_output(), q)
            # shrink the screen
            pty.write_to_child(r'echo $COLUMNS')
            pty.set_window_size(rows=20, columns=40)
            pty.process_input_from_child()

            def redrawn():
                q = pty.screen_contents()
                return '$COLUMNS' in q and q.count(ps1) == 2

            pty.wait_till(redrawn)
            self.ae(ps1 + 'echo $COLUMNS', str(pty.screen.line(pty.screen.cursor.y)))
            pty.write_to_child('\r')
            pty.wait_till(lambda: pty.screen_contents().count(ps1) == 3)
            self.ae('40', str(pty.screen.line(pty.screen.cursor.y - 1)))
            self.ae(ps1 + 'echo $COLUMNS', str(pty.screen.line(pty.screen.cursor.y - 2)))
            pty.send_cmd_to_child('clear')
            pty.wait_till(lambda: pty.screen_contents() == ps1)
            pty.wait_till(lambda: pty.screen.cursor.shape == CURSOR_BEAM)
            pty.send_cmd_to_child('cat')
            pty.wait_till(lambda: pty.screen.cursor.shape == 0)
            pty.write_to_child('\x04')
            pty.wait_till(lambda: pty.screen.cursor.shape == CURSOR_BEAM)
            pty.write_to_child('\x04')
            pty.send_cmd_to_child('clear')
            pty.wait_till(lambda: pty.callbacks.titlebuf)
        with self.run_shell(shell='bash', rc=f'''PS1="{ps1}"\ndeclare LOCAL_KSI_VAR=1''') as pty:
            pty.callbacks.clear()
            pty.send_cmd_to_child('declare')
            pty.wait_till(lambda: 'LOCAL_KSI_VAR' in pty.screen_contents())
            self.assert_command(pty, 'declare')
        with self.run_shell(shell='bash', rc=f'''PS1="{ps1}"''') as pty:
            pty.callbacks.clear()
            pty.send_cmd_to_child('printf "%s\x16\a%s" "a" "b"')
            pty.wait_till(lambda: pty.screen_contents().count(ps1) == 2)
            self.ae(pty.screen_contents(), f'{ps1}printf "%s^G%s" "a" "b"\nab{ps1}')
            self.assertTrue(pty.screen.last_reported_cwd.decode().endswith(self.home_dir))
            pty.send_cmd_to_child('echo $HISTFILE')
            pty.wait_till(lambda: '.bash_history' in pty.screen_contents().replace('\n', ''))
            q = os.path.join(self.home_dir, 'testing-cwd-notification-🐱')
            os.mkdir(q)
            pty.send_cmd_to_child(f'cd {q}')
            pty.wait_till(lambda: pty.screen.last_reported_cwd.decode().endswith(q))

        for ps1 in ('line1\\nline\\2\\prompt> ', 'line1\nprompt> ', 'line1\\nprompt> ',):
            with self.subTest(ps1=ps1), self.run_shell(
                shell='bash', rc=f'''
    PS1="{ps1}"
    ''') as pty:
                ps1 = ps1.replace('\\n', '\n')
                pty.wait_till(lambda: pty.screen_contents().count(ps1) == 1)
                pty.send_cmd_to_child('echo test')
                pty.wait_till(lambda: pty.screen_contents().count(ps1) == 2)
                self.ae(pty.screen_contents(), f'{ps1}echo test\ntest\n{ps1}')
                pty.write_to_child(r'echo $COLUMNS')
                pty.set_window_size(rows=20, columns=40)
                pty.process_input_from_child()
                pty.wait_till(redrawn)
                self.ae(ps1.splitlines()[-1] + 'echo $COLUMNS', str(pty.screen.line(pty.screen.cursor.y)))
                pty.write_to_child('\r')
                pty.wait_till(lambda: pty.screen_contents().count(ps1) == 3)
                self.ae('40', str(pty.screen.line(pty.screen.cursor.y - len(ps1.splitlines()))))
                self.ae(ps1.splitlines()[-1] + 'echo $COLUMNS', str(pty.screen.line(pty.screen.cursor.y - 1 - len(ps1.splitlines()))))
                self.assert_command(pty, 'echo $COLUMNS')

        # test startup file sourcing

        def setup_env(excluded, argv, home_dir, rc='', shell='bash', with_kitten=self.with_kitten):
            ans = basic_shell_env(home_dir)
            if not with_kitten:
                setup_bash_env(ans, argv)
            for x in {'profile', 'bash.bashrc', '.bash_profile', '.bash_login', '.profile', '.bashrc', 'rcfile'} - excluded:
                with open(os.path.join(home_dir, x), 'w') as f:
                    if x == '.bashrc' and rc:
                        print(rc, file=f)
                    else:
                        print(f'echo [{x}]', file=f)
            ans['KITTY_BASH_ETC_LOCATION'] = home_dir
            ans['PS1'] = 'PROMPT $ '
            return ans

        def run_test(argv, *expected, excluded=(), rc='', wait_string='PROMPT $', assert_not_in=False):
            with self.subTest(argv=argv), self.run_shell(shell='bash', setup_env=partial(setup_env, set(excluded)), cmd=argv, rc=rc) as pty:
                pty.wait_till(lambda: wait_string in pty.screen_contents())
                q = pty.screen_contents()
                for x in expected:
                    if assert_not_in:
                        self.assertNotIn(f'[{x}]', q)
                    else:
                        self.assertIn(f'[{x}]', q)

        run_test('bash', 'bash.bashrc', '.bashrc')
        run_test('bash --rcfile rcfile', 'bash.bashrc', 'rcfile')
        run_test('bash --init-file rcfile', 'bash.bashrc', 'rcfile')
        run_test('bash --norc')
        run_test('bash -l', 'profile', '.bash_profile')
        run_test('bash --noprofile -l')
        run_test('bash -l', 'profile', '.bash_login', excluded=('.bash_profile',))
        run_test('bash -l', 'profile', '.profile', excluded=('.bash_profile', '.bash_login'))

        # test argument parsing and non-interactive shell
        run_test('bash -s arg1 --rcfile rcfile', 'rcfile', rc='echo ok;read', wait_string='ok', assert_not_in=True)
        run_test('bash +O login_shell -ic "echo ok;read"', 'bash.bashrc', excluded=('.bash_profile'), wait_string='ok', assert_not_in=True)
        run_test('bash -l .bashrc', 'profile', rc='echo ok;read', wait_string='ok', assert_not_in=True)
        run_test('bash -il -- .bashrc', 'profile', rc='echo ok;read', wait_string='ok')

        with self.run_shell(shell='bash', setup_env=partial(setup_env, set()), cmd='bash',
                            rc=f'''PS1="{ps1}"\nexport ES=$'a\n `b` c\n$d'\nexport ES2="XXX" ''') as pty:
            pty.callbacks.clear()
            pty.send_cmd_to_child('clone-in-kitty')
            pty.wait_till(lambda: len(pty.callbacks.clone_cmds) == 1)
            env = pty.callbacks.clone_cmds[0].env
            self.ae(env.get('ES'), 'a\n `b` c\n$d', f'Screen contents: {pty.screen_contents()!r}')
            self.ae(env.get('ES2'), 'XXX', f'Screen contents: {pty.screen_contents()!r}')

        for q, e in {
            'a': 'a',
            r'a\ab': 'a\ab',
            r'a\x7z': 'a\x07z',
            r'a\7b': 'a\007b',
            r'a\U1f345x': 'a🍅x',
            r'a\c b': 'a\0b',
        }.items():
            self.ae(decode_ansi_c_quoted_string(f"$'{q}'"), e, f'Failed to decode: {q!r}')


class ShellIntegrationWithKitten(ShellIntegration):
    with_kitten = True
