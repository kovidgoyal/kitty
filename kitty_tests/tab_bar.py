#!/usr/bin/env python
# License: GPL v3 Copyright: 2026, Kovid Goyal <kovid at kovidgoyal.net>

from unittest.mock import patch

from kitty.fast_data_types import LEFT_EDGE, Region
from kitty.tab_bar import CellRange, TabBar, TabBarData

from . import BaseTest


def region(left: int, top: int, right: int, bottom: int) -> Region:
    return Region((left, top, right, bottom, right - left, bottom - top))


class DummyBoss:
    class mappings:
        current_keyboard_mode_name = ''

    def tab_for_id(self, tab_id: int) -> None:
        return None


class TestTabBar(BaseTest):

    def test_vertical_tab_bar_hit_testing(self) -> None:
        self.set_options({
            'tab_bar_edge': LEFT_EDGE,
            'tab_bar_style': 'separator',
            'tab_title_template': '{title}',
        })
        central = region(120, 0, 400, 160)
        tab_bar = region(0, 0, 120, 160)
        geometries: list[tuple[int, int, int, int]] = []
        boss = DummyBoss()

        with (
            patch('kitty.tab_bar.cell_size_for_window', return_value=(10, 20)),
            patch('kitty.tab_bar.viewport_for_window', return_value=(central, tab_bar, 400, 160, 10, 20)),
            patch('kitty.tab_bar.set_tab_bar_render_data', side_effect=lambda *args: geometries.append(args[2:6])),
            patch('kitty.tab_bar.get_boss', return_value=boss),
        ):
            tb = TabBar(1)
            tb.layout()
            tb.update((
                TabBarData(title='one', tab_id=1, is_active=True),
                TabBarData(title='two', tab_id=2),
                TabBarData(title='three', tab_id=3),
            ))

        self.assertTrue(tb.is_vertical)
        self.ae(geometries[-1], (0, 0, 120, 160))
        self.ae(tb.drag_axis_coordinate(5, 35), 35)
        # single line titles occupy one line each, separated by a blank line
        self.ae(tuple(te.y for te in tb.tab_extents), (CellRange(0, 0), CellRange(2, 2), CellRange(4, 4)))
        self.ae(tb.tab_id_at(5, 10), 1)
        self.ae(tb.tab_id_at(110, 10), 1)
        self.ae(tb.tab_id_at(60, 50), 2)
        self.ae(tb.tab_id_at(60, 90), 3)
        self.ae(tb.tab_id_at(60, 130), 0)
        self.ae(tb.tab_id_at(180, 10), 0)

    def test_vertical_tab_bar_alignment(self) -> None:
        self.set_options({
            'tab_bar_align': 'end',
            'tab_bar_edge': LEFT_EDGE,
            'tab_bar_style': 'separator',
            'tab_title_template': '{title}',
        })
        central = region(120, 0, 400, 160)
        tab_bar = region(0, 0, 120, 160)
        boss = DummyBoss()

        with (
            patch('kitty.tab_bar.cell_size_for_window', return_value=(10, 20)),
            patch('kitty.tab_bar.viewport_for_window', return_value=(central, tab_bar, 400, 160, 10, 20)),
            patch('kitty.tab_bar.set_tab_bar_render_data'),
            patch('kitty.tab_bar.get_boss', return_value=boss),
        ):
            tb = TabBar(1)
            tb.layout()
            tb.update((
                TabBarData(title='one', tab_id=1, is_active=True),
                TabBarData(title='two', tab_id=2),
            ))

        # 8 lines available, two single line tabs plus a gap, aligned to the end
        self.ae(tuple(te.y for te in tb.tab_extents), (CellRange(5, 5), CellRange(7, 7)))
        self.ae(tb.tab_id_at(5, 10), 0)
        self.ae(tb.tab_id_at(5, 110), 1)
        self.ae(tb.tab_id_at(5, 150), 2)

    def vertical_tab_bar(self, num_tabs: int = 2, height: int = 160, **opts: object) -> TabBar:
        self.set_options({
            'tab_bar_edge': LEFT_EDGE,
            'tab_bar_style': 'separator',
            'tab_title_template': '{title}',
            **opts,
        })
        central = region(120, 0, 400, height)
        tab_bar = region(0, 0, 120, height)
        with (
            patch('kitty.tab_bar.cell_size_for_window', return_value=(10, 20)),
            patch('kitty.tab_bar.viewport_for_window', return_value=(central, tab_bar, 400, height, 10, 20)),
            patch('kitty.tab_bar.set_tab_bar_render_data'),
            patch('kitty.tab_bar.get_boss', return_value=DummyBoss()),
        ):
            tb = TabBar(1)
            tb.layout()
            tb.update(tuple(TabBarData(title=f't{i}', tab_id=i + 1, is_active=i == 0) for i in range(num_tabs)))
        return tb

    def screen_lines(self, tb: TabBar) -> list[str]:
        s = tb.screen
        return [str(s.line(i)).rstrip() for i in range(s.lines)]

    def test_vertical_tab_bar_multiline_titles(self) -> None:
        # newlines are ignored unless tab_title_max_lines allows them
        tb = self.vertical_tab_bar(tab_title_template='{title}\\nbr')
        self.ae(self.screen_lines(tb)[:4], ['t0', '', 't1', ''])
        self.ae(tuple(te.y for te in tb.tab_extents), (CellRange(0, 0), CellRange(2, 2)))

        # a newline now starts a new line at column zero, without staircasing,
        # and each tab occupies the two lines its title needs
        tb = self.vertical_tab_bar(tab_title_template='{title}\\nbr', tab_title_max_lines=2)
        self.ae(self.screen_lines(tb)[:6], ['t0', 'br', '', 't1', 'br', ''])
        self.ae(tuple(te.y for te in tb.tab_extents), (CellRange(0, 1), CellRange(3, 4)))

        # lines beyond the limit are dropped rather than bleeding into the next tab
        tb = self.vertical_tab_bar(tab_title_template='{title}\\nbr\\nextra', tab_title_max_lines=2)
        self.ae(self.screen_lines(tb)[:6], ['t0', 'br', '', 't1', 'br', ''])
        self.ae(tuple(te.y for te in tb.tab_extents), (CellRange(0, 1), CellRange(3, 4)))

    def test_vertical_tab_bar_mixed_title_heights(self) -> None:
        # a tab whose title has no newline stays one line tall even when the
        # limit is higher, so tabs pack according to what they actually use
        self.set_options({
            'tab_bar_edge': LEFT_EDGE,
            'tab_bar_style': 'separator',
            'tab_title_template': '{title}',
            'tab_title_max_lines': 3,
        })
        central = region(120, 0, 400, 160)
        tab_bar = region(0, 0, 120, 160)
        with (
            patch('kitty.tab_bar.cell_size_for_window', return_value=(10, 20)),
            patch('kitty.tab_bar.viewport_for_window', return_value=(central, tab_bar, 400, 160, 10, 20)),
            patch('kitty.tab_bar.set_tab_bar_render_data'),
            patch('kitty.tab_bar.get_boss', return_value=DummyBoss()),
        ):
            tb = TabBar(1)
            tb.layout()
            tb.update((
                TabBarData(title='one\ntwo', tab_id=1, is_active=True),
                TabBarData(title='solo', tab_id=2),
                TabBarData(title='a\nb\nc', tab_id=3),
            ))
        self.ae(self.screen_lines(tb)[:8], ['one', 'two', '', 'solo', '', 'a', 'b', 'c'])
        self.ae(tuple(te.y for te in tb.tab_extents), (CellRange(0, 1), CellRange(3, 3), CellRange(5, 7)))
        self.ae(tb.tab_id_at(5, 10), 1)
        self.ae(tb.tab_id_at(5, 30), 1)
        self.ae(tb.tab_id_at(5, 70), 2)
        self.ae(tb.tab_id_at(5, 110), 3)
        self.ae(tb.tab_id_at(5, 150), 3)

    def test_vertical_tab_bar_tab_spacing(self) -> None:
        # a blank line is left between tabs while there is room for it, but not
        # above the first tab, and the gaps are not part of any tab's extent so
        # clicking one activates nothing
        tb = self.vertical_tab_bar(num_tabs=3)
        self.ae(self.screen_lines(tb)[:6], ['t0', '', 't1', '', 't2', ''])
        self.ae(tuple(te.y for te in tb.tab_extents), (CellRange(0, 0), CellRange(2, 2), CellRange(4, 4)))
        self.ae(tb.tab_id_at(5, 10), 1)
        self.ae(tb.tab_id_at(5, 30), 0)
        self.ae(tb.tab_id_at(5, 50), 2)

        # the gap uses the tab bar background, not the neighbouring tab's
        self.ae(int(tb.screen.line(1).cursor_from(0).bg), 0)

        # spacing applies between multi-line tabs too
        tb = self.vertical_tab_bar(num_tabs=2, tab_title_max_lines=2, tab_title_template='{title}\\nbr')
        self.ae(self.screen_lines(tb)[:6], ['t0', 'br', '', 't1', 'br', ''])
        self.ae(tuple(te.y for te in tb.tab_extents), (CellRange(0, 1), CellRange(3, 4)))

    def test_vertical_tab_bar_tab_spacing_dropped_when_crowded(self) -> None:
        # once the tabs need the space the blank lines go away automatically,
        # rather than tabs being dropped in favour of keeping the gaps
        tb = self.vertical_tab_bar(num_tabs=8, height=160)
        self.ae(self.screen_lines(tb), [f't{i}' for i in range(8)])
        self.ae(len(tb.tab_extents), 8)

        # exactly enough room for spacing: 4 tabs need 4 + 3 gaps == 7 lines
        tb = self.vertical_tab_bar(num_tabs=4, height=140)
        self.ae(self.screen_lines(tb), ['t0', '', 't1', '', 't2', '', 't3'])
        self.ae(len(tb.tab_extents), 4)

    def test_vertical_tab_bar_title_taller_than_bar(self) -> None:
        # a title needing more lines than the bar has must be clipped from the
        # bottom rather than scrolling the tab bar and losing its first lines
        tb = self.vertical_tab_bar(num_tabs=1, height=60, tab_title_template='{title}\\na\\nb\\nc\\nd', tab_title_max_lines=5)
        self.ae(self.screen_lines(tb), ['t0', 'a', 'b'])
        self.ae(tuple(te.y for te in tb.tab_extents), (CellRange(0, 2),))

    def test_vertical_tab_bar_multiline_overflow(self) -> None:
        # only 4 lines fit, so two 2-line tabs are drawn and the rest are
        # replaced by an ellipsis on the last line
        tb = self.vertical_tab_bar(num_tabs=6, height=100, tab_title_template='{title}\\nbr', tab_title_max_lines=2)
        self.ae(self.screen_lines(tb), ['t0', 'br', 't1', 'br', '…'])
        self.ae(tuple(te.y for te in tb.tab_extents), (CellRange(0, 1), CellRange(2, 3)))
