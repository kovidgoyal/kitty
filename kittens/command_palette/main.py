#!/usr/bin/env python
# License: GPLv3 Copyright: 2024, Kovid Goyal <kovid at kovidgoyal.net>

# Entry point: collect_keys_data(opts) — collects all keybinding, alias, and
# mouse data into a JSON-serializable dict consumed by the Go TUI.

import sys
from functools import partial
from typing import Any

from kitty.conf.types import Definition
from kitty.fast_data_types import add_timer, get_boss
from kitty.typing_compat import BossType

from ..tui.handler import result_handler

definition = Definition(
    '!kittens.command_palette',
)

agr = definition.add_group
egr = definition.end_group
map = definition.add_map

# shortcuts {{{
agr('shortcuts', 'Keyboard shortcuts')

map('Move selection up',
    'selection_up --allow-fallback=shifted,ascii ctrl+k selection_up',
    )
map('Move selection up',
    'selection_up --allow-fallback=shifted,ascii ctrl+p selection_up',
    )
map('Move selection down',
    'selection_down --allow-fallback=shifted,ascii ctrl+j selection_down',
    )
map('Move selection down',
    'selection_down --allow-fallback=shifted,ascii ctrl+n selection_down',
    )

egr()  # }}}


def classify_action(
    definition: str, alias_map: Any, action_to_group: dict[str, str]
) -> tuple[str, str, str]:
    """Classify a keybinding definition into (action_name, category, alias).

    Returns the resolved action name, the category it belongs to, and the alias
    name if the definition uses one (empty string otherwise).
    """
    raw_action = definition.split()[0] if definition else 'no_op'
    if raw_action == 'combine':
        return 'combine', 'Combined actions', ''
    if raw_action in action_to_group or raw_action == 'no_op':
        return raw_action, action_to_group.get(raw_action, 'Miscellaneous'), ''
    # Not a known action — try alias resolution
    resolved = alias_map.resolve_aliases(definition)
    if resolved:
        action_name = resolved[0].func
        return action_name, 'Action aliases', raw_action
    return raw_action, 'Miscellaneous', ''


def build_action_lookups() -> tuple[dict[str, str], dict[str, str], dict[str, str]]:
    """Build action->group, action->help, and action->long_help lookups."""
    from kitty.actions import get_all_actions, groups

    action_to_group: dict[str, str] = {}
    action_to_help: dict[str, str] = {}
    action_to_long_help: dict[str, str] = {}
    for group_key, actions in get_all_actions().items():
        for action in actions:
            action_to_group[action.name] = groups[group_key]
            action_to_help[action.name] = action.short_help
            action_to_long_help[action.name] = action.long_help
    return action_to_group, action_to_help, action_to_long_help


def deduplicate_definitions(defns: list[Any]) -> list[Any]:
    """Return unique definitions, keeping the last occurrence of each."""
    seen: set[tuple[Any, ...]] = set()
    uniq: list[Any] = []
    for d in reversed(defns):
        uid = d.unique_identity_within_keymap
        if uid not in seen:
            seen.add(uid)
            uniq.append(d)
    return uniq


def build_binding_entry(
    key_repr: str, action_repr: str, definition: str, alias_map: Any,
    action_to_group: dict[str, str], action_to_help: dict[str, str],
    action_to_long_help: dict[str, str],
) -> tuple[dict[str, str], str]:
    """Build a single binding entry dict and return it with its category."""
    action_name, category, alias = classify_action(definition, alias_map, action_to_group)
    entry: dict[str, str] = {
        'key': key_repr,
        'action': action_name,
        'action_display': action_repr,
        'definition': definition or action_name,
        'help': action_to_help.get(action_name, ''),
        'long_help': action_to_long_help.get(action_name, ''),
    }
    if alias:
        entry['alias'] = alias
    return entry, category


def order_categories(
    categories: dict[str, list[dict[str, str]]], group_order: list[str]
) -> dict[str, list[dict[str, str]]]:
    """Order categories by the groups order, with remaining categories sorted at the end."""
    ordered: dict[str, list[dict[str, str]]] = {}
    for group_title in group_order:
        if group_title in categories:
            ordered[group_title] = categories.pop(group_title)
    for cat_name, binds in sorted(categories.items()):
        ordered[cat_name] = binds
    return ordered


