#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPLv3 Copyright: 2021, Kovid Goyal <kovid at kovidgoyal.net>

import inspect
from typing import Dict, List, NamedTuple

from .boss import Boss
from .tabs import Tab
from .types import run_once, ActionGroup, ActionSpec
from .window import Window


class Action(NamedTuple):
    name: str
    group: str
    short_help: str
    long_help: str


groups: Dict[ActionGroup, str] = {
    'cp': 'Copy/paste',
    'sc': 'Scrolling',
    'win': 'Window management',
    'tab': 'Tab management',
    'mouse': 'Mouse actions',
    'mk': 'Marks',
    'lay': 'Layouts',
    'misc': 'Miscellaneous',
}
group_title = groups.__getitem__


@run_once
def get_all_actions() -> Dict[str, List[Action]]:
    ' test docstring '

    ans: Dict[str, List[Action]] = {}

    def is_action(x: object) -> bool:
        return isinstance(getattr(x, 'action_spec', None), ActionSpec)

    def as_action(x: object) -> Action:
        spec: ActionSpec = getattr(x, 'action_spec')
        doc = inspect.cleandoc(spec.doc)
        lines = doc.splitlines()
        first = lines.pop(0)
        short_help = first
        long_help = '\n'.join(lines).strip()
        return Action(getattr(x, '__name__'), spec.group, short_help, long_help)

    seen = set()
    for cls in (Window, Tab, Boss):
        for (name, func) in inspect.getmembers(cls, is_action):
            ac = as_action(func)
            if ac.name not in seen:
                ans.setdefault(ac.group, []).append(ac)
                seen.add(ac.name)
    for i, which in enumerate('first second third fourth fifth sixth seventh eighth ninth tenth'.split()):
        name = f'{which}_window'
        if name not in seen:
            seen.add(name)
            ans['win'].append(Action(name, 'win', f'Focus the {which} window', ''))

    return ans


def dump() -> None:
    from pprint import pprint
    pprint(get_all_actions())


def as_rst() -> str:
    from .options.definition import definition
    from .conf.types import Mapping
    allg = get_all_actions()
    lines: List[str] = []
    a = lines.append
    maps: Dict[str, List[Mapping]] = {}
    for m in definition.iter_all_maps():
        if m.documented:
            func = m.action_def.split()[0]
            maps.setdefault(func, []).append(m)

    for group in sorted(allg, key=lambda x: group_title(x).lower()):
        title = group_title(group)
        a('')
        a(f'.. _action-group-{group}:')
        a('')
        a(title)
        a('-' * len(title))
        a('')

        for action in allg[group]:
            a('')
            a(f'.. _action-{action.name}:')
            a('')
            a(action.name)
            a('+' * len(action.name))
            a('')
            a(action.short_help)
            a('')
            if action.long_help:
                a(action.long_help)
            if action.name in maps:
                a('')
                a('Default shortcuts using this action:')
                scs = {f':sc:`kitty.{m.name}`' for m in maps[action.name]}
                a(', '.join(sorted(scs)))
    return '\n'.join(lines)
