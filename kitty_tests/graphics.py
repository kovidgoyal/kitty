#!/usr/bin/env python
# License: GPL v3 Copyright: 2016, Kovid Goyal <kovid at kovidgoyal.net>

import os
import random
import tempfile
import time
import unittest
import zlib
from contextlib import suppress
from dataclasses import dataclass
from io import BytesIO

from kitty.fast_data_types import base64_decode, base64_encode, has_avx2, has_sse4_2, load_png_data, shm_unlink, shm_write, test_xor64

from . import BaseTest, parse_bytes

try:
    from PIL import Image
except ImportError:
    Image = None


def send_command(screen, cmd, payload=b''):
    cmd = '\033_G' + cmd
    if payload:
        if isinstance(payload, str):
            payload = payload.encode('utf-8')
        payload = base64_encode(payload).decode('ascii')
        cmd += ';' + payload
    cmd += '\033\\'
    c = screen.callbacks
    c.clear()
    parse_bytes(screen, cmd.encode('ascii'))
    return c.wtcbuf


def parse_response(res):
    if not res:
        return
    return res.decode('ascii').partition(';')[2].partition('\033')[0]


def parse_response_with_ids(res):
    if not res:
        return
    a, b = res.decode('ascii').split(';', 1)
    code = b.partition('\033')[0].split(':', 1)[0]
    a = a.split('G', 1)[1]
    return code, a


@dataclass(frozen=True)
class Response:
    code: str = 'OK'
    msg: str = ''
    image_id: int = 0
    image_number: int = 0
    frame_number: int = 0


def parse_full_response(res):
    if not res:
        return
    a, b = res.decode('ascii').split(';', 1)
    code = b.partition('\033')[0].split(':', 1)
    if len(code) == 1:
        code = code[0]
        msg = ''
    else:
        code, msg = code
    a = a.split('G', 1)[1]
    ans = {'code': code, 'msg': msg}
    for x in a.split(','):
        k, _, v = x.partition('=')
        ans[{'i': 'image_id', 'I': 'image_number', 'r': 'frame_number'}[k]] = int(v)
    return Response(**ans)


all_bytes = bytes(bytearray(range(256)))


def byte_block(sz):
    d, m = divmod(sz, len(all_bytes))
    return (all_bytes * d) + all_bytes[:m]


def load_helpers(self):
    s = self.create_screen()
    g = s.grman

    def pl(payload, **kw):
        kw.setdefault('i', 1)
        cmd = ','.join(f'{k}={v}' for k, v in kw.items())
        res = send_command(s, cmd, payload)
        return parse_response(res)

    def sl(payload, **kw):
        if isinstance(payload, str):
            payload = payload.encode('utf-8')
        data = kw.pop('expecting_data', payload)
        cid = kw.setdefault('i', 1)
        self.ae('OK', pl(payload, **kw))
        img = g.image_for_client_id(cid)
        self.assertIsNotNone(img, f'No image with id {cid} found')
        self.ae(img['client_id'], cid)
        self.ae(img['data'], data)
        if 's' in kw:
            self.ae((kw['s'], kw['v']), (img['width'], img['height']))
        self.ae(img['is_4byte_aligned'], kw.get('f') != 24)
        return img

    return s, g, pl, sl


def put_helpers(self, cw, ch, cols=10, lines=5):
    iid = 0

    def create_screen():
        s = self.create_screen(cols, lines, cell_width=cw, cell_height=ch)
        return s, 2 / s.columns, 2 / s.lines

    def put_cmd(
        z=0, num_cols=0, num_lines=0, x_off=0, y_off=0, width=0, height=0, cell_x_off=0,
        cell_y_off=0, placement_id=0, cursor_movement=0, unicode_placeholder=0, parent_id=0,
        parent_placement_id=0, offset_from_parent_x=0, offset_from_parent_y=0,
    ):
        return (
            f'z={z},c={num_cols},r={num_lines},x={x_off},y={y_off},w={width},h={height},'
            f'X={cell_x_off},Y={cell_y_off},p={placement_id},C={cursor_movement},'
            f'U={unicode_placeholder},P={parent_id},Q={parent_placement_id},'
            f'H={offset_from_parent_x},V={offset_from_parent_y}'
        )

    def put_image(screen, w, h, **kw):
        nonlocal iid
        iid += 1
        imgid = kw.pop('id', None) or iid
        no_id = kw.pop('no_id', False)
        a = kw.pop('a', 'T')
        if no_id:
            cmd = f'a={a},f=24,s=%d,v=%d,%s' % (w, h, put_cmd(**kw))
        else:
            cmd = f'a={a},f=24,i=%d,s=%d,v=%d,%s' % (imgid, w, h, put_cmd(**kw))
        data = b'x' * w * h * 3
        res = send_command(screen, cmd, data)
        return imgid, parse_response(res)

    def put_ref(screen, **kw):
        imgid = kw.pop('id', None) or iid
        cmd = 'a=p,i=%d,%s' % (imgid, put_cmd(**kw))
        return imgid, parse_response_with_ids(send_command(screen, cmd))

    def layers(screen, scrolled_by=0, xstart=-1, ystart=1):
        return screen.grman.update_layers(scrolled_by, xstart, ystart, dx, dy, screen.columns, screen.lines, cw, ch)

    def rect_eq(r, left, top, right, bottom):
        for side in 'left top right bottom'.split():
            a, b = r[side], locals()[side]
            if abs(a - b) > 0.0001:
                self.ae(a, b, 'the %s side is not equal' % side)

    s, dx, dy = create_screen()
    return s, dx, dy, put_image, put_ref, layers, rect_eq


def make_send_command(screen):
    def li(payload='abcdefghijkl'*3, s=4, v=3, f=24, a='f', i=1, **kw):
        if s:
            kw['s'] = s
        if v:
            kw['v'] = v
        if f:
            kw['f'] = f
        if i:
            kw['i'] = i
        kw['a'] = a
        cmd = ','.join(f'{k}={v}' for k, v in kw.items())
        res = send_command(screen, cmd, payload)
        return parse_full_response(res)
    return li


