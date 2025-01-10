#!/usr/bin/env python
# License: GPLv3 Copyright: 2021, Kovid Goyal <kovid at kovidgoyal.net>

import builtins
import re
import textwrap
import typing
from collections.abc import Callable, Iterable, Iterator
from functools import lru_cache
from importlib import import_module
from re import Match
from typing import Any, Optional, Union, cast

import kitty.conf.utils as generic_parsers
from kitty.constants import website_url
from kitty.types import run_once

if typing.TYPE_CHECKING:
    Only = typing.Literal['macos', 'linux', '']
else:
    Only = str


class Unset:
    def __bool__(self) -> bool:
        return False


unset = Unset()
ParserFuncType = Callable[[str], Any]


def expand_opt_references(conf_name: str, text: str) -> str:
    conf_name += '.'

    def expand(m: 'Match[str]') -> str:
        ref = m.group(1)
        if '<' not in ref and '.' not in ref:
            # full ref
            return f':opt:`{ref} <{conf_name}{ref}>`'
        return str(m.group())

    return re.sub(r':opt:`(.+?)`', expand, text)


@run_once
def ref_map() -> dict[str, dict[str, str]]:
    import json

    from ..fast_data_types import get_docs_ref_map
    ans: dict[str, dict[str, str]] = json.loads(get_docs_ref_map())
    return ans


def resolve_ref(ref: str, website_url: Callable[[str], str] = website_url) -> str:
    m = ref_map()
    href = m['ref'].get(ref, '')
    prefix, rest = ref.partition('-')[::2]
    if href:
        pass
    elif ref.startswith('conf-kitty-'):
        href = f'conf#{ref}'
    elif ref.startswith('conf-kitten-'):
        parts = ref.split('-')
        href = "kittens/" + parts[2] + f'/#{ref}'
    elif ref.startswith('at_'):
        base = ref.split('_', 1)[1]
        href = "remote-control/#at-" + base.replace('_', '-')
    elif ref.startswith('at-'):
        base = ref.split('-', 1)[1]
        href = "remote-control/#at-" + base.replace('_', '-')
    elif ref.startswith('action-group-'):
        href = f'actions/#{ref}'
    elif prefix == 'action':
        href = f'actions/#{rest.replace("_", "-")}'
    elif prefix in ('term', 'envvar'):
        href = 'glossary/#' + ref
    elif prefix == 'doc':
        href = rest.lstrip('/')
    elif prefix in ('issues', 'pull', 'discussions'):
        t, num = ref.partition(':')[::2]
        href = f'https://github.com/kovidgoyal/kitty/{prefix}/{rest}'
    if not (href.startswith('https://') or href.startswith('http://')):
        href = website_url(href)
    return href


def remove_markup(text: str) -> str:

    imap = {'iss': 'issues-', 'pull': 'pull-', 'disc': 'discussions-'}

    def extract(m: 'Match[str]') -> tuple[str, str]:
        parts = m.group(2).split('<')
        t = parts[0].strip()
        q = parts[-1].rstrip('>')
        return t, q

    def sub(m: 'Match[str]') -> str:
        key = m.group(1)
        if key in ('ref', 'iss', 'pull', 'disc'):
            t, q = extract(m)
            q = imap.get(key, '') + q
            url = resolve_ref(q)
            if not url:
                raise KeyError(f'Failed to resolve :{m.group(1)}: {q}')
            return f'{t} <{url}>'
        if key == 'doc':
            t, q = extract(m)
            return f'{t} <{website_url(q)}>'
        if key in ('term', 'option'):
            t, _ = extract(m)
            return t
        if key in ('ac', 'opt'):
            t, q = extract(m)
            return f'{t} {q}' if q and q != t else t
        if key == 'code':
            return m.group(2).replace('\\\\', '\\')

        return str(m.group(2))

    return re.sub(r':([a-zA-Z0-9]+):`(.+?)`', sub, text, flags=re.DOTALL)


def strip_inline_literal(text: str) -> str:
    return re.sub(r'``([^`]+)``', r'`\1`', text, flags=re.DOTALL)


