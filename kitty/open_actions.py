#!/usr/bin/env python
# License: GPLv3 Copyright: 2020, Kovid Goyal <kovid at kovidgoyal.net>


import os
import posixpath
import shlex
from collections.abc import Iterable, Iterator
from contextlib import suppress
from typing import Any, NamedTuple, cast
from urllib.parse import ParseResult, unquote, urlparse

from .conf.utils import KeyAction, to_cmdline_implementation
from .constants import config_dir
from .fast_data_types import get_options
from .guess_mime_type import guess_type
from .options.utils import ActionAlias, MapType, resolve_aliases_and_parse_actions
from .types import run_once
from .typing_compat import MatchType
from .utils import expandvars, get_editor, log_error, resolved_shell


class MatchCriteria(NamedTuple):
    type: MatchType
    value: str


class OpenAction(NamedTuple):
    match_criteria: tuple[MatchCriteria, ...]
    actions: tuple[KeyAction, ...]


def parse(lines: Iterable[str]) -> Iterator[OpenAction]:
    match_criteria: list[MatchCriteria] = []
    raw_actions: list[str] = []
    alias_map: dict[str, list[ActionAlias]] = {}
    entries = []

    for line in lines:
        line = line.strip()
        if line.startswith('#'):
            continue
        if not line:
            if match_criteria and raw_actions:
                entries.append((tuple(match_criteria), tuple(raw_actions)))
            match_criteria = []
            raw_actions = []
            continue
        parts = line.split(maxsplit=1)
        if len(parts) != 2:
            continue
        key, rest = parts
        key = key.lower()
        if key == 'action':
            raw_actions.append(rest)
        elif key in ('mime', 'ext', 'protocol', 'file', 'path', 'url', 'fragment_matches'):
            if key != 'url':
                rest = rest.lower()
            match_criteria.append(MatchCriteria(cast(MatchType, key), rest))
        elif key == 'action_alias':
            try:
                alias_name, alias_val = rest.split(maxsplit=1)
            except Exception:
                continue
            alias_map[alias_name] = [ActionAlias(alias_name, alias_val)]
        else:
            log_error(f'Ignoring malformed open actions line: {line}')

    if match_criteria and raw_actions:
        entries.append((tuple(match_criteria), tuple(raw_actions)))

    with to_cmdline_implementation.filter_env_vars(
        'URL', 'FILE_PATH', 'FILE', 'FRAGMENT', 'URL_PATH', 'NETLOC',
        EDITOR=shlex.join(get_editor()),
        SHELL=resolved_shell(get_options())[0]
    ):
        for (mc, action_defns) in entries:
            actions: list[KeyAction] = []
            for defn in action_defns:
                actions.extend(resolve_aliases_and_parse_actions(defn, alias_map, MapType.OPEN_ACTION))
            yield OpenAction(mc, tuple(actions))


def url_matches_criterion(purl: 'ParseResult', url: str, unquoted_path: str, mc: MatchCriteria) -> bool:
    if mc.type == 'url':
        import re
        try:
            pat = re.compile(mc.value)
        except re.error:
            return False
        return pat.search(unquote(url)) is not None

    if mc.type == 'mime':
        import fnmatch
        mt = guess_type(unquoted_path, allow_filesystem_access=purl.scheme in ('', 'file'))
        if not mt:
            return False
        mt = mt.lower()
        for mpat in mc.value.split(','):
            mpat = mpat.strip()
            with suppress(Exception):
                if fnmatch.fnmatchcase(mt, mpat):
                    return True
        return False

    if mc.type == 'ext':
        if not purl.path:
            return False
        path = unquoted_path.lower()
        for ext in mc.value.split(','):
            ext = ext.strip()
            if path.endswith(f'.{ext}'):
                return True
        return False

    if mc.type == 'protocol':
        protocol = (purl.scheme or 'file').lower()
        for key in mc.value.split(','):
            if key.strip() == protocol:
                return True
        return False

    if mc.type == 'fragment_matches':
        import re
        try:
            pat = re.compile(mc.value)
        except re.error:
            return False

        return pat.search(unquote(purl.fragment)) is not None

    if mc.type == 'path':
        import fnmatch
        try:
            return fnmatch.fnmatchcase(unquoted_path.lower(), mc.value)
        except Exception:
            return False

    if mc.type == 'file':
        import fnmatch
        try:
            fname = posixpath.basename(unquoted_path)
        except Exception:
            return False
        try:
            return fnmatch.fnmatchcase(fname.lower(), mc.value)
        except Exception:
            return False


