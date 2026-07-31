#!/usr/bin/env python
# License: GPL v3 Copyright: 2026, Kovid Goyal <kovid at kovidgoyal.net>

from unittest.mock import patch

from kitty.fast_data_types import LEFT_EDGE, Region
from kitty.options.utils import tab_title_wrap
from kitty.tab_bar import CellRange, TabBar, TabBarData, truncate_line, wrap_title

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
        # newlines are ignored unless tab_title_max_lines allows them, and the
        # dropped lines are marked with an ellipsis
        tb = self.vertical_tab_bar(tab_title_template='{title}\\nbr')
        self.ae(self.screen_lines(tb)[:4], ['t0…', '', 't1…', ''])
        self.ae(tuple(te.y for te in tb.tab_extents), (CellRange(0, 0), CellRange(2, 2)))

        # a newline now starts a new line at column zero, without staircasing,
        # and each tab occupies the two lines its title needs
        tb = self.vertical_tab_bar(tab_title_template='{title}\\nbr', tab_title_max_lines=2)
        self.ae(self.screen_lines(tb)[:6], ['t0', 'br', '', 't1', 'br', ''])
        self.ae(tuple(te.y for te in tb.tab_extents), (CellRange(0, 1), CellRange(3, 4)))

        # lines beyond the limit are dropped rather than bleeding into the next tab
        tb = self.vertical_tab_bar(tab_title_template='{title}\\nbr\\nextra', tab_title_max_lines=2)
        self.ae(self.screen_lines(tb)[:6], ['t0', 'br…', '', 't1', 'br…', ''])
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
    def test_vertical_tab_bar_fills_tab_width(self) -> None:
        # every line a tab occupies must be padded to the full width of the bar
        # in that tab's colors, otherwise uneven line lengths leave a ragged edge
        tb = self.vertical_tab_bar(tab_title_template='{title}\\nlonger-line', tab_title_max_lines=2)
        s = tb.screen
        self.ae([len(str(s.line(i))) for i in (0, 1, 3, 4)], [s.columns] * 4)

        def bg_of(line: int, col: int) -> int:
            return int(s.line(line).cursor_from(col).bg)

        # the padding after a short line uses the tab background, not the bar's
        for line in (0, 1):
            self.ae(bg_of(line, s.columns - 1), bg_of(line, 0))
        # and the two tabs still have distinct backgrounds
        self.assertNotEqual(bg_of(0, 0), bg_of(3, 0))

    def test_vertical_tab_bar_title_taller_than_bar(self) -> None:
        # a title needing more lines than the bar has must be clipped from the
        # bottom rather than scrolling the tab bar and losing its first lines
        tb = self.vertical_tab_bar(num_tabs=1, height=60, tab_title_template='{title}\\na\\nb\\nc\\nd', tab_title_max_lines=5)
        self.ae(self.screen_lines(tb), ['t0', 'a', 'b…'])
        self.ae(tuple(te.y for te in tb.tab_extents), (CellRange(0, 2),))

    def test_vertical_tab_bar_multiline_overflow(self) -> None:
        # only 4 lines fit, so two 2-line tabs are drawn and the rest are
        # replaced by an ellipsis on the last line
        tb = self.vertical_tab_bar(num_tabs=6, height=100, tab_title_template='{title}\\nbr', tab_title_max_lines=2)
        self.ae(self.screen_lines(tb), ['t0', 'br', 't1', 'br', '…'])
        self.ae(tuple(te.y for te in tb.tab_extents), (CellRange(0, 1), CellRange(2, 3)))

    def test_wrap_title(self) -> None:
        self.ae(wrap_title('hello world foo', 6).split('\n'), ['hello ', 'world ', 'foo'])
        # a word longer than the width has to be broken mid-word
        self.ae(wrap_title('unbreakable', 4).split('\n'), ['unbr', 'eaka', 'ble'])
        # explicit newlines are preserved and each line wrapped independently
        self.ae(wrap_title('a\nbb ccc', 4).split('\n'), ['a', 'bb c', 'cc'])
        # SGR escapes are zero width, so they do not count towards the width and
        # are never split in half
        self.ae(wrap_title('\x1b[31mred text', 4).split('\n'), ['\x1b[31mred ', 'text'])
        # wide characters take two cells each
        self.ae(wrap_title('日本語', 4).split('\n'), ['日本', '語'])
        # a width of zero means no wrapping
        self.ae(wrap_title('abc', 0), 'abc')

    def test_truncate_line(self) -> None:
        self.ae(truncate_line('abcdef', 4), 'abc…')
        self.ae(truncate_line('日本語', 4), '日…')
        # the ellipsis marks dropped content, so it is added even when the text
        # itself would have fit
        self.ae(truncate_line('ab', 4), 'ab…')
        self.ae(truncate_line('abcd', 4), 'abc…')

    def test_tab_title_wrap_option(self) -> None:
        for off in ('no', 'No', 'n', 'false', 'none', '0'):
            self.ae(tab_title_wrap(off), 0)
        for on in ('yes', 'y', 'true', 'YES'):
            self.ae(tab_title_wrap(on), -1)
        self.ae(tab_title_wrap('20'), 20)

    def test_vertical_tab_bar_wrapping(self) -> None:
        # set_options bypasses the config parser, so these take parsed values:
        # -1 is 'yes' (wrap at the width of the tab bar), a positive int a width
        long_title = 'feature/some-really-long-branch'

        def tb_with(**opts: object) -> list[str]:
            self.set_options({
                'tab_bar_edge': LEFT_EDGE,
                'tab_bar_style': 'separator',
                'tab_title_template': '{title}',
                **opts,
            })
            central, tab_bar = region(140, 0, 740, 240), region(0, 0, 140, 240)
            with (
                patch('kitty.tab_bar.cell_size_for_window', return_value=(10, 20)),
                patch('kitty.tab_bar.viewport_for_window', return_value=(central, tab_bar, 740, 240, 10, 20)),
                patch('kitty.tab_bar.set_tab_bar_render_data'),
                patch('kitty.tab_bar.get_boss', return_value=DummyBoss()),
            ):
                tb = TabBar(1)
                tb.layout()
                tb.update((TabBarData(title=long_title, tab_id=1, is_active=True),))
            return [line for line in self.screen_lines(tb) if line]

        # off by default: the title is truncated onto a single line as before.
        # The trailing text is the tail the separator style draws past the
        # ellipsis, which predates wrapping.
        self.ae(tb_with(tab_title_max_lines=3), ['feature/som… h'])
        # 'yes' wraps at the width of the tab bar
        self.ae(tb_with(tab_title_max_lines=3, tab_title_wrap=-1), ['feature/some-', 'really-long-b', 'ranch'])
        # a number wraps at that many cells
        self.ae(tb_with(tab_title_max_lines=3, tab_title_wrap=8), ['feature/', 'some-rea', 'lly-lon…'])
        # wrapping needs more than one line to have any effect
        self.ae(tb_with(tab_title_max_lines=1, tab_title_wrap=-1), ['feature/som… h'])
        # when wrapping needs more lines than allowed, the last one is truncated
        self.ae(tb_with(tab_title_max_lines=2, tab_title_wrap=-1), ['feature/some-', 'really-long…'])