def iter_blocks(lines: Iterable[str]) -> Iterator[tuple[list[str], int]]:
    current_block: list[str] = []
    prev_indent = 0
    for line in lines:
        indent_size = len(line) - len(line.lstrip())
        if indent_size != prev_indent or not line:
            if current_block:
                yield current_block, prev_indent
            current_block = []
        prev_indent = indent_size
        if not line:
            yield [''], 100
        else:
            current_block.append(line)
    if current_block:
        yield current_block, indent_size


@lru_cache(maxsize=8)
def block_wrapper(comment_symbol: str) -> textwrap.TextWrapper:
    return textwrap.TextWrapper(
            initial_indent=comment_symbol, subsequent_indent=comment_symbol, width=70, break_long_words=False
        )


def wrapped_block(lines: Iterable[str], comment_symbol: str = '#: ') -> Iterator[str]:
    wrapper = block_wrapper(comment_symbol)
    for block, indent_size in iter_blocks(lines):
        if indent_size > 0:
            for line in block:
                if not line:
                    yield line
                else:
                    yield comment_symbol + line
        else:
            for line in wrapper.wrap('\n'.join(block)):
                yield line


def render_block(text: str, comment_symbol: str = '#: ') -> str:
    text = remove_markup(text)
    text = strip_inline_literal(text)
    lines = text.splitlines()
    return '\n'.join(wrapped_block(lines, comment_symbol))


class CoalescedIteratorData:

    option_groups: dict[int, list['Option']] = {}
    action_groups: dict[str, list['Mapping']] = {}
    coalesced: set[int] = set()
    initialized: bool = False
    kitty_mod: str = 'kitty_mod'

    def initialize(self, root: 'Group') -> None:
        if self.initialized:
            return
        self.root = root
        option_groups = self.option_groups = {}
        current_group: list[Option] = []
        action_groups: dict[str, list[Mapping]] = {}
        self.action_groups = action_groups
        coalesced = self.coalesced = set()
        self.kitty_mod = 'kitty_mod'
        for item in root.iter_all_non_groups():
            if isinstance(item, Option):
                if item.name == 'kitty_mod':
                    self.kitty_mod = item.defval_as_string
                if current_group:
                    if item.needs_coalescing:
                        current_group.append(item)
                        coalesced.add(id(item))
                        continue
                    option_groups[id(current_group[0])] = current_group[1:]
                    current_group = [item]
                else:
                    current_group.append(item)
            elif isinstance(item, Mapping):
                if item.name in action_groups:
                    coalesced.add(id(item))
                    action_groups[item.name].append(item)
                else:
                    action_groups[item.name] = []
        if current_group:
            option_groups[id(current_group[0])] = current_group[1:]

    def option_group_for_option(self, opt: 'Option') -> list['Option']:
        return self.option_groups.get(id(opt), [])

    def action_group_for_action(self, ac: 'Mapping') -> list['Mapping']:
        return self.action_groups.get(ac.name, [])


class Option:

    def __init__(
        self, name: str, defval: str, macos_default: Unset | str, parser_func: ParserFuncType,
        long_text: str, documented: bool, group: 'Group', choices: tuple[str, ...], ctype: str,
        has_secret: bool = False,
    ):
        self.name = name
        self.ctype = ctype
        self.defval_as_string = defval
        self.macos_defval = macos_default
        self.long_text = long_text
        self.documented = documented
        self.group = group
        self.parser_func = parser_func
        self.choices = choices
        self.has_secret = has_secret

    @property
    def needs_coalescing(self) -> bool:
        return self.documented and not self.long_text

    @property
    def is_color_table_color(self) -> bool:
        return self.name.startswith('color') and self.name[5:].isdigit()

    def as_conf(self, commented: bool = False, level: int = 0, option_group: list['Option'] = []) -> list[str]:
        ans: list[str] = []
        a = ans.append
        if not self.documented:
            return ans
        if option_group:
            sz = max(len(self.name), max(len(o.name) for o in option_group))
            a(f'{self.name.ljust(sz)} {self.defval_as_string}'.rstrip())
            for o in option_group:
                a(f'{o.name.ljust(sz)} {o.defval_as_string}'.rstrip())
        else:
            a(f'{self.name} {self.defval_as_string}'.rstrip())
        if self.long_text:
            a('')
            a(render_block(self.long_text))
            a('')
        return ans

    def as_rst(
        self, conf_name: str, shortcut_slugs: dict[str, tuple[str, str]],
        kitty_mod: str, level: int = 0, option_group: list['Option'] = []
    ) -> list[str]:
        ans: list[str] = []
        a = ans.append
        if not self.documented:
            return ans
        mopts = [self] + option_group
        a('.. opt:: ' + ', '.join(f'{conf_name}.{mo.name}' for mo in mopts))
        if any(mo.defval_as_string for mo in mopts):
            a('.. code-block:: conf')
            a('')
            sz = max(len(x.name) for x in mopts)
            for mo in mopts:
                a(('    {:%ds} {}' % sz).format(mo.name, mo.defval_as_string))
        a('')
        if self.long_text:
            a(expand_opt_references(conf_name, self.long_text))
            a('')
        return ans


