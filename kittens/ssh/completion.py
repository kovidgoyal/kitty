#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPLv3 Copyright: 2021, Kovid Goyal <kovid at kovidgoyal.net>

import os
import re
import subprocess
from typing import Callable, Dict, Iterable, Iterator, Tuple

from kitty.types import run_once


def lines_from_file(path: str) -> Iterator[str]:
    try:
        f = open(os.path.expanduser(path))
    except OSError:
        pass
    else:
        yield from f


def lines_from_command(*cmd: str) -> Iterator[str]:
    try:
        output = subprocess.check_output(cmd).decode('utf-8')
    except Exception:
        return
    yield from output.splitlines()


def parts_yielder(lines: Iterable[str], pfilter: Callable[[str], Iterator[str]]) -> Iterator[str]:
    for line in lines:
        yield from pfilter(line)


def hosts_from_config_lines(line: str) -> Iterator[str]:
    parts = line.strip().split()
    if len(parts) > 1 and parts[0] == 'Host':
        yield parts[1]


def hosts_from_known_hosts(line: str) -> Iterator[str]:
    parts = line.strip().split()
    if parts:
        yield re.sub(r':\d+$', '', parts[0])


def hosts_from_hosts(line: str) -> Iterator[str]:
    line = line.strip()
    if not line.startswith('#'):
        parts = line.split()
        if parts:
            yield parts[0]
        if len(parts) > 1:
            yield parts[1]
        if len(parts) > 2:
            yield parts[2]


def iter_known_hosts() -> Iterator[str]:
    yield from parts_yielder(lines_from_file('~/.ssh/config'), hosts_from_config_lines)
    yield from parts_yielder(lines_from_file('~/.ssh/known_hosts'), hosts_from_known_hosts)
    yield from parts_yielder(lines_from_file('/etc/ssh/ssh_known_hosts'), hosts_from_known_hosts)
    yield from parts_yielder(lines_from_file('/etc/hosts'), hosts_from_hosts)
    yield from parts_yielder(lines_from_command('getent', 'hosts'), hosts_from_hosts)


@run_once
def known_hosts() -> Tuple[str, ...]:
    return tuple(sorted(filter(lambda x: '*' not in x and '[' not in x, set(iter_known_hosts()))))


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
