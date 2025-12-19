#!/usr/bin/env python
# License: GPLv3

import json

from . import BaseTest


class MockTab:
    """Mock Tab object for testing MRU functionality."""

    def __init__(self, tab_id: int, last_visited_at: float):
        self.id = tab_id
        self.last_visited_at = last_visited_at


class MockTabManager:
    """Mock TabManager object for testing MRU functionality."""

    def __init__(self, os_window_id: int, tabs: list[MockTab]):
        self.os_window_id = os_window_id
        self.tabs = tabs

    def get_mru_tabs(self) -> list[dict[str, any]]:
        """Return tabs sorted by most recently used (MRU) order."""
        tabs_with_timestamps = [
            {'id': tab.id, 'last_visited_at': tab.last_visited_at}
            for tab in self.tabs
        ]
        # Sort by last_visited_at in descending order (most recent first)
        tabs_with_timestamps.sort(key=lambda x: x['last_visited_at'], reverse=True)
        return tabs_with_timestamps


class MockBoss:
    """Mock Boss object for testing MRU functionality."""

    def __init__(self, tab_managers: dict[int, MockTabManager], active_tm_id: int | None = None):
        self.os_window_map = tab_managers
        self.active_tab_manager = tab_managers.get(active_tm_id) if active_tm_id else None

    def get_mru_tabs_all_os_windows(self) -> list[dict[str, any]]:
        """Get MRU tabs across all OS windows, sorted by most recent."""
        all_tabs: list[dict[str, any]] = []
        for os_window_id, tm in self.os_window_map.items():
            for tab_data in tm.get_mru_tabs():
                # Add os_window_id for context
                tab_data['os_window_id'] = os_window_id
                all_tabs.append(tab_data)
        # Sort all tabs across all OS windows by most recent
        all_tabs.sort(key=lambda x: x['last_visited_at'], reverse=True)
        return all_tabs


