#!/usr/bin/env python
# License: GPL v3 Copyright: 2024, Kovid Goyal <kovid at kovidgoyal.net>

from kitty.tab_bar import CellRange, TabExtent
from kitty.types import WindowGeometry

from . import BaseTest


class MockTab:
    def __init__(self, tab_id: int):
        self.id = tab_id


class MockTabBar:
    def __init__(self, extents: list[TabExtent], cell_width: int = 10, left: int = 0):
        self.tab_extents = extents
        self.cell_width = cell_width
        self.window_geometry = WindowGeometry(left=left, top=0, right=100, bottom=20, xnum=10, ynum=1)
        self.laid_out_once = True


class MockTabManager:
    """Mock TabManager for testing tab drag operations."""

    def __init__(self, num_tabs: int = 5):
        self.tabs = [MockTab(i + 1) for i in range(num_tabs)]
        self.os_window_id = 1
        self.swap_calls: list[tuple[int, int]] = []

    def _move_tab_to_index(self, from_index: int, to_index: int) -> None:
        """Move a tab from one index to another."""
        if from_index == to_index or not (0 <= from_index < len(self.tabs)) or not (0 <= to_index < len(self.tabs)):
            return

        tab = self.tabs.pop(from_index)
        self.tabs.insert(to_index, tab)
        # Track swap_tabs calls for verification
        if from_index < to_index:
            for i in range(from_index, to_index):
                self.swap_calls.append((i, i + 1))
        else:
            for i in range(from_index, to_index, -1):
                self.swap_calls.append((i, i - 1))

    def _calculate_drop_index(self, x: int, tab_bar: MockTabBar) -> int:
        """Calculate the drop index based on the x coordinate."""
        extents = tab_bar.tab_extents
        if not extents or not tab_bar.laid_out_once:
            return 0

        # Convert pixel x to cell position
        cell_width = tab_bar.cell_width
        geometry = tab_bar.window_geometry
        cell_x = (x - geometry.left) // cell_width

        for i, te in enumerate(extents):
            mid = (te.cell_range.start + te.cell_range.end) // 2
            if cell_x < mid:
                return i
        return len(extents)

    def tab_ids(self) -> list[int]:
        """Return list of tab IDs in order."""
        return [t.id for t in self.tabs]


