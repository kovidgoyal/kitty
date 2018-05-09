#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2018, Kovid Goyal <kovid at kovidgoyal.net>

import codecs
import shutil
import sys
import tempfile
from base64 import standard_b64encode

from .operations import serialize_gr_command

try:
    fsenc = sys.getfilesystemencoding() or 'utf-8'
    codecs.lookup(fsenc)
except Exception:
    fsenc = 'utf-8'


def can_display_images():
    ans = getattr(can_display_images, 'ans', None)
    if ans is None:
        ans = shutil.which('convert') is not None
        can_display_images.ans = ans
    return ans


class ImageManager:

    def __init__(self, handler):
        self.handler = handler
        self.sent_ids = set()
        self.filesystem_ok = None

    def __enter__(self):
        self.tdir = tempfile.mkdtemp(prefix='kitten-images-')
        with tempfile.NamedTemporaryFile(dir=self.tdir, delete=False) as f:
            f.write(b'abcd')
        self.handler.write(serialize_gr_command(dict(a='q', s=1, v=1, i=1, t='f'), standard_b64encode(f.name.encode(fsenc))))
        self.sent_ids.add(1)

    def __exit__(self, *a):
        shutil.rmtree(self.tdir, ignore_errors=True)
        self.handler.cmd.clear_images_on_screen(delete_data=True)
        self.delete_all_sent_images()
        del self.handler

    def delete_all_sent_images(self):
        for img_id in self.sent_ids:
            self.handler.write(serialize_gr_command({'a': 'D', 'i': str(img_id)}))
        self.sent_ids = set()

    def handle_response(self, apc):
        cdata, payload = apc[1:].partition(';')[::2]
        control = {}
        for x in cdata.split(','):
            k, v = x.partition('=')[::2]
            control[k] = v
        try:
            image_id = int(control.get('i', '0'))
        except Exception:
            image_id = 0
        if image_id == 1:
            self.filesystem_ok = payload == 'OK'
            return