class TestMRU(BaseTest):

    def test_mru_single_os_window(self):
        """Test MRU ordering with tabs in a single OS window."""
        from kitty.rc.mru import mru

        # Create mock tabs with different timestamps
        # Simulate: tab1 created first, tab2 second, tab3 third, then switch back to tab1
        base_time = 1000.0
        tab1 = MockTab(1, base_time + 3.0)  # Most recent (switched back to)
        tab2 = MockTab(2, base_time + 1.0)  # Oldest
        tab3 = MockTab(3, base_time + 2.0)  # Middle

        # Create mock tab manager
        tm = MockTabManager(os_window_id=1, tabs=[tab1, tab2, tab3])

        # Create mock boss
        boss = MockBoss({1: tm}, active_tm_id=1)

        # Test with single OS window (default)
        payload = {'all_os_windows': False}
        result = mru.response_from_kitty(boss, None, lambda k, *args: payload.get(k))
        data = json.loads(result)

        # Verify correct number of tabs
        self.assertEqual(len(data), 3, 'Should return 3 tabs')

        # Verify MRU order: tab1 (most recent), tab3, tab2 (oldest)
        self.assertEqual(data[0]['id'], 1, 'First tab should be tab1 (most recently visited)')
        self.assertEqual(data[1]['id'], 3, 'Second tab should be tab3')
        self.assertEqual(data[2]['id'], 2, 'Third tab should be tab2 (oldest)')

        # Verify all have required fields
        for tab_data in data:
            self.assertIn('id', tab_data, 'Tab should have id')
            self.assertIn('last_visited_at', tab_data, 'Tab should have last_visited_at')
            self.assertIn('os_window_id', tab_data, 'Tab should have os_window_id')
            self.assertEqual(tab_data['os_window_id'], 1, 'OS window ID should be 1')

        # Verify timestamps are in descending order
        for i in range(len(data) - 1):
            self.assertGreaterEqual(
                data[i]['last_visited_at'],
                data[i+1]['last_visited_at'],
                f'Tab at index {i} should have timestamp >= tab at index {i+1}'
            )

    def test_mru_multiple_os_windows(self):
        """Test MRU ordering with tabs across multiple OS windows."""
        from kitty.rc.mru import mru

        # Create tabs in first OS window
        base_time = 1000.0
        tab1_win1 = MockTab(1, base_time + 5.0)  # 2nd most recent overall
        tab2_win1 = MockTab(2, base_time + 2.0)

        # Create tabs in second OS window
        tab1_win2 = MockTab(3, base_time + 7.0)  # Most recent overall
        tab2_win2 = MockTab(4, base_time + 1.0)  # Oldest overall
        tab3_win2 = MockTab(5, base_time + 4.0)

        # Create mock tab managers
        tm1 = MockTabManager(os_window_id=1, tabs=[tab1_win1, tab2_win1])
        tm2 = MockTabManager(os_window_id=2, tabs=[tab1_win2, tab2_win2, tab3_win2])

        # Create mock boss
        boss = MockBoss({1: tm1, 2: tm2}, active_tm_id=1)

        # Test with all OS windows
        payload = {'all_os_windows': True}
        result = mru.response_from_kitty(boss, None, lambda k, *args: payload.get(k))
        data = json.loads(result)

        # Verify correct number of tabs
        self.assertEqual(len(data), 5, 'Should return 5 tabs from both OS windows')

        # Verify MRU order across all OS windows
        expected_order = [3, 1, 5, 2, 4]  # Tab IDs in MRU order
        actual_order = [tab['id'] for tab in data]
        self.assertEqual(actual_order, expected_order, 'Tabs should be sorted by MRU across all OS windows')

        # Verify os_window_id is correct for each tab
        self.assertEqual(data[0]['os_window_id'], 2, 'Tab 3 should be in OS window 2')
        self.assertEqual(data[1]['os_window_id'], 1, 'Tab 1 should be in OS window 1')
        self.assertEqual(data[2]['os_window_id'], 2, 'Tab 5 should be in OS window 2')
        self.assertEqual(data[3]['os_window_id'], 1, 'Tab 2 should be in OS window 1')
        self.assertEqual(data[4]['os_window_id'], 2, 'Tab 4 should be in OS window 2')

        # Verify timestamps are in descending order
        timestamps = [tab['last_visited_at'] for tab in data]
        self.assertEqual(timestamps, sorted(timestamps, reverse=True), 'Timestamps should be in descending order')

    def test_mru_empty_tab_manager(self):
        """Test MRU command when there are no tabs."""
        from kitty.rc.mru import mru

        # Create empty tab manager
        tm = MockTabManager(os_window_id=1, tabs=[])
        boss = MockBoss({1: tm}, active_tm_id=1)

        # Test with empty tab manager
        payload = {'all_os_windows': False}
        result = mru.response_from_kitty(boss, None, lambda k, *args: payload.get(k))
        data = json.loads(result)

        # Verify empty list is returned
        self.assertEqual(len(data), 0, 'Should return empty list when no tabs exist')
        self.assertEqual(data, [], 'Should return empty JSON array')

    def test_mru_no_active_tab_manager(self):
        """Test MRU command when there is no active tab manager."""
        from kitty.rc.mru import mru

        # Create boss with no active tab manager
        boss = MockBoss({}, active_tm_id=None)

        # Test with no active tab manager
        payload = {'all_os_windows': False}
        result = mru.response_from_kitty(boss, None, lambda k, *args: payload.get(k))
        data = json.loads(result)

        # Verify empty list is returned
        self.assertEqual(len(data), 0, 'Should return empty list when no active tab manager')
        self.assertEqual(data, [], 'Should return empty JSON array')

    def test_mru_single_tab(self):
        """Test MRU command with only one tab."""
        from kitty.rc.mru import mru

        # Create single tab
        tab1 = MockTab(42, 1234567.89)
        tm = MockTabManager(os_window_id=1, tabs=[tab1])
        boss = MockBoss({1: tm}, active_tm_id=1)

        # Test with single tab
        payload = {'all_os_windows': False}
        result = mru.response_from_kitty(boss, None, lambda k, *args: payload.get(k))
        data = json.loads(result)

        # Verify single tab is returned
        self.assertEqual(len(data), 1, 'Should return 1 tab')
        self.assertEqual(data[0]['id'], 42, 'Tab ID should be 42')
        self.assertEqual(data[0]['last_visited_at'], 1234567.89, 'Timestamp should match')
        self.assertEqual(data[0]['os_window_id'], 1, 'OS window ID should be 1')

    def test_mru_timestamp_precision(self):
        """Test that MRU correctly handles tabs with very close timestamps."""
        from kitty.rc.mru import mru

        # Create tabs with very close timestamps (microsecond differences)
        base_time = 1000.0
        tab1 = MockTab(1, base_time + 0.001)
        tab2 = MockTab(2, base_time + 0.002)
        tab3 = MockTab(3, base_time + 0.003)

        tm = MockTabManager(os_window_id=1, tabs=[tab1, tab2, tab3])
        boss = MockBoss({1: tm}, active_tm_id=1)

        payload = {'all_os_windows': False}
        result = mru.response_from_kitty(boss, None, lambda k, *args: payload.get(k))
        data = json.loads(result)

        # Verify correct ordering even with close timestamps
        self.assertEqual([d['id'] for d in data], [3, 2, 1], 'Should correctly order tabs with close timestamps')

    def test_mru_json_format(self):
        """Test that MRU returns valid, properly formatted JSON."""
        from kitty.rc.mru import mru

        tab1 = MockTab(1, 1234567.89)
        tab2 = MockTab(2, 1234565.67)
        tm = MockTabManager(os_window_id=1, tabs=[tab1, tab2])
        boss = MockBoss({1: tm}, active_tm_id=1)

        payload = {'all_os_windows': False}
        result = mru.response_from_kitty(boss, None, lambda k, *args: payload.get(k))

        # Verify result is valid JSON
        data = json.loads(result)  # Should not raise exception

        # Verify it's a list
        self.assertIsInstance(data, list, 'Result should be a JSON array')

        # Verify each element is a dict with correct keys
        for tab_data in data:
            self.assertIsInstance(tab_data, dict, 'Each element should be a dict')
            self.assertEqual(set(tab_data.keys()), {'id', 'last_visited_at', 'os_window_id'},
                           'Each tab should have exactly these keys')
            self.assertIsInstance(tab_data['id'], int, 'id should be an integer')
            self.assertIsInstance(tab_data['last_visited_at'], float, 'last_visited_at should be a float')
            self.assertIsInstance(tab_data['os_window_id'], int, 'os_window_id should be an integer')
