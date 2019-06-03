#!/usr/bin/env python3
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2018, Kovid Goyal <kovid at kovidgoyal.net>

import os
import re
from functools import lru_cache
from hashlib import md5
from mimetypes import guess_type
from contextlib import suppress

path_name_map = {}


class Segment:

    __slots__ = ('start', 'end', 'start_code', 'end_code')

    def __init__(self, start, start_code):
        self.start = start
        self.start_code = start_code

    def __repr__(self):
        return 'Segment(start={!r}, start_code={!r}, end={!r}, end_code={!r})'.format(
                self.start, self.start_code, getattr(self, 'end', None), getattr(self, 'end_code', None)
        )


class Collection:

    def __init__(self):
        self.changes = {}
        self.renames = {}
        self.adds = set()
        self.removes = set()
        self.all_paths = []
        self.type_map = {}
        self.added_count = self.removed_count = 0

    def add_change(self, left_path, right_path):
        self.changes[left_path] = right_path
        self.all_paths.append(left_path)
        self.type_map[left_path] = 'diff'

    def add_rename(self, left_path, right_path):
        self.renames[left_path] = right_path
        self.all_paths.append(left_path)
        self.type_map[left_path] = 'rename'

    def add_add(self, right_path):
        self.adds.add(right_path)
        self.all_paths.append(right_path)
        self.type_map[right_path] = 'add'
        if isinstance(data_for_path(right_path), str):
            self.added_count += len(lines_for_path(right_path))

    def add_removal(self, left_path):
        self.removes.add(left_path)
        self.all_paths.append(left_path)
        self.type_map[left_path] = 'removal'
        if isinstance(data_for_path(left_path), str):
            self.removed_count += len(lines_for_path(left_path))

    def finalize(self):
        self.all_paths.sort(key=path_name_map.get)

    def __iter__(self):
        for path in self.all_paths:
            typ = self.type_map[path]
            if typ == 'diff':
                data = self.changes[path]
            elif typ == 'rename':
                data = self.renames[path]
            else:
                data = None
            yield path, typ, data

    def __len__(self):
        return len(self.all_paths)


def collect_files(collection, left, right):
    left_names, right_names = set(), set()
    left_path_map, right_path_map = {}, {}

    def walk(base, names, pmap):
        for dirpath, dirnames, filenames in os.walk(base):
            for filename in filenames:
                path = os.path.abspath(os.path.join(dirpath, filename))
                path_name_map[path] = name = os.path.relpath(path, base)
                names.add(name)
                pmap[name] = path

    walk(left, left_names, left_path_map), walk(right, right_names, right_path_map)
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


def sanitize(text):
    ntext = text.replace('\r\n', '⏎\n')
    return sanitize_pat.sub('░', ntext)


@lru_cache(maxsize=1024)
def mime_type_for_path(path):
    return guess_type(path)[0] or 'application/octet-stream'


@lru_cache(maxsize=1024)
def raw_data_for_path(path):
    with open(path, 'rb') as f:
        return f.read()


def is_image(path):
    return mime_type_for_path(path).startswith('image/')


@lru_cache(maxsize=1024)
def data_for_path(path):
    ans = raw_data_for_path(path)
    if not is_image(path) and not os.path.samefile(path, os.devnull):
        with suppress(UnicodeDecodeError):
            ans = ans.decode('utf-8')
    return ans


@lru_cache(maxsize=1024)
def lines_for_path(path):
    data = data_for_path(path).replace('\t', lines_for_path.replace_tab_by)
    return tuple(sanitize(data).splitlines())


lines_for_path.replace_tab_by = ' ' * 4


@lru_cache(maxsize=1024)
def hash_for_path(path):
    return md5(raw_data_for_path(path)).digest()


def create_collection(left, right):
    collection = Collection()
    if os.path.isdir(left):
        collect_files(collection, left, right)
    else:
        pl, pr = os.path.abspath(left), os.path.abspath(right)
        path_name_map[pl] = left
        path_name_map[pr] = right
        collection.add_change(pl, pr)
    collection.finalize()
    return collection


highlight_data = {}


def set_highlight_data(data):
    global highlight_data
    highlight_data = data


def highlights_for_path(path):
    return highlight_data.get(path, [])
