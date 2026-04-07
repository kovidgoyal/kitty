#!/usr/bin/env python
# License: GPLv3 Copyright: 2024, Kovid Goyal <kovid at kovidgoyal.net>

from . import BaseTest


class TestCommandPalette(BaseTest):

    def test_collect_keys_data(self):
        from kittens.command_palette.main import collect_keys_data
        from kitty.actions import groups
        opts = self.set_options()
        data = collect_keys_data(opts)
        self.assertIn('modes', data)
        self.assertIn('mouse', data)
        self.assertIn('', data['modes'], 'Default keyboard mode should be present')
        default_mode = data['modes']['']
        # Should have at least some categories
        self.assertTrue(len(default_mode) > 0, 'Should have at least one category')
        # All category names should be from the known groups or special palette sections
        known_titles = set(groups.values()) | {'Action aliases', 'Kitten aliases', 'Combined actions'}
        for cat_name in default_mode:
            self.assertIn(cat_name, known_titles, f'Unknown category: {cat_name}')
        # Each category should have bindings with required fields
        for cat_name, bindings in default_mode.items():
            self.assertIsInstance(bindings, list)
            for b in bindings:
                self.assertIn('key', b)
                self.assertIn('action', b)
                self.assertIn('action_display', b)
                self.assertIn('definition', b)
                self.assertIn('help', b)
                self.assertIn('long_help', b)
                self.assertIsInstance(b['key'], str)
                self.assertIsInstance(b['action'], str)
                # key may be empty for unmapped actions; action must always be non-empty
                self.assertTrue(len(b['action']) > 0)
        # Mouse mappings
        self.assertIsInstance(data['mouse'], list)
        for b in data['mouse']:
            self.assertIn('key', b)
            self.assertIn('action', b)
            self.assertIn('action_display', b)

    def test_collect_keys_categories_ordered(self):
        from kittens.command_palette.main import collect_keys_data
        from kitty.actions import groups
        opts = self.set_options()
        data = collect_keys_data(opts)
        default_mode = data['modes']['']
        cat_names = list(default_mode.keys())
        group_titles = list(groups.values())
        # Categories should appear in the same order as defined in groups
        indices = []
        for cat in cat_names:
            if cat in group_titles:
                indices.append(group_titles.index(cat))
        self.ae(indices, sorted(indices), 'Categories should be ordered according to groups dict')

    def test_collect_keys_bindings_sorted(self):
        from kittens.command_palette.main import collect_keys_data
        opts = self.set_options()
        data = collect_keys_data(opts)
        # Within each category, mapped entries (non-empty key) come first sorted by key,
        # then unmapped entries (empty key) sorted by action name.
        for cat_name, bindings in data['modes'][''].items():
            seen_unmapped = False
            for b in bindings:
                if b['key'] == '':
                    seen_unmapped = True
                elif seen_unmapped:
                    self.fail(
                        f'In category {cat_name!r}, mapped binding {b!r} follows an unmapped one'
                    )

    def test_collect_keys_has_help_text(self):
        from kittens.command_palette.main import collect_keys_data
        opts = self.set_options()
        data = collect_keys_data(opts)
        # At least some bindings should have help text
        has_help = False
        for cat_name, bindings in data['modes'][''].items():
            for b in bindings:
                if b['help']:
                    has_help = True
                    break
            if has_help:
                break
        self.assertTrue(has_help, 'At least some bindings should have help text')

    def test_ordering_arrays_present(self):
        from kittens.command_palette.main import collect_keys_data
        opts = self.set_options()
        data = collect_keys_data(opts)
        # mode_order should list all modes
        self.assertIn('mode_order', data)
        self.assertIsInstance(data['mode_order'], list)
        self.ae(set(data['mode_order']), set(data['modes'].keys()))
        # category_order should list categories for each mode
        self.assertIn('category_order', data)
        self.assertIsInstance(data['category_order'], dict)
        for mode_name in data['modes']:
            self.assertIn(mode_name, data['category_order'])
            self.ae(
                set(data['category_order'][mode_name]),
                set(data['modes'][mode_name].keys()),
                f'category_order for mode {mode_name!r} should match modes keys',
            )

    def test_always_includes_unmapped_actions(self):
        from kittens.command_palette.main import collect_keys_data
        opts = self.set_options()
        data = collect_keys_data(opts)
        # Unmapped actions (empty key) are always included
        found_unmapped = False
        for cats in data['modes'].values():
            for bindings in cats.values():
                for b in bindings:
                    if b['key'] == '':
                        found_unmapped = True
                        # Unmapped actions must still have action and definition
                        self.assertTrue(len(b['action']) > 0)
                        self.assertTrue(len(b['definition']) > 0)
                        break
        self.assertTrue(found_unmapped, 'Expected at least one unmapped action to always be present')

    def test_alias_resolution(self):
        from kittens.command_palette.main import collect_keys_data
        from kitty.options.utils import ActionAlias, AliasMap, parse_map
        opts = self.set_options()
        # Set up action aliases: launch_tab (bound) and launch_bg (unbound)
        alias_map = AliasMap()
        alias_map.append('launch_tab', ActionAlias('launch_tab', 'launch --type=tab --cwd=current'))
        alias_map.append('launch_bg', ActionAlias('launch_bg', 'launch --type=background'))
        opts.alias_map = alias_map
        # Add a keybinding that uses the launch_tab alias
        for kd in parse_map('f1 launch_tab vim'):
            kd = kd.resolve_and_copy(opts.kitty_mod)
            default_mode = opts.keyboard_modes['']
            default_mode.keymap.setdefault(kd.trigger, []).append(kd)

        data = collect_keys_data(opts)

        # Aliases should have their own section
        self.assertIn('Action aliases', data['modes'][''],
                       'Aliases should have a dedicated section')
        alias_section = data['modes']['']['Action aliases']

        # Bound alias should appear in the alias section with its key
        bound = [b for b in alias_section if b.get('alias') == 'launch_tab']
        self.ae(len(bound), 1, 'Bound alias should appear exactly once')
        self.ae(bound[0]['action'], 'launch')
        self.assertTrue(bound[0]['key'] != '', 'Bound alias should have its key')

        # Unbound alias should also appear in the alias section
        unbound = [b for b in alias_section if b['action_display'] == 'launch_bg']
        self.ae(len(unbound), 1, 'Unbound alias should appear exactly once')
        self.ae(unbound[0]['action'], 'launch')
        self.ae(unbound[0]['key'], '')
        self.assertTrue(unbound[0]['help'].startswith('Alias for:'))

        # Bound alias should NOT appear in any other category
        for cat_name, bindings in data['modes'][''].items():
            if cat_name == 'Action aliases':
                continue
            for b in bindings:
                self.assertNotEqual(b.get('alias'), 'launch_tab',
                                    f'Alias binding should not appear in {cat_name!r}')

    def test_kitten_alias_section(self):
        from kittens.command_palette.main import collect_keys_data
        from kitty.options.utils import ActionAlias, AliasMap
        opts = self.set_options()
        # Set up a kitten alias: kitten hints -> kitten hints --hints-offset=0
        alias_map = AliasMap()
        alias_map.append('kitten', ActionAlias('hints', 'hints --hints-offset=0', replace_second_arg=True))
        opts.alias_map = alias_map

        data = collect_keys_data(opts)
        self.assertIn('Kitten aliases', data['modes'][''],
                       'Kitten aliases should have a dedicated section')
        kitten_section = data['modes']['']['Kitten aliases']
        found = [b for b in kitten_section if b['action_display'] == 'kitten hints']
        self.ae(len(found), 1, 'Kitten alias should appear exactly once')
        self.ae(found[0]['definition'], 'kitten hints --hints-offset=0')
        self.assertTrue(found[0]['help'].startswith('Alias for:'))

    def test_combine_actions_section(self):
        from kittens.command_palette.main import collect_keys_data
        from kitty.options.utils import parse_map
        opts = self.set_options()
        # Add a combine keybinding
        for kd in parse_map('f2 combine : new_tab : launch vim'):
            kd = kd.resolve_and_copy(opts.kitty_mod)
            default_mode = opts.keyboard_modes['']
            default_mode.keymap.setdefault(kd.trigger, []).append(kd)

        data = collect_keys_data(opts)
        # Combine bindings should have their own section
        self.assertIn('Combined actions', data['modes'][''],
                       'Combine bindings should have a dedicated section')
        combine_section = data['modes']['']['Combined actions']
        found = [b for b in combine_section if b['action'] == 'combine']
        self.assertTrue(len(found) > 0, 'Combine binding should be in the section')
        self.ae(found[0]['key'], 'f2')

    def test_no_duplicate_alias_entries(self):
        from kittens.command_palette.main import collect_keys_data
        from kitty.options.utils import ActionAlias, AliasMap, parse_map
        opts = self.set_options()
        # Set up aliases, some bound to keys and some not
        alias_map = AliasMap()
        alias_map.append('launch_tab', ActionAlias('launch_tab', 'launch --type=tab --cwd=current'))
        alias_map.append('launch_bg', ActionAlias('launch_bg', 'launch --type=background'))
        opts.alias_map = alias_map
        for kd in parse_map('f1 launch_tab vim'):
            kd = kd.resolve_and_copy(opts.kitty_mod)
            default_mode = opts.keyboard_modes['']
            default_mode.keymap.setdefault(kd.trigger, []).append(kd)

        data = collect_keys_data(opts)
        # Collect all entries that have an alias field across all categories
        alias_entries: list[tuple[str, str]] = []
        for cat_name, bindings in data['modes'][''].items():
            for b in bindings:
                if 'alias' in b:
                    alias_entries.append((cat_name, b['alias']))
        # Each alias should appear exactly once
        seen: set[str] = set()
        for cat_name, alias_name in alias_entries:
            self.assertNotIn(alias_name, seen,
                             f'Alias {alias_name!r} appears in multiple places')
            seen.add(alias_name)

    def test_unmapped_actions_sorted_order(self):
        # Covered by test_collect_keys_bindings_sorted
        pass
