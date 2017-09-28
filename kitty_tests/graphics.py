#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2016, Kovid Goyal <kovid at kovidgoyal.net>

import os
import tempfile
import unittest
import zlib
from base64 import standard_b64encode
from io import BytesIO

from kitty.fast_data_types import parse_bytes

from . import BaseTest

try:
    from PIL import Image
except ImportError:
    Image = None


def relpath(name):
    base = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base, name)


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


def helpers(self):
    s = self.create_screen()
    g = s.grman

    def l(payload, **kw):
        kw.setdefault('i', 1)
        cmd = ','.join('%s=%s' % (k, v) for k, v in kw.items())
        res = send_command(s, cmd, payload)
        if not res:
            return
        return res.decode('ascii').partition(';')[2].partition('\033')[0]

    def sl(payload, **kw):
        if isinstance(payload, str):
            payload = payload.encode('utf-8')
        data = kw.pop('expecting_data', payload)
        cid = kw.setdefault('i', 1)
        self.ae('OK', l(payload, **kw))
        img = g.image_for_client_id(cid)
        self.ae(img['client_id'], cid)
        self.ae(img['data'], data)
        if 's' in kw:
            self.ae((kw['s'], kw['v']), (img['width'], img['height']))
        self.ae(img['is_4byte_aligned'], kw.get('f') != 24)
        return img

    return s, g, l, sl


class TestGraphics(BaseTest):

    def test_load_images(self):
        s, g, l, sl = helpers(self)

        # Test simple load
        for f in 32, 24:
            p = 'abc' + ('d' if f == 32 else '')
            img = sl(p, s=1, v=1, f=f)
            self.ae(bool(img['is_4byte_aligned']), f == 32)

        # Test chuunked load
        self.assertIsNone(l('abcd', s=2, v=2, m=1))
        self.assertIsNone(l('efgh', m=1))
        self.assertIsNone(l('ijkl', m=1))
        self.ae(l('mnop', m=0), 'OK')
        img = g.image_for_client_id(1)
        self.ae(img['data'], b'abcdefghijklmnop')

        # Test compression
        random_data = os.urandom(3 * 1024)
        compressed_random_data = zlib.compress(random_data)
        sl(
            compressed_random_data,
            s=24,
            v=32,
            o='z',
            expecting_data=random_data
        )

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
        g.shm_write(name, random_data)
        sl(name, s=24, v=32, t='s', expecting_data=random_data)
        self.assertRaises(
            FileNotFoundError, g.shm_unlink, name
        )  # check that file was deleted

    @unittest.skipIf(Image is None, 'PIL not available, skipping PNG tests')
    def test_load_png(self):
        s, g, l, sl = helpers(self)
        w, h = 5, 3
        img = Image.new('RGBA', (w, h), 'red')
        rgba_data = img.tobytes()

        def png(mode='RGBA'):
            buf = BytesIO()
            i = img
            if mode != i.mode:
                i = img.convert(mode)
            i.save(buf, 'PNG')
            return buf.getvalue()

        for mode in 'RGBA RGB P'.split():
            data = png(mode)
            sl(data, f=100, S=len(data), expecting_data=rgba_data)

        img = img.convert('L')
        rgba_data = img.convert('RGBA').tobytes()
        data = png('L')
        sl(data, f=100, S=len(data), expecting_data=rgba_data)
        self.ae(l(b'a' * 20, f=100, S=20).partition(':')[0], 'EBADPNG')
