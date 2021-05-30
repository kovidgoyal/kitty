#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPLv3 Copyright: 2021, Kovid Goyal <kovid at kovidgoyal.net>

import builtins
import re
import typing
from importlib import import_module
from typing import (
    Any, Callable, Dict, Iterable, Iterator, List, Match, Optional, Tuple,
    Union, cast
)

import kitty.conf.utils as generic_parsers

if typing.TYPE_CHECKING:
    Only = typing.Literal['macos', 'linux', '']
else:
    Only = str


class Unset:
    def __bool__(self) -> bool:
        return False


unset = Unset()


def remove_markup(text: str) -> str:

    def sub(m: Match) -> str:
        if m.group(1) == 'ref':
            return {
                'layouts': 'https://sw.kovidgoyal.net/kitty/index.html#layouts',
                'sessions': 'https://sw.kovidgoyal.net/kitty/index.html#sessions',
                'functional': 'https://sw.kovidgoyal.net/kitty/keyboard-protocol.html#functional-key-definitions',
            }[m.group(2)]
        return str(m.group(2))

    return re.sub(r':([a-zA-Z0-9]+):`(.+?)`', sub, text, flags=re.DOTALL)


def iter_blocks(lines: Iterable[str]) -> Iterator[Tuple[List[str], int]]:
    current_block: List[str] = []
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


def wrapped_block(lines: Iterable[str]) -> Iterator[str]:
    wrapper = getattr(wrapped_block, 'wrapper', None)
    if wrapper is None:
        import textwrap
        wrapper = textwrap.TextWrapper(
            initial_indent='#: ', subsequent_indent='#: ', width=70, break_long_words=False
        )
        setattr(wrapped_block, 'wrapper', wrapper)
    for block, indent_size in iter_blocks(lines):
        if indent_size > 0:
            for line in block:
                if not line:
                    yield line
                else:
                    yield '#: ' + line
        else:
            for line in wrapper.wrap('\n'.join(block)):
                yield line


def render_block(text: str) -> str:
    text = remove_markup(text)
    lines = text.splitlines()
    return '\n'.join(wrapped_block(lines))


class Option:

    def __init__(
        self, name: str, defval: str, macos_default: Union[Unset, str], parser_func: Callable,
        long_text: str, documented: bool, group: 'Group', choices: Tuple[str, ...]
    ):
        self.name = name
        self.defval_as_string = defval
        self.macos_defval = macos_default
        self.long_text = long_text
        self.documented = documented
        self.group = group
        self.parser_func = parser_func
        self.choices = choices

    @property
    def needs_coalescing(self) -> bool:
        return self.documented and not self.long_text

    def as_conf(self, commented: bool = False, level: int = 0, option_group: List['Option'] = []) -> List[str]:
        ans: List[str] = []
        a = ans.append
        if not self.documented:
            return ans
        if option_group:
            sz = max(len(self.name), max(len(o.name) for o in option_group))
            a(f'{self.name.ljust(sz)} {self.defval_as_string}')
            for o in option_group:
                a(f'{o.name.ljust(sz)} {o.defval_as_string}')
        else:
            a(f'{self.name} {self.defval_as_string}')
        if self.long_text:
            a('')
            a(render_block(self.long_text))
            a('')
        return ans


class MultiVal:

    def __init__(self, val_as_str: str, add_to_default: bool, documented: bool, only: Only) -> None:
        self.defval_as_str = val_as_str
        self.documented = documented
        self.only = only
        self.add_to_default = add_to_default


class MultiOption:

    def __init__(self, name: str, parser_func: Callable, long_text: str, group: 'Group'):
        self.name = name
        self.parser_func = parser_func
        self.long_text = long_text
        self.group = group
        self.items: List[MultiVal] = []

    def add_value(self, val_as_str: str, add_to_default: bool, documented: bool, only: Only) -> None:
        self.items.append(MultiVal(val_as_str, add_to_default, documented, only))

    def __iter__(self) -> Iterator[MultiVal]:
        yield from self.items

    def as_conf(self, commented: bool = False, level: int = 0) -> List[str]:
        ans: List[str] = []
        a = ans.append
        for k in self.items:
            if k.documented:
                prefix = '' if k.add_to_default else '# '
                a(f'{prefix}{self.name} {k.defval_as_str}')
        if self.long_text:
            a('')
            a(render_block(self.long_text))
            a('')
        return ans


class Mapping:
    add_to_default: bool
    long_text: str
    documented: bool
    setting_name: str

    @property
    def parseable_text(self) -> str:
        return ''

    def as_conf(self, commented: bool = False, level: int = 0) -> List[str]:
        ans: List[str] = []
        if self.documented:
            a = ans.append
            if self.add_to_default:
                a(self.setting_name + ' ' + self.parseable_text)
            if self.long_text:
                a(''), a(render_block(self.long_text.strip())), a('')
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


NonGroups = Union[Option, MultiOption, ShortcutMapping, MouseMapping]
GroupItem = Union[NonGroups, 'Group']


