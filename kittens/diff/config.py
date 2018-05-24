#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2018, Kovid Goyal <kovid at kovidgoyal.net>

import os

from kitty.config_utils import (
    init_config, key_func, load_config as _load_config, merge_dicts,
    parse_config_base, parse_kittens_key, python_string, resolve_config,
    to_color
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
    formats['text'] = '48' + color_as_sgr(opts.background)
    formats['title'] = '38' + color_as_sgr(opts.title_fg) + ';48' + color_as_sgr(opts.title_bg) + ';1'
    formats['margin'] = '38' + color_as_sgr(opts.margin_fg) + ';48' + color_as_sgr(opts.margin_bg)
    formats['added_margin'] = '38' + color_as_sgr(opts.margin_fg) + ';48' + color_as_sgr(opts.added_margin_bg)
    formats['removed_margin'] = '38' + color_as_sgr(opts.margin_fg) + ';48' + color_as_sgr(opts.removed_margin_bg)
    formats['added'] = '48' + color_as_sgr(opts.added_bg)
    formats['removed'] = '48' + color_as_sgr(opts.removed_bg)
    formats['filler'] = '48' + color_as_sgr(opts.filler_bg)
    formats['hunk_margin'] = '38' + color_as_sgr(opts.margin_fg) + ';48' + color_as_sgr(opts.hunk_margin_bg)
    formats['hunk'] = '38' + color_as_sgr(opts.margin_fg) + ';48' + color_as_sgr(opts.hunk_bg)
    formats['removed_highlight'] = '48' + color_as_sgr(opts.highlight_removed_bg)
    formats['added_highlight'] = '48' + color_as_sgr(opts.highlight_added_bg)


def syntax_aliases(raw):
    ans = {}
    for x in raw.split():
        a, b = x.partition(':')[::2]
        if a and b:
            ans[a.lower()] = b
    return ans


type_map = {
    'syntax_aliases': syntax_aliases,
    'num_context_lines': int,
    'replace_tab_by': python_string,
}

for name in (
    'foreground background title_fg title_bg margin_bg margin_fg removed_bg removed_margin_bg added_bg added_margin_bg filler_bg hunk_bg hunk_margin_bg'
    ' highlight_removed_bg highlight_added_bg'
).split():
    type_map[name] = to_color
func_with_args, args_funcs = key_func()


@func_with_args('scroll_by')
def parse_scroll_by(func, rest):
    try:
        return func, int(rest)
    except Exception:
        return func, 1


@func_with_args('scroll_to')
def parse_scroll_to(func, rest):
    rest = rest.lower()
    if rest not in {'start', 'end', 'next-change', 'prev-change', 'next-page', 'prev-page'}:
        rest = 'start'
    return func, rest


@func_with_args('change_context')
def parse_change_context(func, rest):
    rest = rest.lower()
    if rest in {'all', 'default'}:
        return func, rest
    try:
        amount = int(rest)
    except Exception:
        amount = 5
    return func, amount


def special_handling(key, val, ans):
    if key == 'map':
        action, *key_def = parse_kittens_key(val, args_funcs)
        ans['key_definitions'][tuple(key_def)] = action
        return True


def parse_config(lines, check_keys=True):
    ans = {'key_definitions': {}}
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
