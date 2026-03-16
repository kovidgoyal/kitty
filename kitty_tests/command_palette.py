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
        # All category names should be from the known groups
        known_titles = set(groups.values())
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

    def test_unmapped_actions_sorted_order(self):
        from kittens.command_palette.main import collect_keys_data
        opts = self.set_options()
        data = collect_keys_data(opts)
        # In each category, mapped bindings (non-empty key) should come before unmapped ones
        for cat_name, bindings in data['modes'].get('', {}).items():
            seen_unmapped = False
            for b in bindings:
                if b['key'] == '':
                    seen_unmapped = True
                elif seen_unmapped:
                    self.fail(
                        f'In category {cat_name!r}, mapped binding {b!r} follows an unmapped one'
                    )
