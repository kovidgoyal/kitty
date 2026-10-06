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
    'application/x-fishscript',
    'application/x-awk',
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


def user_mime_map() -> dict[str, str]:
    ans: dict[str, str] | None = getattr(user_mime_map, 'ans', None)
    if ans is None:
        from mimetypes import read_mime_types

        from kitty.constants import config_dir

        ans = read_mime_types(os.path.join(config_dir, 'mime.types')) or {}
        setattr(user_mime_map, 'ans', ans)
    return ans


def clear_mime_cache() -> None:
    if hasattr(initialize_mime_database, 'inited'):
        delattr(initialize_mime_database, 'inited')
    if hasattr(user_mime_map, 'ans'):
        delattr(user_mime_map, 'ans')
    from kitty.fast_data_types import clear_mime_cache_data

    clear_mime_cache_data()


def guess_type_from_user_definitions(path: str) -> str | None:
    umap = user_mime_map()
    if not umap:
        return None
    ext = os.path.splitext(path)[1]
    return umap.get(ext) or umap.get(ext.lower())


def guess_type_from_stdlib(path: str) -> str | None:
    from mimetypes import guess_type as stdlib_guess_type

    initialize_mime_database()
    try:
        return stdlib_guess_type(path)[0]
    except Exception:
        return None


def guess_type(path: str, allow_filesystem_access: bool = False) -> str | None:
    is_dir = is_exe = False

    if allow_filesystem_access:
        with suppress(OSError):
            st = os.stat(path)
            is_dir = bool(stat.S_ISDIR(st.st_mode))
            is_exe = bool(not is_dir and st.st_mode & (stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH) and os.access(path, os.X_OK))

    if is_dir:
        return 'inode/directory'
    from kitty.fast_data_types import mime_type_for_filename

    # The stdlib database is only loaded if the faster shared-mime-info cache
    # lookup fails, as loading it requires parsing various files
    mt = guess_type_from_user_definitions(path) or mime_type_for_filename(path) or guess_type_from_stdlib(path)
    if not mt:
        ext = path.rpartition('.')[-1].lower()
        mt = known_extensions.get(ext)
    if mt:
        mt = textual_mime_type(mt)
    mt = mt or is_special_file(path)
    if not mt:
        if is_dir:
            mt = 'inode/directory'
        elif is_exe:
            mt = 'inode/executable'
    return mt


def textual_mime_type(mt: str) -> str:
    return f'text/{mt.split("/", 1)[-1]}' if mt in text_mimes else mt


def mime_types_for_matching(path: str, mt: str) -> set[str]:
    """
    Return all names that the MIME type mt, as returned by guess_type() for path,
    is known by. This includes the aliases from the shared-mime-info database
    as well as the names that were returned by older versions of kitty, so
    that matching against user specified MIME types keeps working.
    """
    from kitty.fast_data_types import mime_type_aliases

    queries = {mt}
    if mt.startswith('text/'):
        # undo the conversion of textual application/* types done by guess_type()
        orig = f'application/{mt[5:]}'
        if orig in text_mimes:
            queries.add(orig)
    ans: set[str] = set()
    for q in queries:
        for x in mime_type_aliases(q):
            ans.add(x)
            ans.add(textual_mime_type(x))
    legacy = known_extensions.get(path.rpartition('.')[-1].lower()) or is_special_file(path)
    if legacy:
        ans.add(legacy)
    return ans
