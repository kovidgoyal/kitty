#!/usr/bin/env python
# License: GPLv3 Copyright: 2021, Kovid Goyal <kovid at kovidgoyal.net>


import os
import shutil
import stat
import tempfile
import zlib

from kittens.transfer.rsync import Differ, Hasher, Patcher, decode_utf8_buffer, parse_ftc
from kittens.transfer.utils import set_paths
from kitty.file_transmission import Action, Compression, FileTransmissionCommand, FileType, TransmissionType, ZlibDecompressor
from kitty.file_transmission import TestFileTransmission as FileTransmission

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


def generate_data(block_size, num_blocks, *extra) -> bytes:
    extra = ''.join(extra)
    b = b'_' * (block_size * num_blocks) + extra.encode()
    ans = bytearray(b)
    for i in range(num_blocks):
        offset = i * block_size
        p = str(i).encode()
        ans[offset:offset+len(p)] = p
    return bytes(ans)


def patch_data(data, *patches):
    total_patch_size = 0
    ans = bytearray(data)
    for patch in patches:
        o, sep, r = patch.partition(':')
        r = r.encode()
        total_patch_size += len(r)
        offset = int(o)
        ans[offset:offset+len(r)] = r
    return bytes(ans), len(patches), total_patch_size


def run_roundtrip_test(self: 'TestFileTransmission', src_data, changed, num_of_patches, total_patch_size):
    buf = memoryview(bytearray(30))
    signature = bytearray(0)
    p = Patcher(len(changed))
    n = p.signature_header(buf)
    signature.extend(buf[:n])
    src = memoryview(changed)
    bs = p.block_size
    while src:
        n = p.sign_block(src[:bs], buf)
        signature.extend(buf[:n])
        src = src[bs:]
    d = Differ()
    src = memoryview(signature)
    while src:
        d.add_signature_data(src[:13])
        src = src[13:]
    d.finish_signature_data()
    del src, signature
    src = memoryview(src_data)
    delta = bytearray(0)
    def read_into(b):
        nonlocal src
        n = min(len(b), len(src))
        if n > 0:
            b[:n] = src[:n]
            src = src[n:]
        return n
    def write_delta(b):
        delta.extend(b)
    while d.next_op(read_into, write_delta):
        pass
    delta = memoryview(delta)
    del src

    def read_at(pos, output) -> int:
        b = changed[pos:]
        amt = min(len(output), len(b))
        output[:amt] = b[:amt]
        return amt

    output = bytearray(0)

    def write_changes(b):
        output.extend(b)

    def debug_msg():
        return f'\n\nsrc:\n{src_data.decode()}\nchanged:\n{changed.decode()}\noutput:\n{output.decode()}'
    try:
        while delta:
            p.apply_delta_data(delta[:11], read_at, write_changes)
            delta = delta[11:]
        p.finish_delta_data()
    except Exception as err:
        self.fail(f'{err}\n{debug_msg()}')
    self.assertEqual(src_data, bytes(output), debug_msg())
    limit = 2 * (p.block_size * num_of_patches)
    if limit > -1:
        self.assertLessEqual(
            p.total_data_in_delta, limit, f'Unexpectedly poor delta performance: {total_patch_size=} {p.total_data_in_delta=} {limit=}')


def test_rsync_roundtrip(self: 'TestFileTransmission') -> None:
    block_size = 16
    src_data = generate_data(block_size, 16)
    changed, num_of_patches, total_patch_size = patch_data(src_data, "3:patch1", "16:patch2", "130:ptch3", "176:patch4", "222:XXYY")

    run_roundtrip_test(self, src_data, src_data[block_size:], 1, block_size)
    run_roundtrip_test(self, src_data, changed, num_of_patches, total_patch_size)
    run_roundtrip_test(self, src_data, b'', -1, 0)
    run_roundtrip_test(self, src_data, src_data, 0, 0)
    run_roundtrip_test(self, src_data, changed[:len(changed)-3], num_of_patches, total_patch_size)
    run_roundtrip_test(self, src_data, changed[:37] + changed[81:], num_of_patches, total_patch_size)

    block_size = 13
    src_data = generate_data(block_size, 17, "trailer")
    changed, num_of_patches, total_patch_size = patch_data(src_data, "0:patch1", "19:patch2")
    run_roundtrip_test(self, src_data, changed, num_of_patches, total_patch_size)
    run_roundtrip_test(self, src_data, changed[:len(changed)-3], num_of_patches, total_patch_size)
    run_roundtrip_test(self, src_data, changed + b"xyz...", num_of_patches, total_patch_size)


