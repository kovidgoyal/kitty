#!/usr/bin/env python
# License: GPLv3 Copyright: 2022, Kovid Goyal <kovid at kovidgoyal.net>


import fnmatch
import os
from typing import Any, Dict, Iterable, Optional

from kitty.conf.utils import (
    load_config as _load_config, parse_config_base, resolve_config
)
from kitty.constants import config_dir

from .options.types import Options as SSHOptions, defaults, option_names

SYSTEM_CONF = '/etc/xdg/kitty/ssh.conf'
defconf = os.path.join(config_dir, 'ssh.conf')


def host_matches(pat: str, hostname: str, username: str) -> bool:
    upat = '*'
    if '@' in pat:
        upat, pat = pat.split('@', 1)
    return fnmatch.fnmatchcase(hostname, pat) and fnmatch.fnmatchcase(username, upat)


def options_for_host(hostname: str, username: str, per_host_opts: Dict[str, SSHOptions]) -> SSHOptions:
    matches = []
    for spat, opts in per_host_opts.items():
        for pat in spat.split():
            if host_matches(pat, hostname, username):
                matches.append(opts)
    if not matches:
        return SSHOptions({})
    base = matches[0]
    rest = matches[1:]
    if rest:
        ans = SSHOptions(base._asdict())
        for name in option_names:
            for opts in rest:
                val = getattr(opts, name)
                if isinstance(val, dict):
                    getattr(ans, name).update(val)
                else:
                    setattr(ans, name, val)
    else:
        ans = base
    return ans


def load_config(*paths: str, overrides: Optional[Iterable[str]] = None) -> Dict[str, SSHOptions]:
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
    ans: Dict[str, SSHOptions] = {}
    phd = get_per_hosts_dict(opts_dict)
    for hostname in sorted(phd, key=first_seen_positions.__getitem__):
        opts = SSHOptions(phd[hostname])
        opts.config_paths = paths
        opts.config_overrides = overrides
        ans[hostname] = opts
    first_seen_positions.clear()
    return ans


def init_config() -> Dict[str, SSHOptions]:
    config = tuple(resolve_config(SYSTEM_CONF, defconf))
    opts_dict = load_config(*config)
    return opts_dict
