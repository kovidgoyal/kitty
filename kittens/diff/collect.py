#!/usr/bin/env python3
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2018, Kovid Goyal <kovid at kovidgoyal.net>

import os
import re
from contextlib import suppress
from functools import lru_cache
from hashlib import md5
from kitty.guess_mime_type import guess_type
from typing import TYPE_CHECKING, Dict, List, Set, Optional, Iterator, Tuple, Union

if TYPE_CHECKING:
    from .highlight import DiffHighlight  # noqa


path_name_map: Dict[str, str] = {}
remote_dirs: Dict[str, str] = {}


def add_remote_dir(val: str) -> None:
    remote_dirs[val] = os.path.basename(val).rpartition('-')[-1]


class Segment:

    __slots__ = ('start', 'end', 'start_code', 'end_code')

    def __init__(self, start: int, start_code: str):
        self.start = start
        self.start_code = start_code
        self.end: Optional[int] = None
        self.end_code: Optional[str] = None

    def __repr__(self) -> str:
        return 'Segment(start={!r}, start_code={!r}, end={!r}, end_code={!r})'.format(
            self.start, self.start_code, self.end, self.end_code)


class Collection:

    def __init__(self) -> None:
        self.changes: Dict[str, str] = {}
        self.renames: Dict[str, str] = {}
        self.adds: Set[str] = set()
        self.removes: Set[str] = set()
        self.all_paths: List[str] = []
        self.type_map: Dict[str, str] = {}
        self.added_count = self.removed_count = 0

    def add_change(self, left_path: str, right_path: str) -> None:
        self.changes[left_path] = right_path
        self.all_paths.append(left_path)
        self.type_map[left_path] = 'diff'

    def add_rename(self, left_path: str, right_path: str) -> None:
        self.renames[left_path] = right_path
        self.all_paths.append(left_path)
        self.type_map[left_path] = 'rename'

    def add_add(self, right_path: str) -> None:
        self.adds.add(right_path)
        self.all_paths.append(right_path)
        self.type_map[right_path] = 'add'
        if isinstance(data_for_path(right_path), str):
            self.added_count += len(lines_for_path(right_path))

    def add_removal(self, left_path: str) -> None:
        self.removes.add(left_path)
        self.all_paths.append(left_path)
        self.type_map[left_path] = 'removal'
        if isinstance(data_for_path(left_path), str):
            self.removed_count += len(lines_for_path(left_path))

    def finalize(self) -> None:
        def key(x: str) -> str:
            return path_name_map.get(x, '')

        self.all_paths.sort(key=key)

    def __iter__(self) -> Iterator[Tuple[str, str, Optional[str]]]:
        for path in self.all_paths:
            typ = self.type_map[path]
            if typ == 'diff':
                data: Optional[str] = self.changes[path]
            elif typ == 'rename':
                data = self.renames[path]
            else:
                data = None
            yield path, typ, data

    def __len__(self) -> int:
        return len(self.all_paths)


def remote_hostname(path: str) -> Tuple[Optional[str], Optional[str]]:
    for q in remote_dirs:
        if path.startswith(q):
            return q, remote_dirs[q]
    return None, None


def resolve_remote_name(path: str, default: str) -> str:
    remote_dir, rh = remote_hostname(path)
    if remote_dir and rh:
        return rh + ':' + os.path.relpath(path, remote_dir)
    return default


def collect_files(collection: Collection, left: str, right: str) -> None:
    left_names: Set[str] = set()
    right_names: Set[str] = set()
    left_path_map: Dict[str, str] = {}
    right_path_map: Dict[str, str] = {}

    def walk(base: str, names: Set[str], pmap: Dict[str, str]) -> None:
        for dirpath, dirnames, filenames in os.walk(base):
            for filename in filenames:
                path = os.path.abspath(os.path.join(dirpath, filename))
                path_name_map[path] = name = os.path.relpath(path, base)
                names.add(name)
                pmap[name] = path

    walk(left, left_names, left_path_map)
    walk(right, right_names, right_path_map)
    common_names = left_names & right_names
    changed_names = {n for n in common_names if data_for_path(left_path_map[n]) != data_for_path(right_path_map[n])}
    for n in changed_names:
        collection.add_change(left_path_map[n], right_path_map[n])

    removed = left_names - common_names
    added = right_names - common_names
    ahash = {a: hash_for_path(right_path_map[a]) for a in added}
    rhash = {r: hash_for_path(left_path_map[r]) for r in removed}
    for name, rh in rhash.items():
        for n, ah in ahash.items():
            if ah == rh and data_for_path(left_path_map[name]) == data_for_path(right_path_map[n]):
                collection.add_rename(left_path_map[name], right_path_map[n])
                added.discard(n)
                break
        else:
            collection.add_removal(left_path_map[name])

    for name in added:
        collection.add_add(right_path_map[name])


sanitize_pat = re.compile('[\x00-\x09\x0b-\x1f\x7f\x80-\x9f]')


def sanitize(text: str) -> str:
    ntext = text.replace('\r\n', '⏎\n')
    return sanitize_pat.sub('░', ntext)


@lru_cache(maxsize=1024)
def mime_type_for_path(path: str) -> str:
    return guess_type(path) or 'application/octet-stream'


@lru_cache(maxsize=1024)
def raw_data_for_path(path: str) -> bytes:
    with open(path, 'rb') as f:
        return f.read()


def is_image(path: Optional[str]) -> bool:
    return mime_type_for_path(path).startswith('image/') if path else False


@lru_cache(maxsize=1024)
def data_for_path(path: str) -> Union[str, bytes]:
    raw_bytes = raw_data_for_path(path)
    if not is_image(path) and not os.path.samefile(path, os.devnull):
        with suppress(UnicodeDecodeError):
            return raw_bytes.decode('utf-8')
    return raw_bytes


class LinesForPath:

    replace_tab_by = ' ' * 4

    @lru_cache(maxsize=1024)
    def __call__(self, path: str) -> Tuple[str, ...]:
        data = data_for_path(path)
        assert isinstance(data, str)
        data = data.replace('\t', self.replace_tab_by)
        return tuple(sanitize(data).splitlines())


lines_for_path = LinesForPath()


@lru_cache(maxsize=1024)
def hash_for_path(path: str) -> bytes:
    return md5(raw_data_for_path(path)).digest()


def create_collection(left: str, right: str) -> Collection:
    collection = Collection()
    if os.path.isdir(left):
        collect_files(collection, left, right)
    else:
        pl, pr = os.path.abspath(left), os.path.abspath(right)
        path_name_map[pl] = resolve_remote_name(pl, left)
        path_name_map[pr] = resolve_remote_name(pr, right)
        collection.add_change(pl, pr)
    collection.finalize()
    return collection


highlight_data: Dict[str, 'DiffHighlight'] = {}


def set_highlight_data(data: Dict[str, 'DiffHighlight']) -> None:
    global highlight_data
    highlight_data = data


def highlights_for_path(path: str) -> 'DiffHighlight':
    return highlight_data.get(path, [])
