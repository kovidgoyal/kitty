#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPLv3 Copyright: 2021, Kovid Goyal <kovid at kovidgoyal.net>


import os
import shutil
import stat
import tempfile
import zlib
from pathlib import Path

from kittens.transfer.main import (
    files_for_send, parse_transfer_args, set_paths
)
from kitty.file_transmission import (
    Action, Compression, FileTransmissionCommand, FileType,
    TestFileTransmission as FileTransmission, TransmissionType
)

from . import BaseTest


def response(id='', msg='', file_id='', name='', action='status', status=''):
    ans = {'action': 'status'}
    if id:
        ans['id'] = id
    if file_id:
        ans['file_id'] = file_id
    if name:
        ans['name'] = name
    if status:
        ans['status'] = status
    return ans


def names_in(path):
    for dirpath, dirnames, filenames in os.walk(path):
        for d in dirnames + filenames:
            yield os.path.relpath(os.path.join(dirpath, d), path)


def serialized_cmd(**fields) -> str:
    for k, A in (('action', Action), ('ftype', FileType), ('ttype', TransmissionType), ('compression', Compression)):
        if k in fields:
            fields[k] = A[fields[k]]
    if isinstance(fields.get('data'), str):
        fields['data'] = fields['data'].encode('utf-8')
    ans = FileTransmissionCommand(**fields)
    return ans.serialize()


