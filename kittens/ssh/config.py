#!/usr/bin/env python
# License: GPLv3 Copyright: 2022, Kovid Goyal <kovid at kovidgoyal.net>


import fnmatch
import os
from typing import Any, Dict, Iterable, Optional

from kitty.conf.utils import (
    load_config as _load_config, parse_config_base, resolve_config
)
from kitty.constants import config_dir

from .options.types import Options as SSHOptions, defaults

SYSTEM_CONF = '/etc/xdg/kitty/ssh.conf'
defconf = os.path.join(config_dir, 'ssh.conf')


def host_matches(mpat: str, hostname: str, username: str) -> bool:
    for pat in mpat.split():
        upat = '*'
        if '@' in pat:
            upat, pat = pat.split('@', 1)
        if fnmatch.fnmatchcase(hostname, pat) and fnmatch.fnmatchcase(username, upat):
            return True
    return False


def load_config(*paths: str, overrides: Optional[Iterable[str]] = None, hostname: str = '!', username: str = '') -> SSHOptions:
    from .options.parse import (
        create_result_dict, merge_result_dicts, parse_conf_item
    )
    from .options.utils import (
        first_seen_positions, get_per_hosts_dict, init_results_dict
    )

    def merge_dicts(base: Dict[str, Any], vals: Dict[str, Any]) -> Dict[str, Any]:
        base_phd = get_per_hosts_dict(base)
        vals_phd = get_per_hosts_dict(vals)
        for hostname in base_phd:
            vals_phd[hostname] = merge_result_dicts(base_phd[hostname], vals_phd.get(hostname, {}))
        ans: Dict[str, Any] = vals_phd.pop(vals['hostname'])
        ans['per_host_dicts'] = vals_phd
        return ans

    def parse_config(lines: Iterable[str]) -> Dict[str, Any]:
        ans: Dict[str, Any] = init_results_dict(create_result_dict())
        parse_config_base(lines, parse_conf_item, ans)
        return ans

    overrides = tuple(overrides) if overrides is not None else ()
    first_seen_positions.clear()
    first_seen_positions['*'] = 0
    opts_dict, paths = _load_config(
        defaults, parse_config, merge_dicts, *paths, overrides=overrides, initialize_defaults=init_results_dict)
    phd = get_per_hosts_dict(opts_dict)
    final_dict: Dict[str, Any] = {}
    for hostname_pat in sorted(phd, key=first_seen_positions.__getitem__):
        if host_matches(hostname_pat, hostname, username):
            od = phd[hostname_pat]
            for k, v in od.items():
                if isinstance(v, dict):
                    bv = final_dict.setdefault(k, {})
                    bv.update(v)
                else:
                    final_dict[k] = v
    first_seen_positions.clear()
    return SSHOptions(final_dict)


def init_config(hostname: str, username: str, overrides: Optional[Iterable[str]] = None) -> SSHOptions:
    config = tuple(resolve_config(SYSTEM_CONF, defconf))
    return load_config(*config, overrides=overrides, hostname=hostname, username=username)
