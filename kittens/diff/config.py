#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2018, Kovid Goyal <kovid at kovidgoyal.net>

import os

from kitty.config_utils import (
    init_config, load_config as _load_config, merge_dicts, parse_config_base,
    resolve_config, to_color
)
from kitty.constants import config_dir
from kitty.rgb import color_as_sgr

defaults = None
default_config_path = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), 'diff.conf'
)

formats = {
    'title': '',
    'margin': '',
    'text': '',
}


def set_formats(opts):
    formats['text'] = '38' + color_as_sgr(opts.foreground) + ';48' + color_as_sgr(opts.background)
    formats['title'] = '38' + color_as_sgr(opts.title_fg) + ';48' + color_as_sgr(opts.title_bg) + ';1'
    formats['margin'] = '38' + color_as_sgr(opts.margin_fg) + ';48' + color_as_sgr(opts.margin_bg)
    formats['added_margin'] = '38' + color_as_sgr(opts.margin_fg) + ';48' + color_as_sgr(opts.added_margin_bg)
    formats['removed_margin'] = '38' + color_as_sgr(opts.margin_fg) + ';48' + color_as_sgr(opts.removed_margin_bg)
    formats['added'] = '38' + color_as_sgr(opts.foreground) + ';48' + color_as_sgr(opts.added_bg)
    formats['removed'] = '38' + color_as_sgr(opts.foreground) + ';48' + color_as_sgr(opts.removed_bg)
    formats['filler'] = '48' + color_as_sgr(opts.filler_bg)
    formats['hunk_margin'] = '38' + color_as_sgr(opts.margin_fg) + ';48' + color_as_sgr(opts.hunk_margin_bg)
    formats['hunk'] = '38' + color_as_sgr(opts.margin_fg) + ';48' + color_as_sgr(opts.hunk_bg)
    formats['removed_highlight'] = '48' + color_as_sgr(opts.highlight_removed_bg)
    formats['added_highlight'] = '48' + color_as_sgr(opts.highlight_added_bg)


type_map = {}

for name in (
    'foreground background title_fg title_bg margin_bg margin_fg removed_bg removed_margin_bg added_bg added_margin_bg filler_bg hunk_bg hunk_margin_bg'
    ' highlight_removed_bg highlight_added_bg'
).split():
    type_map[name] = to_color


def special_handling(*a):
    pass


def parse_config(lines, check_keys=True):
    ans = {}
    parse_config_base(
        lines,
        defaults,
        type_map,
        special_handling,
        ans,
        check_keys=check_keys
    )
    return ans


def merge_configs(defaults, vals):
    ans = {}
    for k, v in defaults.items():
        if isinstance(v, dict):
            newvals = vals.get(k, {})
            ans[k] = merge_dicts(v, newvals)
        else:
            ans[k] = vals.get(k, v)
    return ans


def parse_defaults(lines, check_keys=False):
    return parse_config(lines, check_keys)


Options, defaults = init_config(default_config_path, parse_defaults)


def load_config(*paths, overrides=None):
    return _load_config(Options, defaults, parse_config, merge_configs, *paths, overrides=overrides)


SYSTEM_CONF = '/etc/xdg/kitty/diff.conf'
defconf = os.path.join(config_dir, 'diff.conf')


def init_config(args):
    config = tuple(resolve_config(SYSTEM_CONF, defconf, args.config))
    overrides = (a.replace('=', ' ', 1) for a in args.override or ())
    opts = load_config(*config, overrides=overrides)
    set_formats(opts)
    return opts
