#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPLv3 Copyright: 2021, Kovid Goyal <kovid at kovidgoyal.net>

import datetime
import http
import json
import os
import shutil
import zipfile
from contextlib import suppress
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from kitty.constants import cache_dir


def fetch_themes(
    name: str = 'kitty-themes',
    url: str = 'https://codeload.github.com/kovidgoyal/kitty-themes/zip/master'
) -> str:
    now = datetime.datetime.now(datetime.timezone.utc)

    class Metadata:
        def __init__(self) -> None:
            self.etag = ''
            self.timestamp = now

    dest_path = os.path.join(cache_dir(), f'{name}.zip')
    m = Metadata()
    with suppress(Exception), zipfile.ZipFile(dest_path, 'r') as zf:
        q = json.loads(zf.comment)
        m.etag = str(q.get('etag') or '')
        m.timestamp = datetime.datetime.fromisoformat(q['timestamp'])
        if (now - m.timestamp).days < 1:
            return dest_path
    rq = Request(url)
    if m.etag:
        rq.add_header('If-None-Match', m.etag)
    try:
        res = urlopen(rq)
    except HTTPError as e:
        if m.etag and e.code == http.HTTPStatus.NOT_MODIFIED:
            return dest_path
        raise
    m.etag = res.headers.get('etag') or ''
    with open(dest_path, 'wb') as f:
        shutil.copyfileobj(res, f)
    with zipfile.ZipFile(dest_path, 'a') as zf:
        zf.comment = json.dumps({'etag': m.etag, 'timestamp': m.timestamp.isoformat()}).encode('utf-8')
    return dest_path