class MultiVal:

    def __init__(self, val_as_str: str, add_to_default: bool, documented: bool, only: Only) -> None:
        self.defval_as_str = val_as_str
        self.documented = documented
        self.only = only
        self.add_to_default = add_to_default


class MultiOption:

    def __init__(self, name: str, parser_func: ParserFuncType, long_text: str, group: 'Group', ctype: str, has_secret: bool = False):
        self.name = name
        self.ctype = ctype
        self.parser_func = parser_func
        self.long_text = long_text
        self.group = group
        self.has_secret = has_secret
        self.items: list[MultiVal] = []

    def add_value(self, val_as_str: str, add_to_default: bool, documented: bool, only: Only) -> None:
        self.items.append(MultiVal(val_as_str, add_to_default, documented, only))

    def __iter__(self) -> Iterator[MultiVal]:
        yield from self.items

    def as_conf(self, commented: bool = False, level: int = 0) -> list[str]:
        ans: list[str] = []
        a = ans.append
        documented = False
        for k in self.items:
            if k.documented:
                documented = True
                if k.add_to_default:
                    a(f'{self.name} {k.defval_as_str}'.rstrip())
                else:
                    # Comment out multi-options that have no default values
                    a(f'# {self.name}'.rstrip())
                if not k.add_to_default and k.defval_as_str:
                    a('')
                    a(f'#: E.g. {self.name} {k.defval_as_str}'.rstrip())
        if self.long_text and documented:
            a('')
            a(render_block(self.long_text))
            a('')
        return ans

    def as_rst(self, conf_name: str, shortcut_slugs: dict[str, tuple[str, str]], kitty_mod: str, level: int = 0) -> list[str]:
        ans: list[str] = []
        a = ans.append
        a(f'.. opt:: {conf_name}.{self.name}')
        documented = tuple(x for x in self.items if x.documented)
        if any(k.defval_as_str for k in documented):
            defaults = tuple(x for x in documented if x.add_to_default)
            if defaults:
                a('.. code-block:: conf')
                a('')
                for k in defaults:
                    a(f'    {self.name:s} {k.defval_as_str}'.rstrip())
            else:
                a('')
                a('Has no default values. Example values are shown below:')
                a('')
                a('.. code-block:: conf')
                a('')
                for k in self.items:
                    a(f'    {self.name:s} {k.defval_as_str}'.rstrip())
        a('')
        if self.long_text:
            a(expand_opt_references(conf_name, self.long_text))
            a('')
        return ans


class Mapping:
    add_to_default: bool
    short_text: str
    long_text: str
    documented: bool
    setting_name: str
    name: str
    only: Only

    @property
    def parseable_text(self) -> str:
        return ''

    @property
    def key_text(self) -> str:
        return ''

    def as_conf(self, commented: bool = False, level: int = 0, action_group: list['Mapping'] = []) -> list[str]:
        ans: list[str] = []
        if not self.documented:
            return ans
        a = ans.append
        if self.short_text:
            a(render_block(self.short_text.strip())), a('')
        for sc in [self] + action_group:
            if sc.documented:
                prefix = '' if sc.add_to_default else '#::  E.g. '
                a(f'{prefix}{sc.setting_name} {sc.parseable_text}')
        if self.long_text:
            a(''), a(render_block(self.long_text.strip(), '#::  '))
        a('')
        return ans

    def as_rst(
        self, conf_name: str, shortcut_slugs: dict[str, tuple[str, str]],
        kitty_mod: str, level: int = 0, action_group: list['Mapping'] = []
    ) -> list[str]:
        ans: list[str] = []
        a = ans.append
        if not self.documented:
            return ans
        if not self.short_text:
            raise ValueError(f'The shortcut for {self.name} has no short_text')
        sc_text = f'{conf_name}.{self.short_text}'
        shortcut_slugs[f'{conf_name}.{self.name}'] = (sc_text, self.key_text.replace('kitty_mod', kitty_mod))
        a(f'.. shortcut:: {sc_text}')
        block_started = False
        for sc in [self] + action_group:
            if sc.add_to_default and sc.documented:
                if not block_started:
                    a('.. code-block:: conf')
                    a('')
                    block_started = True
                suffix = ''
                if sc.only == 'macos':
                    suffix = ' 🍎'
                elif sc.only == 'linux':
                    suffix = ' 🐧'
                a(f'    {sc.setting_name} {sc.parseable_text.replace("kitty_mod", kitty_mod)}{suffix}')
        a('')
        if self.long_text:
            a('')
            a(expand_opt_references(conf_name, self.long_text))
            a('')

        return ans


