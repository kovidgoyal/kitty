#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPLv3 Copyright: 2021, Kovid Goyal <kovid at kovidgoyal.net>

import datetime
import http
import json
import os
import re
import shutil
import signal
import tempfile
import zipfile
from contextlib import suppress
from typing import Any, Callable, Dict, Iterator, Match, Optional, Tuple, Union
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from kitty.config import atomic_save, parse_config
from kitty.constants import cache_dir, config_dir
from kitty.options.types import Options as KittyOptions
from kitty.rgb import Color
from kitty.utils import reload_conf_in_all_kitties

from ..choose.match import match

MARK_BEFORE = '\033[33m'
MARK_AFTER = '\033[39m'


def patch_conf(raw: str, theme_name: str) -> str:
    addition = f'# BEGIN_KITTY_THEME\n# {theme_name}\ninclude current-theme.conf\n# END_KITTY_THEME'
    nraw, num = re.subn(r'^# BEGIN_KITTY_THEME.+?# END_KITTY_THEME', addition, raw, flags=re.MULTILINE | re.DOTALL)
    if not num:
        if raw:
            raw += '\n\n'
        nraw = raw + addition
    # comment out all existing color definitions
    color_conf_items = [f'color{i}' for i in range(256)] + list(filter(None, '''
foreground
background
selection_foreground
selection_background

cursor
cursor_text_color

url_color

active_border_color
inactive_border_color
bell_border_color

wayland_titlebar_color
macos_titlebar_color

active_tab_foreground
active_tab_background
inactive_tab_foreground
inactive_tab_background
tab_bar_background

mark1_foreground
mark1_background
mark2_foreground
mark2_background
mark3_foreground
mark3_background
'''.splitlines()))
    pat = f'^({"|".join(color_conf_items)})'
    return re.sub(pat, r'# \1', nraw, flags=re.MULTILINE)


def set_comment_in_zip_file(path: str, data: str) -> None:
    with zipfile.ZipFile(path, 'a') as zf:
        zf.comment = data.encode('utf-8')


class NoCacheFound(ValueError):
    pass


def fetch_themes(
    name: str = 'kitty-themes',
    url: str = 'https://codeload.github.com/kovidgoyal/kitty-themes/zip/master',
    cache_age: float = 1,
) -> str:
    now = datetime.datetime.now(datetime.timezone.utc)
    cache_age_delta = datetime.timedelta(days=cache_age)

    class Metadata:
        def __init__(self) -> None:
            self.etag = ''
            self.timestamp = now

        def __str__(self) -> str:
            return json.dumps({'etag': self.etag, 'timestamp': self.timestamp.isoformat()})

    dest_path = os.path.join(cache_dir(), f'{name}.zip')
    m = Metadata()
    with suppress(Exception), zipfile.ZipFile(dest_path, 'r') as zf:
        q = json.loads(zf.comment)
        m.etag = str(q.get('etag') or '')
        m.timestamp = datetime.datetime.fromisoformat(q['timestamp'])
        if cache_age < 0 or (now - m.timestamp) < cache_age_delta:
            return dest_path
    if cache_age < 0:
        raise NoCacheFound('No local themes cache found and negative cache age specified, aborting')

    rq = Request(url)
    m.timestamp = now
    if m.etag:
        rq.add_header('If-None-Match', m.etag)
    try:
        res = urlopen(rq, timeout=30)
    except HTTPError as e:
        if m.etag and e.code == http.HTTPStatus.NOT_MODIFIED:
            set_comment_in_zip_file(dest_path, str(m))
            return dest_path
        raise
    m.etag = res.headers.get('etag') or ''

    needs_delete = False
    try:
        with tempfile.NamedTemporaryFile(suffix='-' + os.path.basename(dest_path), dir=os.path.dirname(dest_path), delete=False) as f:
            needs_delete = True
            shutil.copyfileobj(res, f)
            f.flush()
            set_comment_in_zip_file(f.name, str(m))
            os.replace(f.name, dest_path)
            needs_delete = False
    finally:
        if needs_delete:
            os.unlink(f.name)
    return dest_path


