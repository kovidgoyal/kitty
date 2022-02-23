#!/usr/bin/env python
# License: GPLv3 Copyright: 2022, Kovid Goyal <kovid at kovidgoyal.net>


import os
import shlex
import shutil
import tempfile
import unittest
from contextlib import contextmanager
from functools import partial

from kitty.constants import is_macos, kitty_base_dir, terminfo_dir
from kitty.fast_data_types import CURSOR_BEAM, CURSOR_BLOCK, CURSOR_UNDERLINE
from kitty.shell_integration import setup_bash_env, setup_fish_env, setup_zsh_env

from . import BaseTest


def basic_shell_env(home_dir):
    ans = {
        'PATH': os.environ['PATH'],
        'HOME': home_dir,
        'TERM': 'xterm-kitty',
        'TERMINFO': terminfo_dir,
        'KITTY_SHELL_INTEGRATION': 'enabled',
        'KITTY_INSTALLATION_DIR': kitty_base_dir,
    }
    for x in ('USER', 'LANG'):
        if os.environ.get(x):
            ans[x] = os.environ[x]
    return ans


def safe_env_for_running_shell(argv, home_dir, rc='', shell='zsh'):
    ans = basic_shell_env(home_dir)
    if shell == 'zsh':
        ans['ZLE_RPROMPT_INDENT'] = '0'
        with open(os.path.join(home_dir, '.zshenv'), 'w') as f:
            print('unset GLOBAL_RCS', file=f)
        with open(os.path.join(home_dir, '.zshrc'), 'w') as f:
            print(rc + '\n', file=f)
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
        setup_bash_env(ans, argv)
        ans['KITTY_BASH_INJECT'] += ' posix'
        ans['KITTY_BASH_POSIX_ENV'] = os.path.join(home_dir, '.bashrc')
        with open(ans['KITTY_BASH_POSIX_ENV'], 'w') as f:
            # ensure LINES and COLUMNS are kept up to date
            print('shopt -s checkwinsize', file=f)
            if rc:
                print(rc, file=f)
    return ans


class ShellIntegration(BaseTest):

    @contextmanager
    def run_shell(self, shell='zsh', rc='', cmd='', setup_env=None):
        home_dir = os.path.realpath(tempfile.mkdtemp())
        cmd = cmd or shell
        cmd = shlex.split(cmd.format(**locals()))
        env = (setup_env or safe_env_for_running_shell)(cmd, home_dir, rc=rc, shell=shell)
        try:
            pty = self.create_pty(cmd, cwd=home_dir, env=env)
            i = 10
            while i > 0 and not pty.screen_contents().strip():
                pty.process_input_from_child()
                i -= 1
            yield pty
        finally:
            if os.path.exists(home_dir):
                shutil.rmtree(home_dir)

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
            self.ae(pty.screen_contents(), q)
            self.ae(pty.callbacks.titlebuf[-1], '~')
            pty.callbacks.clear()
            pty.send_cmd_to_child('mkdir test && ls -a')
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
            pty.wait_till(lambda: pty.screen_contents().count(rps1) == 3)
            self.ae('40', str(pty.screen.line(pty.screen.cursor.y - 1)))
            self.ae(q, str(pty.screen.line(pty.screen.cursor.y - 2)))
            pty.send_cmd_to_child('clear')
            q = ps1 + ' ' * (pty.screen.columns - len(ps1) - len(rps1)) + rps1
            pty.wait_till(lambda: pty.screen_contents() == q)
            pty.wait_till(lambda: pty.screen.cursor.shape == CURSOR_BEAM)
            pty.send_cmd_to_child('cat')
            pty.wait_till(lambda: pty.screen.cursor.shape == 0)
            pty.write_to_child('\x04')
            pty.wait_till(lambda: pty.screen.cursor.shape == CURSOR_BEAM)

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
function _ksi_test_comp; contains "{completions_dir}" $fish_complete_path; and echo ok; end
''') as pty:
            q = fish_prompt + ' ' * (pty.screen.columns - len(fish_prompt) - len(right_prompt)) + right_prompt
            pty.wait_till(lambda: pty.screen_contents().count(right_prompt) == 1)
            self.ae(pty.screen_contents(), q)

            # XDG_DATA_DIRS
            pty.send_cmd_to_child('set -q XDG_DATA_DIRS; or echo ok')
            pty.wait_till(lambda: pty.screen_contents().count(right_prompt) == 2)
            self.ae(str(pty.screen.line(1)), 'ok')

            # completion and prompt marking
            pty.send_cmd_to_child('clear')
            pty.send_cmd_to_child('_ksi_test_comp')
            pty.wait_till(lambda: pty.screen_contents().count(right_prompt) == 2)
            # with open('/tmp/1.log', 'a') as logf:
            #     print(str(pty.screen_contents()), file=logf)
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
            pty.send_cmd_to_child('fish_vi_key_bindings')
            pty.wait_till(lambda: pty.screen.cursor.shape == CURSOR_BLOCK)
            pty.write_to_child('i')
            pty.wait_till(lambda: pty.screen.cursor.shape == CURSOR_BEAM)
            pty.write_to_child('\x1b')
            pty.wait_till(lambda: pty.screen.cursor.shape == CURSOR_BLOCK)
            pty.write_to_child('r')
            pty.wait_till(lambda: pty.screen.cursor.shape == CURSOR_UNDERLINE)

            pty.write_to_child('\x1biexit\r')

    @unittest.skipUnless(not is_macos and shutil.which('bash'), 'macOS bash is too old' if is_macos else 'bash not installed')
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
            pty.send_cmd_to_child('mkdir test && ls -a')
            pty.wait_till(lambda: pty.callbacks.titlebuf[-2:] == ['mkdir test && ls -a', '~'])
            pty.wait_till(lambda: pty.screen_contents().count(ps1) == 2)
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

        # test startup file sourcing

        def setup_env(excluded, argv, home_dir, rc='', shell='bash'):
            ans = basic_shell_env(home_dir)
            setup_bash_env(ans, argv)
            for x in {'profile', 'bash.bashrc', '.bash_profile', '.bash_login', '.profile', '.bashrc', 'rcfile'} - excluded:
                with open(os.path.join(home_dir, x), 'w') as f:
                    print(f'echo {x}', file=f)
            ans['KITTY_BASH_ETC_LOCATION'] = home_dir
            return ans

        def run_test(argv, *expected, excluded=()):
            with self.subTest(argv=argv), self.run_shell(shell='bash', setup_env=partial(setup_env, set(excluded)), cmd=argv) as pty:
                pty.wait_till(lambda: '$' in pty.screen_contents())
                q = pty.screen_contents()
                for x in expected:
                    self.assertIn(x, q)

        run_test('bash', 'bash.bashrc', '.bashrc')
        run_test('bash --rcfile rcfile', 'bash.bashrc', 'rcfile')
        run_test('bash --init-file rcfile', 'bash.bashrc', 'rcfile')
        run_test('bash --norc')
        run_test('bash -l', 'profile', '.bash_profile')
        run_test('bash --noprofile -l')
        run_test('bash -l', 'profile', '.bash_login', excluded=('.bash_profile',))
        run_test('bash -l', 'profile', '.profile', excluded=('.bash_profile', '.bash_login'))
