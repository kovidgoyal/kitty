#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPLv3 Copyright: 2021, Kovid Goyal <kovid at kovidgoyal.net>


import os
import shutil
import stat
import tempfile
import zlib
from pathlib import Path

from kittens.transfer.librsync import (
    LoadSignature, PatchFile, delta_for_file, signature_of_file
)
from kittens.transfer.main import parse_transfer_args
from kittens.transfer.rsync import decode_utf8_buffer, parse_ftc
from kittens.transfer.send import files_for_send
from kittens.transfer.utils import set_paths
from kitty.file_transmission import (
    Action, Compression, FileTransmissionCommand, FileType,
    TestFileTransmission as FileTransmission, TransmissionType
)

from . import BaseTest


def response(id='test', msg='', file_id='', name='', action='status', status='', size=-1):
    ans = {'action': 'status'}
    if id:
        ans['id'] = id
    if file_id:
        ans['file_id'] = file_id
    if name:
        ans['name'] = name
    if status:
        ans['status'] = status
    if size > -1:
        ans['size'] = size
    return ans


def names_in(path):
    for dirpath, dirnames, filenames in os.walk(path):
        for d in dirnames + filenames:
            yield os.path.relpath(os.path.join(dirpath, d), path)


def serialized_cmd(**fields) -> str:
    if 'id' not in fields:
        fields['id'] = 'test'
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
            os.environ.pop('HOME', None)
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

    def test_rsync_roundtrip(self):
        a_path = os.path.join(self.tdir, 'a')
        b_path = os.path.join(self.tdir, 'b')
        c_path = os.path.join(self.tdir, 'c')

        def files_equal(a_path, c_path):
            self.ae(os.path.getsize(a_path), os.path.getsize(b_path))
            with open(b_path, 'rb') as b, open(c_path, 'rb') as c:
                self.ae(b.read(), c.read())

        def patch(old_path, new_path, output_path, max_delta_len=0):
            sig_loader = LoadSignature()
            for chunk in signature_of_file(old_path):
                sig_loader.add_chunk(chunk)
            sig_loader.commit()
            self.assertTrue(sig_loader.finished)
            delta_len = 0
            with PatchFile(old_path, output_path) as patcher:
                for chunk in delta_for_file(new_path, sig_loader.signature):
                    self.assertFalse(patcher.finished)
                    patcher.write(chunk)
                    delta_len += len(chunk)
            self.assertTrue(patcher.finished)
            if max_delta_len:
                self.assertLessEqual(delta_len, max_delta_len)
            files_equal(output_path, new_path)

        sz = 1024 * 1024 + 37
        with open(a_path, 'wb') as f:
            f.write(os.urandom(sz))
        with open(b_path, 'wb') as f:
            f.write(os.urandom(sz))

        patch(a_path, b_path, c_path)
        # test size of delta
        patch(a_path, a_path, c_path, max_delta_len=256)

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
            self.assertIn('test', ft.active_receives)
            self.ae(ft.test_responses, [] if quiet else [response(status='OK')])
            ft.handle_serialized_command(serialized_cmd(action='file', name=dest))
            self.assertPathEqual(ft.active_file('test').name, dest)
            self.assertIsNone(ft.active_file('test').actual_file)
            self.ae(ft.test_responses, [] if quiet else [response(status='OK'), response(status='STARTED', name=dest)])
            ft.handle_serialized_command(serialized_cmd(action='data', data='abcd'))
            self.assertPathEqual(ft.active_file('test').name, dest)
            ft.handle_serialized_command(serialized_cmd(action='end_data', data='123'))
            self.ae(ft.test_responses, [] if quiet else [response(status='OK'), response(status='STARTED', name=dest), response(status='OK', name=dest)])
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
        self.assertPathEqual(ft.active_file('test').name, dest)
        ft.handle_serialized_command(serialized_cmd(action='data', data='abcd'))
        self.assertTrue(os.path.exists(dest))
        ft.handle_serialized_command(serialized_cmd(action='cancel'))
        self.ae(ft.test_responses, [response(status='OK'), response(status='STARTED', name=dest), response(status='CANCELED')])
        self.assertFalse(ft.active_receives)
        # compress with zlib
        ft = FileTransmission()
        dest = os.path.join(self.tdir, '3.bin')
        ft.handle_serialized_command(serialized_cmd(action='send'))
        self.ae(ft.test_responses, [response(status='OK')])
        ft.handle_serialized_command(serialized_cmd(action='file', name=dest, compression='zlib'))
        self.assertPathEqual(ft.active_file('test').name, dest)
        odata = b'abcd' * 1024 + b'xyz'
        c = zlib.compressobj()
        ft.handle_serialized_command(serialized_cmd(action='data', data=c.compress(odata)))
        self.assertTrue(os.path.exists(dest))
        ft.handle_serialized_command(serialized_cmd(action='end_data', data=c.flush()))
        self.ae(ft.test_responses, [response(status='OK'), response(status='STARTED', name=dest), response(status='OK', name=dest)])
        ft.handle_serialized_command(serialized_cmd(action='finish'))
        with open(dest, 'rb') as f:
            self.ae(f.read(), odata)
        del odata

        # overwriting
        self.clean_tdir()
        ft = FileTransmission()
        one = os.path.join(self.tdir, '1')
        two = os.path.join(self.tdir, '2')
        three = os.path.join(self.tdir, '3')
        open(two, 'w').close()
        os.symlink(two, one)
        ft.handle_serialized_command(serialized_cmd(action='send'))
        ft.handle_serialized_command(serialized_cmd(action='file', name=one))
        ft.handle_serialized_command(serialized_cmd(action='end_data', data='abcd'))
        ft.handle_serialized_command(serialized_cmd(action='finish'))
        self.assertFalse(os.path.islink(one))
        with open(one) as f:
            self.ae(f.read(), 'abcd')
        self.assertTrue(os.path.isfile(two))
        ft = FileTransmission()
        ft.handle_serialized_command(serialized_cmd(action='send'))
        ft.handle_serialized_command(serialized_cmd(action='file', name=two, ftype='symlink'))
        ft.handle_serialized_command(serialized_cmd(action='end_data', data='path:/abcd'))
        ft.handle_serialized_command(serialized_cmd(action='finish'))
        self.ae(os.readlink(two), '/abcd')
        with open(three, 'w') as f:
            f.write('abcd')
        self.responses = []
        ft = FileTransmission()
        ft.handle_serialized_command(serialized_cmd(action='send'))
        self.assertResponses(ft, status='OK')
        ft.handle_serialized_command(serialized_cmd(action='file', name=three))
        self.assertResponses(ft, status='STARTED', name=three, size=4)
        ft.handle_serialized_command(serialized_cmd(action='end_data', data='11'))
        ft.handle_serialized_command(serialized_cmd(action='finish'))
        with open(three) as f:
            self.ae(f.read(), '11')

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
            self.assertResponses(ft, status='OK' if not data else 'STARTED', name=name, file_id=str(fid))
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

    def test_parse_ftc(self):
        def t(raw, *expected):
            a = []

            def c(k, v, has_semicolons):
                a.append(decode_utf8_buffer(k))
                if has_semicolons:
                    v = bytes(v).replace(b';;', b';')
                a.append(decode_utf8_buffer(v))

            parse_ftc(raw, c)
            self.ae(tuple(a), expected)

        t('a=b', 'a', 'b')
        t('a=b;', 'a', 'b')
        t('a1=b1;c=d;;', 'a1', 'b1', 'c', 'd;')
        t('a1=b1;c=d;;e', 'a1', 'b1', 'c', 'd;e')
        t('a1=b1;c=d;;;1=1', 'a1', 'b1', 'c', 'd;', '1', '1')

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
