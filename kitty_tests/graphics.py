#!/usr/bin/env python3
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2016, Kovid Goyal <kovid at kovidgoyal.net>

import os
import random
import tempfile
import time
import unittest
import zlib
from base64 import standard_b64decode, standard_b64encode
from io import BytesIO
from itertools import cycle
from typing import NamedTuple

from kitty.constants import cache_dir
from kitty.fast_data_types import (
    load_png_data, parse_bytes, shm_unlink, shm_write, xor_data
)

from . import BaseTest

try:
    from PIL import Image
except ImportError:
    Image = None


def send_command(screen, cmd, payload=b''):
    cmd = '\033_G' + cmd
    if payload:
        if isinstance(payload, str):
            payload = payload.encode('utf-8')
        payload = standard_b64encode(payload).decode('ascii')
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


class Response(NamedTuple):
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
        cmd = ','.join('%s=%s' % (k, v) for k, v in kw.items())
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


def put_helpers(self, cw, ch):
    iid = 0

    def create_screen():
        s = self.create_screen(10, 5, cell_width=cw, cell_height=ch)
        return s, 2 / s.columns, 2 / s.lines

    def put_cmd(
            z=0, num_cols=0, num_lines=0, x_off=0, y_off=0, width=0,
            height=0, cell_x_off=0, cell_y_off=0, placement_id=0,
            cursor_movement=0
    ):
        return 'z=%d,c=%d,r=%d,x=%d,y=%d,w=%d,h=%d,X=%d,Y=%d,p=%d,C=%d' % (
            z, num_cols, num_lines, x_off, y_off, width, height, cell_x_off,
            cell_y_off, placement_id, cursor_movement
        )

    def put_image(screen, w, h, **kw):
        nonlocal iid
        iid += 1
        imgid = kw.pop('id', None) or iid
        cmd = 'a=T,f=24,i=%d,s=%d,v=%d,%s' % (imgid, w, h, put_cmd(**kw))
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
        cmd = ','.join('%s=%s' % (k, v) for k, v in kw.items())
        res = send_command(screen, cmd, payload)
        return parse_full_response(res)
    return li


