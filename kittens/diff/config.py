#!/usr/bin/env python3
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2018, Kovid Goyal <kovid at kovidgoyal.net>

import os
from typing import Any, Dict, Iterable, Optional

from kitty.cli_stub import DiffCLIOptions
from kitty.conf.utils import (
    load_config as _load_config, parse_config_base, resolve_config
)
from kitty.constants import config_dir
from kitty.rgb import color_as_sgr

from .options.types import Options as DiffOptions, defaults

formats: Dict[str, str] = {
    'title': '',
    'margin': '',
    'text': '',
}


def set_formats(opts: DiffOptions) -> None:
    formats['text'] = '48' + color_as_sgr(opts.background)
    formats['title'] = '38' + color_as_sgr(opts.title_fg) + ';48' + color_as_sgr(opts.title_bg) + ';1'
    formats['margin'] = '38' + color_as_sgr(opts.margin_fg) + ';48' + color_as_sgr(opts.margin_bg)
    formats['added_margin'] = '38' + color_as_sgr(opts.margin_fg) + ';48' + color_as_sgr(opts.added_margin_bg)
    formats['removed_margin'] = '38' + color_as_sgr(opts.margin_fg) + ';48' + color_as_sgr(opts.removed_margin_bg)
    formats['added'] = '48' + color_as_sgr(opts.added_bg)
    formats['removed'] = '48' + color_as_sgr(opts.removed_bg)
    formats['filler'] = '48' + color_as_sgr(opts.filler_bg)
    formats['margin_filler'] = '48' + color_as_sgr(opts.margin_filler_bg or opts.filler_bg)
    formats['hunk_margin'] = '38' + color_as_sgr(opts.margin_fg) + ';48' + color_as_sgr(opts.hunk_margin_bg)
    formats['hunk'] = '38' + color_as_sgr(opts.margin_fg) + ';48' + color_as_sgr(opts.hunk_bg)
    formats['removed_highlight'] = '48' + color_as_sgr(opts.highlight_removed_bg)
    formats['added_highlight'] = '48' + color_as_sgr(opts.highlight_added_bg)


SYSTEM_CONF = '/etc/xdg/kitty/diff.conf'
defconf = os.path.join(config_dir, 'diff.conf')


def load_config(*paths: str, overrides: Optional[Iterable[str]] = None) -> DiffOptions:
    from .options.parse import (
        create_result_dict, merge_result_dicts, parse_conf_item
    )

    def parse_config(lines: Iterable[str]) -> Dict[str, Any]:
        ans: Dict[str, Any] = create_result_dict()
        parse_config_base(
            lines,
            parse_conf_item,
            ans,
        )
        return ans

    overrides = tuple(overrides) if overrides is not None else ()
    opts_dict, paths = _load_config(defaults, parse_config, merge_result_dicts, *paths, overrides=overrides)
    opts = DiffOptions(opts_dict)
    opts.config_paths = paths
    opts.config_overrides = overrides
    return opts


def init_config(args: DiffCLIOptions) -> DiffOptions:
    config = tuple(resolve_config(SYSTEM_CONF, defconf, args.config))
    overrides = (a.replace('=', ' ', 1) for a in args.override or ())
    opts = load_config(*config, overrides=overrides)
    set_formats(opts)
    for (sc, action) in opts.map:
        opts.key_definitions[sc] = action
    return opts