def url_matches_criteria(purl: 'ParseResult', url: str, unquoted_path: str, criteria: Iterable[MatchCriteria]) -> bool:
    for x in criteria:
        try:
            if not url_matches_criterion(purl, url, unquoted_path, x):
                return False
        except Exception:
            return False
    return True


def actions_for_url_from_list(url: str, actions: Iterable[OpenAction]) -> Iterator[KeyAction]:
    try:
        purl = urlparse(url)
    except Exception:
        return
    path = unquote(purl.path)
    up = purl.path
    netloc = unquote(purl.netloc) if purl.netloc else ''
    if purl.query:
        up += f'?{purl.query}'
    frag = unquote(purl.fragment) if purl.fragment else ''
    if frag:
        up += f'#{purl.fragment}'

    env = {
        'URL': url,
        'FILE_PATH': path,
        'URL_PATH': up,
        'FILE': posixpath.basename(path),
        'FRAGMENT': frag,
        'NETLOC': netloc,
    }

    def expand(x: Any) -> Any:
        as_bytes = isinstance(x, bytes)
        if as_bytes:
            x = x.decode('utf-8')
        if isinstance(x, str):
            ans = expandvars(x, env, fallback_to_os_env=False)
            if as_bytes:
                return ans.encode('utf-8')
            return ans
        return x

    for action in actions:
        if url_matches_criteria(purl, url, path, action.match_criteria):
            for ac in action.actions:
                yield ac._replace(args=tuple(map(expand, ac.args)))
            return


actions_cache: dict[str, tuple[os.stat_result, tuple[OpenAction, ...]]] = {}


def load_actions_from_path(path: str) -> tuple[OpenAction, ...]:
    try:
        st = os.stat(path)
    except OSError:
        return ()
    x = actions_cache.get(path)
    if x is None or x[0].st_mtime != st.st_mtime:
        with open(path) as f:
            actions_cache[path] = st, tuple(parse(f))
    else:
        return x[1]
    return actions_cache[path][1]


def load_open_actions() -> tuple[OpenAction, ...]:
    return load_actions_from_path(os.path.join(config_dir, 'open-actions.conf'))


def load_launch_actions() -> tuple[OpenAction, ...]:
    return load_actions_from_path(os.path.join(config_dir, 'launch-actions.conf'))


def clear_caches() -> None:
    actions_cache.clear()


@run_once
def default_open_actions() -> tuple[OpenAction, ...]:
    return tuple(parse('''\
# Open kitty HTML docs links
protocol kitty+doc
action show_kitty_doc $URL_PATH
'''.splitlines()))


@run_once
def default_launch_actions() -> tuple[OpenAction, ...]:
    return tuple(parse('''\
# Open script files. Change confirm-always to confirm-never or confirm-if-needed to
# disable confirmation for all or executable files respectively.
protocol file
ext sh,command,tool
action launch --hold --type=os-window kitten __shebang__ confirm-always $FILE_PATH $SHELL

# Open shell specific script files
protocol file
ext fish,bash,zsh
action launch --hold --type=os-window kitten __shebang__ confirm-always $FILE_PATH __ext__

# Open directories
protocol file
mime inode/directory
action launch --type=os-window --cwd -- $FILE_PATH

# Open executable file. Remove kitten __confirm_and_run_exe__ to execute
# without confirmation.
protocol file
mime inode/executable,application/vnd.microsoft.portable-executable
action launch --hold --type=os-window -- kitten __confirm_and_run_exe__ $FILE_PATH

# Open text files without fragments in the editor
protocol file
mime text/*
action launch --type=os-window -- $EDITOR -- $FILE_PATH

# Open image files with icat
protocol file
mime image/*
action launch --type=os-window kitten icat --hold -- $FILE_PATH

# Open ssh URLs with ssh command
protocol ssh
action launch --type=os-window ssh -- $URL
'''.splitlines()))


def actions_for_url(url: str, actions_spec: str | None = None) -> Iterator[KeyAction]:
    if actions_spec is None:
        actions = load_open_actions()
    else:
        actions = tuple(parse(actions_spec.splitlines()))
    found = False
    for action in actions_for_url_from_list(url, actions):
        found = True
        yield action
    if not found:
        yield from actions_for_url_from_list(url, default_open_actions())


def actions_for_launch(url: str) -> Iterator[KeyAction]:
    # Custom launch actions using kitty URL scheme needs to be prefixed with `kitty:///launch/`
    if url.startswith('kitty://') and not url.startswith('kitty:///launch/'):
        return
    found = False
    for action in actions_for_url_from_list(url, load_launch_actions()):
        found = True
        yield action
    if not found:
        yield from actions_for_url_from_list(url, default_launch_actions())