class Group:

    def __init__(self, name: str, title: str, start_text: str = '', parent: Optional['Group'] = None):
        self.name = name
        self.title = title
        self.start_text = start_text
        self.end_text = ''
        self.items: List[GroupItem] = []
        self.parent = parent

    def append(self, item: GroupItem) -> None:
        self.items.append(item)

    def __iter__(self) -> Iterator[GroupItem]:
        return iter(self.items)

    def __len__(self) -> int:
        return len(self.items)

    def iter_all_non_groups(self) -> Iterator[NonGroups]:
        for x in self:
            if isinstance(x, Group):
                yield from x.iter_all_non_groups()
            else:
                yield x

    def as_conf(self, commented: bool = False, level: int = 0) -> List[str]:
        ans: List[str] = []
        a = ans.append
        if level:
            a('#: ' + self.title + ' {{''{')
            a('')
            if self.start_text:
                a(render_block(self.start_text))
                a('')
        else:
            ans.extend(('# vim:fileencoding=utf-8:ft=conf:foldmethod=marker', ''))

        option_groups = {}
        current_group: List[Option] = []
        coalesced = set()
        for item in self:
            if isinstance(item, Option):
                if current_group:
                    if item.needs_coalescing:
                        current_group.append(item)
                        coalesced.add(id(item))
                        continue
                    option_groups[id(current_group[0])] = current_group[1:]
                    current_group = [item]
                else:
                    current_group.append(item)
        if current_group:
            option_groups[id(current_group[0])] = current_group[1:]

        for item in self:
            if isinstance(item, Option):
                if id(item) in coalesced:
                    continue
                lines = item.as_conf(option_group=option_groups[id(item)])
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
            start: Optional[int] = None
            count: Optional[int] = None
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
                ans = [x if x.startswith('#') or not x.strip() else ('# ' + x) for x in ans]

        return ans


def resolve_import(name: str, module: Any = None) -> Callable:
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
    return cast(Callable, ans)


class Action:

    def __init__(self, name: str, option_type: str, fields: Dict[str, str], imports: Iterable[str]):
        self.name = name
        self._parser_func = option_type
        self.fields = fields
        self.imports = frozenset(imports)

    def resolve_imports(self, module: Any) -> 'Action':
        self.parser_func = resolve_import(self._parser_func, module)
        return self


class Definition:

    def __init__(self, package: str, *actions: Action) -> None:
        self.module_for_parsers = import_module(f'{package}.options.utils')
        self.package = package
        self.root_group = Group('', '')
        self.current_group = self.root_group
        self.option_map: Dict[str, Option] = {}
        self.multi_option_map: Dict[str, MultiOption] = {}
        self.shortcut_map: Dict[str, List[ShortcutMapping]] = {}
        self.mouse_map: Dict[str, List[MouseMapping]] = {}
        self.actions = {a.name: a.resolve_imports(self.module_for_parsers) for a in actions}
        self.deprecations: Dict[Callable, Tuple[str, ...]] = {}

    def iter_all_non_groups(self) -> Iterator[NonGroups]:
        yield from self.root_group.iter_all_non_groups()

    def iter_all_options(self) -> Iterator[Union[Option, MultiOption]]:
        for x in self.iter_all_non_groups():
            if isinstance(x, (Option, MultiOption)):
                yield x

    def iter_all_maps(self, which: str = 'map') -> Iterator[Union[ShortcutMapping, MouseMapping]]:
        for x in self.iter_all_non_groups():
            if isinstance(x, ShortcutMapping) and which == 'map':
                yield x
            elif isinstance(x, MouseMapping) and which == 'mouse_map':
                yield x

    def parser_func(self, name: str) -> Callable:
        ans = getattr(builtins, name, None)
        if callable(ans):
            return cast(Callable, ans)
        ans = getattr(generic_parsers, name, None)
        if callable(ans):
            return cast(Callable, ans)
        ans = getattr(self.module_for_parsers, name)
        if not callable(ans):
            raise TypeError(f'{name} is not a function')
        return cast(Callable, ans)

    def add_group(self, name: str, title: str = '', start_text: str = '') -> None:
        self.current_group = Group(name, title or name, start_text.strip(), self.current_group)
        if self.current_group.parent is not None:
            self.current_group.parent.append(self.current_group)

    def end_group(self, end_text: str = '') -> None:
        self.current_group.end_text = end_text.strip()
        if self.current_group.parent is not None:
            self.current_group = self.current_group.parent

    def add_option(
        self, name: str, defval: Union[str, float, int, bool],
        option_type: str = 'str', long_text: str = '',
        documented: bool = True, add_to_default: bool = False,
        only: Only = '', macos_default: Union[Unset, str] = unset,
        choices: Tuple[str, ...] = ()
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
                self.multi_option_map[name] = MultiOption(name, self.parser_func(option_type), long_text, self.current_group)
            mopt = self.multi_option_map[name]
            if is_new:
                self.current_group.append(mopt)
            mopt.add_value(defval, add_to_default, documented, only)
            return
        opt = Option(name, defval, macos_default, self.parser_func(option_type), long_text, documented, self.current_group, choices)
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

    def as_conf(self, commented: bool = False) -> List[str]:
        return self.root_group.as_conf(commented)
