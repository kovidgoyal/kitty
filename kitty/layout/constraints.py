#!/usr/bin/env python
# License: GPL v3 Copyright: 2026, kitty contributors

from collections import defaultdict
from collections.abc import Sequence
from math import floor
from typing import TYPE_CHECKING, NamedTuple, cast

from kitty.fast_data_types import AmoebaSolver
from kitty.types import Edges

if TYPE_CHECKING:
    from .base import CellBias


# Amoeba caps edit-variable strengths at AM_STRONG (1,000,000). Keep viewport
# edits at that level and all layout preferences below it so a soft preference
# can never enlarge the available geometry.
VIEWPORT_STRENGTH = 1_000_000.0
STRONG_PREFERENCE = 100_000.0
MEDIUM_PREFERENCE = 1_000.0
FRAME_EDGE_PREFERENCE = 10.0


class FrameSpec(NamedTuple):
    allocation: Edges
    preferred: Edges
    margins: Edges
    minimum_width: int
    minimum_height: int


class FrameConstraintModel:
    """Align kitty window frames and give equivalent shared edges a common gutter."""

    def __call__(
        self,
        specs: Sequence[FrameSpec],
        horizontal_neighbors: Sequence[tuple[int, int]],
        vertical_neighbors: Sequence[tuple[int, int]],
        minimum_gaps: tuple[int, int],
        preferred_gaps: tuple[int, int],
        unify_gaps: bool = False,
    ) -> tuple[tuple[Edges, ...], tuple[int, int]]:
        if not specs:
            return (), (0, 0)
        solver = AmoebaSolver()
        # Kitty windows whose allocation edges lie on the same line use the
        # same solver variable. This encodes alignment directly and keeps the
        # tableau small for grids, where many windows share each row/column line.
        aligned: dict[tuple[int, int, int], list[tuple[int, int]]] = defaultdict(list)
        pane_keys = []
        for i, spec in enumerate(specs):
            a = spec.allocation
            keys = ((0, 0, a.left), (1, 0, a.top), (0, 1, a.right), (1, 1, a.bottom))
            pane_keys.append(keys)
            for edge, key in enumerate(keys):
                aligned[key].append((i, edge))
        variables = {key: solver.add_variable() for key in aligned}
        frames = tuple(tuple(variables[key] for key in keys) for keys in pane_keys)

        if unify_gaps:
            gap = solver.add_variable()
            gaps = (gap, gap)
            gap_constraints = ((gap, max(minimum_gaps), max(preferred_gaps)),)
        else:
            gaps = (solver.add_variable(), solver.add_variable())
            gap_constraints = tuple(zip(gaps, minimum_gaps, preferred_gaps))
        for gap, minimum_gap, preferred_gap in gap_constraints:
            solver.add_constraint(((gap, 1.0),), '>=', 0.0)
            solver.add_constraint(((gap, 1.0),), '>=', max(0, minimum_gap), STRONG_PREFERENCE)
            solver.add_constraint(((gap, 1.0),), '==', max(minimum_gap, preferred_gap), MEDIUM_PREFERENCE)

        neighbor_edges: set[tuple[int, int]] = set()
        neighbor_variables: tuple[set[tuple[int, int]], set[tuple[int, int]]] = (set(), set())
        for before, after in horizontal_neighbors:
            neighbor_edges.update(((before, 2), (after, 0)))
            neighbor_variables[0].add((frames[before][2], frames[after][0]))
        for before, after in vertical_neighbors:
            neighbor_edges.update(((before, 3), (after, 1)))
            neighbor_variables[1].add((frames[before][3], frames[after][1]))

        for spec, (left, top, right, bottom) in zip(specs, frames):
            solver.add_constraint(((right, 1.0), (left, -1.0)), '>=', max(0, spec.minimum_width))
            solver.add_constraint(((bottom, 1.0), (top, -1.0)), '>=', max(0, spec.minimum_height))
        for (axis, trailing, coordinate), edges in aligned.items():
            variable = variables[axis, trailing, coordinate]
            relation = '<=' if trailing else '>='
            solver.add_constraint(((variable, 1.0),), relation, coordinate)
            preferred_values = sorted(specs[window].preferred[edge] for window, edge in edges)
            solver.add_constraint(((variable, 1.0),), '==', preferred_values[len(preferred_values) // 2], FRAME_EDGE_PREFERENCE)
            outer = tuple((window, edge) for window, edge in edges if (window, edge) not in neighbor_edges)
            if outer:
                margin = max(specs[window].margins[edge] for window, edge in outer)
                target = coordinate - margin if trailing else coordinate + margin
                solver.add_constraint(((variable, 1.0),), '==', target, STRONG_PREFERENCE)
        for gap, variables_for_axis in zip(gaps, neighbor_variables):
            for before, after in variables_for_axis:
                solver.add_constraint(((after, 1.0), (before, -1.0), (gap, -1.0)), '==', 0.0)

        solver.update_variables()
        # Pin the optimized gutters to integers before reading the frame edges.
        # Geometry and configured margins are pixel-valued, and making the second
        # solve exact prevents independent edge rounding from changing a gap at a
        # shared boundary.
        solved_gaps = tuple(max(0, floor(solver.value(gap) + 1e-9)) for gap in gaps)
        for (gap, _, _), solved_gap in zip(gap_constraints, solved_gaps):
            solver.add_constraint(((gap, 1.0),), '==', solved_gap)
        solver.update_variables()

        ans = []
        for variables in frames:
            values = tuple(round(solver.value(variable)) for variable in variables)
            ans.append(Edges(*values))
        return tuple(ans), cast(tuple[int, int], solved_gaps)


class FixedSize(NamedTuple):
    absolute: int = 0
    fraction: float = 0.0


class FixedConstraintModel:
    """Reserve dock regions, clipping later regions first on shortage.

    Rebuild when the ordered size specifications change. Resizing only updates
    the total-space edit variable, including for percentage sizes.
    """

    def __init__(self) -> None:
        self.signature: tuple[FixedSize, ...] | None = None
        self.solver = AmoebaSolver()
        self.total = 0
        self.content = 0
        self.sizes: tuple[int, ...] = ()

    def rebuild(self, requested: tuple[FixedSize, ...]) -> None:
        self.signature = requested
        self.solver = AmoebaSolver()
        self.total = self.solver.add_variable()
        self.content = self.solver.add_variable()
        self.sizes = tuple(self.solver.add_variable() for _ in requested)
        self.solver.add_edit_variable(self.total, VIEWPORT_STRENGTH)
        self.solver.add_constraint(tuple((size, 1.0) for size in self.sizes) + ((self.content, 1.0), (self.total, -1.0)), '==', 0.0)
        self.solver.add_constraint(((self.content, 1.0),), '>=', 0.0)
        for i, (size, preferred) in enumerate(zip(self.sizes, requested)):
            self.solver.add_constraint(((size, 1.0),), '>=', 0.0)
            priority = float(len(requested) - i)
            self.solver.add_constraint(((size, 1.0), (self.total, -preferred.fraction)), '==', preferred.absolute, priority)

    def __call__(self, total: int, requested: Sequence[FixedSize]) -> tuple[list[int], int]:
        signature = tuple(FixedSize(max(0, x.absolute), max(0.0, x.fraction)) for x in requested)
        if signature != self.signature:
            self.rebuild(signature)
        total = max(0, total)
        self.solver.suggest_value(self.total, total)
        self.solver.update_variables()
        sizes = []
        for size, preferred in zip(self.sizes, signature):
            solved = self.solver.value(size)
            ideal = preferred.absolute + preferred.fraction * total
            if abs(solved - ideal) < 1e-9:
                solved = ideal
            elif abs(solved - round(solved)) < 1e-9:
                solved = round(solved)
            sizes.append(max(0, floor(solved)))
        remainder = total - sum(sizes)
        if remainder < 0:
            raise AssertionError(f'Amoeba allocated {sum(sizes)} fixed pixels from {total}')
        return sizes, remainder


class SplitConstraintModel:
    """Allocate the two children of a split while honoring soft minima.

    Rebuild when the bias, border or either minimum changes. Resizing only
    updates the available-space edit variable.
    """

    def __init__(self) -> None:
        self.signature: tuple[float, int, int, int] | None = None
        self.solver = AmoebaSolver()
        self.available = 0
        self.first = 0
        self.second = 0

    def rebuild(self, bias: float, border: int, first_minimum: int, second_minimum: int) -> None:
        self.signature = bias, border, first_minimum, second_minimum
        self.solver = AmoebaSolver()
        self.available = self.solver.add_variable()
        self.first = self.solver.add_variable()
        self.second = self.solver.add_variable()
        self.solver.add_edit_variable(self.available, VIEWPORT_STRENGTH)
        self.solver.add_constraint(((self.first, 1.0), (self.second, 1.0), (self.available, -1.0)), '==', 0.0)
        self.solver.add_constraint(((self.first, 1.0),), '>=', 0.0)
        self.solver.add_constraint(((self.second, 1.0),), '>=', 0.0)
        self.solver.add_constraint(((self.first, 1.0),), '>=', first_minimum, STRONG_PREFERENCE)
        self.solver.add_constraint(((self.second, 1.0),), '>=', second_minimum, STRONG_PREFERENCE)
        ideal_constant = 2 * bias * border - border
        self.solver.add_constraint(((self.first, 1.0), (self.available, -bias)), '==', ideal_constant, MEDIUM_PREFERENCE)

    def __call__(self, length: int, bias: float, border: int, first_minimum: int, second_minimum: int) -> tuple[int, int]:
        signature = bias, border, first_minimum, second_minimum
        if signature != self.signature:
            self.rebuild(*signature)
        available = max(0, length - 2 * border)
        self.solver.suggest_value(self.available, available)
        self.solver.update_variables()
        solved = self.solver.value(self.first)
        ideal = bias * length - border
        if abs(solved - ideal) < 1e-9:
            solved = ideal
        elif abs(solved - round(solved)) < 1e-9:
            solved = round(solved)
        first = max(0, min(available, floor(solved)))
        return first, available - first


class LinearConstraintModel:
    """Allocate terminal cells along one axis using a persistent Amoeba solver.

    Rebuild when the kitty window count or effective bias shares change.
    Resizing only updates the total-cell edit variable.
    """

    def __init__(self) -> None:
        self.signature: tuple[float, ...] = ()
        self.solver = AmoebaSolver()
        self.total = 0
        self.sizes: tuple[int, ...] = ()

    def rebuild(self, shares: tuple[float, ...]) -> None:
        self.signature = shares
        self.solver = AmoebaSolver()
        self.total = self.solver.add_variable()
        self.solver.add_edit_variable(self.total, VIEWPORT_STRENGTH)
        self.sizes = tuple(self.solver.add_variable() for _ in shares)
        self.solver.add_constraint(tuple((size, 1.0) for size in self.sizes) + ((self.total, -1.0),), '==', 0.0)
        for i, (size, share) in enumerate(zip(self.sizes, shares)):
            self.solver.add_constraint(((size, 1.0),), '>=', 0.0)
            terms = ((size, 1.0), (self.total, -share))
            if i < len(self.sizes) - 1:
                # Existing layouts assign all rounding residue to the last kitty window.
                # Fix the preceding ideal sizes and let the sum constraint derive
                # the final one so that quantization preserves that policy.
                self.solver.add_constraint(terms, '==', 0.0)
            else:
                self.solver.add_constraint(terms, '==', 0.0, MEDIUM_PREFERENCE)

    def __call__(self, bias: 'CellBias', number_of_windows: int, number_of_cells: int) -> list[int]:
        legacy_empty_bias: Sequence[float] | None = None
        if isinstance(bias, dict):
            # Imported lazily to keep the constraint primitives independent of
            # the pixel/decorations layer in base.py.
            from .base import convert_bias_map

            converted = convert_bias_map(cast(dict[int, float], bias), number_of_windows, number_of_cells)
            if bias:
                bias = converted
            else:
                # An empty map means equal shares, so keep a resize-stable
                # solver signature. Retain the converted values only for the
                # legacy float-to-cell quantization below.
                legacy_empty_bias, bias = converted, None
        cells_per_window = number_of_cells // number_of_windows
        has_usable_bias = bias is not None and number_of_windows > 1 and len(bias) == number_of_windows and cells_per_window > 5
        has_usable_empty_bias = legacy_empty_bias is not None and number_of_windows > 1 and cells_per_window > 5
        shares = tuple(map(float, bias)) if has_usable_bias else (1.0 / number_of_windows,) * number_of_windows
        if shares != self.signature:
            self.rebuild(shares)
        self.solver.suggest_value(self.total, number_of_cells)
        self.solver.update_variables()

        # Cassowary is real-valued; terminal geometry is not. Round down first
        # and assign the remainder using kitty's existing deterministic policy.
        if has_usable_empty_bias:
            # Preserve calculate_cells_map()'s historical rounding while the
            # solver itself retains resize-stable equal-share constraints.
            cells_map = [max(0, floor(share * number_of_cells)) for share in legacy_empty_bias]
        else:
            solved_sizes = (self.solver.value(size) for size in self.sizes)
            ideal_sizes = (share * number_of_cells for share in shares)
            # Simplex row operations can move an exact integer by a few ulps.
            # Snap those values back to the declared ideal before flooring so
            # migration does not change kitty's float-to-cell rounding.
            cells_map = [max(0, floor(ideal if abs(solved - ideal) < 1e-9 else solved)) for solved, ideal in zip(solved_sizes, ideal_sizes)]
        if has_usable_bias or has_usable_empty_bias:
            while min(cells_map) < 5:
                maxi, mini = map(cells_map.index, (max(cells_map), min(cells_map)))
                if maxi == mini:
                    break
                cells_map[mini] += 1
                cells_map[maxi] -= 1
        extra = number_of_cells - sum(cells_map)
        if extra < 0:
            raise AssertionError(f'Amoeba allocated {sum(cells_map)} cells from {number_of_cells}')
        cells_map[-1] += extra
        return cells_map
