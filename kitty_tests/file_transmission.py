#!/usr/bin/env python
# License: GPLv3 Copyright: 2021, Kovid Goyal <kovid at kovidgoyal.net>


import os
import shutil
import stat
import tempfile
from collections import namedtuple
from contextlib import contextmanager
from pathlib import Path

from kittens.transfer.rsync import Differ, Hasher, Patcher, parse_ftc
from kittens.transfer.utils import set_paths
from kitty.constants import kitten_exe
from kitty.file_transmission import Action, Compression, FileTransmissionCommand, FileType, TransmissionType, ZlibDecompressor
from kitty.file_transmission import TestFileTransmission as FileTransmission

from . import PTY, BaseTest


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


class PtyFileTransmission(FileTransmission):

    def __init__(self, pty, allow=True):
        self.pty = pty
        super().__init__(allow=allow)
        self.pty.callbacks.ftc = self

    def write_ftc_to_child(self, payload: FileTransmissionCommand, appendleft: bool = False, use_pending: bool = True) -> bool:
        # print('to kitten:', payload)
        self.pty.write_to_child('\x1b]' + payload.serialize(prefix_with_osc_code=True) + '\x1b\\', flush=False)
        return True


class TransferPTY(PTY):

    def __init__(self, cmd, cwd, allow=True, env=None):
        super().__init__(cmd, cwd=cwd, env=env, rows=200, columns=120)
        self.fc = PtyFileTransmission(self, allow=allow)


