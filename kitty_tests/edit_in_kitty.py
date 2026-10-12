#!/usr/bin/env python
# License: GPLv3 Copyright: 2026, Kovid Goyal <kovid at kovidgoyal.net>

import gc
import os
import tempfile
from base64 import standard_b64encode

from kitty.launch import EditCmd, parse_edit_message

from .base import BaseTest


def encode_msg(*fields: tuple[str, str], simple: frozenset[str] = frozenset({'file_inode', 'file_data', 'abort_signaled', 'version'})) -> str:
    parts = []
    for k, v in fields:
        if k not in simple:
            v = standard_b64encode(v.encode('utf-8')).decode('ascii')
        parts.append(f'{k}={v}')
    return ','.join(parts)


class TestEditInKitty(BaseTest):
    def setUp(self):
        super().setUp()
        self.set_options()
        self.tdir = tempfile.mkdtemp()

    def tearDown(self):
        self.rmtree_ignoring_errors(self.tdir)
        super().tearDown()

    def test_edit_message_parsing(self):
        path = os.path.join(self.tdir, 'file.txt')
        with open(path, 'w') as f:
            f.write('local')
        st = os.stat(path)
        msg = encode_msg(
            ('cwd', self.tdir),
            ('a', '--type=tab'),
            ('a', '+17'),
            ('a', 'file.txt'),
            ('file_inode', f'{st.st_dev}:{st.st_ino}:{st.st_mtime_ns}'),
            ('file_data', standard_b64encode(b'local').decode('ascii')),
        )
        req = parse_edit_message(msg)
        self.ae(req.args, ['--type=tab', '+17', 'file.txt'])
        self.ae(req.cwd, self.tdir)
        self.ae(req.file_inode, (st.st_dev, st.st_ino))
        self.ae(req.file_data, b'local')
        self.ae(req.abort_signaled, '')

        c = EditCmd(msg, False)
        self.ae(c.line_number, 17)
        self.ae(c.file_name, 'file.txt')
        self.ae(c.file_localpath, path)
        self.assertTrue(c.is_local_file)
        # no temporary directory is needed for a local file
        self.ae(c.tdir, '')

    def test_edit_of_non_local_file_uses_own_tdir(self):
        msg = encode_msg(
            ('cwd', self.tdir),
            ('a', 'no-such-file.txt'),
            ('file_inode', '1:2:3'),
            ('file_data', standard_b64encode(b'remote data').decode('ascii')),
        )
        c = EditCmd(msg, True)
        self.assertFalse(c.is_local_file)
        self.assertTrue(c.tdir)
        self.assertNotEqual(os.path.realpath(c.tdir), os.path.realpath(self.tdir))
        self.ae(c.file_localpath, os.path.join(c.tdir, 'no-such-file.txt'))
        with open(c.file_localpath) as f:
            self.ae(f.read(), 'remote data')
        tdir = c.tdir
        del c
        gc.collect()
        self.assertFalse(os.path.exists(tdir), 'The temporary directory created for the edit was not deleted')

    def test_edit_message_cannot_overwrite_internal_state(self):
        # A program writing to the terminal must not be able to point tdir at a
        # directory of its choosing, which would then be deleted recursively
        # when the EditCmd object is destroyed.
        victim = os.path.join(self.tdir, 'victim')
        os.mkdir(victim)
        with open(os.path.join(victim, 'data'), 'w') as f:
            f.write('precious')
        msg = encode_msg(('tdir', victim), ('abort_signaled', 'closed'), ('child_is_remote', 'yes'), ('is_local_file', 'yes'))
        c = EditCmd(msg, False)
        self.ae(c.tdir, '')
        self.ae(c.abort_signaled, 'interrupt')
        self.ae(c.child_is_remote, False)
        del c
        gc.collect()
        self.assertTrue(os.path.exists(os.path.join(victim, 'data')), 'The edit protocol message deleted a directory of its choosing')

    def test_unknown_edit_message_keys_are_ignored(self):
        msg = encode_msg(('cwd', self.tdir), ('a', 'x.txt'), ('some_unknown_key', 'value'), ('file_inode', '1:2:3'))
        c = EditCmd(msg, False)
        self.assertFalse(hasattr(c, 'some_unknown_key'))
        # __slots__ prevents even a deliberate attempt at adding state
        with self.assertRaises(AttributeError):
            c.some_unknown_key = 'value'

    def test_malformed_edit_messages(self):
        for inode in ('', 'a:b:c', '1:2', '1:2:x'):
            req = parse_edit_message(encode_msg(('file_inode', inode)))
            self.ae(req.file_inode, (-1, -1))
            self.ae(req.file_size, -1)
        self.assertRaises(ValueError, EditCmd, encode_msg(('version', '1'), ('a', 'x.txt')), False)
