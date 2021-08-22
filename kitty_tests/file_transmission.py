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
        ft = FileTransmission()
        ft.handle_serialized_command(serialized_cmd(action='send', id='1', dest=os.path.join(self.tdir, '1.bin')))
        self.assertIn('1', ft.active_cmds)
        self.ae(os.path.basename(ft.active_cmds['1'].dest), '1.bin')
        self.assertIsNone(ft.active_cmds['1'].file)