class ShortcutMapping(Mapping):
    setting_name: str = 'map'

    def __init__(
        self, name: str, key: str, action_def: str, short_text: str, long_text: str, add_to_default: bool, documented: bool, group: 'Group', only: Only
    ):
        self.name = name
        self.only = only
        self.key = key
        self.action_def = action_def
        self.short_text = short_text
        self.long_text = long_text
        self.documented = documented
        self.add_to_default = add_to_default
        self.group = group

    @property
    def parseable_text(self) -> str:
        return f'{self.key} {self.action_def}'

    @property
    def key_text(self) -> str:
        return self.key


class MouseMapping(Mapping):
    setting_name: str = 'mouse_map'

    def __init__(
        self, name: str, button: str, event: str, modes: str, action_def: str,
        short_text: str, long_text: str, add_to_default: bool, documented: bool, group: 'Group', only: Only
    ):
        self.name = name
        self.only = only
        self.button = button
        self.event = event
        self.modes = modes
        self.action_def = action_def
        self.short_text = short_text
        self.long_text = long_text
        self.documented = documented
        self.add_to_default = add_to_default
        self.group = group

    @property
    def parseable_text(self) -> str:
        return f'{self.button} {self.event} {self.modes} {self.action_def}'

    @property
    def key_text(self) -> str:
        return self.button


NonGroups = Union[Option, MultiOption, ShortcutMapping, MouseMapping]
GroupItem = Union[NonGroups, 'Group']


