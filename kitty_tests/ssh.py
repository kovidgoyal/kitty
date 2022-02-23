#!/usr/bin/env python
# License: GPLv3 Copyright: 2021, Kovid Goyal <kovid at kovidgoyal.net>


import os
import shlex
import shutil
import tempfile

from kittens.ssh.main import bootstrap_script, get_connection_data
from kitty.utils import SSHConnectionData
from kitty.fast_data_types import CURSOR_BEAM

from . import BaseTest
from .shell_integration import bash_ok, basic_shell_env


class SSHTest(BaseTest):

    def test_basic_pty_operations(self):
        pty = self.create_pty('echo hello')
        pty.process_input_from_child()
        self.ae(pty.screen_contents(), 'hello')
        pty = self.create_pty(self.cmd_to_run_python_code('''\
import array, fcntl, sys, termios
buf = array.array('H', [0, 0, 0, 0])
fcntl.ioctl(sys.stdout, termios.TIOCGWINSZ, buf)
print(' '.join(map(str, buf)))'''), lines=13, cols=77)
        pty.process_input_from_child()
        self.ae(pty.screen_contents(), '13 77 770 260')

    def test_ssh_connection_data(self):
        def t(cmdline, binary='ssh', host='main', port=None, identity_file=''):
            if identity_file:
                identity_file = os.path.abspath(identity_file)
            q = get_connection_data(cmdline.split())
            self.ae(q, SSHConnectionData(binary, host, port, identity_file))

        t('ssh main')
        t('ssh un@ip -i ident -p34', host='un@ip', port=34, identity_file='ident')
        t('ssh un@ip -iident -p34', host='un@ip', port=34, identity_file='ident')
        t('ssh -p 33 main', port=33)

    def test_ssh_bootstrap_script(self):
        ok_login_shell = ''
        for sh in ('dash', 'zsh', 'bash', 'posh', 'sh'):
            q = shutil.which(sh)
            if q:
                if sh == 'bash' and not bash_ok():
                    continue
                for login_shell in ('', 'fish', 'zsh', 'bash'):
                    if (login_shell and not shutil.which(login_shell)) or (login_shell == 'bash' and not bash_ok()):
                        continue
                    ok_login_shell = login_shell
                    with self.subTest(sh=sh, login_shell=login_shell), tempfile.TemporaryDirectory() as tdir:
                        self.check_bootstrap(sh, tdir, login_shell)
        # check that turning off shell integration works
        if ok_login_shell in ('bash', 'zsh'):
            for val in ('', 'no-rc'):
                with tempfile.TemporaryDirectory() as tdir:
                    self.check_bootstrap('sh', tdir, ok_login_shell, val)

    def check_bootstrap(self, sh, home_dir, login_shell, SHELL_INTEGRATION_VALUE='enabled'):
        script = bootstrap_script(
            EXEC_CMD='echo "UNTAR_DONE"',
            OVERRIDE_LOGIN_SHELL=login_shell,
            SHELL_INTEGRATION_VALUE=SHELL_INTEGRATION_VALUE,
        )
        env = basic_shell_env(home_dir)
        # Avoid generating unneeded completion scripts
        os.makedirs(os.path.join(home_dir, '.local', 'share', 'fish', 'generated_completions'), exist_ok=True)
        # prevent newuser-install from running
        open(os.path.join(home_dir, '.zshrc'), 'w').close()
        self.assertFalse(os.path.exists(os.path.join(home_dir, '.terminfo/kitty.terminfo')))
        pty = self.create_pty(f'{sh} -c {shlex.quote(script)}', cwd=home_dir, env=env)
        del script
        pty.wait_till(lambda: 'UNTAR_DONE' in pty.screen_contents())
        self.assertTrue(os.path.exists(os.path.join(home_dir, '.terminfo/kitty.terminfo')))
        if SHELL_INTEGRATION_VALUE != 'enabled':
            pty.wait_till(lambda: len(pty.screen_contents().splitlines()) > 1)
            self.assertEqual(pty.screen.cursor.shape, 0)
        else:
            pty.wait_till(lambda: pty.screen.cursor.shape == CURSOR_BEAM)
