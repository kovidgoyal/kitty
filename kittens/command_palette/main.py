#!/usr/bin/env python
# License: GPLv3 Copyright: 2024, Kovid Goyal <kovid at kovidgoyal.net>


import sys
from typing import Any

from kitty.typing_compat import BossType

from ..tui.handler import result_handler


def collect_keys_data(opts: Any) -> dict[str, Any]:
    """Collect all keybinding data from options into a JSON-serializable dict."""
    from kitty.actions import get_all_actions, groups
    from kitty.options.utils import KeyDefinition
    from kitty.types import Shortcut

    # Build action->group and action->help lookups
    action_to_group: dict[str, str] = {}
    action_to_help: dict[str, str] = {}
    action_to_long_help: dict[str, str] = {}
    for group_key, actions in get_all_actions().items():
        for action in actions:
            action_to_group[action.name] = groups[group_key]
            action_to_help[action.name] = action.short_help
            action_to_long_help[action.name] = action.long_help

    modes: dict[str, dict[str, list[dict[str, str]]]] = {}

    def as_sc(k: 'Any', v: KeyDefinition) -> Shortcut:
        if v.is_sequence:
            return Shortcut((v.trigger,) + v.rest)
        return Shortcut((k,))

    for mode_name, mode in opts.keyboard_modes.items():
        categories: dict[str, list[dict[str, str]]] = {}
        for key, defns in mode.keymap.items():
            # Use last non-duplicate definition
            seen: set[tuple[Any, ...]] = set()
            uniq: list[KeyDefinition] = []
            for d in reversed(defns):
                uid = d.unique_identity_within_keymap
                if uid not in seen:
                    seen.add(uid)
                    uniq.append(d)
            for d in uniq:
                sc = as_sc(key, d)
                key_repr = sc.human_repr(opts.kitty_mod)
                action_repr = d.human_repr()
                # Determine category from first word of action definition
                action_name = d.definition.split()[0] if d.definition else 'no_op'
                category = action_to_group.get(action_name, 'Miscellaneous')
                help_text = action_to_help.get(action_name, '')
                long_help = action_to_long_help.get(action_name, '')
                categories.setdefault(category, []).append({
                    'key': key_repr,
                    'action': action_name,
                    'action_display': action_repr,
                    'help': help_text,
                    'long_help': long_help,
                })
        # Sort within categories
        for cat in categories:
            categories[cat].sort(key=lambda b: b['key'])
        # Order categories by the groups order
        ordered: dict[str, list[dict[str, str]]] = {}
        for group_title in groups.values():
            if group_title in categories:
                ordered[group_title] = categories.pop(group_title)
        # Add any remaining
        for cat_name, binds in sorted(categories.items()):
            ordered[cat_name] = binds
        modes[mode_name] = ordered

    # Emit explicit mode and category ordering since JSON maps lose insertion order
    mode_order = list(modes.keys())
    category_order: dict[str, list[str]] = {}
    for mode_name, cats in modes.items():
        category_order[mode_name] = list(cats.keys())

    # Mouse mappings
    mouse: list[dict[str, str]] = []
    for event, action in opts.mousemap.items():
        key_repr = event.human_repr(opts.kitty_mod)
        mouse.append({'key': key_repr, 'action': action, 'action_display': action, 'help': '', 'long_help': ''})
    mouse.sort(key=lambda b: b['key'])

    return {
        'modes': modes,
        'mouse': mouse,
        'mode_order': mode_order,
        'category_order': category_order,
    }


def main(args: list[str]) -> None:
    raise SystemExit('This must be run as kitten command-palette')


main.allow_remote_control = True  # type: ignore[attr-defined]
main.remote_control_password = True  # type: ignore[attr-defined]


@result_handler(has_ready_notification=True)
def handle_result(args: list[str], data: dict[str, Any], target_window_id: int, boss: BossType) -> None:
    pass


help_text = 'Browse and trigger keyboard shortcuts and actions'
usage = ''
OPTIONS = ''.format


if __name__ == '__main__':
    main(sys.argv)
elif __name__ == '__doc__':
    cd = sys.cli_docs  # type: ignore
    cd['usage'] = usage
    cd['options'] = OPTIONS
    cd['help_text'] = help_text
    cd['short_desc'] = help_text
