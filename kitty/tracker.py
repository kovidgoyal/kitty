#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2016, Kovid Goyal <kovid at kovidgoyal.net>

from collections import defaultdict
from operator import itemgetter
from typing import Set, Tuple, Iterator

from .data_types import Cursor


def merge_ranges(ranges: Set[Tuple[int]]) -> Iterator[Tuple[int]]:
    if ranges:
        sorted_intervals = sorted(ranges, key=itemgetter(0))
        # low and high represent the bounds of the current run of merges
        low, high = sorted_intervals[0]

        for iv in sorted_intervals[1:]:
            if iv[0] <= high + 1:  # new interval overlaps current run or borders it
                high = max(high, iv[1])  # merge with the current run
            else:  # current run is over
                yield low, high  # yield accumulated interval
                low, high = iv  # start new run

        yield low, high  # end the final run


class ChangeTracker:

    def __init__(self, mark_dirtied=lambda: None):
        self.reset()
        self.mark_dirtied = mark_dirtied

    def reset(self):
        self._dirty = False
        self.changed_cursor = None
        self.changed_cells = defaultdict(set)
        self.changed_lines = set()
        self.screen_changed = False
        self.history_line_added_count = 0

    def dirty(self):
        if not self._dirty:
            self._dirty = True
            self.mark_dirtied()

    def cursor_changed(self, cursor: Cursor) -> None:
        self.changed_cursor = cursor
        self.dirty()

    def cursor_position_changed(self, cursor: Cursor) -> None:
        self.changed_cursor = cursor
        self.dirty()

    def update_screen(self):
        self.screen_changed = True
        self.dirty()

    def update_line_range(self, first_line, last_line):
        self.changed_lines |= set(range(first_line, last_line + 1))
        self.dirty()

    def update_cell_range(self, y, first_cell, last_cell):
        self.changed_cells[y].add((first_cell, last_cell))
        self.dirty()

    def line_added_to_history(self):
        self.history_line_added_count += 1
        self.dirty()

    def consolidate_changes(self):
        if self.screen_changed:
            self.changed_lines.clear()
            cc = {}
        else:
            cc = {y: tuple(merge_ranges(cell_ranges)) for y, cell_ranges in self.changed_cells.items() if y not in self.changed_lines}
        changes = {'screen': self.screen_changed, 'cursor': self.changed_cursor, 'lines': self.changed_lines,
                   'cells': cc, 'history_line_added_count': self.history_line_added_count}
        self.reset()
        return changes
