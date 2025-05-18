#!/usr/bin/env python
# License: GPLv3 Copyright: 2021, Kovid Goyal <kovid at kovidgoyal.net>


import glob
import json
import os
import shutil
import subprocess
import tempfile
from contextlib import suppress
from functools import lru_cache

from kittens.ssh.utils import get_connection_data
from kitty.constants import is_macos, kitten_exe, runtime_dir
from kitty.fast_data_types import CURSOR_BEAM, shm_unlink
from kitty.utils import SSHConnectionData

from . import BaseTest, retry_on_failure
from .shell_integration import bash_ok, basic_shell_env


def files_in(path):
    for record in os.walk(path):
        for f in record[-1]:
            yield os.path.relpath(os.path.join(record[0], f), path)


class SSHKitten(BaseTest):

    @retry_on_failure()
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

    @retry_on_failure()
    def test_ssh_connection_data(self):
        def t(cmdline, binary='ssh', host='main', port=None, identity_file='', extra_args=()):
            if identity_file:
                identity_file = os.path.abspath(identity_file)
            en = {f'{x[0]}' for x in extra_args}
            q = get_connection_data(cmdline.split(), extra_args=en)
            self.ae(q, SSHConnectionData(binary, host, port, identity_file, extra_args))

        t('ssh main')
        t('ssh un@ip -i ident -p34', host='un@ip', port=34, identity_file='ident')
        t('ssh un@ip -iident -p34', host='un@ip', port=34, identity_file='ident')
        t('ssh -p 33 main', port=33)
        t('ssh -p 34 ssh://un@ip:33/', host='un@ip', port=34)
        t('ssh --kitten=one -p 12 --kitten two -ix main', identity_file='x', port=12, extra_args=(('--kitten', 'one'), ('--kitten', 'two')))
        self.assertTrue(runtime_dir())

    @property
    @lru_cache
    def all_possible_sh(self):
        python = 'python3' if shutil.which('python3') else 'python'
        return tuple(filter(shutil.which, ('dash', 'zsh', 'bash', 'posh', 'sh', python)))

    @retry_on_failure()
    def test_ssh_copy(self):
        simple_data = 'rkjlhfwf9whoaa'

        def touch(p):
            with open(os.path.join(local_home, p), 'w') as f:
                f.write(simple_data)

        for sh in self.all_possible_sh:
            with tempfile.TemporaryDirectory() as remote_home, tempfile.TemporaryDirectory() as local_home:
                tuple(map(touch, 'simple-file g.1 g.2'.split()))
                os.makedirs(f'{local_home}/d1/d2/d3')
                touch('d1/d2/x')
                touch('d1/d2/w.exclude')
                os.mkdir(f'{local_home}/d1/r')
                touch('d1/r/noooo')
                os.symlink('d2/x', f'{local_home}/d1/y')
                os.symlink('simple-file', f'{local_home}/s1')
                os.symlink('simple-file', f'{local_home}/s2')

                conf = '''\
copy simple-file
copy s1
copy --symlink-strategy=keep-path s2
copy --dest=a/sfa simple-file
copy --glob g.*
copy --exclude **/w.* --exclude **/r d1
'''
                self.check_bootstrap(
                    sh, remote_home, test_script='env; exit 0', SHELL_INTEGRATION_VALUE='', conf=conf, home=local_home,
                )
                tname = '.terminfo'
                if os.path.exists('/usr/share/misc/terminfo.cdb'):
                    tname += '.cdb'
                self.assertTrue(os.path.lexists(f'{remote_home}/{tname}/78'))
                self.assertTrue(os.path.exists(f'{remote_home}/{tname}/78/xterm-kitty'))
                self.assertTrue(os.path.exists(f'{remote_home}/{tname}/x/xterm-kitty'))
                for w in ('simple-file', 'a/sfa', 's2'):
                    with open(os.path.join(remote_home, w)) as f:
                        self.ae(f.read(), simple_data)
                    self.assertFalse(os.path.islink(f.name))
                self.assertTrue(os.path.lexists(f'{remote_home}/d1/y'))
                self.assertTrue(os.path.exists(f'{remote_home}/d1/y'))
                self.ae(os.readlink(f'{remote_home}/d1/y'), 'd2/x')
                self.ae(os.readlink(f'{remote_home}/s1'), 'simple-file')
                contents = set(files_in(remote_home))
                contents.discard('.zshrc')  # added by check_bootstrap()
                # depending on platform one of these is a symlink and hence
                # isn't in contents
                contents.discard(f'{tname}/x/xterm-kitty')
                contents.discard(f'{tname}/78/xterm-kitty')
                self.ae(contents, {
                    'g.1', 'g.2', f'{tname}/kitty.terminfo', 'simple-file', 'd1/d2/x', 'd1/y', 'a/sfa', 's1', 's2',
                    '.local/share/kitty-ssh-kitten/kitty/version', '.local/share/kitty-ssh-kitten/kitty/bin/kitty',
                    '.local/share/kitty-ssh-kitten/kitty/bin/kitten'
                })
                self.ae(len(glob.glob(f'{remote_home}/{tname}/*/xterm-kitty')), 2)

    @retry_on_failure()
    def test_ssh_env_vars(self):
        tset = '$A-$(echo no)-`echo no2` !Q5 "something else"'
        for sh in self.all_possible_sh:
            with tempfile.TemporaryDirectory() as tdir:
                os.mkdir(os.path.join(tdir, 'cwd'))
                conf = f'''
cwd $HOME/cwd
env A=AAA
env TSET={tset}
env COLORTERM
'''
                pty = self.check_bootstrap(
                    sh, tdir, test_script='env; pwd; exit 0', SHELL_INTEGRATION_VALUE='', conf=conf
                )
                pty.wait_till(lambda: 'TSET={}'.format(tset.replace('$A', 'AAA')) in pty.screen_contents())
                self.assertNotIn('COLORTERM', pty.screen_contents())
                pty.wait_till(lambda: '/cwd' in pty.screen_contents())
                self.assertTrue(pty.is_echo_on())

    @retry_on_failure()
    def test_ssh_bootstrap_with_different_launchers(self):
        for launcher in self.all_possible_sh:
            if 'python' in launcher:
                continue
            for sh in self.all_possible_sh:
                if sh == 'sh' or 'python' in sh:
                    q = shutil.which(launcher)
                    if q:
                        with tempfile.TemporaryDirectory() as tdir:
                            self.check_bootstrap(sh, tdir, test_script='env; exit 0', SHELL_INTEGRATION_VALUE='', launcher=q)

    @retry_on_failure()
    def test_ssh_leading_data(self):
        script = 'echo "ld:$leading_data"; exit 0'
        for sh in self.all_possible_sh:
            if 'python' in sh:
                script = 'print("ld:" + leading_data.decode("ascii")); raise SystemExit(0);'
            with tempfile.TemporaryDirectory() as tdir:
                pty = self.check_bootstrap(
                    sh, tdir, test_script=script,
                    SHELL_INTEGRATION_VALUE='', pre_data='before_tarfile')
                self.ae(pty.screen_contents(), 'UNTAR_DONE\nld:before_tarfile')

    @retry_on_failure()
    def test_ssh_login_shell_detection(self):
        methods = []
        if shutil.which('python') or shutil.which('python3') or shutil.which('python2'):
            methods.append('using_python')
        if is_macos:
            methods += ['using_id']
        else:
            if shutil.which('getent'):
                methods.append('using_getent')
            if os.access('/etc/passwd', os.R_OK):
                methods.append('using_passwd')
        self.assertTrue(methods)
        import pwd
        try:
            expected_login_shell = pwd.getpwuid(os.geteuid()).pw_shell
        except KeyError:
            self.skipTest('Skipping login shell detection as getpwuid() failed to read login shell')
        if os.path.basename(expected_login_shell) == 'nologin':
            self.skipTest('Skipping login shell detection as login shell is set to nologin')
        for m in methods:
            for sh in self.all_possible_sh:
                if 'python' in sh:
                    continue
                with tempfile.TemporaryDirectory() as tdir:
                    pty = self.check_bootstrap(sh, tdir, test_script=f'{m}; echo "$login_shell"; exit 0', SHELL_INTEGRATION_VALUE='')
                    self.assertIn(expected_login_shell, pty.screen_contents())

    @retry_on_failure()
    def test_ssh_shell_integration(self):
        ok_login_shell = ''
        for sh in self.all_possible_sh:
            for login_shell in {'fish', 'zsh', 'bash'} & set(self.all_possible_sh):
                if login_shell == 'bash' and not bash_ok():
                    continue
                ok_login_shell = login_shell
                with tempfile.TemporaryDirectory() as tdir:
                    pty = self.check_bootstrap(sh, tdir, login_shell)
                    if login_shell == 'bash':
                        pty.send_cmd_to_child('echo $HISTFILE')
                        pty.wait_till(lambda: '/.bash_history' in pty.screen_contents())
                    elif login_shell == 'zsh':
                        pty.send_cmd_to_child('echo "login_shell=$ZSH_NAME"')
                        pty.wait_till(lambda: 'login_shell=zsh' in pty.screen_contents())
                    self.assertIn(b'\x1b]133;', pty.received_bytes)
        # check that turning off shell integration works
        if ok_login_shell in ('bash', 'zsh'):
            for val in ('', 'no-rc', 'enabled no-rc'):
                for sh in self.all_possible_sh:
                    with tempfile.TemporaryDirectory() as tdir:
                        pty = self.check_bootstrap(sh, tdir, ok_login_shell, val)
                        num_lines = len(pty.screen_contents().splitlines())
                        pty.send_cmd_to_child('echo "$TERM=fruity"')
                        pty.wait_till(lambda: 'kitty=fruity' in pty.screen_contents(), timeout=30)
                        pty.wait_till(lambda: len(pty.screen_contents().splitlines()) >= num_lines + 2)
                        self.assertEqual(pty.screen.cursor.shape, 0)
                        self.assertNotIn(b'\x1b]133;', pty.received_bytes)

    def check_bootstrap(self, sh, home_dir, login_shell='', SHELL_INTEGRATION_VALUE='enabled', test_script='', pre_data='', conf='', launcher='sh', home=''):
        if login_shell:
            conf += f'\nlogin_shell {login_shell}'
        if 'python' in sh:
            if test_script.startswith('env;'):
                test_script = f'os.execlp("sh", "sh", "-c", {test_script!r})'
            test_script = f'print("UNTAR_DONE", flush=True); {test_script}'
        else:
            test_script = f'echo "UNTAR_DONE"; {test_script}'
        conf += '\nshell_integration ' + (SHELL_INTEGRATION_VALUE or 'disabled')
        conf += '\ninterpreter ' + sh
        env = os.environ.copy()
        if home:
            env['HOME'] = home
        cp = subprocess.run([kitten_exe(), '__pytest__', 'ssh', test_script], env=env, stdout=subprocess.PIPE, input=conf.encode('utf-8'))
        self.assertEqual(cp.returncode, 0)
        self.rdata = json.loads(cp.stdout)
        del cp
        try:
            env = basic_shell_env(home_dir)
            # Avoid generating unneeded completion scripts
            os.makedirs(os.path.join(home_dir, '.local', 'share', 'fish', 'generated_completions'), exist_ok=True)
            # prevent newuser-install from running
            open(os.path.join(home_dir, '.zshrc'), 'w').close()
            pty = self.create_pty([launcher, '-c', ' '.join(self.rdata['cmd'])], cwd=home_dir, env=env)
            pty.turn_off_echo()
            if pre_data:
                pty.write_buf = pre_data.encode('utf-8')

            def check_untar_or_fail():
                q = pty.screen_contents()
                return 'UNTAR_DONE' in q
            pty.wait_till(check_untar_or_fail, timeout=60)
            self.assertTrue(os.path.exists(os.path.join(home_dir, '.terminfo/kitty.terminfo')))
            if SHELL_INTEGRATION_VALUE != 'enabled':
                pty.wait_till(lambda: len(pty.screen_contents().splitlines()) > 1, timeout=60)
                self.assertEqual(pty.screen.cursor.shape, 0)
            else:
                pty.wait_till(lambda: pty.screen.cursor.shape == CURSOR_BEAM, timeout=60)
            return pty
        finally:
            with suppress(FileNotFoundError):
                shm_unlink(self.rdata['shm_name'])
