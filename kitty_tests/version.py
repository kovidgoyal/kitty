#!/usr/bin/env python
# License: GPLv3 Copyright: 2026, Kovid Goyal <kovid at kovidgoyal.net>

import os
import re
import runpy
import select
import shlex
import subprocess
import sys
import tempfile
import unittest
from contextlib import chdir
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from kitty import fast_data_types
from kitty.cli import version
from kitty.constants import kitten_exe, kitty_exe, str_version

from .base import BaseTest

REVISION = '8e4780f8ec0953205c154bb7fac9bc78983963d3'
TIMESTAMP = 946684800
SUFFIX = '-nightly-8e4780f8ec (built 2000-01-01T00:00:00Z)'


def load_build_script(name):
    root = Path(__file__).resolve().parent.parent
    path = root / name
    if not path.is_file():
        raise unittest.SkipTest('Build scripts are only available in the source tree')
    with chdir(root), patch.object(sys, 'running_from_setup', False, create=True):
        return runpy.run_path(str(path))


class TestVersion(BaseTest):
    def test_version_format(self):
        with patch('sys.stdout.isatty', return_value=False), patch.object(fast_data_types, 'KITTY_VCS_REV', REVISION):
            for suffix in ('', SUFFIX):
                with self.subTest(suffix=suffix), patch.object(fast_data_types, 'KITTY_VERSION_SUFFIX', suffix, create=True):
                    expected = f'kitty {str_version}{suffix} created by Kovid Goyal'
                    self.ae(version(), expected)
                    if suffix:
                        self.ae(version(add_rev=True), expected)
                    else:
                        self.ae(version(add_rev=True), f'kitty {str_version} ({REVISION[:10]}) created by Kovid Goyal')

    def test_version_cli(self):
        with patch('sys.stdout.isatty', return_value=False):
            expected = version() + '\n'
        for name, exe, flags in (('kitty', kitty_exe(), ('--version', '-v')), ('kitten', kitten_exe(), ('--version',))):
            for flag in flags:
                with self.subTest(exe=exe, flag=flag):
                    result = subprocess.run([exe, flag], capture_output=True, check=True, timeout=10)
                    self.ae(result.stdout.decode(), name + ' ' + expected.partition(' ')[2])
                    self.ae(result.stderr, b'')
        master, slave = os.openpty()
        try:
            subprocess.run([kitty_exe(), '--version'], stdout=slave, stderr=subprocess.PIPE, check=True, timeout=10)
            self.assertTrue(select.select([master], [], [], 5)[0], 'No version output on the terminal')
            output = os.read(master, 4096).decode().replace('\r\n', '\n')
        finally:
            os.close(master)
            os.close(slave)
        self.assertIn('\x1b[', output)
        self.ae(re.sub(r'\x1b\[[0-9;]*m', '', output), expected)

    def test_version_ignores_path(self):
        with tempfile.TemporaryDirectory() as tdir:
            fake = Path(tdir) / 'kitty'
            fake.write_text('#!/bin/sh\nexit 99\n')
            fake.chmod(0o755)
            env = dict(os.environ, PATH=tdir + os.pathsep + os.environ.get('PATH', ''))
            code = 'from kitty.constants import kitty_exe; print(kitty_exe())'
            actual = subprocess.check_output([kitty_exe(), '+runpy', code], env=env, text=True, timeout=10)
            self.ae(actual.strip(), kitty_exe())

    def test_nightly_build_version(self):
        setup = load_build_script('setup.py')
        args = setup['option_parser']().parse_args(['--nightly', f'--vcs-rev={REVISION}', f'--build-timestamp={TIMESTAMP}'], namespace=setup['Options']())
        self.ae(setup['version_suffix'](args), SUFFIX)
        self.ae(setup['version_suffix'](setup['Options']()), '')

    def test_nightly_metadata_resolved_once(self):
        setup = load_build_script('setup.py')
        resolve = setup['version_suffix']
        args = setup['Options']()
        args.nightly = True
        revision = Mock(return_value=REVISION)
        with patch.dict(resolve.__globals__, {'get_vcs_rev': revision}), patch.dict(os.environ, SOURCE_DATE_EPOCH=str(TIMESTAMP)):
            self.ae(resolve(args), SUFFIX)
            self.ae(args.vcs_rev, REVISION)
            self.ae(args.build_timestamp, TIMESTAMP)
            with patch.dict(os.environ, SOURCE_DATE_EPOCH='invalid'):
                self.ae(resolve(args), SUFFIX)
        revision.assert_called_once()
        explicit = setup['Options']()
        explicit.nightly, explicit.vcs_rev, explicit.build_timestamp = True, REVISION, 0
        with patch.dict(os.environ, SOURCE_DATE_EPOCH='invalid'):
            self.assertIn('built 1970-01-01T00:00:00Z', resolve(explicit))

    def test_invalid_build_metadata(self):
        load_build_script('setup.py')
        root = Path(__file__).resolve().parent.parent
        cases = (
            (['--nightly'], None, '--nightly requires --build-timestamp or SOURCE_DATE_EPOCH'),
            (['--nightly'], 'invalid', 'Invalid SOURCE_DATE_EPOCH'),
            (['--nightly'], '-1', 'non-negative Unix timestamp'),
            (['--nightly'], '999999999999999999999999', 'supported date range'),
            (['--build-timestamp=1'], None, '--build-timestamp requires --nightly'),
            (['--nightly', '--build-timestamp=invalid'], None, 'non-negative Unix timestamp'),
        )
        code = 'import runpy; runpy.run_path("setup.py", run_name="__main__")'
        for argv, epoch, message in cases:
            with self.subTest(argv=argv, epoch=epoch):
                env = dict(os.environ)
                env.pop('SOURCE_DATE_EPOCH', None)
                if epoch is not None:
                    env['SOURCE_DATE_EPOCH'] = epoch
                result = subprocess.run([kitty_exe(), '+runpy', code, *argv], env=env, cwd=root, capture_output=True, text=True, timeout=10)
                self.ae(result.returncode, 2)
                self.assertIn(message, result.stderr)
                self.assertNotIn('Traceback', result.stderr)

    def test_nightly_publish_metadata(self):
        build = load_build_script('publish.py')['run_build']
        for nightly in (False, True):
            call = Mock()
            with (
                self.subTest(nightly=nightly),
                patch.dict(build.__globals__, {'building_nightly': nightly, 'call': call}),
                patch('runpy.run_path', return_value={'get_vcs_rev': lambda: REVISION}),
                patch('time.time', return_value=TIMESTAMP),
            ):
                build(None)
            payloads = []
            for recorded in call.call_args_list:
                cmd = shlex.split(recorded.args[0]) if len(recorded.args) == 1 else list(recorded.args)
                if '--extra-program-data' in cmd:
                    payloads.append(cmd[cmd.index('--extra-program-data') + 1])
            self.ae(len(payloads), 3)
            expected = f'nightly:{REVISION}:{TIMESTAMP}' if nightly else REVISION
            for payload in payloads:
                self.ae(payload, expected)
                remote_argv = ['program', '--extra-program-data', payload]
                self.ae(shlex.split(' '.join(remote_argv)), remote_argv)
            expected_options = [f'--vcs-rev={REVISION}'] + (['--nightly', f'--build-timestamp={TIMESTAMP}'] if nightly else [])
            static_call = call.call_args_list[-1].args
            self.ae(static_call, ('./setup.py', 'build-static-binaries', *expected_options))

    def test_packaged_build_metadata(self):
        constants = SimpleNamespace(BIN='', LIBDIR='', PREFIX='', PYTHON=sys.executable, ismacos=False, worker_env={}, SRC='')
        with patch.dict(sys.modules, {'bypy.constants': constants, 'bypy.utils': SimpleNamespace(run_shell=Mock(), walk=Mock())}):
            env = load_build_script('bypy/init_env.py')
        build = env['build_c_extensions']
        payloads = (
            ('', []),
            (REVISION, [f'--vcs-rev={REVISION}']),
            (
                f'nightly:{REVISION}:{TIMESTAMP}',
                [f'--vcs-rev={REVISION}', '--nightly', f'--build-timestamp={TIMESTAMP}'],
            ),
        )
        for ismacos in (False, True):
            for payload, expected in payloads:
                with self.subTest(ismacos=ismacos, payload=payload), tempfile.TemporaryDirectory() as tdir:
                    src = Path(tdir) / 'source'
                    (src / 'kitty' / 'launcher').mkdir(parents=True)
                    ext_dir = Path(tdir) / 'extensions'
                    ext_dir.mkdir()
                    run = Mock(return_value=0)
                    with patch.dict(build.__globals__, {'KITTY_DIR': str(src), 'ismacos': ismacos, 'kitty_constants': {'appname': 'kitty'}, 'run': run}):
                        args = SimpleNamespace(dont_strip=False, extra_program_data=payload)
                        build(str(ext_dir), args)
                        env['build_frozen_launcher']([], args)
                        env['build_frozen_tools'](str(ext_dir / 'kitty' / 'bin' / 'kitty'), args)
                    self.ae(run.call_count, 3)
                    for recorded in run.call_args_list:
                        options = [x for x in recorded.args if x == '--nightly' or x.startswith(('--vcs-rev=', '--build-timestamp='))]
                        self.ae(options, expected)
                        self.ae(recorded.kwargs['cwd'], str(ext_dir / 'src'))

    def test_resumed_build_metadata(self):
        constants = SimpleNamespace(BIN='', LIBDIR='', PREFIX='', PYTHON=sys.executable, ismacos=False, worker_env={}, SRC='')
        with patch.dict(sys.modules, {'bypy.constants': constants, 'bypy.utils': SimpleNamespace(run_shell=Mock(), walk=Mock())}):
            env = load_build_script('bypy/init_env.py')
        launcher = env['build_frozen_launcher']
        args = SimpleNamespace(extra_program_data=f'nightly:{REVISION}:{TIMESTAMP}')
        run = Mock(return_value=0)
        with tempfile.TemporaryDirectory() as tdir, patch.dict(launcher.__globals__, {'run': run}):
            launcher.prefix = tdir
            launcher.writeable_src_dir = tdir
            launcher([], args)
        self.ae(run.call_count, 1)
        self.assertIn('--nightly', run.call_args.args)
        self.assertIn(f'--build-timestamp={TIMESTAMP}', run.call_args.args)
