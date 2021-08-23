#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPLv3 Copyright: 2021, Kovid Goyal <kovid at kovidgoyal.net>


import os
import shutil
import tempfile

from kitty.file_transmission import (
    Action, Compression, Container, FileTransmissionCommand,
    TestFileTransmission as FileTransmission
)

from . import BaseTest


def serialized_cmd(**fields) -> str:
    for k, A in (('action', Action), ('container_fmt', Container), ('compression', Compression)):
        if k in fields:
            fields[k] = A[fields[k]]
    if isinstance(fields.get('data'), str):
        fields['data'] = fields['data'].encode('utf-8')
    ans = FileTransmissionCommand()
    for k in fields:
        setattr(ans, k, fields[k])
    return ans.serialize()


class TestFileTransmission(BaseTest):

    def setUp(self):
        self.tdir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tdir)

    def test_file_put(self):
        # send refusal
        for quiet in (0, 1, 2):
            ft = FileTransmission()
            ft.handle_serialized_command(serialized_cmd(action='send', id='x', quiet=quiet))
            self.ae(ft.test_responses, [] if quiet == 2 else [{'status': 'EPERM:User refused the transfer', 'id': 'x'}])
            self.assertFalse(ft.active_cmds)
        # simple single file send
        ft = FileTransmission()
        dest = os.path.join(self.tdir, '1.bin')
        ft.handle_serialized_command(serialized_cmd(action='send', dest=dest))
        self.assertIn('', ft.active_cmds)
        self.ae(os.path.basename(ft.active_cmds[''].dest), '1.bin')
        self.assertIsNone(ft.active_cmds[''].file)
        self.ae(ft.test_responses, [{'status': 'OK'}])
        ft.handle_serialized_command(serialized_cmd(action='data', data='abcd'))
        self.assertIsNotNone(ft.active_cmds[''].file)
        ft.handle_serialized_command(serialized_cmd(action='end_data', data='123'))
        self.assertFalse(ft.active_cmds)
        self.ae(ft.test_responses, [{'status': 'OK'}, {'status': 'COMPLETED'}])
        with open(dest) as f:
            self.ae(f.read(), 'abcd123')
