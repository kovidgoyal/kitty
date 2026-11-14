#!/usr/bin/env python
# License: GPLv3 Copyright: 2022, Kovid Goyal <kovid at kovidgoyal.net>


import json
import os
import shlex
import subprocess
import tempfile

from datty.constants import daddy_exe as daddy
from datty.session import SESSION_FILE_EXTENSIONS

from .base import BaseTest


class TestCompletion(BaseTest):
    def test_completion(self):
        with tempfile.TemporaryDirectory() as tdir:
            completion(self, tdir)


def get_all_words(result):
    all_words = set()
    for group in result.get('groups', ()):
        for m in group['matches']:
            all_words.add(m['word'])
    return all_words


def has_words(*words):
    def t(self, result):
        q = set(words)
        missing = q - get_all_words(result)
        self.assertFalse(missing, f'Words missing. Command line: {self.current_cmd!r}')

    return t


def does_not_have_words(*words):
    def t(self, result):
        q = set(words)
        all_words = get_all_words(result)
        self.assertFalse(q & all_words, f'Words unexpectedly present. Command line: {self.current_cmd!r}')

    return t


def all_words(*words):
    def t(self, result):
        expected = set(words)
        actual = get_all_words(result)
        self.assertEqual(expected, actual, f'Command line: {self.current_cmd!r}')

    return t


def is_delegate(num_to_remove: int = 0, command: str = ''):
    q = {}
    if num_to_remove:
        q['num_to_remove'] = num_to_remove
    if command:
        q['command'] = command

    def t(self, result):
        d = result['delegate']
        self.assertEqual(d, q, f'Command line: {self.current_cmd!r}')

    return t


def completion(self: TestCompletion, tdir: str):
    all_cmds = []
    all_argv = []
    all_tests = []

    def add(cmdline: str, *tests):
        all_cmds.append(cmdline)
        new_word = cmdline.endswith(' ')
        if new_word:
            cmdline = cmdline[:-1]
        all_argv.append(shlex.split(cmdline))
        if new_word:
            all_argv[-1].append('')
        all_tests.append(tests)

    def run_tool():
        env = os.environ.copy()
        env['PATH'] = os.path.join(tdir, 'bin')
        env['HOME'] = os.path.join(tdir, 'sub')
        env['DATTY_CONFIG_DIRECTORY'] = os.path.join(tdir, 'sub')
        cp = subprocess.run([daddy(), '__complete__', 'json'], check=True, stdout=subprocess.PIPE, cwd=tdir, input=json.dumps(all_argv).encode(), env=env)
        self.assertEqual(cp.returncode, 0, f'daddy __complete__ failed with exit code: {cp.returncode}')
        return json.loads(cp.stdout)

    add('datty ', has_words('@', '+', '+open'))
    add('datty @ l', has_words('ls', 'last-used-layout', 'launch'))
    add('datty @ set-o', has_words('set-os-window-title'))

    def make_file(path, mode=None):
        with open(os.path.join(tdir, path), mode='x') as f:
            if mode is not None:
                os.chmod(f.fileno(), mode)

    os.mkdir(os.path.join(tdir, 'bin'))
    os.mkdir(os.path.join(tdir, 'sub'))
    make_file('bin/exe1', 0o700)
    make_file('bin/exe-not1')
    make_file('exe2', 0o700)
    make_file('exe-not2.jpeg')
    make_file('sub/exe3', 0o700)
    make_file('sub/exe-not3.png')
    session_files = tuple(f'project.{ext}' for ext in sorted(SESSION_FILE_EXTENSIONS))
    for path in session_files:
        make_file(f'sub/{path}')

    add('datty x', all_words())
    add('datty e', all_words('exe1', 'exe2'))
    add('datty ./', all_words('./bin/', './sub/', './exe2'))
    add('datty ./e', all_words('./exe2'))
    add('datty ./s', all_words('./sub/'))
    add('datty ~', all_words('~/exe3'))
    add('datty ~/', all_words('~/exe3'))
    add('datty ~/e', all_words('~/exe3'))

    add('datty @ goto-layout ', has_words('tall', 'fat'))
    add('datty @ goto-layout spli', all_words('splits'))
    add('datty @ goto-layout f f', all_words())
    add('datty @ set-window-logo ', all_words('exe-not2.jpeg', 'sub/'))
    add('datty @ set-window-logo e', all_words('exe-not2.jpeg'))
    add('datty @ set-window-logo e e', all_words())
    add('datty +ope', has_words('+open'))
    add('datty +open -', has_words('-1', '-T'))

    add('datty -', has_words('-c', '-1', '--'), does_not_have_words('--config', '--single-instance'))
    add('datty -c', all_words('-c'))
    add('datty --', has_words('--config', '--single-instance', '--'))
    add('datty --s', has_words('--session', '--start-as'))
    add('datty --session ', all_words(*session_files))
    add('datty --start-as', all_words('--start-as'))
    add('datty --start-as ', all_words('minimized', 'maximized', 'fullscreen', 'normal', 'hidden'))
    add('datty -1 ', does_not_have_words('@ls', '@'))
    add('datty --directory ', all_words('bin/', 'sub/'))
    add('datty -1d ', all_words('exe1'))
    add('datty -1d', all_words('-1d'))
    add('datty -o a', has_words('allow_remote_control='))
    add('datty --listen-on ', all_words('unix:', 'tcp:'))
    add('datty --listen-on unix:b', all_words('unix:bin/'))
    add('datty --directory=', all_words('--directory=bin/', '--directory=sub/'))
    add('datty --start-as=m', all_words('--start-as=minimized', '--start-as=maximized'))
    add('datty @launch --ty', has_words('--type'))
    add('datty @launch --type ', has_words('window', 'background', 'overlay'))
    add('datty @launch --cwd ', has_words('current', 'oldest', 'last_reported'))
    add('datty @launch --logo ', all_words('exe-not3.png'))
    add('datty @launch --logo ~', all_words('~/exe-not3.png'))
    add('daddy ', has_words('@'))
    add('daddy ', does_not_have_words('__complete__'))
    add('daddy @launch --ty', has_words('--type'))

    add('datty + ', has_words('launch', 'daddy'))
    add('datty + daddy ', has_words('icat', 'diff'))
    add('datty +daddy icat ', has_words('sub/', 'exe-not2.jpeg'))
    add('datty + daddy icat --pr', has_words('--print-window-size'))
    add('datty + daddy diff ', has_words('exe-not2.jpeg'))
    add('datty + daddy themes --', has_words('--cache-age'))
    add('datty + daddy themes D', has_words('Default'))
    add('datty + daddy hyperlinked_grep ', is_delegate(3, 'rg'))
    add('datty +daddy hyperlinked_grep ', is_delegate(2, 'rg'))

    add('clone-in-datty --ty', has_words('--type'))

    add('datty bash ', is_delegate(1, 'bash'))
    add('datty -1 bash ', is_delegate(2, 'bash'))
    add('datty -1 bash --n', is_delegate(2, 'bash'))
    add('datty @launch --type tab bash --n', is_delegate(4, 'bash'))
    add('datty +daddy hyperlinked_grep --s', is_delegate(2, 'rg'))
    add('datty @launch e', all_words('exe1', 'exe2'))

    for cmd, tests, result in zip(all_cmds, all_tests, run_tool()):
        self.current_cmd = cmd
        for test in tests:
            test(self, result)
