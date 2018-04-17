#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2018, Kovid Goyal <kovid at kovidgoyal.net>

import os
from functools import lru_cache
from hashlib import md5
from mimetypes import guess_type


class Collection:

    def __init__(self):
        self.changes = []
        self.renames = {}
        self.adds = []
        self.removes = []

    def add_change(self, left_path, right_path):
        self.changes.append((left_path, right_path))

    def add_rename(self, left_path, right_path):
        self.renames[left_path] = right_path

    def add_add(self, right_path):
        self.adds.append(right_path)

    def add_removal(self, left_path):
        self.removes.append(left_path)


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
                collection.add_rename(left_path_map[name], right_path_map[name])
                added.discard(n)
                break
        else:
            collection.add_removal(left_path_map[name])

    for name in added:
        collection.add_add(right_path_map[name])


@lru_cache(maxsize=1024)
def mime_type_for_path(path):
    return guess_type(path)[0] or 'application/octet-stream'


@lru_cache(maxsize=1024)
def data_for_path(path):
    with open(path, 'rb') as f:
        ans = f.read()
    if not mime_type_for_path(path).startswith('image/'):
        try:
            ans = ans.decode('utf-8')
        except UnicodeDecodeError:
            pass
    return ans


@lru_cache(maxsize=1024)
def hash_for_path(path):
    md5(data_for_path(path)).digest()


path_name_map = {}


def create_collection(left, right):
    collection = Collection()
    if os.path.isdir(left):
        collect_files(collection, left, right)
    else:
        pl, pr = os.path.abspath(left), os.path.abspath(right)
        path_name_map[left] = pl
        path_name_map[right] = pr
        collection.add_change(pl, pr)
    return collection
