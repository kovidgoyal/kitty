#!/usr/bin/env python
# License: GPLv3 Copyright: 2022, Kovid Goyal <kovid at kovidgoyal.net>


import os
import shutil
import tempfile
import unittest
from contextlib import contextmanager

from kitty.constants import kitty_base_dir, terminfo_dir
from kitty.fast_data_types import CURSOR_BEAM
from kitty.shell_integration import rc_inset, setup_zsh_env

from . import BaseTest


def safe_env_for_running_shell(home_dir, rc='', shell='zsh'):
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
    if shell == 'zsh':
        ans['ZLE_RPROMPT_INDENT'] = '0'
        with open(os.path.join(home_dir, '.zshenv'), 'w') as f:
            print('unset GLOBAL_RCS', file=f)
        with open(os.path.join(home_dir, '.zshrc'), 'w') as f:
            print(rc + '\n', file=f)
        setup_zsh_env(ans)
    elif shell == 'bash':
        with open(os.path.join(home_dir, '.bash_profile'), 'w') as f:
            print('if [ -f ~/.bashrc ]; then . ~/.bashrc; fi', file=f)
        with open(os.path.join(home_dir, '.bashrc'), 'w') as f:
            # there is no way to prevent bash from reading the system
            # /etc/profile and some distros set a PROMPT_COMMAND in it.
            print('unset PROMPT_COMMAND', file=f)
            # ensure LINES and COLUMNS are kept up to date
            print('shopt -s checkwinsize', file=f)
            # Not sure why bash turns off echo in this scenario
            print('stty echo', file=f)
            if rc:
                print(rc, file=f)
            print(rc_inset('bash'), file=f)
    return ans


class ShellIntegration(BaseTest):

    @contextmanager
    def run_shell(self, shell='zsh', rc='', cmd='{shell} -il'):
        home_dir = os.path.realpath(tempfile.mkdtemp())
        try:
            pty = self.create_pty(cmd.format(**locals()), cwd=home_dir, env=safe_env_for_running_shell(home_dir, rc=rc, shell=shell))
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
            except TimeoutError:
                raise AssertionError(f'Cursor was not changed to beam. Screen contents: {repr(pty.screen_contents())}')
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

    @unittest.skipUnless(shutil.which('bash'), 'bash not installed')
    def test_bash_integration(self):
        ps1 = 'prompt> '
        with self.run_shell(
            shell='bash', rc=f'''
PS1="{ps1}"
''') as pty:
            try:
                pty.wait_till(lambda: pty.screen.cursor.shape == CURSOR_BEAM)
            except TimeoutError:
                raise AssertionError(f'Cursor was not changed to beam. Screen contents: {repr(pty.screen_contents())}')
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
