#!/usr/bin/env python3
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2018, Kovid Goyal <kovid at kovidgoyal.net>

import os
from typing import Any, Dict, FrozenSet, Iterable, Optional, Tuple, Type, Union

from kitty.cli_stub import DiffCLIOptions
from kitty.conf.definition import config_lines
from kitty.conf.utils import (
    init_config as _init_config, key_func, load_config as _load_config,
    merge_dicts, parse_config_base, parse_kittens_key, resolve_config
)
from kitty.constants import config_dir
from kitty.options_stub import DiffOptions
from kitty.rgb import color_as_sgr

from .config_data import all_options

defaults: Optional[DiffOptions] = None

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


func_with_args, args_funcs = key_func()


@func_with_args('scroll_by')
def parse_scroll_by(func: str, rest: str) -> Tuple[str, int]:
    try:
        return func, int(rest)
    except Exception:
        return func, 1


@func_with_args('scroll_to')
def parse_scroll_to(func: str, rest: str) -> Tuple[str, str]:
    rest = rest.lower()
    if rest not in {'start', 'end', 'next-change', 'prev-change', 'next-page', 'prev-page', 'next-match', 'prev-match'}:
        rest = 'start'
    return func, rest


@func_with_args('change_context')
def parse_change_context(func: str, rest: str) -> Tuple[str, Union[int, str]]:
    rest = rest.lower()
    if rest in {'all', 'default'}:
        return func, rest
    try:
        amount = int(rest)
    except Exception:
        amount = 5
    return func, amount


@func_with_args('start_search')
def parse_start_search(func: str, rest: str) -> Tuple[str, Tuple[bool, bool]]:
    rest_ = rest.lower().split()
    is_regex = bool(rest_ and rest_[0] == 'regex')
    is_backward = bool(len(rest_) > 1 and rest_[1] == 'backward')
    return func, (is_regex, is_backward)


def special_handling(key: str, val: str, ans: Dict) -> bool:
    if key == 'map':
        x = parse_kittens_key(val, args_funcs)
        if x is not None:
            action, key_def = x
            ans['key_definitions'][key_def] = action
            return True
    return False


def parse_config(lines: Iterable[str], check_keys: bool = True) -> Dict[str, Any]:
    ans: Dict[str, Any] = {'key_definitions': {}}
    defs: Optional[FrozenSet] = None
    if check_keys:
        defs = frozenset(defaults._fields)  # type: ignore

    parse_config_base(
        lines,
        defs,
        all_options,
        special_handling,
        ans,
    )
    return ans


def merge_configs(defaults: Dict, vals: Dict) -> Dict:
    ans = {}
    for k, v in defaults.items():
        if isinstance(v, dict):
            newvals = vals.get(k, {})
            ans[k] = merge_dicts(v, newvals)
        else:
            ans[k] = vals.get(k, v)
    return ans


def parse_defaults(lines: Iterable[str], check_keys: bool = False) -> Dict[str, Any]:
    return parse_config(lines, check_keys)


x = _init_config(config_lines(all_options), parse_defaults)
Options: Type[DiffOptions] = x[0]
defaults = x[1]


def load_config(*paths: str, overrides: Optional[Iterable[str]] = None) -> DiffOptions:
    return _load_config(Options, defaults, parse_config, merge_configs, *paths, overrides=overrides)


SYSTEM_CONF = '/etc/xdg/kitty/diff.conf'
defconf = os.path.join(config_dir, 'diff.conf')


def init_config(args: DiffCLIOptions) -> DiffOptions:
    config = tuple(resolve_config(SYSTEM_CONF, defconf, args.config))
    overrides = (a.replace('=', ' ', 1) for a in args.override or ())
    opts = load_config(*config, overrides=overrides)
    set_formats(opts)
    return opts