def collect_keyboard_bindings(
    opts: Any,
    action_to_group: dict[str, str],
    action_to_help: dict[str, str],
    action_to_long_help: dict[str, str],
) -> dict[str, dict[str, list[dict[str, str]]]]:
    """Collect keybindings from all keyboard modes into categorized dicts."""
    from kitty.actions import groups
    from kitty.options.utils import KeyDefinition
    from kitty.types import Shortcut

    def as_sc(k: 'Any', v: KeyDefinition) -> Shortcut:
        if v.is_sequence:
            return Shortcut((v.trigger,) + v.rest)
        return Shortcut((k,))

    modes: dict[str, dict[str, list[dict[str, str]]]] = {}
    for mode_name, mode in opts.keyboard_modes.items():
        categories: dict[str, list[dict[str, str]]] = {}
        for key, defns in mode.keymap.items():
            for d in deduplicate_definitions(defns):
                sc = as_sc(key, d)
                entry, category = build_binding_entry(
                    sc.human_repr(opts.kitty_mod), d.human_repr(),
                    d.definition or '', opts.alias_map,
                    action_to_group, action_to_help, action_to_long_help)
                categories.setdefault(category, []).append(entry)
        for cat in categories:
            categories[cat].sort(key=lambda b: b['key'])
        modes[mode_name] = order_categories(categories, list(groups.values()))
    return modes


def relocate_mode_entry_bindings(
    modes: dict[str, dict[str, list[dict[str, str]]]]
) -> None:
    """Move push_keyboard_mode bindings into their target mode's section."""
    if '' not in modes:
        return
    new_default_cats: dict[str, list[dict[str, str]]] = {}
    for cat_name, bindings in modes[''].items():
        keep: list[dict[str, str]] = []
        for b in bindings:
            if b['action'] == 'push_keyboard_mode':
                parts = b['definition'].split()
                target = parts[1] if len(parts) > 1 else ''
                if target and target in modes:
                    if 'Enter mode' not in modes[target]:
                        new_target: dict[str, list[dict[str, str]]] = {'Enter mode': [b]}
                        new_target.update(modes[target])
                        modes[target] = new_target
                    else:
                        modes[target]['Enter mode'].append(b)
                    continue
            keep.append(b)
        if keep:
            new_default_cats[cat_name] = keep
    modes[''] = new_default_cats


def add_unmapped_actions(
    modes: dict[str, dict[str, list[dict[str, str]]]]
) -> None:
    """Add actions with no keyboard shortcut to the default mode."""
    from kitty.actions import get_all_actions, groups

    mapped_actions: set[str] = set()
    for mode_cats in modes.values():
        for bindings in mode_cats.values():
            for b in bindings:
                mapped_actions.add(b['action'])

    default_mode_cats = modes.setdefault('', {})
    for group_key, actions in get_all_actions().items():
        category = groups[group_key]
        for action in actions:
            if action.name not in mapped_actions:
                default_mode_cats.setdefault(category, []).append({
                    'key': '',
                    'action': action.name,
                    'action_display': action.name,
                    'definition': action.name,
                    'help': action.short_help,
                    'long_help': action.long_help,
                })

    # Re-sort: mapped entries (non-empty key) first, then unmapped by action name.
    for cat in default_mode_cats:
        default_mode_cats[cat].sort(key=lambda b: (b['key'] == '', b['key'] or b['action']))

    # Re-order by groups ordering
    modes[''] = order_categories(default_mode_cats, list(groups.values()))


def collect_bound_aliases(
    modes: dict[str, dict[str, list[dict[str, str]]]]
) -> set[str]:
    """Collect alias names that are already present from keybindings."""
    bound: set[str] = set()
    for mode_cats in modes.values():
        for bindings in mode_cats.values():
            bound.update(b['alias'] for b in bindings if 'alias' in b)
    return bound


