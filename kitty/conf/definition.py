#!/usr/bin/env python3
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2018, Kovid Goyal <kovid at kovidgoyal.net>

import re
from functools import partial
from typing import (
    Any, Callable, Dict, Generator, Iterable, List, Match, Optional, Sequence,
    Set, Tuple, Union, get_type_hints
)

from .utils import Choice, to_bool


class Group:

    __slots__ = 'name', 'short_text', 'start_text', 'end_text'

    def __init__(self, name: str, short_text: str, start_text: str = '', end_text: str = '') -> None:
        self.name, self.short_text = name, short_text.strip()
        self.start_text, self.end_text = start_text.strip(), end_text.strip()


class Option:

    __slots__ = 'name', 'group', 'long_text', 'option_type', 'defval_as_string', 'add_to_default', 'add_to_docs', 'line', 'is_multiple'

    def __init__(self, name: str, group: Group, defval: str, option_type: Any, long_text: str, add_to_default: bool, add_to_docs: bool, is_multiple: bool):
        self.name, self.group = name, group
        self.long_text, self.option_type = long_text.strip(), option_type
        self.defval_as_string = defval
        self.add_to_default = add_to_default
        self.add_to_docs = add_to_docs
        self.is_multiple = is_multiple
        self.line = self.name + ' ' + self.defval_as_string

    def type_definition(self, imports: Set[Tuple[str, str]]) -> str:

        def type_name(x: type) -> str:
            ans = x.__name__
            if x.__module__ and x.__module__ != 'builtins':
                imports.add((x.__module__, x.__name__))
            return ans

        def option_type_as_str(x: Any) -> str:
            if hasattr(x, '__name__'):
                return type_name(x)
            ans = repr(x)
            ans = ans.replace('NoneType', 'None')
            if self.is_multiple:
                ans = ans[ans.index('[') + 1:-1]
                ans = ans.replace('Tuple', 'Dict', 1)
            return ans

        if type(self.option_type) is type:
            return type_name(self.option_type)
        if isinstance(self.option_type, Choice):
            return 'typing.Literal[{}]'.format(','.join(f'{x!r}' for x in self.option_type.all_choices))
        th = get_type_hints(self.option_type)
        try:
            rettype = th['return']
        except KeyError:
            raise ValueError('The Option {} has an unknown option_type: {}'.format(self.name, self.option_type))
        return option_type_as_str(rettype)


class Shortcut:

    __slots__ = 'name', 'group', 'key', 'action_def', 'short_text', 'long_text', 'add_to_default', 'add_to_docs', 'line'

    def __init__(self, name: str, group: Group, key: str, action_def: str, short_text: str, long_text: str, add_to_default: bool, add_to_docs: bool):
        self.name, self.group, self.key, self.action_def = name, group, key, action_def
        self.short_text, self.long_text = short_text, long_text
        self.add_to_default = add_to_default
        self.add_to_docs = add_to_docs
        self.line = 'map ' + self.key + ' ' + self.action_def


class MouseAction:

    __slots__ = 'name', 'group', 'button', 'event', 'modes', 'action_def', 'short_text', 'long_text', 'add_to_default', 'add_to_docs', 'line'

    def __init__(
            self, name: str, group: Group,
            button: str, event: str, modes: str, action_def: str,
            short_text: str, long_text: str, add_to_default: bool, add_to_docs: bool
    ):
        self.name, self.group, self.button, self.event, self.action_def = name, group, button, event, action_def
        self.modes, self.short_text, self.long_text = modes, short_text, long_text
        self.add_to_default = add_to_default
        self.add_to_docs = add_to_docs
        self.line = f'mouse_map {self.button} {self.event} {self.modes} {self.action_def}'

    @property
    def key(self) -> str:
        return self.button


def option(
    all_options: Dict[str, Option],
    group: Sequence[Group],
    name: str,
    defval: Any,
    long_text: str = '',
    option_type: Callable[[str], Any] = str,
    add_to_default: bool = True,
    add_to_docs: bool = True
) -> Option:
    is_multiple = name.startswith('+')
    if is_multiple:
        name = name[1:]
    defval_type = type(defval)
    if defval_type is not str:
        if option_type is str:
            if defval_type is bool:
                option_type = to_bool
            else:
                option_type = defval_type
        if defval_type is bool:
            defval = 'yes' if defval else 'no'
        else:
            defval = str(defval)

    ans = Option(name, group[0], defval, option_type, long_text, add_to_default, add_to_docs, is_multiple)
    all_options[name] = ans
    return ans


def shortcut(
    all_options: Dict[str, List[Shortcut]],
    group: Sequence[Group],
    action_name: str,
    key: str,
    action_def: str,
    short_text: str = '',
    long_text: str = '',
    add_to_default: bool = True,
    add_to_docs: bool = True,
) -> Shortcut:
    ans = Shortcut(action_name, group[0], key, action_def, short_text, long_text, add_to_default, add_to_docs)
    key = 'sc-' + action_name
    all_options.setdefault(key, []).append(ans)
    return ans


def mouse_action(
    all_options: Dict[str, List[MouseAction]],
    group: Sequence[Group],
    action_name: str,
    button: str,
    event: str,
    modes: str,
    action_def: str,
    short_text: str = '',
    long_text: str = '',
    add_to_default: bool = True,
    add_to_docs: bool = True,
) -> MouseAction:
    ans = MouseAction(action_name, group[0], button, event, modes, action_def, short_text, long_text, add_to_default, add_to_docs)
    key = 'ma-' + action_name
    all_options.setdefault(key, []).append(ans)
    return ans