class TestFileTransmission(BaseTest):

    def setUp(self):
        super().setUp()
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
        super().tearDown()

    def clean_tdir(self):
        shutil.rmtree(self.tdir)
        self.tdir = os.path.realpath(tempfile.mkdtemp())
        self.responses = []

    def cr(self, a, b):
        def f(r):
            r.pop('size', None)
            return r
        a = tuple(f(r) for r in a if r.get('status') != 'PROGRESS')
        b = tuple(f(r) for r in b if r.get('status') != 'PROGRESS')
        self.ae(a, b)

    def assertResponses(self, ft, limit=1024, **kw):
        self.responses.append(response(**kw))
        self.cr(ft.test_responses[:limit], self.responses[:limit])

    def assertPathEqual(self, a, b):
        a = os.path.abspath(os.path.realpath(a))
        b = os.path.abspath(os.path.realpath(b))
        self.ae(a, b)

    def test_rsync_roundtrip(self):
        test_rsync_roundtrip(self)

    def test_file_get(self):
        # send refusal
        for quiet in (0, 1, 2):
            ft = FileTransmission(allow=False)
            ft.handle_serialized_command(serialized_cmd(action='receive', id='x', quiet=quiet))
            self.cr(ft.test_responses, [] if quiet == 2 else [response(id='x', status='EPERM:User refused the transfer')])
            self.assertFalse(ft.active_sends)
        # reading metadata for specs
        cwd = os.path.join(self.tdir, 'cwd')
        home = os.path.join(self.tdir, 'home')
        os.mkdir(cwd), os.mkdir(home)
        with set_paths(cwd=cwd, home=home):
            ft = FileTransmission()
            self.responses = []
            ft.handle_serialized_command(serialized_cmd(action='receive', size=1))
            self.assertResponses(ft, status='OK')
            ft.handle_serialized_command(serialized_cmd(action='file', file_id='missing', name='XXX'))
            self.responses.append(response(status='ENOENT:Failed to read spec', file_id='missing'))
            self.assertResponses(ft, status='OK', name=home)
            ft = FileTransmission()
            self.responses = []
            ft.handle_serialized_command(serialized_cmd(action='receive', size=2))
            self.assertResponses(ft, status='OK')
            with open(os.path.join(home, 'a'), 'w') as f:
                f.write('a')
            os.mkdir(f.name + 'd')
            with open(os.path.join(f.name + 'd', 'b'), 'w') as f2:
                f2.write('bbb')
            os.symlink(f.name, f.name + 'd/s')
            os.link(f.name, f.name + 'd/h')
            os.symlink('XXX', f.name + 'd/q')
            ft.handle_serialized_command(serialized_cmd(action='file', file_id='a', name='a'))
            ft.handle_serialized_command(serialized_cmd(action='file', file_id='b', name='ad'))
            files = {r['name']: r for r in ft.test_responses if r['action'] == 'file'}
            self.ae(len(files), 6)
            q = files[f.name]
            tgt = q['status'].encode('ascii')
            self.ae(q['size'], 1), self.assertNotIn('ftype', q)
            q = files[f.name + 'd']
            self.ae(q['ftype'], 'directory')
            q = files[f.name + 'd/b']
            self.ae(q['size'], 3)
            q = files[f.name + 'd/s']
            self.ae(q['ftype'], 'symlink')
            self.ae(q['data'], tgt)
            q = files[f.name + 'd/h']
            self.ae(q['ftype'], 'link')
            self.ae(q['data'], tgt)
            q = files[f.name + 'd/q']
            self.ae(q['ftype'], 'symlink')
            self.assertNotIn('data', q)
        base = os.path.join(self.tdir, 'base')
        os.mkdir(base)
        src = os.path.join(base, 'src.bin')
        data = os.urandom(16 * 1024)
        with open(src, 'wb') as f:
            f.write(data)
        sl = os.path.join(base, 'src.link')
        os.symlink(src, sl)
        for compress in ('none', 'zlib'):
            ft = FileTransmission()
            self.responses = []
            ft.handle_serialized_command(serialized_cmd(action='receive', size=1))
            self.assertResponses(ft, status='OK')
            ft.handle_serialized_command(serialized_cmd(action='file', file_id='src', name=src))
            ft.active_sends['test'].metadata_sent = True
            ft.test_responses = []
            ft.handle_serialized_command(serialized_cmd(action='file', file_id='src', name=src, compression=compress))
            received = b''.join(x['data'] for x in ft.test_responses)
            if compress == 'zlib':
                received = ZlibDecompressor()(received, True)
            self.ae(data, received)
            ft.test_responses = []
            ft.handle_serialized_command(serialized_cmd(action='file', file_id='sl', name=sl, compression=compress))
            received = b''.join(x['data'] for x in ft.test_responses)
            self.ae(received.decode('utf-8'), src)

    def test_file_put(self):
        self.skipTest("TODO: Port this test")
        # send refusal
        for quiet in (0, 1, 2):
            ft = FileTransmission(allow=False)
            ft.handle_serialized_command(serialized_cmd(action='send', id='x', quiet=quiet))
            self.cr(ft.test_responses, [] if quiet == 2 else [response(id='x', status='EPERM:User refused the transfer')])
            self.assertFalse(ft.active_receives)
        # simple single file send
        for quiet in (0, 1, 2):
            ft = FileTransmission()
            dest = os.path.join(self.tdir, '1.bin')
            ft.handle_serialized_command(serialized_cmd(action='send', quiet=quiet))
            self.assertIn('test', ft.active_receives)
            self.cr(ft.test_responses, [] if quiet else [response(status='OK')])
            ft.handle_serialized_command(serialized_cmd(action='file', name=dest))
            self.assertPathEqual(ft.active_file('test').name, dest)
            self.assertIsNone(ft.active_file('test').actual_file)
            self.cr(ft.test_responses, [] if quiet else [response(status='OK'), response(status='STARTED', name=dest)])
            ft.handle_serialized_command(serialized_cmd(action='data', data='abcd'))
            self.assertPathEqual(ft.active_file('test').name, dest)
            ft.handle_serialized_command(serialized_cmd(action='end_data', data='123'))
            self.cr(ft.test_responses, [] if quiet else [response(status='OK'), response(status='STARTED', name=dest), response(status='OK', name=dest)])
            self.assertTrue(ft.active_receives)
            ft.handle_serialized_command(serialized_cmd(action='finish'))
            self.assertFalse(ft.active_receives)
            with open(dest) as f:
                self.ae(f.read(), 'abcd123')
        # cancel a send
        ft = FileTransmission()
        dest = os.path.join(self.tdir, '2.bin')
        ft.handle_serialized_command(serialized_cmd(action='send'))
        self.cr(ft.test_responses, [response(status='OK')])
        ft.handle_serialized_command(serialized_cmd(action='file', name=dest))
        self.assertPathEqual(ft.active_file('test').name, dest)
        ft.handle_serialized_command(serialized_cmd(action='data', data='abcd'))
        self.assertTrue(os.path.exists(dest))
        ft.handle_serialized_command(serialized_cmd(action='cancel'))
        self.cr(ft.test_responses, [response(status='OK'), response(status='STARTED', name=dest), response(status='CANCELED')])
        self.assertFalse(ft.active_receives)
        # compress with zlib
        ft = FileTransmission()
        dest = os.path.join(self.tdir, '3.bin')
        ft.handle_serialized_command(serialized_cmd(action='send'))
        self.cr(ft.test_responses, [response(status='OK')])
        ft.handle_serialized_command(serialized_cmd(action='file', name=dest, compression='zlib'))
        self.assertPathEqual(ft.active_file('test').name, dest)
        odata = b'abcd' * 1024 + b'xyz'
        c = zlib.compressobj()
        ft.handle_serialized_command(serialized_cmd(action='data', data=c.compress(odata)))
        self.assertTrue(os.path.exists(dest))
        ft.handle_serialized_command(serialized_cmd(action='end_data', data=c.flush()))
        self.cr(ft.test_responses, [response(status='OK'), response(status='STARTED', name=dest), response(status='OK', name=dest)])
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

        send(dest, b'xyz', permissions=0o777, mtime=13000)
        st = os.stat(dest)
        self.ae(st.st_nlink, 1)
        self.ae(stat.S_IMODE(st.st_mode), 0o777)
        self.ae(st.st_mtime_ns, 13000)
        send(dest + 's1', 'path:' + os.path.basename(dest), permissions=0o777, mtime=17000, ftype='symlink')
        st = os.stat(dest + 's1', follow_symlinks=False)
        self.ae(stat.S_IMODE(st.st_mode), 0o777)
        self.ae(st.st_mtime_ns, 17000)
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
        send(dest + 'd1', '', ftype='directory', mtime=29000)
        send(dest + 'd2', '', ftype='directory', mtime=29000)
        with open(dest + 'd1/1') as f:
            self.ae(f.read(), 'in_dir')
        self.assertTrue(os.path.isdir(dest + 'd1'))
        self.assertTrue(os.path.isdir(dest + 'd2'))

        ft.handle_serialized_command(serialized_cmd(action='finish'))
        self.ae(os.stat(dest + 'd1').st_mtime_ns, 29000)
        self.ae(os.stat(dest + 'd2').st_mtime_ns, 29000)
        self.assertFalse(ft.active_receives)

    def test_parse_ftc(self):
        def t(raw, *expected):
            a = []

            def c(k, v):
                a.append(decode_utf8_buffer(k))
                a.append(decode_utf8_buffer(v))

            parse_ftc(raw, c)
            self.ae(tuple(a), expected)

        t('a=b', 'a', 'b')
        t('a=b;', 'a', 'b')
        t('a1=b1;c=d;;', 'a1', 'b1', 'c', 'd')
        t('a1=b1;c=d;;e', 'a1', 'b1', 'c', 'd')
        t('a1=b1;c=d;;;1=1', 'a1', 'b1', 'c', 'd', '1', '1')

    def test_path_mapping_receive(self):
        self.skipTest('TODO: Port this test')

    def test_rsync_hashers(self):
        h = Hasher("xxh3-64")
        h.update(b'abcd')
        self.assertEqual(h.hexdigest(), '6497a96f53a89890')
        self.assertEqual(h.digest64(), 7248448420886124688)
        h128 = Hasher("xxh3-128")
        h128.update(b'abcd')
        self.assertEqual(h128.hexdigest(), '8d6b60383dfa90c21be79eecd1b1353d')