class TestTabDrag(BaseTest):

    def test_move_tab_to_index_forward(self):
        """Test moving a tab forward in the list."""
        tm = MockTabManager(5)
        self.ae(tm.tab_ids(), [1, 2, 3, 4, 5])

        # Move tab 0 to position 3
        tm._move_tab_to_index(0, 3)
        self.ae(tm.tab_ids(), [2, 3, 4, 1, 5])

        # Verify swap calls: 0->1, 1->2, 2->3
        self.ae(tm.swap_calls, [(0, 1), (1, 2), (2, 3)])

    def test_move_tab_to_index_backward(self):
        """Test moving a tab backward in the list."""
        tm = MockTabManager(5)
        self.ae(tm.tab_ids(), [1, 2, 3, 4, 5])

        # Move tab 4 to position 1
        tm._move_tab_to_index(4, 1)
        self.ae(tm.tab_ids(), [1, 5, 2, 3, 4])

        # Verify swap calls: 4->3, 3->2, 2->1
        self.ae(tm.swap_calls, [(4, 3), (3, 2), (2, 1)])

    def test_move_tab_to_index_adjacent(self):
        """Test moving a tab to an adjacent position."""
        tm = MockTabManager(5)

        # Move tab 2 to position 3
        tm._move_tab_to_index(2, 3)
        self.ae(tm.tab_ids(), [1, 2, 4, 3, 5])
        self.ae(tm.swap_calls, [(2, 3)])

        # Reset and move backward
        tm = MockTabManager(5)
        tm._move_tab_to_index(3, 2)
        self.ae(tm.tab_ids(), [1, 2, 4, 3, 5])
        self.ae(tm.swap_calls, [(3, 2)])

    def test_move_tab_to_index_same_position(self):
        """Test that moving to the same position is a no-op."""
        tm = MockTabManager(5)
        tm._move_tab_to_index(2, 2)
        self.ae(tm.tab_ids(), [1, 2, 3, 4, 5])
        self.ae(tm.swap_calls, [])

    def test_move_tab_to_index_invalid(self):
        """Test that invalid indices are handled gracefully."""
        tm = MockTabManager(5)

        # Out of bounds
        tm._move_tab_to_index(-1, 2)
        self.ae(tm.tab_ids(), [1, 2, 3, 4, 5])

        tm._move_tab_to_index(2, 10)
        self.ae(tm.tab_ids(), [1, 2, 3, 4, 5])

        tm._move_tab_to_index(10, 2)
        self.ae(tm.tab_ids(), [1, 2, 3, 4, 5])

    def test_move_tab_to_index_first_to_last(self):
        """Test moving the first tab to the last position."""
        tm = MockTabManager(5)
        tm._move_tab_to_index(0, 4)
        self.ae(tm.tab_ids(), [2, 3, 4, 5, 1])

    def test_move_tab_to_index_last_to_first(self):
        """Test moving the last tab to the first position."""
        tm = MockTabManager(5)
        tm._move_tab_to_index(4, 0)
        self.ae(tm.tab_ids(), [5, 1, 2, 3, 4])

    def test_calculate_drop_index_basic(self):
        """Test basic drop index calculation."""
        # Create tab extents: 3 tabs at cells [0-9], [10-19], [20-29]
        extents = [
            TabExtent(tab_id=1, cell_range=CellRange(start=0, end=9)),
            TabExtent(tab_id=2, cell_range=CellRange(start=10, end=19)),
            TabExtent(tab_id=3, cell_range=CellRange(start=20, end=29)),
        ]
        tab_bar = MockTabBar(extents, cell_width=10, left=0)
        tm = MockTabManager(3)

        # Click in the first half of tab 1 (cells 0-4) -> drop at index 0
        self.ae(tm._calculate_drop_index(20, tab_bar), 0)  # cell 2

        # Click in the second half of tab 1 (cells 5-9) -> drop at index 1
        self.ae(tm._calculate_drop_index(70, tab_bar), 1)  # cell 7

        # Click in the first half of tab 2 (cells 10-14) -> drop at index 1
        self.ae(tm._calculate_drop_index(120, tab_bar), 1)  # cell 12

        # Click in the second half of tab 2 (cells 15-19) -> drop at index 2
        self.ae(tm._calculate_drop_index(170, tab_bar), 2)  # cell 17

        # Click after all tabs -> drop at index 3 (end)
        self.ae(tm._calculate_drop_index(300, tab_bar), 3)  # cell 30

    def test_calculate_drop_index_with_offset(self):
        """Test drop index calculation with window geometry offset."""
        extents = [
            TabExtent(tab_id=1, cell_range=CellRange(start=0, end=9)),
            TabExtent(tab_id=2, cell_range=CellRange(start=10, end=19)),
        ]
        # Tab bar starts at x=50 (left margin)
        tab_bar = MockTabBar(extents, cell_width=10, left=50)
        tm = MockTabManager(2)

        # Click at x=50 (first pixel of tab bar) -> cell 0 -> drop at index 0
        self.ae(tm._calculate_drop_index(50, tab_bar), 0)

        # Click at x=100 (cell 5) -> first half boundary -> drop at index 1
        self.ae(tm._calculate_drop_index(100, tab_bar), 1)

        # Click at x=200 (cell 15) -> second half of tab 2 -> drop at index 2
        self.ae(tm._calculate_drop_index(200, tab_bar), 2)

    def test_calculate_drop_index_empty(self):
        """Test drop index with no tab extents."""
        tab_bar = MockTabBar([], cell_width=10, left=0)
        tm = MockTabManager(0)

        # Should return 0 for empty tab bar
        self.ae(tm._calculate_drop_index(100, tab_bar), 0)

    def test_calculate_drop_index_not_laid_out(self):
        """Test drop index when tab bar is not laid out."""
        extents = [TabExtent(tab_id=1, cell_range=CellRange(start=0, end=9))]
        tab_bar = MockTabBar(extents, cell_width=10, left=0)
        tab_bar.laid_out_once = False
        tm = MockTabManager(1)

        # Should return 0 when not laid out
        self.ae(tm._calculate_drop_index(100, tab_bar), 0)

    def test_calculate_drop_index_single_tab(self):
        """Test drop index with a single tab."""
        extents = [TabExtent(tab_id=1, cell_range=CellRange(start=0, end=9))]
        tab_bar = MockTabBar(extents, cell_width=10, left=0)
        tm = MockTabManager(1)

        # Click before midpoint -> drop at 0
        self.ae(tm._calculate_drop_index(30, tab_bar), 0)  # cell 3

        # Click after midpoint -> drop at 1 (end)
        self.ae(tm._calculate_drop_index(70, tab_bar), 1)  # cell 7
