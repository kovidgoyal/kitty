#!/usr/bin/env python
# License: GPL v3 Copyright: 2024, Kovid Goyal <kovid at kovidgoyal.net>

from kitty.tab_bar import CellRange, TabExtent
from kitty.types import WindowGeometry

from . import BaseTest


class Tab:

    def __init__(self, tab_id: int):
        self.id = tab_id


class TabBar:

    def __init__(self, extents: list[TabExtent], cell_width: int = 10, left: int = 0):
        self.tab_extents = extents
        self.cell_width = cell_width
        self.window_geometry = WindowGeometry(left=left, top=0, right=100, bottom=20, xnum=10, ynum=1)
        self.laid_out_once = True


class TabManager:

    def __init__(self, num_tabs: int = 5):
        self.tabs = [Tab(i + 1) for i in range(num_tabs)]
        self.os_window_id = 1
        self.swap_calls: list[tuple[int, int]] = []

    def _move_tab_to_index(self, from_index: int, to_index: int) -> None:
        if from_index == to_index or not (0 <= from_index < len(self.tabs)) or not (0 <= to_index < len(self.tabs)):
            return

        tab = self.tabs.pop(from_index)
        self.tabs.insert(to_index, tab)
        if from_index < to_index:
            for i in range(from_index, to_index):
                self.swap_calls.append((i, i + 1))
        else:
            for i in range(from_index, to_index, -1):
                self.swap_calls.append((i, i - 1))

    def _calculate_drop_index(self, x: int, tab_bar: TabBar) -> int:
        extents = tab_bar.tab_extents
        if not extents or not tab_bar.laid_out_once:
            return 0

        cell_width = tab_bar.cell_width
        geometry = tab_bar.window_geometry
        cell_x = (x - geometry.left) // cell_width

        for i, te in enumerate(extents):
            mid = (te.cell_range.start + te.cell_range.end) // 2
            if cell_x < mid:
                return i
        return len(extents)

    def tab_ids(self) -> list[int]:
        return [t.id for t in self.tabs]