class TestGraphics(BaseTest):

    def setUp(self):
        cache_dir.set_override(tempfile.mkdtemp())

    def tearDown(self):
        os.rmdir(cache_dir())
        cache_dir.clear_override()

    def test_xor_data(self):

        def xor(skey, data):
            ckey = cycle(bytearray(skey))
            return bytes(bytearray(k ^ d for k, d in zip(ckey, bytearray(data))))

        base_data = os.urandom(64)
        key = os.urandom(len(base_data))
        for base in (b'', base_data):
            for extra in range(len(base_data)):
                data = base + base_data[:extra]
                self.assertEqual(xor_data(key, data), xor(key, data))

    def test_disk_cache(self):
        s = self.create_screen()
        dc = s.grman.disk_cache
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

        for i in range(25):
            self.assertIsNone(add(i, f'{i}' * i))

        self.assertEqual(dc.total_size, sum(map(len, data.values())))
        self.assertTrue(dc.wait_for_write())
        check_data()
        sz = dc.size_on_disk()
        self.assertEqual(sz, sum(map(len, data.values())))
        for x in (2, 4, 6, 8):
            remove(x)
            check_data()
            self.assertRaises(KeyError, dc.get, key_as_bytes(x))
            self.assertEqual(sz, dc.size_on_disk())
        for x in ('xy', 'C'*4, 'B'*6, 'A'*8):
            add(x, x)
            self.assertTrue(dc.wait_for_write())
            self.assertEqual(sz, dc.size_on_disk())
            check_data()
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

    def test_suppressing_gr_command_responses(self):
        s, g, l, sl = load_helpers(self)
        self.ae(l('abcd', s=10, v=10, q=1), 'ENODATA:Insufficient image data: 4 < 400')
        self.ae(l('abcd', s=10, v=10, q=2), None)
        self.assertIsNone(l('abcd', s=1, v=1, a='q', q=1))
        # Test chunked load
        self.assertIsNone(l('abcd', s=2, v=2, m=1, q=1))
        self.assertIsNone(l('efgh', m=1))
        self.assertIsNone(l('ijkl', m=1))
        self.assertIsNone(l('mnop', m=0))

        # errors
        self.assertIsNone(l('abcd', s=2, v=2, m=1, q=1))
        self.ae(l('mnop', m=0), 'ENODATA:Insufficient image data: 8 < 16')
        self.assertIsNone(l('abcd', s=2, v=2, m=1, q=2))
        self.assertIsNone(l('mnop', m=0))

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
        s, g, l, sl = load_helpers(self)
        self.assertEqual(g.disk_cache.total_size, 0)

        # Test load query
        self.ae(l('abcd', s=1, v=1, a='q'), 'OK')
        self.ae(g.image_count, 0)

        # Test simple load
        for f in 32, 24:
            p = 'abc' + ('d' if f == 32 else '')
            img = sl(p, s=1, v=1, f=f)
            self.ae(bool(img['is_4byte_aligned']), f == 32)

        # Test chunked load
        self.assertIsNone(l('abcd', s=2, v=2, m=1))
        self.assertIsNone(l('efgh', m=1))
        self.assertIsNone(l('ijkl', m=1))
        self.ae(l('mnop', m=0), 'OK')
        img = g.image_for_client_id(1)
        self.ae(img['data'], b'abcdefghijklmnop')

        # Test compression
        random_data = byte_block(3 * 1024)
        compressed_random_data = zlib.compress(random_data)
        sl(
            compressed_random_data,
            s=24,
            v=32,
            o='z',
            expecting_data=random_data
        )

        # Test chunked + compressed
        b = len(compressed_random_data) // 2
        self.assertIsNone(l(compressed_random_data[:b], s=24, v=32, o='z', m=1))
        self.ae(l(compressed_random_data[b:], m=0), 'OK')
        img = g.image_for_client_id(1)
        self.ae(img['data'], random_data)

        # Test loading from file
        f = tempfile.NamedTemporaryFile()
        f.write(random_data), f.flush()
        sl(f.name, s=24, v=32, t='f', expecting_data=random_data)
        self.assertTrue(os.path.exists(f.name))
        f.seek(0), f.truncate(), f.write(compressed_random_data), f.flush()
        sl(f.name, s=24, v=32, t='t', o='z', expecting_data=random_data)
        self.assertRaises(
            FileNotFoundError, f.close
        )  # check that file was deleted

        # Test loading from POSIX SHM
        name = '/kitty-test-shm'
        shm_write(name, random_data)
        sl(name, s=24, v=32, t='s', expecting_data=random_data)
        self.assertRaises(
            FileNotFoundError, shm_unlink, name
        )  # check that file was deleted
        s.reset()
        self.assertEqual(g.disk_cache.total_size, 0)

    @unittest.skipIf(Image is None, 'PIL not available, skipping PNG tests')
    def test_load_png(self):
        s, g, l, sl = load_helpers(self)
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

        self.ae(l(b'a' * 20, f=100, S=20).partition(':')[0], 'EBADPNG')
        s.reset()
        self.assertEqual(g.disk_cache.total_size, 0)

    def test_load_png_simple(self):
        # 1x1 transparent PNG
        png_data = standard_b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+P+/HgAFhAJ/wlseKgAAAABJRU5ErkJggg==')
        expected = b'\x00\xff\xff\x7f'
        self.ae(load_png_data(png_data), (expected, 1, 1))
        s, g, l, sl = load_helpers(self)
        sl(png_data, f=100, expecting_data=expected)
        # test error handling for loading bad png data
        self.assertRaisesRegex(ValueError, '[EBADPNG]', load_png_data, b'dsfsdfsfsfd')

    def test_gr_operations_with_numbers(self):
        s = self.create_screen()
        g = s.grman
        self.assertEqual(g.disk_cache.total_size, 0)

        def li(payload, **kw):
            cmd = ','.join('%s=%s' % (k, v) for k, v in kw.items())
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
            cmd = ','.join('%s=%s' % (k, v) for k, v in kw.items())
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
                cmd += ',d={}'.format(ac)
            if kw:
                cmd += ',' + ','.join('{}={}'.format(k, v) for k, v in kw.items())
            send_command(s, cmd)

        count = s.grman.image_count
        put(i=1), put(i=2), put(i=3), put(i=4), put(i=5)
        delete(I=94)
        self.ae(s.grman.image_count, count)
        delete(I=93)
        self.ae(s.grman.image_count, count - 1)
        delete(I=1)
        self.ae(s.grman.image_count, count - 2)
        s.reset()
        self.assertEqual(g.disk_cache.total_size, 0)

    def test_image_put(self):
        cw, ch = 10, 20
        s, dx, dy, put_image, put_ref, layers, rect_eq = put_helpers(self, cw, ch)
        self.ae(put_image(s, 10, 20)[1], 'OK')
        l0 = layers(s)
        self.ae(len(l0), 1)
        rect_eq(l0[0]['src_rect'], 0, 0, 1, 1)
        rect_eq(l0[0]['dest_rect'], -1, 1, -1 + dx, 1 - dy)
        self.ae(l0[0]['group_count'], 1)
        self.ae(s.cursor.x, 1), self.ae(s.cursor.y, 0)
        iid, (code, idstr) = put_ref(s, num_cols=s.columns, x_off=2, y_off=1, width=3, height=5, cell_x_off=3, cell_y_off=1, z=-1, placement_id=17)
        self.ae(idstr, f'i={iid},p=17')
        l2 = layers(s)
        self.ae(len(l2), 2)
        rect_eq(l2[0]['src_rect'], 2 / 10, 1 / 20, (2 + 3) / 10, (1 + 5)/20)
        left, top = -1 + dx + 3 * dx / cw, 1 - 1 * dy / ch
        rect_eq(l2[0]['dest_rect'], left, top, -1 + (1 + s.columns) * dx, top - dy * 5 / ch)
        rect_eq(l2[1]['src_rect'], 0, 0, 1, 1)
        rect_eq(l2[1]['dest_rect'], -1, 1, -1 + dx, 1 - dy)
        self.ae(l2[0]['group_count'], 1), self.ae(l2[1]['group_count'], 1)
        self.ae(s.cursor.x, 0), self.ae(s.cursor.y, 1)
        self.ae(put_image(s, 10, 20, cursor_movement=1)[1], 'OK')
        self.ae(s.cursor.x, 0), self.ae(s.cursor.y, 1)
        s.reset()
        self.assertEqual(s.grman.disk_cache.total_size, 0)

    def test_gr_scroll(self):
        cw, ch = 10, 20
        s, dx, dy, put_image, put_ref, layers, rect_eq = put_helpers(self, cw, ch)
        put_image(s, 10, 20)  # a one cell image at (0, 0)
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
        put_image(s, cw, 2*ch, z=-1)  # 1x2 cell image
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
        put_image(s, cw, 2*ch, z=-1)  # 1x2 cell image
        self.ae(s.grman.image_count, 3)
        self.ae(layers(s)[0]['src_rect'], {'left': 0.0, 'top': 0.0, 'right': 1.0, 'bottom': 1.0})
        while s.cursor.y != 1:
            s.reverse_index()
        s.reverse_index()
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
                cmd += ',d={}'.format(ac)
            if kw:
                cmd += ',' + ','.join('{}={}'.format(k, v) for k, v in kw.items())
            send_command(s, cmd)

        put_image(s, cw, ch)
        delete()
        self.ae(len(layers(s)), 0), self.ae(s.grman.image_count, 1)
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
        self.assertIsNone(li(a='d', d='F', i=1))
        self.ae(g.image_count, 0)
        self.assertEqual(g.disk_cache.total_size, 0)

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
