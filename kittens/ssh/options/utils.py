#!/usr/bin/env python
# License: GPLv3 Copyright: 2022, Kovid Goyal <kovid at kovidgoyal.net>

import posixpath
from typing import Any, Dict, Iterable, Optional, Tuple

from ..copy import CopyInstruction, parse_copy_instructions

DELETE_ENV_VAR = '_delete_this_env_var_'


def relative_dir(val: str) -> str:
    if posixpath.isabs(val):
        raise ValueError(f'Absolute paths not allowed. {val} is invalid.')
    base = '/ffjdg'
    q = posixpath.normpath(posixpath.join(base, val))
    if q == base or not q.startswith(base):
        raise ValueError(f'Paths that escape their parent dir are not allowed. {val} is not valid')
    return posixpath.normpath(val)


def env(val: str, current_val: Dict[str, str]) -> Iterable[Tuple[str, str]]:
    val = val.strip()
    if val:
        if '=' in val:
            key, v = val.split('=', 1)
            key, v = key.strip(), v.strip()
            if key:
                yield key, v
        else:
            yield val, DELETE_ENV_VAR


def copy(val: str, current_val: Dict[str, str]) -> Iterable[Tuple[str, CopyInstruction]]:
    yield from parse_copy_instructions(val, current_val)


def init_results_dict(ans: Dict[str, Any]) -> Dict[str, Any]:
    ans['hostname'] = '*'
    ans['per_host_dicts'] = {}
    return ans


def get_per_hosts_dict(results_dict: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    ans: Dict[str, Dict[str, Any]] = results_dict.get('per_host_dicts', {}).copy()
    h = results_dict['hostname']
    hd = {k: v for k, v in results_dict.items() if k != 'per_host_dicts'}
    ans[h] = hd
    return ans


first_seen_positions: Dict[str, int] = {}


def hostname(val: str, dict_with_parse_results: Optional[Dict[str, Any]] = None) -> str:
    if dict_with_parse_results is not None:
        ch = dict_with_parse_results['hostname']
        if val != ch:
            from .parse import create_result_dict
            phd = get_per_hosts_dict(dict_with_parse_results)
            dict_with_parse_results.clear()
            dict_with_parse_results.update(phd.pop(val, create_result_dict()))
            dict_with_parse_results['per_host_dicts'] = phd
            dict_with_parse_results['hostname'] = val
            if val not in first_seen_positions:
                first_seen_positions[val] = len(first_seen_positions)
    return val