def zip_file_loader(path_to_zip: str, theme_file_name: str, file_name: str) -> Callable[[], str]:

    name = os.path.join(os.path.dirname(theme_file_name), file_name)

    def zip_loader() -> str:
        with zipfile.ZipFile(path_to_zip, 'r') as zf, zf.open(name) as f:
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
    if ans['num_settings'] < 1 and fname != 'default.conf':
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
        self._loader = loader
        self._raw: Optional[str] = None
        self._opts: Optional[KittyOptions] = None

    @property
    def raw(self) -> str:
        if self._raw is None:
            self._raw = self._loader()
        return self._raw

    @property
    def kitty_opts(self) -> KittyOptions:
        if self._opts is None:
            self._opts = KittyOptions(options_dict=parse_config(self.raw.splitlines()))
        return self._opts

    def save_in_dir(self, dirpath: str) -> None:
        atomic_save(self.raw.encode('utf-8'), os.path.join(dirpath, f'{self.name}.conf'))

    def save_in_conf(self, confdir: str, reload_in: str) -> None:
        atomic_save(self.raw.encode('utf-8'), os.path.join(confdir, 'current-theme.conf'))
        confpath = os.path.realpath(os.path.join(confdir, 'kitty.conf'))
        try:
            with open(confpath) as f:
                raw = f.read()
        except FileNotFoundError:
            raw = ''
        nraw = patch_conf(raw, self.name)
        if raw:
            with open(confpath + '.bak', 'w') as f:
                f.write(raw)
        atomic_save(nraw.encode('utf-8'), confpath)
        if reload_in == 'parent':
            if 'KITTY_PID' in os.environ:
                os.kill(int(os.environ['KITTY_PID']), signal.SIGUSR1)
        elif reload_in == 'all':
            reload_conf_in_all_kitties()


class Themes:

    def __init__(self) -> None:
        self.themes: Dict[str, Theme] = {}
        self.index_map: Tuple[str, ...] = ()

    def __len__(self) -> int:
        return len(self.themes)

    def __iter__(self) -> Iterator[Theme]:
        return iter(self.themes.values())

    def __getitem__(self, key: Union[int, str]) -> Theme:
        if isinstance(key, str):
            return self.themes[key]
        if key < 0:
            key += len(self.index_map)
        return self.themes[self.index_map[key]]

    def load_from_zip(self, path_to_zip: str) -> None:
        with zipfile.ZipFile(path_to_zip, 'r') as zf:
            for name in zf.namelist():
                if os.path.basename(name) == 'themes.json':
                    theme_file_name = name
                    with zf.open(theme_file_name) as f:
                        items = json.loads(f.read())
                    break
            else:
                raise ValueError(f'No themes.json found in {path_to_zip}')

            for item in items:
                t = Theme(zip_file_loader(path_to_zip, theme_file_name, item['file']))
                t.apply_dict(item)
                if t.name:
                    self.themes[t.name] = t

    def load_from_dir(self, path: str) -> None:
        if not os.path.isdir(path):
            return
        for name in os.listdir(path):
            if name.endswith('.conf'):
                with open(os.path.join(path, name), 'rb') as f:
                    raw = f.read().decode()
                try:
                    d = parse_theme(name, raw)
                except (Exception, SystemExit):
                    continue
                t = Theme(lambda: raw)
                t.apply_dict(d)
                if t.name:
                    self.themes[t.name] = t

    def filtered(self, is_ok: Callable[[Theme], bool]) -> 'Themes':
        ans = Themes()

        def sort_key(k: Tuple[str, Theme]) -> str:
            return k[1].name.lower()

        ans.themes = {k: v for k, v in sorted(self.themes.items(), key=sort_key) if is_ok(v)}
        ans.index_map = tuple(ans.themes)
        return ans

    def copy(self) -> 'Themes':
        ans = Themes()
        ans.themes = self.themes.copy()
        ans.index_map = self.index_map
        return ans

    def apply_search(
        self, expression: str, mark_before: str = MARK_BEFORE, mark_after: str = MARK_AFTER
    ) -> Iterator[str]:
        raw = '\n'.join(self.themes)
        results = match(raw, expression, positions=True, level1=' ')
        themes: Dict[str, Theme] = {}
        for r in results:
            pos, k = r.split(':', 1)
            positions = tuple(map(int, pos.split(',')))
            text = k
            for p in reversed(positions):
                text = text[:p] + mark_before + text[p] + mark_after + text[p+1:]
            themes[k] = self.themes[k]
            yield text
        self.themes = themes
        self.index_map = tuple(self.themes)


def load_themes(cache_age: float = 1., ignore_no_cache: bool = False) -> Themes:
    ans = Themes()
    try:
        fetched = fetch_themes(cache_age=cache_age)
    except NoCacheFound:
        if not ignore_no_cache:
            raise
    ans.load_from_zip(fetched)
    ans.load_from_dir(os.path.join(config_dir, 'themes'))
    ans.index_map = tuple(ans.themes)
    return ans