def build_alias_entry(alias_map: Any, display: str, expansion: str) -> dict[str, str]:
    """Build a single alias section entry."""
    resolved = alias_map.resolve_aliases(display)
    resolved_action = resolved[0].func if resolved else display.split()[0]
    return {
        'key': '',
        'action': resolved_action,
        'action_display': display,
        'definition': expansion,
        'help': f'Alias for: {expansion}',
        'long_help': '',
        'alias': display,
    }


def add_alias_sections(
    opts: Any,
    modes: dict[str, dict[str, list[dict[str, str]]]]
) -> None:
    """Add Action aliases and Kitten aliases sections for unbound aliases."""
    bound_aliases = collect_bound_aliases(modes)

    action_alias_entries: list[dict[str, str]] = []
    kitten_alias_entries: list[dict[str, str]] = []
    for alias_name, alias_list in opts.alias_map.aliases.items():
        for aa in alias_list:
            if aa.replace_second_arg:
                display = f'{alias_name} {aa.name}'
                expansion = f'{alias_name} {aa.value}'
                target_list = kitten_alias_entries
            else:
                display = aa.name
                expansion = aa.value
                target_list = action_alias_entries
            if display not in bound_aliases:
                target_list.append(build_alias_entry(opts.alias_map, display, expansion))

    default_mode_cats = modes.setdefault('', {})
    sort_key = lambda b: (b['key'] == '', b['key'] or b['action_display'])
    for section_name, entries in (('Action aliases', action_alias_entries), ('Kitten aliases', kitten_alias_entries)):
        if entries:
            existing = default_mode_cats.get(section_name, [])
            existing.extend(entries)
            existing.sort(key=sort_key)
            default_mode_cats[section_name] = existing


def collect_mouse_bindings(opts: Any) -> list[dict[str, str]]:
    """Collect mouse mappings."""
    mouse: list[dict[str, str]] = []
    for event, action in opts.mousemap.items():
        key_repr = event.human_repr(opts.kitty_mod)
        mouse.append({'key': key_repr, 'action': action, 'action_display': action, 'help': '', 'long_help': ''})
    mouse.sort(key=lambda b: b['key'])
    return mouse


def collect_keys_data(opts: Any) -> dict[str, Any]:
    """Collect all keybinding data from options into a JSON-serializable dict."""
    action_to_group, action_to_help, action_to_long_help = build_action_lookups()
    modes = collect_keyboard_bindings(opts, action_to_group, action_to_help, action_to_long_help)
    relocate_mode_entry_bindings(modes)
    add_unmapped_actions(modes)
    add_alias_sections(opts, modes)

    mode_order = list(modes.keys())
    category_order: dict[str, list[str]] = {}
    for mode_name, cats in modes.items():
        category_order[mode_name] = list(cats.keys())

    return {
        'modes': modes,
        'mouse': collect_mouse_bindings(opts),
        'mode_order': mode_order,
        'category_order': category_order,
    }


def main(args: list[str]) -> None:
    raise SystemExit('This kitten must be used only from a kitty.conf mapping')


def callback(target_window_id: int, action: str, timer_id: int | None) -> None:
    boss = get_boss()
    w = boss.window_id_map.get(target_window_id)
    boss.combine(action, w)


@result_handler(has_ready_notification=True)
def handle_result(args: list[str], data: dict[str, Any], target_window_id: int, boss: BossType) -> None:
    if data and (action := data.get('action')):
        # run action after event loop tick so command palette overlay is closed
        add_timer(partial(callback, target_window_id, action), 0, False)

help_text = 'Browse and trigger keyboard shortcuts and actions'
usage = ''
OPTIONS = r'''
'''.format


if __name__ == '__main__':
    main(sys.argv)
elif __name__ == '__doc__':
    cd = sys.cli_docs  # type: ignore
    cd['usage'] = usage
    cd['options'] = OPTIONS
    cd['help_text'] = help_text
    cd['short_desc'] = help_text
elif __name__ == '__conf__':
    sys.options_definition = definition  # type: ignore