class Group:

    def __init__(self, name: str, title: str, coalesced_iterator_data: CoalescedIteratorData, start_text: str = '', parent: Optional['Group'] = None):
        self.name = name
        self.coalesced_iterator_data = coalesced_iterator_data
        self.title = title
        self.start_text = start_text
        self.end_text = ''
        self.items: list[GroupItem] = []
        self.parent = parent

    def append(self, item: GroupItem) -> None:
        self.items.append(item)

    def __iter__(self) -> Iterator[GroupItem]:
        return iter(self.items)

    def __len__(self) -> int:
        return len(self.items)

    def iter_with_coalesced_options(self) -> Iterator[GroupItem]:
        for item in self:
            if id(item) not in self.coalesced_iterator_data.coalesced:
                yield item

    def iter_all(self) -> Iterator[GroupItem]:
        for x in self:
            yield x
            if isinstance(x, Group):
                yield from x.iter_all()

    def iter_all_non_groups(self) -> Iterator[NonGroups]:
        for x in self:
            if isinstance(x, Group):
                yield from x.iter_all_non_groups()
            else:
                yield x

    def as_rst(self, conf_name: str, shortcut_slugs: dict[str, tuple[str, str]], kitty_mod: str = 'kitty_mod', level: int = 0) -> list[str]:
        ans: list[str] = []
        a = ans.append
        if level:
            a('')
            a(f'.. _conf-{conf_name}-{self.name}:')
            a('')
            a(self.title)
            heading_level = '+' if level > 1 else '-'
            a(heading_level * (len(self.title) + 20))
            a('')
            if self.start_text:
                a(self.start_text)
                a('')
        else:
            ans.extend(('.. default-domain:: conf', ''))

        kitty_mod = self.coalesced_iterator_data.kitty_mod
        for item in self.iter_with_coalesced_options():
            if isinstance(item, Option):
                lines = item.as_rst(conf_name, shortcut_slugs, kitty_mod, option_group=self.coalesced_iterator_data.option_group_for_option(item))
            elif isinstance(item, Mapping):
                lines = item.as_rst(conf_name, shortcut_slugs, kitty_mod, level + 1, action_group=self.coalesced_iterator_data.action_group_for_action(item))
            else:
                lines = item.as_rst(conf_name, shortcut_slugs, kitty_mod, level + 1)
            ans.extend(lines)

        if level:
            if self.end_text:
                a('')
                a(self.end_text)
        return ans

    def as_conf(self, commented: bool = False, level: int = 0) -> list[str]:
        ans: list[str] = []
        a = ans.append
        if level:
            a('#: ' + self.title + ' {{''{')
            a('')
            if self.start_text:
                a(render_block(self.start_text))
                a('')
        else:
            ans.extend(('# vim:fileencoding=utf-8:foldmethod=marker', ''))

        for item in self.iter_with_coalesced_options():
            if isinstance(item, Option):
                lines = item.as_conf(option_group=self.coalesced_iterator_data.option_group_for_option(item))
            elif isinstance(item, Mapping):
                lines = item.as_conf(commented, level + 1, action_group=self.coalesced_iterator_data.action_group_for_action(item))
            else:
                lines = item.as_conf(commented, level + 1)
            ans.extend(lines)

        if level:
            if self.end_text:
                a('')
                a(render_block(self.end_text))
            a('#: }}''}')
            a('')
        else:
            map_groups = []
            start: int | None = None
            count: int | None = None
            for i, line in enumerate(ans):
                if line.startswith('map ') or line.startswith('mouse_map '):
                    if start is None:
                        start = i
                        count = 1
                    else:
                        if count is not None:
                            count += 1
                else:
                    if start is not None and count is not None:
                        map_groups.append((start, count))
                        start = count = None
            for start, count in map_groups:
                r = range(start, start + count)
                sz = max(len(ans[i].split(' ', 3)[1]) for i in r)
                for i in r:
                    line = ans[i]
                    parts = line.split(' ', 3)
                    parts[1] = parts[1].ljust(sz)
                    ans[i] = ' '.join(parts)

            if commented:
                ans = [x if x.startswith('#') or not x.strip() else (f'# {x}') for x in ans]
            else:
                # Comment out any invalid options that have no value
                ans = [f'# {x}' if not x.startswith('#') and len(x.strip().split()) == 1 else x for x in ans]

        return ans


def resolve_import(name: str, module: Any = None) -> ParserFuncType:
    ans = None
    if name.count('.') > 1:
        m = import_module(name.rpartition('.')[0])
        ans = getattr(m, name.rpartition('.')[2])
    else:
        ans = getattr(builtins, name, None)
        if not callable(ans):
            ans = getattr(generic_parsers, name, None)
            if not callable(ans):
                ans = getattr(module, name)
    if not callable(ans):
        raise TypeError(f'{name} is not a function')
    return cast(ParserFuncType, ans)


class Action:

    def __init__(self, name: str, option_type: str, fields: dict[str, str], imports: Iterable[str]):
        self.name = name
        self._parser_func = option_type
        self.fields = fields
        self.imports = frozenset(imports)

    def resolve_imports(self, module: Any) -> 'Action':
        self.parser_func = resolve_import(self._parser_func, module)
        return self


