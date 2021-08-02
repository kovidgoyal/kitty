#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPLv3 Copyright: 2021, Kovid Goyal <kovid at kovidgoyal.net>

import datetime
import http
import json
import os
import re
import shutil
import zipfile
from contextlib import suppress
from typing import Any, Callable, Dict, Match
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from kitty.config import parse_config
from kitty.constants import cache_dir
from kitty.rgb import Color


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


def zip_file_loader(path_to_zip: str, theme_file_name: str, file_name: str) -> Callable[[], str]:

    name = os.path.join(os.path.dirname(theme_file_name), file_name)

    def zip_loader() -> str:
        with zipfile.ZipFile(path_to_zip, 'r') as zf, zf.open(name, 'rb') as f:
            return f.read().decode('utf-8')

    return zip_loader


def theme_name_from_file_name(fname: str) -> str:
    ans = fname.rsplit('.', 1)[0]
    ans = ans.replace('_', ' ')

    def camel_case(m: Match) -> str:
        return str(m.group(1) + ' ' + m.group(2))

    ans = re.sub(r'([a-z])([A-Z])', camel_case, ans)
    return ' '.join(x.capitalize() for x in filter(None, ans.split()))


class LineParser:

    def __init__(self) -> None:
        self.in_metadata = False
        self.in_blurb = False
        self.keep_going = True

    def __call__(self, line: str, ans: Dict[str, Any]) -> None:
        is_block = line.startswith('## ')
        if self.in_metadata and not is_block:
            self.keep_going = False
            return
        if not self.in_metadata and is_block:
            self.in_metadata = True
        if not self.in_metadata:
            return
        line = line[3:]
        if self.in_blurb:
            ans['blurb'] += ' ' + line
            return
        try:
            key, val = line.split(':', 1)
        except Exception:
            self.keep_going = False
            return
        key = key.strip().lower()
        val = val.strip()
        if val:
            ans[key] = val
        if key == 'blurb':
            self.in_blurb = True


def parse_theme(fname: str, raw: str) -> Dict[str, Any]:
    lines = raw.splitlines()
    conf = parse_config(lines)
    bg = conf.get('background', Color())
    is_dark = max(bg) < 115
    ans: Dict[str, Any] = {'name': theme_name_from_file_name(fname)}
    parser = LineParser()
    for i, line in enumerate(raw.splitlines()):
        line = line.strip()
        if not line:
            continue
        try:
            parser(line, ans)
        except Exception as e:
            raise SystemExit(
                f'Failed to parse {fname} line {i+1} with error: {e}')
        if not parser.keep_going:
            break
    if is_dark:
        ans['is_dark'] = True
    ans['num_settings'] = len(conf) - len(parse_config(()))
    if ans['num_settings'] < 1:
        raise SystemExit(f'The theme {fname} has no settings')
    return ans


class Theme:
    name: str = ''
    author: str = ''
    license: str = ''
    is_dark: bool = False
    blurb: str = ''
    num_settings: int = 0

    def apply_dict(self, d: Dict[str, Any]) -> None:
        self.name = str(d['name'])
        for x in ('author', 'license', 'blurb'):
            a = d.get(x)
            if isinstance(a, str):
                setattr(self, x, a)
        for x in ('is_dark', 'num_settings'):
            a = d.get(x)
            if isinstance(a, int):
                setattr(self, x, a)

    def __init__(self, loader: Callable[[], str]):
        self.loader = loader


class Themes:

    def __init__(self) -> None:
        self.themes: Dict[str, Theme] = {}

    def load_from_zip(self, path_to_zip: str) -> None:
        with zipfile.ZipFile(path_to_zip, 'r') as zf:
            for name in zf.namelist():
                if os.path.basename(name) == 'themes.json':
                    theme_file_name = name
                    with zf.open(theme_file_name, 'rb') as f:
                        items = json.loads(f.read())
                    break
            else:
                raise ValueError(f'No themes.json found in {path_to_zip}')

            for item in items:
                t = Theme(zip_file_loader(path_to_zip, theme_file_name, item['file']))
                t.apply_dict(item)
                if t.name:
                    self.themes[t.name] = t
