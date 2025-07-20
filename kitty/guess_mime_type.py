#!/usr/bin/env python
# License: GPLv3 Copyright: 2020, Kovid Goyal <kovid at kovidgoyal.net>

import os
import stat
from contextlib import suppress

known_extensions = {
    'asciidoc': 'text/asciidoctor',
    'conf': 'text/config',
    'md': 'text/markdown',
    'pyj': 'text/rapydscript-ng',
    'recipe': 'text/python',
    'rst': 'text/restructured-text',
    'rb': 'text/ruby',
    'toml': 'text/toml',
    'vim': 'text/vim',
    'yaml': 'text/yaml',
    'js': 'text/javascript',
    'json': 'text/json',
    'nix': 'text/nix',
}


text_mimes = (
    'application/x-sh',
    'application/x-csh',
    'application/x-shellscript',
    'application/javascript',
    'application/json',
    'application/xml',
    'application/x-yaml',
    'application/yaml',
    'application/x-toml',
    'application/x-lua',
    'application/toml',
    'application/rss+xml',
    'application/xhtml+xml',
    'application/x-tex',
    'application/x-latex',
)


def is_special_file(path: str) -> str | None:
    name = os.path.basename(path)
    lname = name.lower()
    if lname == 'makefile' or lname.startswith('makefile.'):
        return 'text/makefile'
    if '.' not in name and name.endswith('rc'):
        return 'text/plain'  # rc file
    return None


def is_folder(path: str) -> bool:
    with suppress(OSError):
        return os.path.isdir(path)
    return False


def initialize_mime_database() -> None:
    if hasattr(initialize_mime_database, 'inited'):
        return
    setattr(initialize_mime_database, 'inited', True)
    from mimetypes import init
    init(None)
    from kitty.constants import config_dir
    local_defs = os.path.join(config_dir, 'mime.types')
    if os.path.exists(local_defs):
        init((local_defs,))


def clear_mime_cache() -> None:
    if hasattr(initialize_mime_database, 'inited'):
        delattr(initialize_mime_database, 'inited')


def guess_type(path: str, allow_filesystem_access: bool = False) -> str | None:
    is_dir = is_exe = False

    if allow_filesystem_access:
        with suppress(OSError):
            st = os.stat(path)
            is_dir = bool(stat.S_ISDIR(st.st_mode))
            is_exe = bool(not is_dir and st.st_mode & (stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH) and os.access(path, os.X_OK))

    if is_dir:
        return 'inode/directory'
    from mimetypes import guess_type as stdlib_guess_type
    initialize_mime_database()
    mt = None
    with suppress(Exception):
        mt = stdlib_guess_type(path)[0]
    if not mt:
        ext = path.rpartition('.')[-1].lower()
        mt = known_extensions.get(ext)
    if mt in text_mimes:
        mt = f'text/{mt.split("/", 1)[-1]}'
    mt = mt or is_special_file(path)
    if not mt:
        if is_dir:
            mt = 'inode/directory'  # type: ignore
        elif is_exe:
            mt = 'inode/executable'
    return mt
