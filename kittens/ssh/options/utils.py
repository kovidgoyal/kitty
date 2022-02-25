#!/usr/bin/env python
# License: GPLv3 Copyright: 2022, Kovid Goyal <kovid at kovidgoyal.net>

from typing import Any, Dict, Optional


def init_results_dict(ans: Dict[str, Any]) -> Dict[str, Any]:
    ans['current_hostname'] = '*'
    ans['current_host_dict'] = chd = {'hostname': '*'}
    ans['per_host_dicts'] = {'*': chd}
    return ans


ignored_dict_keys = tuple(init_results_dict({}))


def hostname(val: str, dict_with_parse_results: Optional[Dict[str, Any]] = None) -> str:
    if dict_with_parse_results is not None:
        ch = dict_with_parse_results['current_hostname']
        if val != ch:
            hd = dict_with_parse_results.copy()
            for k in ignored_dict_keys:
                del hd[k]
            phd = dict_with_parse_results['per_host_dicts']
            phd[ch] = hd
            dict_with_parse_results.clear()
            dict_with_parse_results['per_host_dicts'] = phd
            dict_with_parse_results['current_hostname'] = val
            dict_with_parse_results['current_host_dict'] = phd.setdefault(val, {'hostname': val})
    return val
