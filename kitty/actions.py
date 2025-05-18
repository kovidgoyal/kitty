#!/usr/bin/env python
# License: GPLv3 Copyright: 2021, Kovid Goyal <kovid at kovidgoyal.net>

import inspect
from typing import NamedTuple, cast

from .boss import Boss
from .tabs import Tab
from .types import ActionGroup, ActionSpec, run_once
from .window import Window


class Action(NamedTuple):
    name: str
    group: ActionGroup
    short_help: str
    long_help: str


groups: dict[ActionGroup, str] = {
    'cp': 'Copy/paste',
    'sc': 'Scrolling',
    'win': 'Window management',
    'tab': 'Tab management',
    'mouse': 'Mouse actions',
    'mk': 'Marks',
    'lay': 'Layouts',
    'misc': 'Miscellaneous',
    'debug': 'Debugging',
}
group_title = groups.__getitem__


@run_once
def get_all_actions() -> dict[ActionGroup, list[Action]]:
    ' test docstring '

    ans: dict[ActionGroup, list[Action]] = {}

    def is_action(x: object) -> bool:
        return isinstance(getattr(x, 'action_spec', None), ActionSpec)

    def as_action(x: object) -> Action:
        spec: ActionSpec = getattr(x, 'action_spec')
        doc = inspect.cleandoc(spec.doc)
        lines = doc.splitlines()
        first = lines.pop(0)
        short_help = first
        long_help = '\n'.join(lines).strip()
        assert spec.group in groups
        return Action(getattr(x, '__name__'), cast(ActionGroup, spec.group), short_help, long_help)

    seen = set()
    for cls in (Window, Tab, Boss):
        for (name, func) in inspect.getmembers(cls, is_action):
            ac = as_action(func)
            if ac.name not in seen:
                ans.setdefault(ac.group, []).append(ac)
                seen.add(ac.name)

    ans['misc'].append(Action('no_op', 'misc', 'Unbind a shortcut',
                              'Mapping a shortcut to no_op causes kitty to not intercept the key stroke anymore,'
                              ' instead passing it to the program running inside it.'))
    return ans


def dump() -> None:
    from pprint import pprint
    pprint(get_all_actions())


def as_rst() -> str:
    from .conf.types import Mapping
    from .options.definition import definition
    allg = get_all_actions()
    lines: list[str] = []
    a = lines.append
    maps: dict[str, list[Mapping]] = {}
    for m in definition.iter_all_maps():
        if m.documented:
            func = m.action_def.split()[0]
            maps.setdefault(func, []).append(m)

    def key(x: ActionGroup) -> str:
        return group_title(x).lower()

    def kitten_link(text: str) -> str:
        x = text.split()
        return f':doc:`kittens/{x[2]}`' if len(x) > 2 else ''

    for group in sorted(allg, key=key):
        title = group_title(group)
        a('')
        a(f'.. _action-group-{group}:')
        a('')
        a(title)
        a('-' * len(title))
        a('')

        for action in allg[group]:
            a('')
            a(f'.. action:: {action.name}')
            a('')
            a(action.short_help)
            a('')
            if action.long_help:
                a(action.long_help)
            if action.name in maps:
                a('')
                a('Default shortcuts using this action:')
                if action.name == 'kitten':
                    a('')
                    scs = {(kitten_link(m.parseable_text), m.short_text, f':sc:`kitty.{m.name}`') for m in maps[action.name]}
                    for s in sorted(scs):
                        a(f'- {s[0]} - {s[2]} {s[1]}')
                else:
                    sscs = {f':sc:`kitty.{m.name}`' for m in maps[action.name]}
                    a(', '.join(sorted(sscs)))
    return '\n'.join(lines)
