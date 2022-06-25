#!/usr/bin/env python3
# License: GPL v3 Copyright: 2016, Kovid Goyal <kovid at kovidgoyal.net>

import json
import os
from contextlib import contextmanager, suppress
from functools import partial
from typing import Any, Dict, Generator, Iterable, List, Optional, Tuple

from .conf.utils import BadLine, load_config as _load_config, parse_config_base
from .constants import cache_dir, defconf
from .options.types import Options, defaults, option_names
from .options.utils import (
    KeyDefinition, KeyMap, MouseMap, MouseMapping, SequenceMap,
    build_action_aliases
)
from .typing import TypedDict
from .utils import log_error


def option_names_for_completion() -> Tuple[str, ...]:
    return option_names


def build_ansi_color_table(opts: Optional[Options] = None) -> int:
    if opts is None:
        opts = defaults
    addr, length = opts.color_table.buffer_info()
    if length != 256 or opts.color_table.typecode != 'L':
        raise TypeError(f'The color table has incorrect size length: {length} typecode: {opts.color_table.typecode}')
    return addr


def atomic_save(data: bytes, path: str) -> None:
    import shutil
    import tempfile
    path = os.path.realpath(path)
    fd, p = tempfile.mkstemp(dir=os.path.dirname(path), suffix='.tmp')
    try:
        with os.fdopen(fd, 'wb') as f:
            f.write(data)
        with suppress(FileNotFoundError):
            shutil.copystat(path, p)
        os.utime(p)
        os.replace(p, path)
    finally:
        try:
            os.remove(p)
        except FileNotFoundError:
            pass
        except Exception as err:
            log_error(f'Failed to delete temp file {p} for atomic save with error: {err}')


@contextmanager
def cached_values_for(name: str) -> Generator[Dict[str, Any], None, None]:
    cached_path = os.path.join(cache_dir(), f'{name}.json')
    cached_values: Dict[str, Any] = {}
    try:
        with open(cached_path, 'rb') as f:
            cached_values.update(json.loads(f.read().decode('utf-8')))
    except FileNotFoundError:
        pass
    except Exception as err:
        log_error(f'Failed to load cached in {name} values with error: {err}')

    yield cached_values

    try:
        data = json.dumps(cached_values).encode('utf-8')
        atomic_save(data, cached_path)
    except Exception as err:
        log_error(f'Failed to save cached values with error: {err}')


def commented_out_default_config() -> str:
    from .options.definition import definition
    return '\n'.join(definition.as_conf(commented=True))


def prepare_config_file_for_editing() -> str:
    if not os.path.exists(defconf):
        d = os.path.dirname(defconf)
        with suppress(FileExistsError):
            os.makedirs(d)
        with open(defconf, 'w', encoding='utf-8') as f:
            f.write(commented_out_default_config())
    return defconf


def finalize_keys(opts: Options, accumulate_bad_lines: Optional[List[BadLine]] = None) -> None:
    defns: List[KeyDefinition] = []
    for d in opts.map:
        if d is None:  # clear_all_shortcuts
            defns = []  # type: ignore
        else:
            try:
                defns.append(d.resolve_and_copy(opts.kitty_mod))
            except Exception as err:
                if accumulate_bad_lines is None:
                    log_error(f'Ignoring map with invalid action: {d.definition}. Error: {err}')
                else:
                    accumulate_bad_lines.append(BadLine(d.definition_location.number, d.definition_location.line, err, d.definition_location.file))

    keymap: KeyMap = {}
    sequence_map: SequenceMap = {}

    for defn in defns:
        is_no_op = defn.is_no_op
        if defn.is_sequence:
            keymap.pop(defn.trigger, None)
            s = sequence_map.setdefault(defn.trigger, {})
            if is_no_op:
                s.pop(defn.rest, None)
                if not s:
                    del sequence_map[defn.trigger]
            else:
                s[defn.rest] = defn.definition
        else:
            sequence_map.pop(defn.trigger, None)
            if is_no_op:
                keymap.pop(defn.trigger, None)
            else:
                keymap[defn.trigger] = defn.definition
    opts.keymap = keymap
    opts.sequence_map = sequence_map


def finalize_mouse_mappings(opts: Options, accumulate_bad_lines: Optional[List[BadLine]] = None) -> None:
    defns: List[MouseMapping] = []
    for d in opts.mouse_map:
        if d is None:  # clear_all_mouse_actions
            defns = []  # type: ignore
        else:
            try:
                defns.append(d.resolve_and_copy(opts.kitty_mod))
            except Exception as err:
                if accumulate_bad_lines is None:
                    log_error(f'Ignoring mouse_map with invalid action: {d.definition}. Error: {err}')
                else:
                    accumulate_bad_lines.append(BadLine(d.definition_location.number, d.definition_location.line, err, d.definition_location.file))
    mousemap: MouseMap = {}

    for defn in defns:
        is_no_op = defn.is_no_op
        if is_no_op:
            mousemap.pop(defn.trigger, None)
        else:
            mousemap[defn.trigger] = defn.definition
    opts.mousemap = mousemap


def parse_config(lines: Iterable[str], accumulate_bad_lines: Optional[List[BadLine]] = None) -> Dict[str, Any]:
    from .options.parse import create_result_dict, parse_conf_item
    ans: Dict[str, Any] = create_result_dict()
    parse_config_base(
        lines,
        parse_conf_item,
        ans,
        accumulate_bad_lines=accumulate_bad_lines
    )
    return ans


def load_config(*paths: str, overrides: Optional[Iterable[str]] = None, accumulate_bad_lines: Optional[List[BadLine]] = None) -> Options:
    from .options.parse import merge_result_dicts

    overrides = tuple(overrides) if overrides is not None else ()
    opts_dict, paths = _load_config(defaults, partial(parse_config, accumulate_bad_lines=accumulate_bad_lines), merge_result_dicts, *paths, overrides=overrides)
    opts = Options(opts_dict)

    opts.alias_map = build_action_aliases(opts.kitten_alias, 'kitten')
    opts.alias_map.update(build_action_aliases(opts.action_alias))
    finalize_keys(opts, accumulate_bad_lines)
    finalize_mouse_mappings(opts, accumulate_bad_lines)
    # delete no longer needed definitions, replacing with empty placeholders
    opts.kitten_alias = {}
    opts.action_alias = {}
    opts.mouse_map = []
    opts.map = []
    opts.config_paths = paths
    opts.config_overrides = overrides
    return opts


class KittyCommonOpts(TypedDict):
    select_by_word_characters: str
    open_url_with: List[str]
    url_prefixes: Tuple[str, ...]


def common_opts_as_dict(opts: Optional[Options] = None) -> KittyCommonOpts:
    if opts is None:
        opts = defaults
    return {
        'select_by_word_characters': opts.select_by_word_characters,
        'open_url_with': opts.open_url_with,
        'url_prefixes': opts.url_prefixes,
    }