class TestFileTransmission(BaseTest):

    def setUp(self):
        self.tdir = os.path.realpath(tempfile.mkdtemp())
        self.responses = []
        self.orig_home = os.environ.get('HOME')

    def tearDown(self):
        shutil.rmtree(self.tdir)
        self.responses = []
        if self.orig_home is None:
            os.environ.pop('HOME')
        else:
            os.environ['HOME'] = self.orig_home

    def clean_tdir(self):
        shutil.rmtree(self.tdir)
        self.tdir = os.path.realpath(tempfile.mkdtemp())
        self.responses = []

    def assertResponses(self, ft, **kw):
        self.responses.append(response(**kw))
        self.ae(ft.test_responses, self.responses)

    def assertPathEqual(self, a, b):
        a = os.path.abspath(os.path.realpath(a))
        b = os.path.abspath(os.path.realpath(b))
        self.ae(a, b)

    def test_file_put(self):
        # send refusal
        for quiet in (0, 1, 2):
            ft = FileTransmission(allow=False)
            ft.handle_serialized_command(serialized_cmd(action='send', id='x', quiet=quiet))
            self.ae(ft.test_responses, [] if quiet == 2 else [response(id='x', status='EPERM:User refused the transfer')])
            self.assertFalse(ft.active_receives)
        # simple single file send
        for quiet in (0, 1, 2):
            ft = FileTransmission()
            dest = os.path.join(self.tdir, '1.bin')
            ft.handle_serialized_command(serialized_cmd(action='send', quiet=quiet))
            self.assertIn('', ft.active_receives)
            ft.handle_serialized_command(serialized_cmd(action='file', name=dest, quiet=quiet))
            self.assertPathEqual(ft.active_file().name, dest)
            self.assertIsNone(ft.active_file().actual_file)
            self.ae(ft.test_responses, [] if quiet else [response(status='OK')])
            ft.handle_serialized_command(serialized_cmd(action='data', data='abcd'))
            self.assertPathEqual(ft.active_file().actual_file.name, dest)
            ft.handle_serialized_command(serialized_cmd(action='end_data', data='123'))
            self.ae(ft.test_responses, [] if quiet else [response(status='OK'), response(status='OK', name=dest)])
            self.assertTrue(ft.active_receives)
            ft.handle_serialized_command(serialized_cmd(action='finish'))
            self.assertFalse(ft.active_receives)
            with open(dest) as f:
                self.ae(f.read(), 'abcd123')
        # cancel a send
        ft = FileTransmission()
        dest = os.path.join(self.tdir, '2.bin')
        ft.handle_serialized_command(serialized_cmd(action='send'))
        self.ae(ft.test_responses, [response(status='OK')])
        ft.handle_serialized_command(serialized_cmd(action='file', name=dest))
        self.assertPathEqual(ft.active_file().name, dest)
        ft.handle_serialized_command(serialized_cmd(action='data', data='abcd'))
        self.assertTrue(os.path.exists(dest))
        ft.handle_serialized_command(serialized_cmd(action='cancel'))
        self.ae(ft.test_responses, [response(status='OK')])
        self.assertFalse(ft.active_receives)
        # compress with zlib
        ft = FileTransmission()
        dest = os.path.join(self.tdir, '3.bin')
        ft.handle_serialized_command(serialized_cmd(action='send'))
        self.ae(ft.test_responses, [response(status='OK')])
        ft.handle_serialized_command(serialized_cmd(action='file', name=dest, compression='zlib'))
        self.assertPathEqual(ft.active_file().name, dest)
        odata = b'abcd' * 1024
        data = zlib.compress(odata)
        ft.handle_serialized_command(serialized_cmd(action='data', data=data[:len(data)//2]))
        self.assertTrue(os.path.exists(dest))
        ft.handle_serialized_command(serialized_cmd(action='end_data', data=data[len(data)//2:]))
        self.ae(ft.test_responses, [response(status='OK'), response(status='OK', name=dest)])
        ft.handle_serialized_command(serialized_cmd(action='finish'))
        with open(dest, 'rb') as f:
            self.ae(f.read(), odata)
        del odata
        del data

        # multi file send
        self.clean_tdir()
        ft = FileTransmission()
        dest = os.path.join(self.tdir, '2.bin')
        ft.handle_serialized_command(serialized_cmd(action='send'))
        self.assertResponses(ft, status='OK')
        fid = 0

        def send(name, data, **kw):
            nonlocal fid
            fid += 1
            kw['action'] = 'file'
            kw['file_id'] = str(fid)
            kw['name'] = name
            ft.handle_serialized_command(serialized_cmd(**kw))
            if data:
                ft.handle_serialized_command(serialized_cmd(action='end_data', file_id=str(fid), data=data))
            self.assertResponses(ft, status='OK', name=name, file_id=str(fid))

        send(dest, b'xyz', permissions=0o777, mtime=13)
        st = os.stat(dest)
        self.ae(st.st_nlink, 1)
        self.ae(stat.S_IMODE(st.st_mode), 0o777)
        self.ae(st.st_mtime_ns, 13)
        send(dest + 's1', 'path:' + os.path.basename(dest), permissions=0o777, mtime=17, ftype='symlink')
        st = os.stat(dest + 's1', follow_symlinks=False)
        self.ae(stat.S_IMODE(st.st_mode), 0o777)
        self.ae(st.st_mtime_ns, 17)
        self.ae(os.readlink(dest + 's1'), os.path.basename(dest))
        send(dest + 's2', 'fid:1', ftype='symlink')
        self.ae(os.readlink(dest + 's2'), os.path.basename(dest))
        send(dest + 's3', 'fid_abs:1', ftype='symlink')
        self.assertPathEqual(os.readlink(dest + 's3'), dest)
        send(dest + 'l1', 'path:' + os.path.basename(dest), ftype='link')
        self.ae(os.stat(dest).st_nlink, 2)
        send(dest + 'l2', 'fid:1', ftype='link')
        self.ae(os.stat(dest).st_nlink, 3)
        send(dest + 'd1/1', 'in_dir')
        send(dest + 'd1', '', ftype='directory', mtime=29)
        send(dest + 'd2', '', ftype='directory', mtime=29)
        with open(dest + 'd1/1') as f:
            self.ae(f.read(), 'in_dir')
        self.assertTrue(os.path.isdir(dest + 'd1'))
        self.assertTrue(os.path.isdir(dest + 'd2'))

        ft.handle_serialized_command(serialized_cmd(action='finish'))
        self.ae(os.stat(dest + 'd1').st_mtime_ns, 29)
        self.ae(os.stat(dest + 'd2').st_mtime_ns, 29)
        self.assertFalse(ft.active_receives)

    def test_path_mapping(self):
        opts = parse_transfer_args([])[0]
        b = Path(os.path.join(self.tdir, 'b'))
        os.makedirs(b)
        open(b / 'r', 'w').close()
        os.mkdir(b / 'd')
        open(b / 'd' / 'r', 'w').close()

        def gm(*args):
            return files_for_send(opts, list(map(str, args)))

        def am(files, kw):
            m = {f.expanded_local_path: f.remote_path for f in files}
            kw = {str(k): str(v) for k, v in kw.items()}
            self.ae(m, kw)

        def tf(args, expected):
            files = gm(*args)
            self.ae(len(files), len(expected))
            am(files, expected)

        opts.mode = 'mirror'
        with set_paths(cwd=b, home='/foo/bar'):
            tf(['r', 'd'], {b/'r': b/'r', b/'d': b/'d', b/'d'/'r': b/'d'/'r'})
            tf(['r', 'd/r'], {b/'r': b/'r', b/'d'/'r': b/'d'/'r'})
        with set_paths(cwd=b, home=self.tdir):
            tf(['r', 'd'], {b/'r': '~/b/r', b/'d': '~/b/d', b/'d'/'r': '~/b/d/r'})
        opts.mode = 'normal'
        with set_paths(cwd='/some/else', home='/foo/bar'):
            tf([b/'r', b/'d', '/dest'], {b/'r': '/dest/r', b/'d': '/dest/d', b/'d'/'r': '/dest/d/r'})
            tf([b/'r', b/'d', '~/dest'], {b/'r': '~/dest/r', b/'d': '~/dest/d', b/'d'/'r': '~/dest/d/r'})
        with set_paths(cwd=b, home='/foo/bar'):
            tf(['r', 'd', '/dest'], {b/'r': '/dest/r', b/'d': '/dest/d', b/'d'/'r': '/dest/d/r'})

        os.symlink('/foo/b', b / 'e')
        os.symlink('r', b / 's')
        os.link(b / 'r', b / 'h')
        with set_paths(cwd='/some/else', home='/foo/bar'):
            files = gm(b / 'e', 'dest')
            self.ae(files[0].symbolic_link_target, 'path:/foo/b')
            files = gm(b / 's', b / 'r', 'dest')
            self.ae(files[0].symbolic_link_target, 'fid:2')
            files = gm(b / 'h', 'dest')
            self.ae(files[0].file_type, FileType.regular)
            files = gm(b / 'h', b / 'r', 'dest')
            self.ae(files[1].file_type, FileType.link)
            self.ae(files[1].hard_link_target, '1')