class TestFileTransmission(BaseTest):

    def setUp(self):
        self.direction_receive = False
        self.kitty_home = self.kitty_cwd = self.kitten_home = self.kitten_cwd = ''
        super().setUp()
        self.tdir = os.path.realpath(tempfile.mkdtemp())
        self.responses = []
        self.orig_home = os.environ.get('HOME')

    def tearDown(self):
        self.rmtree_ignoring_errors(self.tdir)
        self.responses = []
        if self.orig_home is None:
            os.environ.pop('HOME', None)
        else:
            os.environ['HOME'] = self.orig_home
        super().tearDown()

    def clean_tdir(self):
        for x in os.listdir(self.tdir):
            x = os.path.join(self.tdir, x)
            if os.path.isdir(x):
                shutil.rmtree(x)
            else:
                os.remove(x)
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

    def test_parse_ftc(self):
        def t(raw, *expected):
            a = []

            def c(k, v):
                a.append(str(k, 'utf-8'))
                a.append(str(v, 'utf-8'))

            parse_ftc(raw, c)
            self.ae(tuple(a), expected)

        t('a=b', 'a', 'b')
        t('a=b;', 'a', 'b')
        t('a1=b1;c=d;;', 'a1', 'b1', 'c', 'd')
        t('a1=b1;c=d;;e', 'a1', 'b1', 'c', 'd')
        t('a1=b1;c=d;;;1=1', 'a1', 'b1', 'c', 'd', '1', '1')

    def test_rsync_hashers(self):
        h = Hasher("xxh3-64")
        h.update(b'abcd')
        self.assertEqual(h.hexdigest(), '6497a96f53a89890')
        self.assertEqual(h.digest64(), 7248448420886124688)
        h128 = Hasher("xxh3-128")
        h128.update(b'abcd')
        self.assertEqual(h128.hexdigest(), '8d6b60383dfa90c21be79eecd1b1353d')

    @contextmanager
    def run_kitten(self, cmd, home_dir='', allow=True, cwd=''):
        cwd = cwd or self.kitten_cwd or self.tdir
        cmd = [kitten_exe(), 'transfer'] + (['--direction=receive'] if self.direction_receive else []) + cmd
        env = {'PWD': cwd}
        env['HOME'] = home_dir or self.kitten_home or self.tdir
        with set_paths(home=self.kitty_home, cwd=self.kitty_cwd):
            pty = TransferPTY(cmd, cwd=cwd, allow=allow, env=env)
            i = 10
            while i > 0 and not pty.screen_contents().strip():
                pty.process_input_from_child()
                i -= 1
            yield pty

    def basic_transfer_tests(self):
        src = os.path.join(self.tdir, 'src')
        self.src_data = os.urandom(11113)
        with open(src, 'wb') as s:
            s.write(self.src_data)
        dest = os.path.join(self.tdir, 'dest')
        with self.run_kitten([src, dest], allow=False) as pty:
            pty.wait_till_child_exits(require_exit_code=1)
        self.assertFalse(os.path.exists(dest))

        def single_file(*cmd):
            with self.run_kitten(list(cmd) + [src, dest]) as pty:
                pty.wait_till_child_exits(require_exit_code=0)
            with open(dest, 'rb') as f:
                self.assertEqual(self.src_data, f.read())

        single_file()
        single_file()
        single_file('--transmit-deltas')
        with open(dest, 'wb') as d:
            d.write(os.urandom(1023))
        single_file('--transmit-deltas')
        os.remove(dest)
        single_file('--transmit-deltas')
        single_file('--compress=never')
        single_file('--compress=always')
        single_file('--transmit-deltas', '--compress=never')

        def multiple_files(*cmd):
            src = os.path.join(self.tdir, 'msrc')
            dest = os.path.join(self.tdir, 'mdest')
            if os.path.exists(src):
                shutil.rmtree(src)
            os.mkdir(src)
            os.makedirs(dest, exist_ok=True)

            expected = {}
            Entry = namedtuple('Entry', 'relpath mtime mode nlink')

            def entry(path, base=src):
                st = os.stat(path, follow_symlinks=False)
                mtime = st.st_mtime_ns
                if stat.S_ISDIR(st.st_mode):
                    mtime = 0  # mtime is flaky for dirs on CI even empty ones
                return Entry(os.path.relpath(path, base), mtime, oct(st.st_mode), st.st_nlink)

            def se(path):
                e = entry(path)
                expected[e.relpath] = e

            b = Path(src)
            with open(b / 'simple', 'wb') as f:
                f.write(os.urandom(1317))
                os.fchmod(f.fileno(), 0o766)
            os.link(f.name, b / 'hardlink')
            os.utime(f.name, (1.3, 1.3))
            se(f.name)
            se(str(b/'hardlink'))
            os.mkdir(b / 'empty')
            se(str(b/'empty'))
            s = b / 'sub'
            os.mkdir(s)
            with open(s / 'reg', 'wb') as f:
                f.write(os.urandom(113))
            os.utime(f.name, (1171.3, 1171.3))
            se(f.name)
            se(str(s))
            os.symlink('/', b/'abssym')
            os.utime(b/'abssym', (1234.5, 1234.5), follow_symlinks=False)
            se(b/'abssym')
            os.symlink('sub/reg', b/'sym')
            os.utime(b/'sym', (6789.1, 6789.1), follow_symlinks=False)
            se(b/'sym')

            with self.run_kitten(list(cmd) + [src, dest]) as pty:
                pty.wait_till_child_exits(require_exit_code=0)

            actual = {}
            def de(path):
                e = entry(path, os.path.join(dest, os.path.basename(src)))
                if e.relpath != '.':
                    actual[e.relpath] = e

            for dirpath, dirnames, filenames in os.walk(dest):
                for x in dirnames:
                    de(os.path.join(dirpath, x))
                for x in filenames:
                    de(os.path.join(dirpath, x))

            self.assertEqual(expected, actual)

            for key, e in expected.items():
                ex = os.path.join(src, key)
                ax = os.path.join(dest, os.path.basename(src), key)
                if os.path.islink(ex):
                    self.ae(os.readlink(ex), os.readlink(ax))
                elif os.path.isfile(ex):
                    with open(ex, 'rb') as ef, open(ax, 'rb') as af:
                        self.assertEqual(ef.read(), af.read())

        multiple_files()
        multiple_files('--compress=always')
        self.clean_tdir()
        multiple_files('--transmit-deltas')
        multiple_files('--transmit-deltas')

    def setup_dirs(self):
        self.clean_tdir()
        self.kitty_home = os.path.join(self.tdir, 'kitty-home')
        self.kitty_cwd = os.path.join(self.tdir, 'kitty-cwd')
        self.kitten_home = os.path.join(self.tdir, 'kitten-home')
        self.kitten_cwd = os.path.join(self.tdir, 'kitten-cwd')
        tuple(map(os.mkdir, (self.kitty_home, self.kitty_cwd, self.kitten_home, self.kitten_cwd)))

    def create_src(self, base):
        src = os.path.join(base, 'src')
        with open(src, 'wb') as s:
            s.write(self.src_data)
        return src

    def mirror_test(self, src, dest, prefix=''):
        self.create_src(src)
        os.symlink('/', os.path.join(src, 'sym'))
        os.mkdir(os.path.join(src, 'sub'))
        os.link(os.path.join(src, 'src'), os.path.join(src, 'sub', 'hardlink'))
        with self.run_kitten(['--mode=mirror', f'{prefix}src', f'{prefix}sym', f'{prefix}sub']) as pty:
            pty.wait_till_child_exits(require_exit_code=0)
        os.remove(os.path.join(dest, 'src'))
        os.remove(os.path.join(dest, 'sym'))
        shutil.rmtree(os.path.join(dest, 'sub'))

    def test_transfer_receive(self):
        self.direction_receive = True
        self.basic_transfer_tests()

        self.setup_dirs()
        self.create_src(self.kitty_home)

        # dir expansion with single transfer
        with self.run_kitten(['~/src', '~/src']) as pty:
            pty.wait_till_child_exits(require_exit_code=0)
        os.remove(os.path.join(self.kitten_home, 'src'))

        with self.run_kitten(['src', 'src']) as pty:
            pty.wait_till_child_exits(require_exit_code=0)
        os.remove(os.path.join(self.kitten_cwd, 'src'))

        # dir expansion with multiple transfers
        os.symlink('/', os.path.join(self.kitty_home, 'sym'))
        with self.run_kitten(['~/src', '~/sym', '~']) as pty:
            pty.wait_till_child_exits(require_exit_code=0)
        os.remove(os.path.join(self.kitten_home, 'src'))
        os.remove(os.path.join(self.kitten_home, 'sym'))

        with self.run_kitten(['src', 'sym', '.']) as pty:
            pty.wait_till_child_exits(require_exit_code=0)
        os.remove(os.path.join(self.kitten_cwd, 'src'))
        os.remove(os.path.join(self.kitten_cwd, 'sym'))

        # mirroring
        self.setup_dirs()
        self.mirror_test(self.kitty_home, self.kitten_home)

    def test_transfer_send(self):
        self.basic_transfer_tests()
        src = os.path.join(self.tdir, 'src')
        with open(src, 'wb') as s:
            s.write(self.src_data)

        self.setup_dirs()
        self.create_src(self.kitten_home)

        # dir expansion with single transfer
        with self.run_kitten(['~/src', '~/src']) as pty:
            pty.wait_till_child_exits(require_exit_code=0)
        os.remove(os.path.join(self.kitty_home, 'src'))

        self.create_src(self.kitten_cwd)
        with self.run_kitten(['src', 'src']) as pty:
            pty.wait_till_child_exits(require_exit_code=0)
        os.remove(os.path.join(self.kitty_home, 'src'))

        # dir expansion with multiple transfers
        os.symlink('/', os.path.join(self.kitten_home, 'sym'))
        with self.run_kitten(['~/src', '~/sym', '~']) as pty:
            pty.wait_till_child_exits(require_exit_code=0)
        os.remove(os.path.join(self.kitty_home, 'src'))
        os.remove(os.path.join(self.kitty_home, 'sym'))

        os.symlink('/', os.path.join(self.kitten_cwd, 'sym'))
        with self.run_kitten(['src', 'sym', '.']) as pty:
            pty.wait_till_child_exits(require_exit_code=0)
        os.remove(os.path.join(self.kitty_home, 'src'))
        os.remove(os.path.join(self.kitty_home, 'sym'))

        # mirroring
        self.setup_dirs()
        self.mirror_test(self.kitten_home, self.kitty_home, prefix='~/')
