#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPLv3 Copyright: 2020, Kovid Goyal <kovid at kovidgoyal.net>

import os
from contextlib import suppress
from typing import Optional

known_extensions = {
    'asciidoc': 'text/asciidoctor',
    'conf': 'text/config',
    'md': 'text/markdown',
    'pyj': 'text/rapydscript-ng',
    'recipe': 'text/python',
    'rst': 'text/restructured-text',
    'toml': 'text/toml',
    'vim': 'text/vim',
    'yaml': 'text/yaml',
}


def is_rc_file(path: str) -> bool:
    name = os.path.basename(path)
    return '.' not in name and name.endswith('rc')


def guess_type(path: str) -> Optional[str]:
    if not hasattr(guess_type, 'inited'):
        setattr(guess_type, 'inited', True)
        from mimetypes import init
        init(None)
        from kitty.constants import config_dir
        local_defs = os.path.join(config_dir, 'mime.types')
        if os.path.exists(local_defs):
            init((local_defs,))
    from mimetypes import guess_type as stdlib_guess_type
    mt = None
    with suppress(Exception):
        mt = stdlib_guess_type(path)[0]
    if not mt:
        ext = path.rpartition('.')[-1].lower()
        mt = known_extensions.get(ext)
    if not mt and is_rc_file(path):
        mt = 'text/plain'
    return mt
