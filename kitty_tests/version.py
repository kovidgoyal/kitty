#!/usr/bin/env python
# License: GPLv3 Copyright: 2026, Kovid Goyal <kovid at kovidgoyal.net>

import json
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
from kitty.constants import kitty_exe, str_version

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
        for flag in ('--version', '-v'):
            result = subprocess.run([kitty_exe(), flag], capture_output=True, check=True, timeout=10)
            self.ae(result.stdout.decode(), expected)
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

    def test_nightly_build_version(self):
        setup = load_build_script('setup.py')
        args = setup['option_parser']().parse_args(['--nightly', f'--vcs-rev={REVISION}', f'--build-timestamp={TIMESTAMP}'], namespace=setup['Options']())
        self.ae(setup['version_suffix'](args), SUFFIX)
        args.nightly = False
        self.ae(setup['version_suffix'](args), '')

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
                cmd = shlex.split(recorded.args[0])
                if '--extra-program-data' in cmd:
                    payloads.append(cmd[cmd.index('--extra-program-data') + 1])
            self.ae(len(payloads), 3)
            expected = {'vcs_rev': REVISION, 'nightly': True, 'build_timestamp': TIMESTAMP} if nightly else REVISION
            for payload in payloads:
                self.ae(json.loads(payload) if nightly else payload, expected)

    def test_packaged_build_metadata(self):
        constants = SimpleNamespace(BIN='', LIBDIR='', PREFIX='', PYTHON=sys.executable, ismacos=False, worker_env={}, SRC='')
        with patch.dict(sys.modules, {'bypy.constants': constants, 'bypy.utils': SimpleNamespace(run_shell=Mock(), walk=Mock())}):
            env = load_build_script('bypy/init_env.py')
        build = env['build_c_extensions']
        payloads = (
            ('', []),
            (REVISION, [f'--vcs-rev={REVISION}']),
            (
                json.dumps({'vcs_rev': REVISION, 'nightly': True, 'build_timestamp': TIMESTAMP}),
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
                        build(str(ext_dir), SimpleNamespace(dont_strip=False, extra_program_data=payload))
                        env['build_frozen_launcher']([])
                    self.ae(run.call_count, 2)
                    for recorded in run.call_args_list:
                        options = [x for x in recorded.args if x == '--nightly' or x.startswith(('--vcs-rev=', '--build-timestamp='))]
                        self.ae(options, expected)
                        self.ae(recorded.kwargs['cwd'], str(ext_dir / 'src'))