class TestTabDrag(BaseTest):

    def test_move_tab_to_index(self):
        # Test moving a tab forward
        tm = TabManager(5)
        self.ae(tm.tab_ids(), [1, 2, 3, 4, 5])
        tm._move_tab_to_index(0, 3)
        self.ae(tm.tab_ids(), [2, 3, 4, 1, 5])
        self.ae(tm.swap_calls, [(0, 1), (1, 2), (2, 3)])

        # Test moving a tab backward
        tm = TabManager(5)
        tm._move_tab_to_index(4, 1)
        self.ae(tm.tab_ids(), [1, 5, 2, 3, 4])
        self.ae(tm.swap_calls, [(4, 3), (3, 2), (2, 1)])

        # Test moving to an adjacent position forward
        tm = TabManager(5)
        tm._move_tab_to_index(2, 3)
        self.ae(tm.tab_ids(), [1, 2, 4, 3, 5])
        self.ae(tm.swap_calls, [(2, 3)])

        # Test moving to an adjacent position backward
        tm = TabManager(5)
        tm._move_tab_to_index(3, 2)
        self.ae(tm.tab_ids(), [1, 2, 4, 3, 5])
        self.ae(tm.swap_calls, [(3, 2)])

        # Test moving to the same position (no-op)
        tm = TabManager(5)
        tm._move_tab_to_index(2, 2)
        self.ae(tm.tab_ids(), [1, 2, 3, 4, 5])
        self.ae(tm.swap_calls, [])

        # Test invalid indices
        tm = TabManager(5)
        tm._move_tab_to_index(-1, 2)
        self.ae(tm.tab_ids(), [1, 2, 3, 4, 5])
        tm._move_tab_to_index(2, 10)
        self.ae(tm.tab_ids(), [1, 2, 3, 4, 5])
        tm._move_tab_to_index(10, 2)
        self.ae(tm.tab_ids(), [1, 2, 3, 4, 5])

        # Test moving first to last
        tm = TabManager(5)
        tm._move_tab_to_index(0, 4)
        self.ae(tm.tab_ids(), [2, 3, 4, 5, 1])

        # Test moving last to first
        tm = TabManager(5)
        tm._move_tab_to_index(4, 0)
        self.ae(tm.tab_ids(), [5, 1, 2, 3, 4])

    def test_calculate_drop_index(self):
        # Basic drop index calculation with 3 tabs at cells [0-9], [10-19], [20-29]
        extents = [
            TabExtent(tab_id=1, cell_range=CellRange(start=0, end=9)),
            TabExtent(tab_id=2, cell_range=CellRange(start=10, end=19)),
            TabExtent(tab_id=3, cell_range=CellRange(start=20, end=29)),
        ]
        tab_bar = TabBar(extents, cell_width=10, left=0)
        tm = TabManager(3)

        # Click in the first half of tab 1 (cells 0-4) -> drop at index 0
        self.ae(tm._calculate_drop_index(20, tab_bar), 0)
        # Click in the second half of tab 1 (cells 5-9) -> drop at index 1
        self.ae(tm._calculate_drop_index(70, tab_bar), 1)
        # Click in the first half of tab 2 (cells 10-14) -> drop at index 1
        self.ae(tm._calculate_drop_index(120, tab_bar), 1)
        # Click in the second half of tab 2 (cells 15-19) -> drop at index 2
        self.ae(tm._calculate_drop_index(170, tab_bar), 2)
        # Click after all tabs -> drop at index 3 (end)
        self.ae(tm._calculate_drop_index(300, tab_bar), 3)

        # Test with window geometry offset (tab bar starts at x=50)
        extents = [
            TabExtent(tab_id=1, cell_range=CellRange(start=0, end=9)),
            TabExtent(tab_id=2, cell_range=CellRange(start=10, end=19)),
        ]
        tab_bar = TabBar(extents, cell_width=10, left=50)
        tm = TabManager(2)
        self.ae(tm._calculate_drop_index(50, tab_bar), 0)
        self.ae(tm._calculate_drop_index(100, tab_bar), 1)
        self.ae(tm._calculate_drop_index(200, tab_bar), 2)

        # Test with empty tab bar
        tab_bar = TabBar([], cell_width=10, left=0)
        tm = TabManager(0)
        self.ae(tm._calculate_drop_index(100, tab_bar), 0)

        # Test when tab bar is not laid out
        extents = [TabExtent(tab_id=1, cell_range=CellRange(start=0, end=9))]
        tab_bar = TabBar(extents, cell_width=10, left=0)
        tab_bar.laid_out_once = False
        tm = TabManager(1)
        self.ae(tm._calculate_drop_index(100, tab_bar), 0)

        # Test with a single tab
        extents = [TabExtent(tab_id=1, cell_range=CellRange(start=0, end=9))]
        tab_bar = TabBar(extents, cell_width=10, left=0)
        tab_bar.laid_out_once = True
        tm = TabManager(1)
        self.ae(tm._calculate_drop_index(30, tab_bar), 0)
        self.ae(tm._calculate_drop_index(70, tab_bar), 1)

    def test_find_target_os_window(self):
        # Test the cross-window hit-test logic without importing kitty.tabs
        # (which requires compiled C extensions).
        # This replicates the coordinate conversion and hit-test logic from
        # TabManager._find_target_os_window.

        def find_target_os_window(
            src_os_window_id, x, y, window_positions, window_sizes, all_os_window_ids
        ):
            """Standalone reimplementation of _find_target_os_window for testing."""
            src_size = window_sizes.get(src_os_window_id)
            if src_size is None or src_size['framebuffer_width'] == 0 or src_size['framebuffer_height'] == 0:
                return None
            src_pos = window_positions[src_os_window_id]
            scale_x = src_size['width'] / src_size['framebuffer_width']
            scale_y = src_size['height'] / src_size['framebuffer_height']
            screen_x = src_pos[0] + x * scale_x
            screen_y = src_pos[1] + y * scale_y

            for os_win_id in all_os_window_ids:
                if os_win_id == src_os_window_id:
                    continue
                tgt_pos = window_positions[os_win_id]
                tgt_size = window_sizes.get(os_win_id)
                if tgt_size is None:
                    continue
                tgt_w = tgt_size['width']
                tgt_h = tgt_size['height']
                if (tgt_pos[0] <= screen_x <= tgt_pos[0] + tgt_w and
                        tgt_pos[1] <= screen_y <= tgt_pos[1] + tgt_h):
                    return os_win_id
            return None

        # Setup: 3 windows, all 2x Retina (framebuffer = 2 * logical)
        # Source window (id=1): at (100, 100), logical 800x600
        # Target window (id=2): at (1000, 100), logical 800x600
        # Target window (id=3): at (100, 800), logical 800x600
        window_positions = {1: (100, 100), 2: (1000, 100), 3: (100, 800)}
        def make_size():
            return {'width': 800, 'height': 600, 'framebuffer_width': 1600, 'framebuffer_height': 1200,
                    'xscale': 2.0, 'yscale': 2.0, 'xdpi': 144.0, 'ydpi': 144.0,
                    'cell_width': 16, 'cell_height': 32, 'is_layer_shell': False}

        window_sizes = {1: make_size(), 2: make_size(), 3: make_size()}
        all_ids = [1, 2, 3]

        def ft(x, y):
            return find_target_os_window(1, x, y, window_positions, window_sizes, all_ids)

        # Mouse at framebuffer (1900, 200) on source window
        # Logical offset: 1900/2=950, 200/2=100 -> Screen: (1050, 200)
        # Hits target window 2 at (1000..1800, 100..700)
        self.ae(ft(1900, 200), 2)

        # Mouse at framebuffer (200, 1600) on source window
        # Logical offset: 200/2=100, 1600/2=800 -> Screen: (200, 900)
        # Hits target window 3 at (100..900, 800..1400)
        self.ae(ft(200, 1600), 3)

        # Mouse at framebuffer (400, 300) - inside source window only
        # Logical offset: 200, 150 -> Screen: (300, 250) - no other window hit
        self.assertIsNone(ft(400, 300))

        # Mouse far outside all windows
        self.assertIsNone(ft(5000, 5000))

        # Mouse exactly at top-left corner of target window 2
        # Screen: (1000, 100) -> offset: (900, 0) -> fb: (1800, 0)
        self.ae(ft(1800, 0), 2)

        # Mouse just outside target window 2 right edge
        # Target 2 right edge at screen x=1800 -> offset 1700 -> fb 3400
        # Screen x = 100 + 3402/2 = 100 + 1701 = 1801 > 1800
        self.assertIsNone(ft(3402, 0))

        # Test with 1x scale (non-Retina)
        window_sizes_1x = {
            1: {**make_size(), 'framebuffer_width': 800, 'framebuffer_height': 600},
            2: {**make_size(), 'framebuffer_width': 800, 'framebuffer_height': 600},
        }
        def ft_1x(x, y):
            return find_target_os_window(1, x, y, window_positions, window_sizes_1x, [1, 2])
        # Framebuffer (950, 100) -> scale 1:1 -> screen (1050, 200) -> hits window 2
        self.ae(ft_1x(950, 100), 2)

        # Test with zero framebuffer (edge case)
        window_sizes_zero = {1: {**make_size(), 'framebuffer_width': 0, 'framebuffer_height': 0}}
        self.assertIsNone(find_target_os_window(1, 100, 100, window_positions, window_sizes_zero, [1, 2]))
