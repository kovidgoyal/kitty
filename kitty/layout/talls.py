#!/usr/bin/env python
# License: GPLv3 Copyright: 2020, Kovid Goyal <kovid at kovidgoyal.net>

from kitty.typing_compat import WindowType
from kitty.window_list import WindowList

from .splits import Pair, Splits, SplitsLayoutOpts


class TallSplits(Splits):

    name = 'talls'
    layout_opts = SplitsLayoutOpts({})

    def _count_items_in_chain(self, node: 'Pair | int | None', horizontal: bool) -> int:
        """Count items in a chain of pairs with the given orientation."""
        if node is None:
            return 0
        if isinstance(node, int):
            return 1
        if node.horizontal == horizontal and not node.is_redundant:
            return 1 + self._count_items_in_chain(node.two, horizontal)
        return 1

    def _rebalance_chain(self, node: 'Pair | int | None', horizontal: bool) -> None:
        """Rebalance a chain of pairs so all items get equal space."""
        if node is None or isinstance(node, int):
            return
        if node.horizontal != horizontal or node.is_redundant:
            return
        count = self._count_items_in_chain(node, horizontal)
        if count <= 1:
            return
        current = node
        remaining = count
        while (isinstance(current, Pair) and current.horizontal == horizontal
               and not current.is_redundant and remaining > 1):
            current.bias = 1.0 / remaining
            remaining -= 1
            current = current.two

    def _find_chain_root(self, start: 'Pair', horizontal: bool) -> 'Pair':
        """Walk up to find the topmost pair of the given orientation in this chain."""
        root = self.pairs_root
        current = start
        while True:
            parent = current.parent(root)
            if parent is None or parent.horizontal != horizontal or parent is root:
                break
            current = parent
        return current

    def _rebalance_right_column(self) -> None:
        self._rebalance_chain(self.pairs_root.two, horizontal=False)

    def _append_to_right_column(self, new_group_id: int) -> None:
        """Add a new window as the last row in the right column."""
        root = self.pairs_root
        right = root.two

        if right is None:
            root.two = new_group_id
            return

        if isinstance(right, int):
            new_pair = Pair(horizontal=False)
            new_pair.one = right
            new_pair.two = new_group_id
            root.two = new_pair
            return

        current = right
        while isinstance(current, Pair) and not current.horizontal and not current.is_redundant:
            next_node = current.two
            if isinstance(next_node, Pair) and not next_node.horizontal and not next_node.is_redundant:
                current = next_node
            else:
                break

        new_pair = Pair(horizontal=False)
        new_pair.one = current.two
        new_pair.two = new_group_id
        current.two = new_pair

    def _is_top_level(self, group_id: int) -> bool:
        """Check if window is the main (left) pane or a direct row in the right column."""
        root = self.pairs_root
        if root.one == group_id:
            return True
        current = root.two
        while isinstance(current, Pair) and not current.horizontal and not current.is_redundant:
            if current.one == group_id:
                return True
            current = current.two
        if current == group_id:
            return True
        return False

    def _rebalance_around(self, window: WindowType, all_windows: WindowList, horizontal: bool) -> None:
        """Find the chain containing window and rebalance it."""
        root = self.pairs_root
        wg = all_windows.group_for_window(window)
        if wg is None:
            return
        pair = root.pair_for_window(wg.id)
        if pair is not None:
            chain_root = self._find_chain_root(pair, horizontal)
            self._rebalance_chain(chain_root, horizontal)

    def remove_windows(self, *windows_to_remove: int) -> None:
        super().remove_windows(*windows_to_remove)
        self._rebalance_right_column()

    def add_non_overlay_window(
        self,
        all_windows: WindowList,
        window: WindowType,
        location: str | None,
        bias: float | None = None,
        next_to: WindowType | None = None,
    ) -> None:
        if location in ('vsplit', 'hsplit', 'split'):
            super().add_non_overlay_window(all_windows, window, location, bias, next_to)
            # Rebalance the chain matching the split orientation
            if location == 'vsplit':
                self._rebalance_around(window, all_windows, horizontal=True)
            elif location == 'hsplit':
                self._rebalance_around(window, all_windows, horizontal=False)
            return

        root = self.pairs_root
        window_count = sum(1 for _ in root.all_window_ids())

        after = True
        if location in ('before', 'first'):
            after = False

        aw = next_to or all_windows.active_window

        if window_count <= 1:
            if bias:
                bias = max(0, min(abs(bias), 100)) / 100
            if aw is not None and (ag := all_windows.group_for_window(aw)) is not None:
                group_id = ag.id
                pair = root.pair_for_window(group_id)
                if pair is not None:
                    target_group = all_windows.add_window(window, next_to=aw, before=not after)
                    parent_pair = pair.split_and_add(group_id, target_group.id, horizontal=True, after=after)
                    if bias is not None:
                        parent_pair.bias = bias if parent_pair.one == target_group.id else (1 - bias)
                    return
            all_windows.add_window(window)
            g = all_windows.group_for_window(window)
            assert g is not None
            root.balanced_add(g.id)
            return

        if aw is not None and (ag := all_windows.group_for_window(aw)) is not None:
            group_id = ag.id

            if not self._is_top_level(group_id):
                # Nested inside a sub-split: add below focused pane
                pair = root.pair_for_window(group_id)
                if pair is not None:
                    target_group = all_windows.add_window(window, next_to=aw, before=not after)
                    pair.split_and_add(group_id, target_group.id, horizontal=False, after=True)
                    # Rebalance the vertical chain
                    new_pair = root.pair_for_window(target_group.id)
                    if new_pair is not None:
                        chain_root = self._find_chain_root(new_pair, horizontal=False)
                        self._rebalance_chain(chain_root, horizontal=False)
                    return

        # Top-level: append new row to right column
        target_group = all_windows.add_window(window, next_to=aw, before=not after)
        self._append_to_right_column(target_group.id)
        self._rebalance_right_column()
