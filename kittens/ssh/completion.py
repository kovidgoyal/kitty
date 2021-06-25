#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPLv3 Copyright: 2021, Kovid Goyal <kovid at kovidgoyal.net>

import os
import subprocess
from typing import Dict, Iterator, Tuple
from kitty.types import run_once


def iter_known_hosts() -> Iterator[str]:
    try:
        f = open(os.path.expanduser('~/.ssh/config'))
    except OSError:
        pass
    else:
        for line in f:
            parts = line.split()
            if parts and parts[0] == 'Host' and len(parts) > 1:
                yield parts[1]

    try:
        f = open(os.path.expanduser('~/.ssh/known_hosts'))
    except OSError:
        pass
    else:
        for line in f:
            parts = line.split()
            if parts:
                yield parts[0]


@run_once
def known_hosts() -> Tuple[str, ...]:
    return tuple(iter_known_hosts())


@run_once
def ssh_options() -> Dict[str, str]:
    stderr = subprocess.Popen(['ssh'], stderr=subprocess.PIPE).stderr
    assert stderr is not None
    raw = stderr.read().decode('utf-8')
    ans: Dict[str, str] = {}
    pos = 0
    while True:
        pos = raw.find('[', pos)
        if pos < 0:
            break
        num = 1
        epos = pos
        while num > 0:
            epos += 1
            if raw[epos] not in '[]':
                continue
            num += 1 if raw[epos] == '[' else -1
        q = raw[pos+1:epos]
        pos = epos
        if len(q) < 2 or q[0] != '-':
            continue
        if ' ' in q:
            opt, desc = q.split(' ', 1)
            ans[opt[1:]] = desc
        else:
            ans.update(dict.fromkeys(q[1:], ''))
    return ans
