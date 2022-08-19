#!/usr/bin/env python
# License: GPLv3 Copyright: 2022, Kovid Goyal <kovid at kovidgoyal.net>

import os
import re
from typing import Dict, Iterator

tgt_pat = re.compile(r'^.. _(\S+?):$', re.MULTILINE)


def find_explicit_targets(text: str) -> Iterator[str]:
    for m in tgt_pat.finditer(text):
        yield m.group(1)


def main() -> Dict[str, str]:
    refs = {'github_discussions': 'https://github.com/kovidgoyal/kitty/discussions'}
    base = os.path.dirname(os.path.abspath(__file__))
    for dirpath, dirnames, filenames in os.walk(base):
        if 'generated' in dirnames:
            dirnames.remove('generated')
        for f in filenames:
            if f.endswith('.rst'):
                with open(os.path.join(dirpath, f)) as stream:
                    raw = stream.read()
                href = os.path.relpath(stream.name, base).replace(os.sep, '/')
                href = href.rpartition('.')[0] + '/'
                for explicit_target in find_explicit_targets(raw):
                    refs[explicit_target] = href + f'#{explicit_target.replace("_", "-")}'
    return {'ref': refs}


if __name__ == '__main__':
    import json
    print(json.dumps(main(), indent=2))