def option_func(all_options: Dict[str, Any], all_groups: Dict[str, Sequence[str]]) -> Tuple[
        Callable, Callable, Callable, Callable[[str], None], Dict[str, Group]]:
    all_groups_ = {k: Group(k, *v) for k, v in all_groups.items()}
    group: List[Optional[Group]] = [None]

    def change_group(name: str) -> None:
        group[0] = all_groups_[name]

    return partial(option, all_options, group), partial(shortcut, all_options, group), partial(mouse_action, all_options, group), change_group, all_groups_


OptionOrAction = Union[Option, List[Union[Shortcut, MouseAction]]]


def merged_opts(all_options: Sequence[OptionOrAction], opt: Option, i: int) -> Generator[Option, None, None]:
    yield opt
    for k in range(i + 1, len(all_options)):
        q = all_options[k]
        if not isinstance(q, Option):
            break
        if not q.long_text and q.add_to_docs:
            yield q
        else:
            break


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


def iter_blocks(lines: Iterable[str]) -> Generator[Tuple[List[str], int], None, None]:
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


def wrapped_block(lines: Iterable[str]) -> Generator[str, None, None]:
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


def as_conf_file(all_options: Iterable[OptionOrAction]) -> List[str]:
    ans = ['# vim:fileencoding=utf-8:ft=conf:foldmethod=marker', '']
    a = ans.append
    current_group: Optional[Group] = None
    group_folds = []
    all_options_ = list(all_options)

    def render_group(group: Group, is_shortcut: bool) -> None:
        a('#: ' + group.short_text + ' {{''{')
        group_folds.append(group.name)
        a('')
        if group.start_text:
            a(render_block(group.start_text))
            a('')

    def handle_group_end(group: Group, new_group_name: str = '', new_group_is_shortcut: bool = False) -> None:
        if group.end_text:
            a(''), a(render_block(group.end_text))
        is_subgroup = new_group_name.startswith(group.name + '.')
        while group_folds:
            is_subgroup = new_group_name.startswith(group_folds[-1] + '.')
            if is_subgroup:
                break
            a('#: }}''}'), a('')
            del group_folds[-1]

    def handle_group(new_group: Group, is_shortcut: bool = False) -> None:
        nonlocal current_group
        if new_group is not current_group:
            if current_group:
                handle_group_end(current_group, new_group.name, is_shortcut)
            current_group = new_group
            render_group(current_group, is_shortcut)

    def handle_shortcut(shortcuts: Sequence[Union[Shortcut, MouseAction]]) -> None:
        handle_group(shortcuts[0].group, True)
        for sc in shortcuts:
            if sc.add_to_default:
                a(sc.line)
            if sc.long_text:
                a(''), a(render_block(sc.long_text.strip())), a('')

    def handle_option(opt: Option) -> None:
        if not opt.long_text or not opt.add_to_docs:
            return
        handle_group(opt.group)
        mopts = list(merged_opts(all_options_, opt, i))
        sz = max(len(x.name) for x in mopts)
        for mo in mopts:
            prefix = '' if mo.add_to_default else '# '
            a('{}{} {}'.format(prefix, mo.name.ljust(sz), mo.defval_as_string))
        a('')
        a(render_block(opt.long_text))
        a('')

    for i, opt in enumerate(all_options_):
        if isinstance(opt, Option):
            handle_option(opt)
        else:
            handle_shortcut(opt)

    if current_group:
        handle_group_end(current_group)
        while group_folds:
            a('# }}''}')
            del group_folds[-1]

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

    return ans


def config_lines(
    all_options: Dict[str, OptionOrAction],
) -> Generator[str, None, None]:
    for opt in all_options.values():
        if isinstance(opt, Option):
            if opt.add_to_default:
                yield opt.line
        else:
            for sc in opt:
                if sc.add_to_default:
                    yield sc.line


def as_type_stub(
    all_options: Dict[str, OptionOrAction],
    preamble_lines: Union[Tuple[str, ...], List[str], Iterable[str]] = (),
    extra_fields: Union[Tuple[Tuple[str, str], ...], List[Tuple[str, str]], Iterable[Tuple[str, str]]] = (),
    class_name: str = 'Options'
) -> str:
    ans = ['import typing\n'] + list(preamble_lines) + ['', 'class {}:'.format(class_name)]
    imports: Set[Tuple[str, str]] = set()
    for name, val in all_options.items():
        if isinstance(val, Option):
            field_name = name.partition(' ')[0]
            ans.append('    {}: {}'.format(field_name, val.type_definition(imports)))
    for mod, name in imports:
        ans.insert(0, 'from {} import {}'.format(mod, name))
        ans.insert(0, 'import {}'.format(mod))
    for field_name, type_def in extra_fields:
        ans.append('    {}: {}'.format(field_name, type_def))
    ans.append('    def __iter__(self) -> typing.Iterator[str]: pass')
    ans.append('    def __len__(self) -> int: pass')
    ans.append('    def __getitem__(self, k: typing.Union[int, str]) -> typing.Any: pass')
    ans.append('    def _replace(self, **kw: typing.Any) -> {}: pass'.format(class_name))
    return '\n'.join(ans) + '\n\n\n'


def save_type_stub(text: str, fpath: str) -> None:
    fpath += 'i'
    preamble = '# Update this file by running: ./test.py mypy\n\n'
    try:
        existing = open(fpath).read()
    except FileNotFoundError:
        existing = ''
    current = preamble + text
    if existing != current:
        open(fpath, 'w').write(current)