class Definition:

    def __init__(self, package: str, *actions: Action, has_color_table: bool = False) -> None:
        if package.startswith('!'):
            self.module_for_parsers = import_module(package[1:])
        else:
            self.module_for_parsers = import_module(f'{package}.options.utils')
        self.has_color_table = has_color_table
        self.coalesced_iterator_data = CoalescedIteratorData()
        self.root_group = Group('', '', self.coalesced_iterator_data)
        self.current_group = self.root_group
        self.option_map: dict[str, Option] = {}
        self.multi_option_map: dict[str, MultiOption] = {}
        self.shortcut_map: dict[str, list[ShortcutMapping]] = {}
        self.mouse_map: dict[str, list[MouseMapping]] = {}
        self.actions = {a.name: a.resolve_imports(self.module_for_parsers) for a in actions}
        self.deprecations: dict[ParserFuncType, tuple[str, ...]] = {}

    def iter_all_non_groups(self) -> Iterator[NonGroups]:
        yield from self.root_group.iter_all_non_groups()

    def iter_all_options(self) -> Iterator[Option | MultiOption]:
        for x in self.iter_all_non_groups():
            if isinstance(x, (Option, MultiOption)):
                yield x

    def iter_all_maps(self, which: str = 'map') -> Iterator[ShortcutMapping | MouseMapping]:
        for x in self.iter_all_non_groups():
            if isinstance(x, ShortcutMapping) and which in ('map', '*'):
                yield x
            elif isinstance(x, MouseMapping) and which in ('mouse_map', '*'):
                yield x

    def parser_func(self, name: str) -> ParserFuncType:
        ans = getattr(builtins, name, None)
        if callable(ans):
            return cast(ParserFuncType, ans)
        ans = getattr(generic_parsers, name, None)
        if callable(ans):
            return cast(ParserFuncType, ans)
        ans = getattr(self.module_for_parsers, name)
        if not callable(ans):
            raise TypeError(f'{name} is not a function')
        return cast(ParserFuncType, ans)

    def add_group(self, name: str, title: str = '', start_text: str = '') -> None:
        self.current_group = Group(name, title or name, self.coalesced_iterator_data, start_text.strip(), self.current_group)
        if self.current_group.parent is not None:
            self.current_group.parent.append(self.current_group)

    def end_group(self, end_text: str = '') -> None:
        self.current_group.end_text = end_text.strip()
        if self.current_group.parent is not None:
            self.current_group = self.current_group.parent

    def add_option(
        self, name: str, defval: str | float | int | bool,
        option_type: str = 'str', long_text: str = '',
        documented: bool = True, add_to_default: bool = False,
        only: Only = '', macos_default: Unset | str = unset,
        choices: tuple[str, ...] = (),
        ctype: str = '', has_secret: bool = False,
    ) -> None:
        if isinstance(defval, bool):
            defval = 'yes' if defval else 'no'
        else:
            defval = str(defval)
        is_multiple = name.startswith('+')
        long_text = long_text.strip()
        if is_multiple:
            name = name[1:]
            if macos_default is not unset:
                raise TypeError(f'Cannot specify macos_default for is_multiple option: {name} use only instead')
            is_new = name not in self.multi_option_map
            if is_new:
                self.multi_option_map[name] = MultiOption(name, self.parser_func(option_type), long_text, self.current_group, ctype, has_secret)
            mopt = self.multi_option_map[name]
            if is_new:
                self.current_group.append(mopt)
            mopt.add_value(defval, add_to_default, documented, only)
            return
        opt = Option(name, defval, macos_default, self.parser_func(option_type), long_text, documented, self.current_group, choices, ctype, has_secret)
        self.current_group.append(opt)
        self.option_map[name] = opt

    def add_map(
        self, short_text: str, defn: str, long_text: str = '', add_to_default: bool = True, documented: bool = True, only: Only = ''
    ) -> None:
        name, key, action_def = defn.split(maxsplit=2)
        sc = ShortcutMapping(name, key, action_def, short_text, long_text.strip(), add_to_default, documented, self.current_group, only)
        self.current_group.append(sc)
        self.shortcut_map.setdefault(name, []).append(sc)

    def add_mouse_map(
        self, short_text: str, defn: str, long_text: str = '', add_to_default: bool = True, documented: bool = True, only: Only = ''
    ) -> None:
        name, button, event, modes, action_def = defn.split(maxsplit=4)
        mm = MouseMapping(name, button, event, modes, action_def, short_text, long_text.strip(), add_to_default, documented, self.current_group, only)
        self.current_group.append(mm)
        self.mouse_map.setdefault(name, []).append(mm)

    def add_deprecation(self, parser_name: str, *aliases: str) -> None:
        self.deprecations[self.parser_func(parser_name)] = aliases

    def as_conf(self, commented: bool = False) -> list[str]:
        self.coalesced_iterator_data.initialize(self.root_group)
        return self.root_group.as_conf(commented)

    def as_rst(self, conf_name: str, shortcut_slugs: dict[str, tuple[str, str]]) -> list[str]:
        self.coalesced_iterator_data.initialize(self.root_group)
        return self.root_group.as_rst(conf_name, shortcut_slugs)
