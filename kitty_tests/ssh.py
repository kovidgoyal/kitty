#!/usr/bin/env python
# License: GPLv3 Copyright: 2021, Kovid Goyal <kovid at kovidgoyal.net>


import glob
import os
import shutil
import tempfile
from functools import lru_cache

from kittens.ssh.config import load_config, options_for_host
from kittens.ssh.main import (
    bootstrap_script, get_connection_data, wrap_bootstrap_script
)
from kittens.ssh.options.types import Options as SSHOptions
from kittens.ssh.options.utils import DELETE_ENV_VAR
from kittens.transfer.utils import set_paths
from kitty.constants import is_macos, runtime_dir
from kitty.fast_data_types import CURSOR_BEAM
from kitty.utils import SSHConnectionData

from . import BaseTest
from .shell_integration import bash_ok, basic_shell_env


def files_in(path):
    for record in os.walk(path):
        for f in record[-1]:
            yield os.path.relpath(os.path.join(record[0], f), path)


class SSHKitten(BaseTest):

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
        def t(cmdline, binary='ssh', host='main', port=None, identity_file='', extra_args=()):
            if identity_file:
                identity_file = os.path.abspath(identity_file)
            en = set(f'{x[0]}' for x in extra_args)
            q = get_connection_data(cmdline.split(), extra_args=en)
            self.ae(q, SSHConnectionData(binary, host, port, identity_file, extra_args))

        t('ssh main')
        t('ssh un@ip -i ident -p34', host='un@ip', port=34, identity_file='ident')
        t('ssh un@ip -iident -p34', host='un@ip', port=34, identity_file='ident')
        t('ssh -p 33 main', port=33)
        t('ssh --kitten=one -p 12 --kitten two -ix main', identity_file='x', port=12, extra_args=(('--kitten', 'one'), ('--kitten', 'two')))
        self.assertTrue(runtime_dir())

    def test_ssh_config_parsing(self):
        def parse(conf):
            return load_config(overrides=conf.splitlines())

        def for_host(hostname, conf, username='kitty'):
            if isinstance(conf, str):
                conf = parse(conf)
            return options_for_host(hostname, username, conf)

        self.ae(for_host('x', '').env, {})
        self.ae(for_host('x', 'env a=b').env, {'a': 'b'})
        pc = parse('env a=b\nhostname 2\nenv a=c\nenv b=b')
        self.ae(set(pc.keys()), {'*', '2'})
        self.ae(for_host('x', pc).env, {'a': 'b'})
        self.ae(for_host('2', pc).env, {'a': 'c', 'b': 'b'})
        self.ae(for_host('x', 'env a=').env, {'a': ''})
        self.ae(for_host('x', 'env a').env, {'a': '_delete_this_env_var_'})
        pc = parse('env a=b\nhostname test@2\nenv a=c\nenv b=b')
        self.ae(set(pc.keys()), {'*', 'test@2'})
        self.ae(for_host('x', pc).env, {'a': 'b'})
        self.ae(for_host('2', pc).env, {'a': 'b'})
        self.ae(for_host('2', pc, 'test').env, {'a': 'c', 'b': 'b'})
        pc = parse('env a=b\nhostname 1 2\nenv a=c\nenv b=b')
        self.ae(for_host('x', pc).env, {'a': 'b'})
        self.ae(for_host('1', pc).env, {'a': 'c', 'b': 'b'})
        self.ae(for_host('2', pc).env, {'a': 'c', 'b': 'b'})

    @property
    @lru_cache()
    def all_possible_sh(self):
        python = 'python3' if shutil.which('python3') else 'python'
        return tuple(filter(shutil.which, ('dash', 'zsh', 'bash', 'posh', 'sh', python)))

    def test_ssh_copy(self):
        simple_data = 'rkjlhfwf9whoaa'

        def touch(p):
            with open(os.path.join(local_home, p), 'w') as f:
                f.write(simple_data)

        for sh in self.all_possible_sh:
            with self.subTest(sh=sh), tempfile.TemporaryDirectory() as remote_home, tempfile.TemporaryDirectory() as local_home, set_paths(home=local_home):
                tuple(map(touch, 'simple-file g.1 g.2'.split()))
                os.makedirs(f'{local_home}/d1/d2/d3')
                touch('d1/d2/x')
                touch('d1/d2/w.exclude')
                os.symlink('d2/x', f'{local_home}/d1/y')

                conf = '''\
copy simple-file
copy --dest=a/sfa simple-file
copy --glob g.*
copy --exclude */w.* d1
'''
                copy = load_config(overrides=filter(None, conf.splitlines()))['*'].copy
                self.check_bootstrap(
                    sh, remote_home, test_script='env; exit 0', SHELL_INTEGRATION_VALUE='',
                    ssh_opts={'copy': copy}
                )
                tname = '.terminfo'
                if os.path.exists('/usr/share/misc/terminfo.cdb'):
                    tname += '.cdb'
                self.assertTrue(os.path.lexists(f'{remote_home}/{tname}/78'))
                self.assertTrue(os.path.exists(f'{remote_home}/{tname}/78/xterm-kitty'))
                self.assertTrue(os.path.exists(f'{remote_home}/{tname}/x/xterm-kitty'))
                for w in ('simple-file', 'a/sfa'):
                    with open(os.path.join(remote_home, w), 'r') as f:
                        self.ae(f.read(), simple_data)
                self.assertTrue(os.path.lexists(f'{remote_home}/d1/y'))
                self.assertTrue(os.path.exists(f'{remote_home}/d1/y'))
                self.ae(os.readlink(f'{remote_home}/d1/y'), 'd2/x')
                contents = set(files_in(remote_home))
                contents.discard('.zshrc')  # added by check_bootstrap()
                # depending on platform one of these is a symlink and hence
                # isnt in contents
                contents.discard(f'{tname}/x/xterm-kitty')
                contents.discard(f'{tname}/78/xterm-kitty')
                self.ae(contents, {
                    'g.1', 'g.2', f'{tname}/kitty.terminfo', 'simple-file', 'd1/d2/x', 'd1/y', 'a/sfa'
                })
                self.ae(len(glob.glob(f'{remote_home}/{tname}/*/xterm-kitty')), 2)

    def test_ssh_env_vars(self):
        tset = '$A-$(echo no)-`echo no2` "something"'
        for sh in self.all_possible_sh:
            with self.subTest(sh=sh), tempfile.TemporaryDirectory() as tdir:
                os.mkdir(os.path.join(tdir, 'cwd'))
                pty = self.check_bootstrap(
                    sh, tdir, test_script='env; pwd; exit 0', SHELL_INTEGRATION_VALUE='',
                    ssh_opts={'cwd': '$HOME/cwd', 'env': {
                        'A': 'AAA',
                        'TSET': tset,
                        'COLORTERM': DELETE_ENV_VAR,
                    }}
                )
                pty.wait_till(lambda: 'TSET={}'.format(tset.replace('$A', 'AAA')) in pty.screen_contents())
                self.assertNotIn('COLORTERM', pty.screen_contents())
                pty.wait_till(lambda: '/cwd' in pty.screen_contents())
                self.assertTrue(pty.is_echo_on())

    def test_ssh_bootstrap_with_different_launchers(self):
        for launcher in self.all_possible_sh:
            if 'python' in launcher:
                continue
            for sh in self.all_possible_sh:
                if sh == 'sh' or 'python' in sh:
                    q = shutil.which(launcher)
                    if q:
                        with self.subTest(sh=sh, launcher=q), tempfile.TemporaryDirectory() as tdir:
                            self.check_bootstrap(sh, tdir, test_script='env; exit 0', SHELL_INTEGRATION_VALUE='', launcher=q)

    def test_ssh_leading_data(self):
        script = 'echo "ld:$leading_data"; exit 0'
        for sh in self.all_possible_sh:
            if 'python' in sh:
                script = 'print("ld:" + leading_data.decode("ascii")); raise SystemExit(0);'
            with self.subTest(sh=sh), tempfile.TemporaryDirectory() as tdir:
                pty = self.check_bootstrap(
                    sh, tdir, test_script=script,
                    SHELL_INTEGRATION_VALUE='', pre_data='before_tarfile')
                self.ae(pty.screen_contents(), 'UNTAR_DONE\nld:before_tarfile')

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
        expected_login_shell = pwd.getpwuid(os.geteuid()).pw_shell
        for m in methods:
            for sh in self.all_possible_sh:
                if 'python' in sh:
                    continue
                with self.subTest(sh=sh, method=m), tempfile.TemporaryDirectory() as tdir:
                    pty = self.check_bootstrap(sh, tdir, test_script=f'{m}; echo "$login_shell"; exit 0', SHELL_INTEGRATION_VALUE='')
                    self.assertIn(expected_login_shell, pty.screen_contents())

    def test_ssh_shell_integration(self):
        ok_login_shell = ''
        for sh in self.all_possible_sh:
            for login_shell in {'fish', 'zsh', 'bash'} & set(self.all_possible_sh):
                if login_shell == 'bash' and not bash_ok():
                    continue
                ok_login_shell = login_shell
                with self.subTest(sh=sh, login_shell=login_shell), tempfile.TemporaryDirectory() as tdir:
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
                        pty.wait_till(lambda: 'kitty=fruity' in pty.screen_contents())
                        pty.wait_till(lambda: len(pty.screen_contents().splitlines()) >= num_lines + 2)
                        self.assertEqual(pty.screen.cursor.shape, 0)
                        self.assertNotIn(b'\x1b]133;', pty.received_bytes)

    def check_bootstrap(self, sh, home_dir, login_shell='', SHELL_INTEGRATION_VALUE='enabled', test_script='', pre_data='', ssh_opts=None, launcher='sh'):
        ssh_opts = ssh_opts or {}
        if login_shell:
            ssh_opts['login_shell'] = login_shell
        if 'python' in sh:
            if test_script.startswith('env;'):
                test_script = f'os.execlp("sh", "sh", "-c", {test_script!r})'
            test_script = f'print("UNTAR_DONE", flush=True); {test_script}'
        else:
            test_script = f'echo "UNTAR_DONE"; {test_script}'
        ssh_opts['shell_integration'] = SHELL_INTEGRATION_VALUE or 'disabled'
        script, replacements, shm = bootstrap_script(
            SSHOptions(ssh_opts), script_type='py' if 'python' in sh else 'sh', request_id="testing", test_script=test_script
        )
        try:
            env = basic_shell_env(home_dir)
            # Avoid generating unneeded completion scripts
            os.makedirs(os.path.join(home_dir, '.local', 'share', 'fish', 'generated_completions'), exist_ok=True)
            # prevent newuser-install from running
            open(os.path.join(home_dir, '.zshrc'), 'w').close()
            cmd = wrap_bootstrap_script(script, sh)
            pty = self.create_pty([launcher, '-c', ' '.join(cmd)], cwd=home_dir, env=env)
            pty.turn_off_echo()
            del cmd
            if pre_data:
                pty.write_buf = pre_data.encode('utf-8')
            del script

            def check_untar_or_fail():
                q = pty.screen_contents()
                if 'bzip2' in q:
                    raise ValueError('Untarring failed with screen contents:\n' + q)
                return 'UNTAR_DONE' in q
            pty.wait_till(check_untar_or_fail)
            self.assertTrue(os.path.exists(os.path.join(home_dir, '.terminfo/kitty.terminfo')))
            if SHELL_INTEGRATION_VALUE != 'enabled':
                pty.wait_till(lambda: len(pty.screen_contents().splitlines()) > 1)
                self.assertEqual(pty.screen.cursor.shape, 0)
            else:
                pty.wait_till(lambda: pty.screen.cursor.shape == CURSOR_BEAM)
            return pty
        finally:
            shm.unlink()
