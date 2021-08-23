#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPLv3 Copyright: 2021, Kovid Goyal <kovid at kovidgoyal.net>


import os
import shutil
import tarfile
import tempfile
import zipfile
import zlib
from io import BytesIO

from kitty.file_transmission import (
    Action, Compression, Container, FileTransmissionCommand,
    TestFileTransmission as FileTransmission
)

from . import BaseTest


def names_in(path):
    for dirpath, dirnames, filenames in os.walk(path):
        for d in dirnames + filenames:
            yield os.path.relpath(os.path.join(dirpath, d), path)


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

    def clean_tdir(self):
        shutil.rmtree(self.tdir)
        self.tdir = tempfile.mkdtemp()

    def assertPathEqual(self, a, b):
        a = os.path.abspath(os.path.realpath(a))
        b = os.path.abspath(os.path.realpath(b))
        self.ae(a, b)

    def test_file_put(self):
        # send refusal
        for quiet in (0, 1, 2):
            ft = FileTransmission()
            ft.handle_serialized_command(serialized_cmd(action='send', id='x', quiet=quiet))
            self.ae(ft.test_responses, [] if quiet == 2 else [{'status': 'EPERM:User refused the transfer', 'id': 'x'}])
            self.assertFalse(ft.active_cmds)
        # simple single file send
        for quiet in (0, 1, 2):
            ft = FileTransmission()
            dest = os.path.join(self.tdir, '1.bin')
            ft.handle_serialized_command(serialized_cmd(action='send', dest=dest, quiet=quiet))
            self.assertIn('', ft.active_cmds)
            self.ae(os.path.basename(ft.active_cmds[''].dest), '1.bin')
            self.assertIsNone(ft.active_cmds[''].file)
            self.ae(ft.test_responses, [] if quiet else [{'status': 'OK'}])
            ft.handle_serialized_command(serialized_cmd(action='data', data='abcd'))
            self.assertPathEqual(ft.active_cmds[''].file.name, dest)
            ft.handle_serialized_command(serialized_cmd(action='end_data', data='123'))
            self.assertFalse(ft.active_cmds)
            self.ae(ft.test_responses, [] if quiet else [{'status': 'OK'}, {'status': 'COMPLETED'}])
            with open(dest) as f:
                self.ae(f.read(), 'abcd123')
        # cancel a send
        ft = FileTransmission()
        dest = os.path.join(self.tdir, '2.bin')
        ft.handle_serialized_command(serialized_cmd(action='send', dest=dest))
        self.ae(ft.test_responses, [{'status': 'OK'}])
        ft.handle_serialized_command(serialized_cmd(action='data', data='abcd'))
        self.assertTrue(os.path.exists(dest))
        ft.handle_serialized_command(serialized_cmd(action='cancel'))
        self.ae(ft.test_responses, [{'status': 'OK'}])
        self.assertFalse(os.path.exists(dest))
        self.assertFalse(ft.active_cmds)
        # compress with zlib
        ft = FileTransmission()
        dest = os.path.join(self.tdir, '3.bin')
        ft.handle_serialized_command(serialized_cmd(action='send', dest=dest, compression='zlib'))
        self.ae(ft.test_responses, [{'status': 'OK'}])
        odata = 'abcd' * 1024
        data = zlib.compress(odata.encode('ascii'))
        ft.handle_serialized_command(serialized_cmd(action='data', data=data[:len(data)//2]))
        self.assertTrue(os.path.exists(dest))
        ft.handle_serialized_command(serialized_cmd(action='end_data', data=data[len(data)//2:]))
        with open(dest) as f:
            self.ae(f.read(), odata)
        self.ae(ft.test_responses, [{'status': 'OK'}, {'status': 'COMPLETED'}])
        del odata
        del data

        # zip send
        self.clean_tdir()
        buf = BytesIO()
        with zipfile.ZipFile(buf, 'w') as zf:
            zf.writestr('one.txt', '1' * 1111)
            zf.writestr('two/one', '2' * 2222)
            zf.writestr('onex/../../three', '3333')
            zf.writestr('/onex', '3333')
        ft = FileTransmission()
        dest = os.path.join(self.tdir, 'zf')
        ft.handle_serialized_command(serialized_cmd(action='send', dest=dest, container_fmt='zip'))
        self.ae(ft.test_responses, [{'status': 'OK'}])
        ft.handle_serialized_command(serialized_cmd(action='end_data', data=buf.getvalue()))
        self.ae(ft.test_responses, [{'status': 'OK'}, {'status': 'COMPLETED'}])
        with open(os.path.join(dest, 'one.txt')) as f:
            self.ae(f.read(), '1' * 1111)
        with open(os.path.join(dest, 'two', 'one')) as f:
            self.ae(f.read(), '2' * 2222)
        self.ae({'zf', 'zf/two', 'zf/one.txt', 'zf/two/one'}, set(names_in(self.tdir)))

        # tar send
        for mode in ('', 'gz', 'bz2', 'xz'):
            buf = BytesIO()
            with tarfile.open(fileobj=buf, mode=f'w:{mode}') as tf:
                def a(name, data, mode=0o717, lt=None):
                    ti = tarfile.TarInfo(name)
                    ti.mtime = 13
                    ti.size = len(data)
                    ti.mode = mode
                    if lt:
                        ti.linkname = data
                        ti.type = lt
                        tf.addfile(ti)
                    else:
                        tf.addfile(ti, BytesIO(data.encode('utf-8')))
                a('a.txt', 'abcd')
                a('/b.txt', 'abcd')
                a('../c.txt', 'abcd')
                a('sym', 'a.txt', lt=tarfile.SYMTYPE)
                a('asym', '/abstarget', lt=tarfile.SYMTYPE)
                a('link', 'a.txt', lt=tarfile.LNKTYPE)
            self.clean_tdir()
            ft = FileTransmission()
            dest = os.path.join(self.tdir, 'tf')
            ft.handle_serialized_command(serialized_cmd(action='send', dest=dest, container_fmt='t' + (mode or 'ar')))
            self.ae(ft.test_responses, [{'status': 'OK'}])
            ft.handle_serialized_command(serialized_cmd(action='end_data', data=buf.getvalue()))
            self.ae(ft.test_responses, [{'status': 'OK'}, {'status': 'COMPLETED'}])
            with open(os.path.join(dest, 'a.txt')) as f:
                self.ae(f.read(), 'abcd')
            st = os.stat(f.name)
            self.ae(st.st_mode & 0b111111111, 0o717)
            self.ae(st.st_mtime, 13)
            self.ae(os.path.realpath(os.path.join(dest, 'sym')), f.name)
            self.ae(os.path.realpath(os.path.join(dest, 'asym')), '/abstarget')
            self.assertTrue(os.path.samefile(f.name, os.path.join(dest, 'link')))
            self.ae({'tf', 'tf/a.txt', 'tf/sym', 'tf/asym', 'tf/link'}, set(names_in(self.tdir)))
            self.ae(len(os.listdir(self.tdir)), 1)
