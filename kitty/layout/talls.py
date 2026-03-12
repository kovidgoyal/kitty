#!/usr/bin/env python
# License: GPLv3 Copyright: 2020, Kovid Goyal <kovid at kovidgoyal.net>

from kitty.typing_compat import WindowType
from kitty.window_list import WindowList

from .splits import Pair, Splits, SplitsLayoutOpts


class TallSplits(Splits):

    name = 'talls'
    layout_opts = SplitsLayoutOpts({})

    # -- Chain helpers (work for both horizontal and vertical chains) --

    def _collect_chain_leaves(self, node: 'Pair | int | None', horizontal: bool) -> 'list[Pair | int]':
        """Collect all leaf items from a chain in order.
        Items of the same orientation are flattened; other pairs are kept as opaque leaves."""
        if node is None:
            return []
        if isinstance(node, int):
            return [node]
        if node.horizontal == horizontal and not node.is_redundant:
            return (self._collect_chain_leaves(node.one, horizontal) +
                    self._collect_chain_leaves(node.two, horizontal))
        return [node]

    def _rebuild_chain_in_place(self, chain_root: 'Pair', horizontal: bool) -> None:
        """Flatten a chain into right-leaning form and set equal biases, modifying in place."""
        leaves = self._collect_chain_leaves(chain_root, horizontal)
        if len(leaves) <= 1:
            return

        # Build right-leaning structure directly into chain_root
        # First leaf goes into .one of chain_root, rest builds right-leaning into .two
        chain_root.horizontal = horizontal
        chain_root.one = leaves[0]

        if len(leaves) == 2:
            chain_root.two = leaves[1]
        else:
            # Build the rest as new pairs hanging off .two
            current = chain_root
            for i in range(1, len(leaves) - 1):
                new_pair = Pair(horizontal=horizontal)
                new_pair.one = leaves[i]
                current.two = new_pair
                current = new_pair
            current.two = leaves[-1]

        # Set equal biases: at depth i with remaining items, bias = 1/remaining
        current = chain_root
        remaining = len(leaves)
        while isinstance(current, Pair) and current.horizontal == horizontal and remaining > 1:
            current.bias = 1.0 / remaining
            remaining -= 1
            current = current.two

    def _find_chain_root(self, start: 'Pair', horizontal: bool) -> 'Pair':
        """Walk up to find the topmost pair of the given orientation in this chain."""
        root = self.pairs_root
        current = start
        while True:
            parent = current.parent(root)
            if parent is None or parent.horizontal != horizontal:
                break
            current = parent
        return current

    def _rebalance_chain_for_group(self, group_id: int, horizontal: bool) -> None:
        """Find the chain containing group_id, flatten it in place, and rebalance."""
        pair = self.pairs_root.pair_for_window(group_id)
        if pair is None:
            return
        chain_root = self._find_chain_root(pair, horizontal)
        self._rebuild_chain_in_place(chain_root, horizontal)

    def _rebalance_chain_around(self, window: WindowType, all_windows: WindowList, horizontal: bool) -> None:
        """Find the chain containing window, flatten it in place, and rebalance."""
        wg = all_windows.group_for_window(window)
        if wg is None:
            return
        self._rebalance_chain_for_group(wg.id, horizontal)

    def _insert_in_right_column(self, new_group_id: int, after_group_id: int | None = None) -> None:
        """Insert a new window into the right column.
        If after_group_id is given, insert right after that window.
        Otherwise append to the end."""
        root = self.pairs_root
        right = root.two

        if right is None:
            root.two = new_group_id
            return

        if isinstance(right, int):
            new_pair = Pair(horizontal=False)
            if after_group_id is not None and right == after_group_id:
                new_pair.one = right
                new_pair.two = new_group_id
            else:
                new_pair.one = right
                new_pair.two = new_group_id
            root.two = new_pair
            return

        # Walk the vertical chain to find insertion point
        if after_group_id is not None:
            current = right
            while isinstance(current, Pair) and not current.horizontal and not current.is_redundant:
                if current.one == after_group_id:
                    # Insert between current.one and current.two
                    new_pair = Pair(horizontal=False)
                    new_pair.one = new_group_id
                    new_pair.two = current.two
                    current.two = new_pair
                    return
                if current.two == after_group_id:
                    # after_group_id is the last item, append after it
                    new_pair = Pair(horizontal=False)
                    new_pair.one = current.two
                    new_pair.two = new_group_id
                    current.two = new_pair
                    return
                next_node = current.two
                if isinstance(next_node, Pair) and not next_node.horizontal and not next_node.is_redundant:
                    current = next_node
                else:
                    break

        # Fallback: append to end
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

    def _rebalance_all_chains(self) -> None:
        """Find all chain roots in the tree and rebalance each one."""
        root = self.pairs_root
        chain_roots = []
        for pair in root.self_and_descendants():
            if pair.is_redundant:
                continue
            parent = pair.parent(root)
            if parent is None or parent.horizontal != pair.horizontal:
                chain_roots.append(pair)
        for cr in chain_roots:
            self._rebuild_chain_in_place(cr, cr.horizontal)

    def remove_windows(self, *windows_to_remove: int) -> None:
        super().remove_windows(*windows_to_remove)
        self._rebalance_all_chains()

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
            if location == 'vsplit':
                self._rebalance_chain_around(window, all_windows, horizontal=True)
            elif location == 'hsplit':
                self._rebalance_chain_around(window, all_windows, horizontal=False)
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

        insert_after = None
        if aw is not None and (ag := all_windows.group_for_window(aw)) is not None:
            group_id = ag.id

            if not self._is_top_level(group_id):
                pair = root.pair_for_window(group_id)
                if pair is not None:
                    target_group = all_windows.add_window(window, next_to=aw, before=not after)
                    pair.split_and_add(group_id, target_group.id, horizontal=False, after=True)
                    self._rebalance_chain_for_group(target_group.id, horizontal=False)
                    return

            # If focused on a right-column tile, insert after it
            if group_id != root.one:
                insert_after = group_id

        target_group = all_windows.add_window(window, next_to=aw, before=not after)
        self._insert_in_right_column(target_group.id, after_group_id=insert_after)
        self._rebalance_all_chains()
