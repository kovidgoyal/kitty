#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2016, Kovid Goyal <kovid at kovidgoyal.net>

import os

from . import BaseTest
from base64 import standard_b64encode

from kitty.fast_data_types import parse_bytes


def img_path(name):
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


class TestGraphics(BaseTest):

    def test_load_images(self):
        s = self.create_screen()
        g = s.grman

        def l(payload, **kw):
            kw.setdefault('i', 1)
            cmd = ','.join('%s=%s' % (k, v) for k, v in kw.items())
            res = send_command(s, cmd, payload)
            if not res:
                return
            return res.decode('ascii').partition(';')[2].partition(':')[0].partition('\033')[0]

        def sl(payload, **kw):
            if isinstance(payload, str):
                payload = payload.encode('utf-8')
            cid = kw.setdefault('i', 1)
            self.ae('OK', l(payload, **kw))
            img = g.image_for_client_id(cid)
            self.ae(img['client_id'], cid)
            self.ae(img['data'], payload)
            if 's' in kw:
                self.ae((kw['s'], kw['v']), (img['width'], img['height']))
            return img

        for f in 32, 24:
            p = 'abc' + ('d' if f == 32 else '')
            img = sl(p, s=1, v=1, f=f)
            self.ae(bool(img['is_4byte_aligned']), f == 32)
