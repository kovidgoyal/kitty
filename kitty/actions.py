#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPLv3 Copyright: 2021, Kovid Goyal <kovid at kovidgoyal.net>

from typing import NamedTuple, Dict, List
from .window import Window
from .tabs import Tab
from .boss import Boss
from .types import run_once
import inspect


class Action(NamedTuple):
    name: str
    group: str
    short_help: str
    long_help: str


groups = {
    'cp': 'Copy/paste',
    'sc': 'Scrolling',
    'win': 'Window management',
    'tab': 'Tab management',
    'mouse': 'Mouse actions',
    'mk': 'Marks',
    'misc': 'Miscellaneous',
}
group_title = groups.__getitem__


@run_once
def get_all_actions() -> Dict[str, List[Action]]:

    ans: Dict[str, List[Action]] = {}

    def is_action(x: object) -> bool:
        doc = getattr(x, '__doc__', '')
        return bool(doc and doc.strip().startswith('@ac:'))

    def as_action(x: object) -> Action:
        doc = (x.__doc__ or '').strip()
        lines = doc.splitlines()
        first = lines.pop(0)
        parts = first.split(':', 2)
        grp = parts[1].strip()
        short_help = parts[2].strip()
        long_help = '\n'.join(lines).strip()
        return Action(getattr(x, '__name__'), grp, short_help, long_help)

    seen = set()
    for cls in (Window, Tab, Boss):
        for (name, func) in inspect.getmembers(cls, is_action):
            ac = as_action(func)
            if ac.name not in seen:
                ans.setdefault(ac.group, []).append(ac)
                seen.add(ac.name)
    return ans


def dump() -> None:
    from pprint import pprint
    pprint(get_all_actions())


def as_rst() -> str:
    allg = get_all_actions()
    lines: List[str] = []
    a = lines.append
    for group in sorted(allg, key=lambda x: group_title(x).lower()):
        title = group_title(group)
        a('')
        a(f'.. _action-group-{group}:')
        a('')
        a(title)
        a('-' * len(title))
        a('')
        a('.. contents::')
        a('   :local:')
        a('   :depth: 1')
        a('')

        for action in allg[group]:
            a('')
            a(f'.. _action-{action.name}:')
            a('')
            a(action.name)
            a('^' * len(action.name))
            a('')
            a(action.short_help)
            a('')
            if action.long_help:
                a(action.long_help)
    return '\n'.join(lines)
