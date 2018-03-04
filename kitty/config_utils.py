#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2018, Kovid Goyal <kovid at kovidgoyal.net>

import re
from collections import namedtuple

from .utils import log_error
from .rgb import to_color as as_color

key_pat = re.compile(r'([a-zA-Z][a-zA-Z0-9_-]*)\s+(.+)$')


def to_color(x):
    return as_color(x, validate=True)


def positive_int(x):
    return max(0, int(x))


def positive_float(x):
    return max(0, float(x))


def unit_float(x):
    return max(0, min(float(x), 1))


def to_bool(x):
    return x.lower() in 'y yes true'.split()


def parse_config_base(
    lines, defaults, type_map, special_handling, ans, check_keys=True
):
    if check_keys:
        all_keys = defaults._asdict()
    for line in lines:
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        m = key_pat.match(line)
        if m is not None:
            key, val = m.groups()
            if special_handling(key, val, ans):
                continue
            if check_keys:
                if key not in all_keys:
                    log_error('Ignoring unknown config key: {}'.format(key))
                    continue
            tm = type_map.get(key)
            if tm is not None:
                val = tm(val)
            ans[key] = val


def init_config(defaults_path, parse_config):
    with open(defaults_path, encoding='utf-8') as f:
        defaults = parse_config(f.read().splitlines(), check_keys=False)
    Options = namedtuple('Defaults', ','.join(defaults.keys()))
    defaults = Options(**defaults)
    return Options, defaults