class TestGraphics(BaseTest):

    def test_xor_data(self):
        base_data = b'\x01' * 64
        key = b'\x02' * 64
        sizes = []
        if has_sse4_2:
            sizes.append(2)
        if has_avx2:
            sizes.append(3)
        sizes.append(0)

        def t(key, data, align_offset=0):
            expected = test_xor64(key, data, 1, 0)
            for which_function in sizes:
                actual = test_xor64(key, data, which_function, align_offset)
                self.ae(expected, actual, f'{align_offset=} {len(data)=}')

        t(key, b'')

        for base in (b'abc', base_data):
            for extra in range(len(base_data)):
                for align_offset in range(64):
                    data = base + base_data[:extra]
                    t(key, data, align_offset)

    def test_disk_cache(self):
        s = self.create_screen()
        dc = s.grman.disk_cache
        dc.small_hole_threshold = 0
        data = {}

        def key_as_bytes(key):
            if isinstance(key, int):
                key = str(key)
            if isinstance(key, str):
                key = key.encode('utf-8')
            return bytes(key)

        def add(key, val):
            bkey = key_as_bytes(key)
            data[key] = key_as_bytes(val)
            dc.add(bkey, data[key])

        def remove(key):
            bkey = key_as_bytes(key)
            data.pop(key, None)
            return dc.remove(bkey)

        def check_data():
            for key, val in data.items():
                self.ae(dc.get(key_as_bytes(key)), val)

        def reset(small_hole_threshold=0, defrag_factor=2):
            nonlocal dc, data, s
            s = self.create_screen()
            dc = s.grman.disk_cache
            dc.small_hole_threshold = small_hole_threshold
            dc.defrag_factor = defrag_factor
            data = {}

        holes_to_create = 2, 4, 6, 8
        for i in range(25):
            self.assertIsNone(add(i, f'{i}' * i))
            if i <= max(holes_to_create):
                # We wait here to ensure data is written in order, otherwise the
                # holes test below can fail
                self.assertTrue(dc.wait_for_write())

        self.assertEqual(dc.total_size, sum(map(len, data.values())))
        self.assertTrue(dc.wait_for_write())
        check_data()
        sz = dc.size_on_disk()
        self.assertEqual(sz, sum(map(len, data.values())))
        self.assertFalse(dc.holes())
        holes = set()
        for x in holes_to_create:
            remove(x)
            holes.add(x)
            check_data()
            self.assertRaises(KeyError, dc.get, key_as_bytes(x))
            self.assertEqual(sz, dc.size_on_disk())
            self.assertEqual(holes, {x[1] for x in dc.holes()})
        self.assertEqual(sz, dc.size_on_disk())
        # fill holes largest first to ensure small one doesn't go into large accidentally causing fragmentation
        for i, x in enumerate(sorted(holes, reverse=True)):
            x = 'ABCDEFGH'[i] * x
            add(x, x)
            self.assertTrue(dc.wait_for_write())
            check_data()
            holes.discard(len(x))
            self.assertEqual(holes, {x[1] for x in dc.holes()})
            self.assertEqual(sz, dc.size_on_disk(), f'Disk cache has unexpectedly grown from {sz} to {dc.size_on_disk} with data: {x!r}')
        check_data()
        dc.clear()
        st = time.monotonic()
        while dc.size_on_disk() and time.monotonic() - st < 2:
            time.sleep(0.001)
        self.assertEqual(dc.size_on_disk(), 0)

        data.clear()
        for i in range(25):
            self.assertIsNone(add(i, f'{i}' * i))
        dc.wait_for_write()
        check_data()

        before = dc.size_on_disk()
        while dc.total_size > before // 3:
            key = random.choice(tuple(data))
            self.assertTrue(remove(key))
        check_data()
        add('trigger defrag', 'XXX')
        dc.wait_for_write()
        self.assertLess(dc.size_on_disk(), before)
        check_data()
        dc.clear()

        st = time.monotonic()
        while dc.size_on_disk() and time.monotonic() - st < 20:
            time.sleep(0.01)
        self.assertEqual(dc.size_on_disk(), 0)
        for frame in range(32):
            add(f'1:{frame}', f'{frame:02d}' * 8)
        dc.wait_for_write()
        self.assertEqual(dc.size_on_disk(), 32 * 16)
        self.assertEqual(dc.num_cached_in_ram(), 0)
        num_in_ram = 0
        for frame in range(32):
            dc.get(key_as_bytes(f'1:{frame}'))
        self.assertEqual(dc.num_cached_in_ram(), num_in_ram)
        for frame in range(32):
            dc.get(key_as_bytes(f'1:{frame}'), True)
            num_in_ram += 1
        self.assertEqual(dc.num_cached_in_ram(), num_in_ram)

        def clear_predicate(key):
            return key.startswith(b'1:')

        dc.remove_from_ram(clear_predicate)
        self.assertEqual(dc.num_cached_in_ram(), 0)

        reset(small_hole_threshold=512, defrag_factor=20)
        self.assertIsNone(add(1, '1' * 1024))
        self.assertIsNone(add(2, '2' * 1024))
        dc.wait_for_write()
        sz = dc.size_on_disk()
        remove(1)
        self.ae(sz, dc.size_on_disk())
        self.ae({x[1] for x in dc.holes()}, {1024})
        self.assertIsNone(add(3, '3' * 800))
        dc.wait_for_write()
        self.assertFalse(dc.holes())
        self.ae(sz, dc.size_on_disk())
        self.assertIsNone(add(4, '4' * 100))
        sz += 100
        dc.wait_for_write()
        self.ae(sz, dc.size_on_disk())
        check_data()
        self.assertFalse(dc.holes())
        remove(4)
        self.assertFalse(dc.holes())
        self.assertIsNone(add(5, '5' * 10))
        sz += 10
        dc.wait_for_write()
        self.ae(sz, dc.size_on_disk())

        # test hole coalescing
        reset(defrag_factor=20)
        for i in range(1, 6):
            self.assertIsNone(add(i, str(i)*i))
            dc.wait_for_write()
        remove(2)
        remove(4)
        self.assertEqual(dc.holes(), {(1, 2), (6, 4)})
        remove(3)
        self.assertEqual(dc.holes(), {(1, 9)})

    def test_suppressing_gr_command_responses(self):
        s, g, pl, sl = load_helpers(self)
        self.ae(pl('abcd', s=10, v=10, q=1), 'ENODATA:Insufficient image data: 4 < 400')
        self.ae(pl('abcd', s=10, v=10, q=2), None)
        self.assertIsNone(pl('abcd', s=1, v=1, a='q', q=1))
        # Test chunked load
        self.assertIsNone(pl('abcd', s=2, v=2, m=1, q=1))
        self.assertIsNone(pl('efgh', m=1))
        self.assertIsNone(pl('ijkl', m=1))
        self.assertIsNone(pl('mnop', m=0))

        # errors
        self.assertIsNone(pl('abcd', s=2, v=2, m=1, q=1))
        self.ae(pl('mnop', m=0), 'ENODATA:Insufficient image data: 8 < 16')
        self.assertIsNone(pl('abcd', s=2, v=2, m=1, q=2))
        self.assertIsNone(pl('mnop', m=0))

        # frames
        s = self.create_screen()
        li = make_send_command(s)
        self.assertEqual(li().code, 'ENOENT')
        self.assertIsNone(li(q=2))
        self.assertIsNone(li(a='t', q=1))
        self.assertIsNone(li(payload='2' * 12, z=77, m=1, q=1))
        self.assertIsNone(li(payload='2' * 12, m=1))
        self.assertIsNone(li(payload='2' * 12))
        self.assertIsNone(li(payload='2' * 12, z=77, m=1, q=1))
        self.ae(li(payload='2' * 12).code, 'ENODATA')
        self.assertIsNone(li(payload='2' * 12, z=77, m=1, q=2))
        self.assertIsNone(li(payload='2' * 12))

    def test_load_images(self):
        s, g, pl, sl = load_helpers(self)
        self.assertEqual(g.disk_cache.total_size, 0)

        # Test load query
        self.ae(pl('abcd', s=1, v=1, a='q'), 'OK')
        self.ae(g.image_count, 0)

        # Test simple load
        for f in 32, 24:
            p = 'abc' + ('d' if f == 32 else '')
            img = sl(p, s=1, v=1, f=f)
            self.ae(bool(img['is_4byte_aligned']), f == 32)

        # Test chunked load
        self.assertIsNone(pl('abcd', s=2, v=2, m=1))
        self.assertIsNone(pl('efgh', m=1))
        self.assertIsNone(pl('ijkl', m=1))
        self.ae(pl('mnop', m=0), 'OK')
        img = g.image_for_client_id(1)
        self.ae(img['data'], b'abcdefghijklmnop')

        # Test interrupted and retried chunked load
        self.assertIsNone(pl('abcd', s=2, v=2, m=1))
        self.assertIsNone(pl('efgh', m=1))
        send_command(s, 'a=d')  # delete command should clear partial transfer
        self.assertIsNone(pl('abcd', s=2, v=2, m=1))
        self.assertIsNone(pl('efgh', m=1))
        self.assertIsNone(pl('ijkl', m=1))
        self.ae(pl('1234', m=0), 'OK')
        img = g.image_for_client_id(1)
        self.ae(img['data'], b'abcdefghijkl1234')

        random_data = byte_block(32 * 1024)
        sl(
            random_data,
            s=1024,
            v=8,
            expecting_data=random_data
        )

        # Test compression
        compressed_random_data = zlib.compress(random_data)
        sl(
            compressed_random_data,
            s=1024,
            v=8,
            o='z',
            expecting_data=random_data
        )

        # Test chunked + compressed
        b = len(compressed_random_data) // 2
        self.assertIsNone(pl(compressed_random_data[:b], s=1024, v=8, o='z', m=1))
        self.ae(pl(compressed_random_data[b:], m=0), 'OK')
        img = g.image_for_client_id(1)
        self.ae(img['data'], random_data)

        # Test loading from file
        def load_temp(prefix='tty-graphics-protocol-'):
            f = tempfile.NamedTemporaryFile(prefix=prefix)
            f.write(random_data), f.flush()
            sl(f.name, s=1024, v=8, t='f', expecting_data=random_data)
            self.assertTrue(os.path.exists(f.name))
            f.seek(0), f.truncate(), f.write(compressed_random_data), f.flush()
            sl(f.name, s=1024, v=8, t='t', o='z', expecting_data=random_data)
            return f

        f = load_temp()
        self.assertFalse(os.path.exists(f.name), f'Temp file at {f.name} was not deleted')
        with suppress(FileNotFoundError):
            f.close()
        f = load_temp('')
        self.assertTrue(os.path.exists(f.name), f'Temp file at {f.name} was deleted')
        f.close()

        # Test loading from POSIX SHM
        name = '/kitty-test-shm'
        shm_write(name, random_data)
        sl(name, s=1024, v=8, t='s', expecting_data=random_data)
        self.assertRaises(
            FileNotFoundError, shm_unlink, name
        )  # check that file was deleted
        s.reset()
        self.assertEqual(g.disk_cache.total_size, 0)

    @unittest.skipIf(Image is None, 'PIL not available, skipping PNG tests')
    def test_load_png(self):
        s, g, pl, sl = load_helpers(self)
        w, h = 5, 3
        rgba_data = byte_block(w * h * 4)
        img = Image.frombytes('RGBA', (w, h), rgba_data)
        rgb_data = img.convert('RGB').convert('RGBA').tobytes()
        self.assertEqual(g.disk_cache.total_size, 0)

        def png(mode='RGBA'):
            buf = BytesIO()
            i = img
            if mode != i.mode:
                i = img.convert(mode)
            i.save(buf, 'PNG')
            return buf.getvalue()

        for mode in 'RGBA RGB'.split():
            data = png(mode)
            sl(data, f=100, expecting_data=rgb_data if mode == 'RGB' else rgba_data)

        for m in 'LP':
            img = img.convert(m)
            rgba_data = img.convert('RGBA').tobytes()
            data = png(m)
        sl(data, f=100, expecting_data=rgba_data)

        self.ae(pl(b'a' * 20, f=100, S=20).partition(':')[0], 'EBADPNG')
        s.reset()
        self.assertEqual(g.disk_cache.total_size, 0)

    def test_load_png_simple(self):
        # 1x1 transparent PNG
        png_data = base64_decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+P+/HgAFhAJ/wlseKgAAAABJRU5ErkJggg==')
        expected = b'\x00\xff\xff\x7f'
        self.ae(load_png_data(png_data), (expected, 1, 1))
        s, g, pl, sl = load_helpers(self)
        sl(png_data, f=100, expecting_data=expected)
        # test error handling for loading bad png data
        self.assertRaisesRegex(ValueError, '[EBADPNG]', load_png_data, b'dsfsdfsfsfd')

    def test_gr_operations_with_numbers(self):
        s = self.create_screen()
        g = s.grman
        self.assertEqual(g.disk_cache.total_size, 0)

        def li(payload, **kw):
            cmd = ','.join(f'{k}={v}' for k, v in kw.items())
            res = send_command(s, cmd, payload)
            return parse_response_with_ids(res)

        code, ids = li('abc', s=1, v=1, f=24, I=1, i=3)
        self.ae(code, 'EINVAL')

        code, ids = li('abc', s=1, v=1, f=24, I=1)
        self.ae((code, ids), ('OK', 'i=1,I=1'))
        img = g.image_for_client_number(1)
        self.ae(img['client_number'], 1)
        self.ae(img['client_id'], 1)
        code, ids = li('abc', s=1, v=1, f=24, I=1)
        self.ae((code, ids), ('OK', 'i=2,I=1'))
        img = g.image_for_client_number(1)
        self.ae(img['client_number'], 1)
        self.ae(img['client_id'], 2)
        code, ids = li('abc', s=1, v=1, f=24, I=1)
        self.ae((code, ids), ('OK', 'i=3,I=1'))
        code, ids = li('abc', s=1, v=1, f=24, i=5)
        self.ae((code, ids), ('OK', 'i=5'))
        code, ids = li('abc', s=1, v=1, f=24, I=3)
        self.ae((code, ids), ('OK', 'i=4,I=3'))

        # Test chunked load with number
        self.assertIsNone(li('abcd', s=2, v=2, m=1, I=93))
        self.assertIsNone(li('efgh', m=1))
        self.assertIsNone(li('ijkx', m=1))
        self.ae(li('mnop', m=0), ('OK', 'i=6,I=93'))
        img = g.image_for_client_number(93)
        self.ae(img['data'], b'abcdefghijkxmnop')
        self.ae(img['client_id'], 6)

        # test put with number
        def put(**kw):
            cmd = ','.join(f'{k}={v}' for k, v in kw.items())
            cmd = 'a=p,' + cmd
            return parse_response_with_ids(send_command(s, cmd))

        code, idstr = put(c=2, r=2, I=93)
        self.ae((code, idstr), ('OK', 'i=6,I=93'))
        code, idstr = put(c=2, r=2, I=94)
        self.ae(code, 'ENOENT')

        # test delete with number
        def delete(ac='N', **kw):
            cmd = 'a=d'
            if ac:
                cmd += f',d={ac}'
            if kw:
                cmd += ',' + ','.join(f'{k}={v}' for k, v in kw.items())
            send_command(s, cmd)

        count = s.grman.image_count
        put(i=1), put(i=2), put(i=3), put(i=4), put(i=5)
        delete(I=94)
        self.ae(s.grman.image_count, count)
        delete(I=93)
        self.ae(s.grman.image_count, count - 1)
        delete(I=1)
        self.ae(s.grman.image_count, count - 2)
        cn = 1117
        li('abc', s=1, v=1, f=24, I=cn)
        first_id = g.image_for_client_number(cn)['internal_id']
        li('abc', s=1, v=1, f=24, I=cn)
        second_id = g.image_for_client_number(cn)['internal_id']
        self.assertNotEqual(first_id, second_id)
        count = s.grman.image_count
        delete(I=cn)
        self.ae(g.image_for_client_number(cn)['internal_id'], first_id)
        self.ae(s.grman.image_count, count - 1)
        s.reset()
        self.assertEqual(g.disk_cache.total_size, 0)

    def test_image_put(self):
        cw, ch = 10, 20
        s, dx, dy, put_image, put_ref, layers, rect_eq = put_helpers(self, cw, ch)
        self.ae(put_image(s, cw, ch)[1], 'OK')
        l0 = layers(s)
        self.ae(len(l0), 1)
        rect_eq(l0[0]['src_rect'], 0, 0, 1, 1)
        rect_eq(l0[0]['dest_rect'], -1, 1, -1 + dx, 1 - dy)
        self.ae(l0[0]['group_count'], 1)
        self.ae(s.cursor.x, 1), self.ae(s.cursor.y, 0)
        src_width, src_height = 3, 5
        iid, (code, idstr) = put_ref(s, num_cols=s.columns, num_lines=1, x_off=2, y_off=1, width=src_width, height=src_height,
                                     cell_x_off=3, cell_y_off=1, z=-1, placement_id=17)
        self.ae(idstr, f'i={iid},p=17')
        l2 = layers(s)
        self.ae(len(l2), 2)
        self.ae(l2[1], l0[0])
        rect_eq(l2[0]['src_rect'], 2 / 10, 1 / 20, (2 + 3) / 10, (1 + 5)/20)
        self.ae(l2[0]['group_count'], 2)
        left, top = -1 + dx + 3 * dx / cw, 1 - 1 * dy / ch
        right = -1 + (1 + s.columns) * dx
        bottom = 1 - dy
        rect_eq(l2[0]['dest_rect'], left, top, right, bottom)
        self.ae(s.cursor.x, 0), self.ae(s.cursor.y, 1)
        self.ae(put_image(s, 10, 20, cursor_movement=1)[1], 'OK')
        self.ae(s.cursor.x, 0), self.ae(s.cursor.y, 1)
        s.reset()
        self.assertEqual(s.grman.disk_cache.total_size, 0)
        self.ae(put_image(s, 2*cw, 2*ch, num_cols=3)[1], 'OK')
        self.ae((s.cursor.x, s.cursor.y), (3, 2))
        rect_eq(layers(s)[0]['dest_rect'], -1, 1, -1 + 3 * dx, 1 - 3*dy)

    def test_image_layer_grouping(self):
        cw, ch = 10, 20
        s, dx, dy, put_image, put_ref, layers, rect_eq = put_helpers(self, cw, ch)

        def group_counts():
            return tuple(x['group_count'] for x in layers(s))

        self.ae(put_image(s, 10, 20, id=1)[1], 'OK')
        self.ae(group_counts(), (1,))
        put_ref(s, id=1, num_cols=2, num_lines=1, placement_id=2)
        put_ref(s, id=1, num_cols=2, num_lines=1, placement_id=3, z=-2)
        put_ref(s, id=1, num_cols=2, num_lines=1, placement_id=4, z=-2)
        self.ae(group_counts(), (4, 3, 2, 1))
        self.ae(put_image(s, 8, 16, id=2, z=-1)[1], 'OK')
        self.ae(group_counts(), (2, 1, 1, 2, 1))

    def test_image_parents(self):
        cw, ch = 10, 20
        iw, ih = 10, 20
        s, dx, dy, put_image, put_ref, layers, rect_eq = put_helpers(self, cw, ch)

        def positions():
            ans = {}
            def x(x):
                return round(((x + 1)/2) * s.columns)
            def y(y):
                return int(((-y + 1)/2) * s.lines)

            for i in layers(s):
                d = i['dest_rect']
                ans[(i['image_id'], i['ref_id'])] = {'x': x(d['left']), 'y': y(d['top'])}
            return ans

        def p(x, y=0):
            return {'x':x, 'y': y}

        self.ae(put_image(s, iw, ih, id=1)[1], 'OK')
        self.ae(put_ref(s, id=1, placement_id=1), (1, ('OK', 'i=1,p=1')))
        pos = {(1, 1): p(0), (1, 2): p(1)}
        self.ae(positions(), pos)
        # check that adding a reference to a non-existent parent fails
        self.ae(put_ref(s, id=1, placement_id=33, parent_id=1, parent_placement_id=2), (1, ('ENOPARENT', 'i=1,p=33')))
        self.ae(put_ref(s, id=1, placement_id=33, parent_id=33), (1, ('ENOPARENT', 'i=1,p=33')))
        # check that we cannot add a reference that is its own parent
        self.ae(put_ref(s, id=1, placement_id=1, parent_id=1, parent_placement_id=1), (1, ('EINVAL', 'i=1,p=1')))

        self.ae(put_image(s, iw, ih, id=2)[1], 'OK')
        pos[(2,1)] = p(2)
        self.ae(positions(), pos)
        # Add two children to the first placement of img2
        before = s.cursor.x, s.cursor.y
        self.ae(put_ref(s, id=1, placement_id=2, parent_id=2, offset_from_parent_y=3), (1, ('OK', 'i=1,p=2')))
        self.ae(before, (s.cursor.x, s.cursor.y), 'Cursor must not move for child image')
        pos[(1,3)] = p(2, 3)
        self.ae(positions(), pos)
        self.ae(put_ref(s, id=2, placement_id=3, parent_id=2, offset_from_parent_y=4), (2, ('OK', 'i=2,p=3')))
        pos[(2,2)] = p(2, 4)
        self.ae(positions(), pos)
        # Add a grand child to the second child of img2
        self.ae(put_ref(s, id=2, placement_id=4, parent_id=2, parent_placement_id=3, offset_from_parent_x=-1), (2, ('OK', 'i=2,p=4')))
        pos[(2,3)] = p(pos[(2,2)]['x']-1, pos[(2,2)]['y'])
        self.ae(positions(), pos)
        # Check that creating a cycle is prevented
        self.ae(put_ref(s, id=2, placement_id=3, parent_id=2, parent_placement_id=4), (2, ('ECYCLE', 'i=2,p=3')))
        self.ae(positions(), pos)
        # Check that depth is limited
        for i in range(5, 12):
            q = put_ref(s, id=2, placement_id=i, parent_id=2, parent_placement_id=i-1, offset_from_parent_x=-1)[1][0]
            if q == 'ETOODEEP':
                break
            self.ae(q, 'OK')
        else:
            self.assertTrue(False, 'Failed to limit reference chain depth')
        # Check that deleting a parent removes all descendants
        send_command(s, 'a=d,d=i,i=2,p=3')
        pos.pop((2,3)), pos.pop((2,2))
        self.ae(positions(), pos)
        # Check that deleting a parent deletes all descendants and also removes
        # images with no remaining placements
        self.ae(put_ref(s, id=2, placement_id=3, parent_id=2, offset_from_parent_y=4), (2, ('OK', 'i=2,p=3')))
        pos[(2,11)] = p(2, 4)
        self.ae(positions(), pos)
        self.ae(put_image(s, iw, ih, id=3, placement_id=97, parent_id=2, parent_placement_id=3)[1], 'OK')
        pos[(3,1)] = p(2, 4)
        self.ae(positions(), pos)
        send_command(s, 'a=d,d=i,i=2')
        pos.pop((3,1)), pos.pop((2,11)), pos.pop((2,1)), pos.pop((1,3))
        self.ae(positions(), pos)
        # Check that virtual placements that try to be relative are rejected
        self.ae(put_ref(s, id=1, placement_id=11, parent_id=1, unicode_placeholder=1), (1, ('EINVAL', 'i=1,p=11')))
        # Check creation of children of a unicode placeholder based image
        s, dx, dy, put_image, put_ref, layers, rect_eq = put_helpers(self, cw, ch)
        put_image(s, 20, 20, num_cols=4, num_lines=2, unicode_placeholder=1, id=42)
        s.update_only_line_graphics_data()
        self.assertFalse(positions())  # the reference is virtual
        self.ae(put_ref(s, id=42, placement_id=11, parent_id=42, offset_from_parent_y=2, offset_from_parent_x=1), (42, ('OK', 'i=42,p=11')))
        self.assertFalse(positions())  # the reference is virtual without any cell images so the child is invisible
        s.apply_sgr("38;5;42")
        # These two characters will become one 2x1 ref.
        s.cursor.x = s.cursor.y = 1
        s.draw("\U0010EEEE\u0305\u0305\U0010EEEE\u0305\u030D")
        s.cursor.x = s.cursor.y = 0
        s.draw("\U0010EEEE\u0305\u0305\U0010EEEE\u0305\u030D")
        s.update_only_line_graphics_data()
        pos = {(1, 2): p(1, 2), (1, 3): p(0), (1, 4): p(1)}
        self.ae(positions(), pos)
        s.cursor.x = s.cursor.y = 0
        s.erase_in_display(0, False)
        s.update_only_line_graphics_data()
        self.assertFalse(positions())  # the reference is virtual without any cell images so the child is invisible
        s.cursor.x = s.cursor.y = 2
        s.draw("\U0010EEEE\u0305\u0305\U0010EEEE\u0305\u030D")
        s.update_only_line_graphics_data()
        self.ae(positions(), {(1, 5): {'x': 2, 'y': 2}, (1, 2): {'x': 3, 'y': 4}})

    def test_unicode_placeholders(self):
        # This test tests basic image placement using using unicode placeholders
        cw, ch = 10, 20
        s, dx, dy, put_image, put_ref, layers, rect_eq = put_helpers(self, cw, ch)
        # Upload two images.
        put_image(s, 20, 20, num_cols=4, num_lines=2, unicode_placeholder=1, id=42)
        put_image(s, 10, 20, num_cols=4, num_lines=2, unicode_placeholder=1, id=(42<<16) + (43<<8) + 44)
        # The references are virtual, so no visible refs yet.
        s.update_only_line_graphics_data()
        refs = layers(s)
        self.ae(len(refs), 0)
        # A reminder of row/column diacritics meaning (assuming 0-based):
        # \u0305 -> 0
        # \u030D -> 1
        # \u030E -> 2
        # \u0310 -> 3
        # Now print the placeholders for the first image.
        # Encode the id as an 8-bit color.
        s.apply_sgr("38;5;42")
        # These two characters will become one 2x1 ref.
        s.draw("\U0010EEEE\u0305\u0305\U0010EEEE\u0305\u030D")
        # These two characters will be two separate refs (not contiguous).
        s.draw("\U0010EEEE\u0305\u0305\U0010EEEE\u0305\u030E")
        s.cursor_move(4)
        s.update_only_line_graphics_data()
        refs = layers(s)
        self.ae(len(refs), 3)
        self.ae(refs[0]['src_rect'], {'left': 0.0, 'top': 0.0, 'right': 0.5, 'bottom': 0.5})
        self.ae(refs[1]['src_rect'], {'left': 0.0, 'top': 0.0, 'right': 0.25, 'bottom': 0.5})
        self.ae(refs[2]['src_rect'], {'left': 0.5, 'top': 0.0, 'right': 0.75, 'bottom': 0.5})
        # Erase the line.
        s.erase_in_line(2)
        # There must be 0 refs after the line is erased.
        s.update_only_line_graphics_data()
        refs = layers(s)
        self.ae(len(refs), 0)
        # Now test encoding IDs with the 24-bit color.
        # The first image, 1x1
        s.apply_sgr("38;2;0;0;42")
        s.draw("\U0010EEEE\u0305\u0305")
        # The second image, 2x1
        s.apply_sgr("38;2;42;43;44")
        s.draw("\U0010EEEE\u0305\u030D\U0010EEEE\u0305\u030E")
        s.cursor_move(2)
        s.update_only_line_graphics_data()
        refs = layers(s)
        self.ae(len(refs), 2)
        self.ae(refs[0]['src_rect'], {'left': 0.0, 'top': 0.0, 'right': 0.25, 'bottom': 0.5})
        # The second ref spans the whole widths of the second image because it's
        # fit to height and centered in a 4x2 box (specified in put_image).
        self.ae(refs[1]['src_rect'], {'left': 0.0, 'top': 0.0, 'right': 1.0, 'bottom': 0.5})
        # Erase the line.
        s.erase_in_line(2)
        # Now test implicit column numbers.
        # We will mix implicit and explicit column/row specifications, but they
        # will be combine into just two references.
        s.apply_sgr("38;5;42")
        # full row 0 of the first image
        s.draw("\U0010EEEE\u0305\u0305\U0010EEEE\u0305\U0010EEEE\U0010EEEE\u0305")
        # full row 1 of the first image
        s.draw("\U0010EEEE\u030D\U0010EEEE\U0010EEEE\U0010EEEE\u030D\u0310")
        s.cursor_move(8)
        s.update_only_line_graphics_data()
        refs = layers(s)
        self.ae(len(refs), 2)
        self.ae(refs[0]['src_rect'], {'left': 0.0, 'top': 0.0, 'right': 1.0, 'bottom': 0.5})
        self.ae(refs[1]['src_rect'], {'left': 0.0, 'top': 0.5, 'right': 1.0, 'bottom': 1.0})
        # Now reset the screen, the images should be erased.
        s.reset()
        refs = layers(s)
        self.ae(len(refs), 0)

    def test_unicode_placeholders_3rd_combining_char(self):
        # This test tests that we can use the 3rd diacritic for the most
        # significant byte
        cw, ch = 10, 20
        s, dx, dy, put_image, put_ref, layers, rect_eq = put_helpers(self, cw, ch)
        # Upload two images.
        put_image(s, 20, 20, num_cols=4, num_lines=2, unicode_placeholder=1, id=42)
        put_image(s, 20, 10, num_cols=4, num_lines=1, unicode_placeholder=1, id=(42 << 24) + 43)
        # This one will have id=43, which does not exist.
        s.apply_sgr("38;2;0;0;43")
        s.draw("\U0010EEEE\u0305\U0010EEEE\U0010EEEE\U0010EEEE")
        s.cursor_move(4)
        s.update_only_line_graphics_data()
        refs = layers(s)
        self.ae(len(refs), 0)
        s.erase_in_line(2)
        # This one will have id=42. We explicitly specify that the most
        # significant byte is 0 (third \u305). Specifying the zero byte like
        # this is not necessary but is correct.
        s.apply_sgr("38;2;0;0;42")
        s.draw("\U0010EEEE\u0305\u0305\u0305\U0010EEEE\u0305\u030D\u0305")
        # This is the second image.
        # \u059C -> 42
        s.apply_sgr("38;2;0;0;43")
        s.draw("\U0010EEEE\u0305\u0305\u059C\U0010EEEE\u0305\u030D\u059C")
        # Check that we can continue by using implicit row/column specification.
        s.draw("\U0010EEEE\u0305\U0010EEEE")
        s.cursor_move(6)
        s.update_only_line_graphics_data()
        refs = layers(s)
        self.ae(len(refs), 2)
        self.ae(refs[0]['src_rect'], {'left': 0.0, 'top': 0.0, 'right': 0.5, 'bottom': 0.5})
        self.ae(refs[1]['src_rect'], {'left': 0.0, 'top': 0.0, 'right': 1.0, 'bottom': 1.0})
        s.erase_in_line(2)
        # Now test the 8-bit color mode. Using the third diacritic, we can
        # specify 16 bits: the most significant byte and the least significant
        # byte.
        s.apply_sgr("38;5;42")
        s.draw("\U0010EEEE\u0305\u0305\u0305\U0010EEEE")
        s.apply_sgr("38;5;43")
        s.draw("\U0010EEEE\u0305\u0305\u059C\U0010EEEE\U0010EEEE\u0305\U0010EEEE")
        s.cursor_move(6)
        s.update_only_line_graphics_data()
        refs = layers(s)
        self.ae(len(refs), 2)
        self.ae(refs[0]['src_rect'], {'left': 0.0, 'top': 0.0, 'right': 0.5, 'bottom': 0.5})
        self.ae(refs[1]['src_rect'], {'left': 0.0, 'top': 0.0, 'right': 1.0, 'bottom': 1.0})

    def test_unicode_placeholders_multiple_placements(self):
        # Here we test placement specification via underline color.
        cw, ch = 10, 20
        s, dx, dy, put_image, put_ref, layers, rect_eq = put_helpers(self, cw, ch)
        put_image(s, 20, 20, num_cols=1, num_lines=1, placement_id=1, unicode_placeholder=1, id=42)
        put_ref(s, id=42, num_cols=2, num_lines=1, placement_id=22, unicode_placeholder=1)
        put_ref(s, id=42, num_cols=4, num_lines=2, placement_id=44, unicode_placeholder=1)
        # The references are virtual, so no visible refs yet.
        s.update_only_line_graphics_data()
        refs = layers(s)
        self.ae(len(refs), 0)
        # Draw the first row of each placement.
        s.apply_sgr("38;5;42")
        s.apply_sgr("58;5;1")
        s.draw("\U0010EEEE\u0305")
        s.apply_sgr("58;5;22")
        s.draw("\U0010EEEE\u0305\U0010EEEE\u0305")
        s.apply_sgr("58;5;44")
        s.draw("\U0010EEEE\u0305\U0010EEEE\u0305\U0010EEEE\u0305\U0010EEEE\u0305")
        s.update_only_line_graphics_data()
        refs = layers(s)
        self.ae(len(refs), 3)
        self.ae(refs[0]['src_rect'], {'left': 0.0, 'top': 0.0, 'right': 1.0, 'bottom': 1.5})
        self.ae(refs[1]['src_rect'], {'left': 0.0, 'top': 0.0, 'right': 1.0, 'bottom': 1.0})
        self.ae(refs[2]['src_rect'], {'left': 0.0, 'top': 0.0, 'right': 1.0, 'bottom': 0.5})

    def test_unicode_placeholders_scroll(self):
        # Here we test scrolling of a region. We'll draw an image spanning 8
        # rows and then scroll only the middle part of this image. Each
        # reference corresponds to one row.
        cw, ch = 5, 10
        s, dx, dy, put_image, put_ref, layers, rect_eq = put_helpers(self, cw, ch, lines=8)
        put_image(s, 5, 80, num_cols=1, num_lines=8, unicode_placeholder=1, id=42)
        s.apply_sgr("38;5;42")
        s.cursor_position(1, 0)
        s.draw("\U0010EEEE\u0305\n")
        s.cursor_position(2, 0)
        s.draw("\U0010EEEE\u030D\n")
        s.cursor_position(3, 0)
        s.draw("\U0010EEEE\u030E\n")
        s.cursor_position(4, 0)
        s.draw("\U0010EEEE\u0310\n")
        s.cursor_position(5, 0)
        s.draw("\U0010EEEE\u0312\n")
        s.cursor_position(6, 0)
        s.draw("\U0010EEEE\u033D\n")
        s.cursor_position(7, 0)
        s.draw("\U0010EEEE\u033E\n")
        s.cursor_position(8, 0)
        s.draw("\U0010EEEE\u033F")
        # Each line will contain a part of the image.
        s.update_only_line_graphics_data()
        refs = layers(s)
        refs = sorted(refs, key=lambda r: r['src_rect']['top'])
        self.ae(len(refs), 8)
        for i in range(8):
            self.ae(refs[i]['src_rect'], {'left': 0.0, 'top': 0.125*i, 'right': 1.0, 'bottom': 0.125*(i + 1)})
            self.ae(refs[i]['dest_rect']['top'], 1 - 0.25*i)
        # Now set margins to lines 3 and 6.
        s.set_margins(3, 6)  # 1-based indexing
        # Scroll two lines down (i.e. move lines 3..6 up).
        # Lines 3 and 4 will be erased.
        s.cursor_position(6, 0)
        s.index()
        s.index()
        s.update_only_line_graphics_data()
        refs = layers(s)
        refs = sorted(refs, key=lambda r: r['src_rect']['top'])
        self.ae(len(refs), 6)
        # Lines 1 and 2 are outside of the region, not scrolled.
        self.ae(refs[0]['src_rect'], {'left': 0.0, 'top': 0.0, 'right': 1.0, 'bottom': 0.125})
        self.ae(refs[0]['dest_rect']['top'], 1.0)
        self.ae(refs[1]['src_rect'], {'left': 0.0, 'top': 0.125*1, 'right': 1.0, 'bottom': 0.125*2})
        self.ae(refs[1]['dest_rect']['top'], 1.0 - 0.25*1)
        # Lines 3 and 4 are erased.
        # Lines 5 and 6 are now higher.
        self.ae(refs[2]['src_rect'], {'left': 0.0, 'top': 0.125*4, 'right': 1.0, 'bottom': 0.125*5})
        self.ae(refs[2]['dest_rect']['top'], 1.0 - 0.25*2)
        self.ae(refs[3]['src_rect'], {'left': 0.0, 'top': 0.125*5, 'right': 1.0, 'bottom': 0.125*6})
        self.ae(refs[3]['dest_rect']['top'], 1.0 - 0.25*3)
        # Lines 7 and 8 are outside of the region.
        self.ae(refs[4]['src_rect'], {'left': 0.0, 'top': 0.125*6, 'right': 1.0, 'bottom': 0.125*7})
        self.ae(refs[4]['dest_rect']['top'], 1.0 - 0.25*6)
        self.ae(refs[5]['src_rect'], {'left': 0.0, 'top': 0.125*7, 'right': 1.0, 'bottom': 0.125*8})
        self.ae(refs[5]['dest_rect']['top'], 1.0 - 0.25*7)
        # Now scroll three lines up (i.e. move lines 5..6 down).
        # Line 6 will be erased.
        s.cursor_position(3, 0)
        s.reverse_index()
        s.reverse_index()
        s.reverse_index()
        s.update_only_line_graphics_data()
        refs = layers(s)
        refs = sorted(refs, key=lambda r: r['src_rect']['top'])
        self.ae(len(refs), 5)
        # Lines 1 and 2 are outside of the region, not scrolled.
        self.ae(refs[0]['src_rect'], {'left': 0.0, 'top': 0.0, 'right': 1.0, 'bottom': 0.125})
        self.ae(refs[0]['dest_rect']['top'], 1.0)
        self.ae(refs[1]['src_rect'], {'left': 0.0, 'top': 0.125*1, 'right': 1.0, 'bottom': 0.125*2})
        self.ae(refs[1]['dest_rect']['top'], 1.0 - 0.25*1)
        # Lines 3, 4 and 6 are erased.
        # Line 5 is now lower.
        self.ae(refs[2]['src_rect'], {'left': 0.0, 'top': 0.125*4, 'right': 1.0, 'bottom': 0.125*5})
        self.ae(refs[2]['dest_rect']['top'], 1.0 - 0.25*5)
        # Lines 7 and 8 are outside of the region.
        self.ae(refs[3]['src_rect'], {'left': 0.0, 'top': 0.125*6, 'right': 1.0, 'bottom': 0.125*7})
        self.ae(refs[3]['dest_rect']['top'], 1.0 - 0.25*6)
        self.ae(refs[4]['src_rect'], {'left': 0.0, 'top': 0.125*7, 'right': 1.0, 'bottom': 0.125*8})
        self.ae(refs[4]['dest_rect']['top'], 1.0 - 0.25*7)

    def test_gr_scroll(self):
        cw, ch = 10, 20
        s, dx, dy, put_image, put_ref, layers, rect_eq = put_helpers(self, cw, ch)
        put_image(s, 10, 20, no_id=True)  # a one cell image at (0, 0)
        self.ae(len(layers(s)), 1)
        for i in range(s.lines):
            s.index()
        self.ae(len(layers(s)), 0), self.ae(s.grman.image_count, 1)
        for i in range(s.historybuf.ynum - 1):
            s.index()
            self.ae(len(layers(s)), 0), self.ae(s.grman.image_count, 1)
        s.index()
        self.ae(s.grman.image_count, 0)

        # Now test with margins
        s.reset()
        # Test images outside page area untouched
        put_image(s, cw, ch)  # a one cell image at (0, 0)
        for i in range(s.lines - 1):
            s.index()
        put_image(s, cw, ch)  # a one cell image at (0, bottom)
        s.set_margins(2, 4)  # 1-based indexing
        self.ae(s.grman.image_count, 2)
        for i in range(s.lines + s.historybuf.ynum):
            s.index()
            self.ae(s.grman.image_count, 2)
        for i in range(s.lines):  # ensure cursor is at top margin
            s.reverse_index()
        # Test clipped scrolling during index
        put_image(s, cw, 2*ch, z=-1, no_id=True)  # 1x2 cell image
        self.ae(s.grman.image_count, 3)
        self.ae(layers(s)[0]['src_rect'], {'left': 0.0, 'top': 0.0, 'right': 1.0, 'bottom': 1.0})
        s.index(), s.index()
        l0 = layers(s)
        self.ae(len(l0), 3)
        self.ae(layers(s)[0]['src_rect'],  {'left': 0.0, 'top': 0.5, 'right': 1.0, 'bottom': 1.0})
        s.index()
        self.ae(s.grman.image_count, 2)
        # Test clipped scrolling during reverse_index
        for i in range(s.lines):
            s.reverse_index()
        put_image(s, cw, 2*ch, z=-1, no_id=True)  # 1x2 cell image
        self.ae(s.grman.image_count, 3)
        self.ae(layers(s)[0]['src_rect'], {'left': 0.0, 'top': 0.0, 'right': 1.0, 'bottom': 1.0})
        while s.cursor.y != 1:
            s.reverse_index()
        s.reverse_index(), s.reverse_index()
        self.ae(layers(s)[0]['src_rect'], {'left': 0.0, 'top': 0.0, 'right': 1.0, 'bottom': 0.5})
        s.reverse_index()
        self.ae(s.grman.image_count, 2)
        s.reset()
        self.assertEqual(s.grman.disk_cache.total_size, 0)

    def test_gr_reset(self):
        cw, ch = 10, 20
        s, dx, dy, put_image, put_ref, layers, rect_eq = put_helpers(self, cw, ch)
        put_image(s, cw, ch)  # a one cell image at (0, 0)
        self.ae(len(layers(s)), 1)
        s.reset()
        self.ae(s.grman.image_count, 0)
        put_image(s, cw, ch)  # a one cell image at (0, 0)
        self.ae(s.grman.image_count, 1)
        for i in range(s.lines):
            s.index()
        s.reset()
        self.ae(s.grman.image_count, 1)

    def test_gr_delete(self):
        cw, ch = 10, 20
        s, dx, dy, put_image, put_ref, layers, rect_eq = put_helpers(self, cw, ch)

        def delete(ac=None, **kw):
            cmd = 'a=d'
            if ac:
                cmd += f',d={ac}'
            if kw:
                cmd += ',' + ','.join(f'{k}={v}' for k, v in kw.items())
            send_command(s, cmd)

        iid = put_image(s, cw, ch, a='t')[0]
        self.ae(s.grman.image_count, 1)
        delete('I', i=iid)
        self.ae(s.grman.image_count, 0)
        iid1 = put_image(s, cw, ch, a='t')[0]
        iid2 = put_image(s, cw, ch, a='t')[0]
        self.ae(s.grman.image_count, 2)
        delete('R', x=iid1, y=iid2)
        self.ae(s.grman.image_count, 0)

        put_image(s, cw, ch)
        delete()
        self.ae(s.grman.image_count, 1)
        self.ae(len(layers(s)), 0)
        delete('A')
        self.ae(s.grman.image_count, 1)
        s.reset()
        self.ae(s.grman.image_count, 0)
        put_image(s, cw, ch)
        self.ae(s.grman.image_count, 1)
        delete('A')
        self.ae(s.grman.image_count, 0)
        self.assertEqual(s.grman.disk_cache.total_size, 0)
        iid = put_image(s, cw, ch)[0]
        delete('I', i=iid, p=7)
        self.ae(s.grman.image_count, 1)
        delete('I', i=iid)
        self.ae(s.grman.image_count, 0)
        self.assertEqual(s.grman.disk_cache.total_size, 0)
        iid = put_image(s, cw, ch, placement_id=9)[0]
        delete('I', i=iid, p=9)
        self.ae(s.grman.image_count, 0)
        self.assertEqual(s.grman.disk_cache.total_size, 0)
        s.reset()
        put_image(s, cw, ch)
        put_image(s, cw, ch)
        delete('C')
        self.ae(s.grman.image_count, 2)
        s.cursor_position(1, 1)
        delete('C')
        self.ae(s.grman.image_count, 1)
        delete('P', x=2, y=1)
        self.ae(s.grman.image_count, 0)
        self.assertEqual(s.grman.disk_cache.total_size, 0)
        put_image(s, cw, ch, z=9)
        delete('Z', z=9)
        self.ae(s.grman.image_count, 0)
        put_image(s, cw, ch, id=1)
        put_image(s, cw, ch, id=2)
        put_image(s, cw, ch, id=3)
        delete('R', y=2)
        self.ae(s.grman.image_count, 1)
        delete('R', x=3, y=3)
        self.ae(s.grman.image_count, 0)
        self.assertEqual(s.grman.disk_cache.total_size, 0)

        # test put + delete + put
        iid = 999999
        self.ae(put_image(s, cw, ch, id=iid), (iid, 'OK'))
        self.ae(put_ref(s, id=iid), (iid, ('OK', f'i={iid}')))
        delete('i', i=iid)
        self.ae(s.grman.image_count, 1)
        self.ae(put_ref(s, id=iid), (iid, ('OK', f'i={iid}')))
        delete('I', i=iid)
        self.ae(put_ref(s, id=iid), (iid, ('ENOENT', f'i={iid}')))
        self.ae(s.grman.image_count, 0)
        self.assertEqual(s.grman.disk_cache.total_size, 0)

        # test delete but not free
        s.reset()
        iid = 9999999
        self.ae(put_image(s, cw, ch, id=iid), (iid, 'OK'))
        self.ae(put_ref(s, id=iid), (iid, ('OK', f'i={iid}')))
        self.ae(put_image(s, cw, ch, id=iid+1), (iid+1, 'OK'))
        self.ae(put_ref(s, id=iid+1), (iid+1, ('OK', f'i={iid+1}')))
        delete('i', i=iid)
        self.ae(s.grman.image_count, 2)
        delete('I', i=iid+1)
        self.ae(s.grman.image_count, 1)

    def test_animation_frame_loading(self):
        s = self.create_screen()
        g = s.grman
        li = make_send_command(s)

        def t(code='OK', image_id=1, frame_number=2, **kw):
            res = li(**kw)
            if code is not None:
                self.assertEqual(code, res.code, f'{code} != {res.code}: {res.msg}')
            if image_id is not None:
                self.assertEqual(image_id, res.image_id)
            if frame_number is not None:
                self.assertEqual(frame_number, res.frame_number)

        # test error on send frame for non-existent image
        self.assertEqual(li().code, 'ENOENT')

        # create image
        self.assertEqual(li(a='t').code, 'OK')
        self.assertEqual(g.disk_cache.total_size, 36)

        # simple new frame (width=4, height=3)
        self.assertIsNone(li(payload='2' * 12, z=77, m=1))
        self.assertIsNone(li(payload='2' * 12, z=77, m=1))
        t(payload='2' * 12, z=77)
        img = g.image_for_client_id(1)
        self.assertEqual(img['extra_frames'], ({'gap': 77, 'id': 2, 'data': b'2' * 36},))
        # test editing a frame
        t(payload='3' * 36, r=2)
        img = g.image_for_client_id(1)
        self.assertEqual(img['extra_frames'], ({'gap': 77, 'id': 2, 'data': b'3' * 36},))
        # test editing part of a frame
        t(payload='4' * 12, r=2, s=2, v=2)
        img = g.image_for_client_id(1)

        def expand(*rows):
            ans = []
            for r in rows:
                ans.append(''.join(x * 3 for x in str(r)))
            return ''.join(ans).encode('ascii')

        self.assertEqual(img['extra_frames'], ({'gap': 77, 'id': 2, 'data': expand(4433, 4433, 3333)},))
        t(payload='5' * 12, r=2, s=2, v=2, x=1, y=1)
        img = g.image_for_client_id(1)
        self.assertEqual(img['extra_frames'], ({'gap': 77, 'id': 2, 'data': expand(4433, 4553, 3553)},))
        t(payload='3' * 36, r=2)
        img = g.image_for_client_id(1)
        self.assertEqual(img['extra_frames'], ({'gap': 77, 'id': 2, 'data': b'3' * 36},))
        # test loading from previous frame
        t(payload='4' * 12, c=2, s=2, v=2, z=101, frame_number=3)
        img = g.image_for_client_id(1)
        self.assertEqual(img['extra_frames'], (
            {'gap': 77, 'id': 2, 'data': b'3' * 36},
            {'gap': 101, 'id': 3, 'data': b'444444333333444444333333333333333333'},
        ))
        # test changing gaps
        img = g.image_for_client_id(1)
        self.assertEqual(img['root_frame_gap'], 0)
        self.assertIsNone(li(a='a', i=1, r=1, z=13))
        img = g.image_for_client_id(1)
        self.assertEqual(img['root_frame_gap'], 13)
        self.assertIsNone(li(a='a', i=1, r=2, z=43))
        img = g.image_for_client_id(1)
        self.assertEqual(img['extra_frames'][0]['gap'], 43)
        # test changing current frame
        img = g.image_for_client_id(1)
        self.assertEqual(img['current_frame_index'], 0)
        self.assertIsNone(li(a='a', i=1, c=2))
        img = g.image_for_client_id(1)
        self.assertEqual(img['current_frame_index'], 1)

        # test delete of frames
        t(payload='5' * 36, frame_number=4)
        img = g.image_for_client_id(1)
        self.assertEqual(img['extra_frames'], (
            {'gap': 43, 'id': 2, 'data': b'3' * 36},
            {'gap': 101, 'id': 3, 'data': b'444444333333444444333333333333333333'},
            {'gap': 40, 'id': 4, 'data': b'5' * 36},
        ))
        self.assertEqual(img['current_frame_index'], 1)
        self.assertIsNone(li(a='d', d='f', i=1, r=1))
        img = g.image_for_client_id(1)
        self.assertEqual(img['current_frame_index'], 0)
        self.assertEqual(img['data'], b'3' * 36)
        self.assertEqual(img['extra_frames'], (
            {'gap': 101, 'id': 3, 'data': b'444444333333444444333333333333333333'},
            {'gap': 40, 'id': 4, 'data': b'5' * 36},
        ))
        self.assertIsNone(li(a='a', i=1, c=3))
        img = g.image_for_client_id(1)
        self.assertEqual(img['current_frame_index'], 2)
        self.assertIsNone(li(a='d', d='f', i=1, r=2))
        img = g.image_for_client_id(1)
        self.assertEqual(img['current_frame_index'], 1)
        self.assertEqual(img['data'], b'3' * 36)
        self.assertEqual(img['extra_frames'], (
            {'gap': 40, 'id': 4, 'data': b'5' * 36},
        ))
        self.assertIsNone(li(a='d', d='f', i=1))
        img = g.image_for_client_id(1)
        self.assertEqual(img['current_frame_index'], 0)
        self.assertEqual(img['data'], b'5' * 36)
        self.assertFalse(img['extra_frames'])
        self.assertIsNone(li(a='d', d='f', i=1))
        img = g.image_for_client_id(1)
        self.assertEqual(img['data'], b'5' * 36)
        self.ae(g.image_count, 1)
        self.assertIsNone(li(a='d', d='F', i=1))
        self.ae(g.image_count, 0)
        self.assertEqual(g.disk_cache.total_size, 0)

        # test frame composition
        self.assertEqual(li(a='t').code, 'OK')
        self.assertEqual(g.disk_cache.total_size, 36)
        t(payload='2' * 36)
        t(payload='3' * 36, frame_number=3)
        img = g.image_for_client_id(1)
        self.assertEqual(img['extra_frames'], (
            {'gap': 40, 'id': 2, 'data': b'2' * 36},
            {'gap': 40, 'id': 3, 'data': b'3' * 36},
        ))
        self.assertEqual(li(a='c', i=11).code, 'ENOENT')
        self.assertEqual(li(a='c', i=1, r=1, c=2).code, 'OK')
        img = g.image_for_client_id(1)
        self.assertEqual(img['extra_frames'], (
            {'gap': 40, 'id': 2, 'data': b'abcdefghijkl'*3},
            {'gap': 40, 'id': 3, 'data': b'3' * 36},
        ))
        self.assertEqual(li(a='c', i=1, r=2, c=3, w=1, h=2, x=1, y=1).code, 'OK')
        img = g.image_for_client_id(1)
        self.assertEqual(img['extra_frames'], (
            {'gap': 40, 'id': 2, 'data': b'abcdefghijkl'*3},
            {'gap': 40, 'id': 3, 'data': b'3' * 12 + (b'333abc' + b'3' * 6) * 2},
        ))

    def test_graphics_quota_enforcement(self):
        s = self.create_screen()
        g = s.grman
        g.storage_limit = 36*2
        li = make_send_command(s)
        # test quota for simple images
        self.assertEqual(li(a='T').code, 'OK')
        self.assertEqual(li(a='T', i=2).code, 'OK')
        self.assertEqual(g.disk_cache.total_size, g.storage_limit)
        self.assertEqual(g.image_count, 2)
        self.assertEqual(li(a='T', i=3).code, 'OK')
        self.assertEqual(g.disk_cache.total_size, g.storage_limit)
        self.assertEqual(g.image_count, 2)
        # test quota for frames
        for i in range(8):
            self.assertEqual(li(payload=f'{i}' * 36, i=2).code, 'OK')
        self.assertEqual(li(payload='x' * 36, i=2).code, 'ENOSPC')
        # test editing should not trigger quota
        self.assertEqual(li(payload='4' * 12, r=2, s=2, v=2, i=2).code, 'OK')

        s.reset()
        self.ae(g.image_count, 0)
        self.assertEqual(g.disk_cache.total_size, 0)

    @unittest.skipIf(Image is None, 'PIL not available, skipping PNG tests')
    def test_cached_rgba_conversion(self):
        from kitty.render_cache import ImageRenderCacheForTesting
        w, h = 5, 3
        rgba_data = byte_block(w * h * 4)
        img = Image.frombytes('RGBA', (w, h), rgba_data)
        buf = BytesIO()
        img.save(buf, 'PNG')
        png_data = buf.getvalue()
        with tempfile.TemporaryDirectory() as cache_path:
            irc = ImageRenderCacheForTesting(cache_path)
            srcs, outputs = [], []
            for i in range(2 * irc.max_entries):
                with open(os.path.join(cache_path, f'{i}.png'), 'wb') as f:
                    f.write(png_data)
                srcs.append(f.name)
                outputs.append(irc.render(f.name))
                entries = list(irc.entries())
                self.assertLessEqual(len(entries), irc.max_entries)
            self.ae(irc.num_of_renders, len(outputs))
            remaining_outputs = outputs[-irc.max_entries:]
            for x in remaining_outputs:
                self.assertTrue(os.path.exists(x))
            for x in outputs[:-irc.max_entries]:
                self.assertFalse(os.path.exists(x))
            self.assertLess(os.path.getmtime(remaining_outputs[0]), os.path.getmtime(remaining_outputs[1]))
            remaining_srcs = srcs[-irc.max_entries:]
            self.ae(irc.render(remaining_srcs[0]), remaining_outputs[0])
            self.ae(irc.num_of_renders, len(outputs))
            self.assertGreater(os.path.getmtime(remaining_outputs[0]), os.path.getmtime(remaining_outputs[1]))

            width, height, fd = irc(remaining_srcs[-1])
            with open(fd, 'rb') as f:
                self.ae((width, height), (w, h))
                f.seek(8)
                self.ae(rgba_data, f.read())
