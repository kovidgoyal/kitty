#!/usr/bin/env python
# License: GPLv3 Copyright: 2022, Kovid Goyal <kovid at kovidgoyal.net>


import os
from typing import Any, Dict, Iterable, Optional

from kitty.conf.utils import (
    load_config as _load_config, parse_config_base, resolve_config
)
from kitty.constants import config_dir

from .options.types import Options as SSHOptions, defaults

SYSTEM_CONF = '/etc/xdg/kitty/ssh.conf'
defconf = os.path.join(config_dir, 'ssh.conf')


def load_config(*paths: str, overrides: Optional[Iterable[str]] = None) -> Dict[str, SSHOptions]:
    from .options.parse import (
        create_result_dict, merge_result_dicts, parse_conf_item
    )
    from .options.utils import init_results_dict

    def parse_config(lines: Iterable[str]) -> Dict[str, Any]:
        ans: Dict[str, Any] = init_results_dict(create_result_dict())
        parse_config_base(lines, parse_conf_item, ans)
        return ans

    overrides = tuple(overrides) if overrides is not None else ()
    opts_dict, paths = _load_config(defaults, parse_config, merge_result_dicts, *paths, overrides=overrides)
    ans: Dict[str, SSHOptions] = {}
    for hostname, host_opts_dict in opts_dict['per_host_dicts'].items():
        opts = SSHOptions(host_opts_dict)
        opts.config_paths = paths
        opts.config_overrides = overrides
        ans[hostname] = opts
    return ans


def init_config() -> Dict[str, SSHOptions]:
    config = tuple(resolve_config(SYSTEM_CONF, defconf))
    opts_dict = load_config(*config)
    return opts_dict
