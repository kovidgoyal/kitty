#!/usr/bin/env python
# License: GPLv3 Copyright: 2026, Kovid Goyal, <kovid at kovidgoyal.net>

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING
from weakref import WeakKeyDictionary

from kitty.layout.splits import Pair, Splits

from .base import MATCH_WINDOW_OPTION, ArgsType, Boss, PayloadGetType, PayloadType, RCOptions, RemoteCommand, ResponseType, Window
from .resize_window import resize_window

if TYPE_CHECKING:
    from kitty.cli_stub import ResizeWindowEdgeRCOptions as CLIOptions


@dataclass
class EdgeResizeSession:
    layout: Splits
    biases: tuple[tuple[Pair, float], ...]
    topology: tuple[tuple[int, bool, int, int], ...]
    selected: str = ''
    divider: Pair | None = None
    horizontal: bool | None = None


def topology(layout: Splits) -> tuple[tuple[int, bool, int, int], ...]:
    def child_id(child: Pair | int | None) -> int:
        return id(child) if isinstance(child, Pair) else child or 0

    return tuple((id(p), p.horizontal, child_id(p.one), child_id(p.two)) for p in layout.pairs_root.self_and_descendants())


class ResizeWindowEdge(RemoteCommand):
    protocol_spec = __doc__ = """
    match/str: Which pane or resize overlay to use
    self/bool: Use the window in which this command is run
    operation/choices.start.state.select.move.reset: The resize session operation
    edge/choices.none.left.right.top.bottom: The edge to select or move
    increment/int: Number of cells to move, positive rightwards or downwards
    fraction/float: Fraction of remaining steps, or zero for ordinary steps
    divider/str: Optional divider identity returned by selection
    """
    short_desc = 'Select and move an internal pane edge in the Splits layout'
    desc = (
        'Move a specific internal pane edge, keeping other same-axis dividers in place.'
        ' Positive increments move rightwards or downwards; negative increments move leftwards or upwards.'
        ' The resize-window kitten uses this command for its edge strategy.'
        ' Start opens a session; reset restores its original divider proportions if the split structure has not changed.'
    )
    options_spec = (
        MATCH_WINDOW_OPTION
        + """\n
--operation
type=choices
choices=start,state,select,move,reset
default=move
Select a session operation. Start creates a session if needed, preserving an
existing snapshot, and automatically selects a sole internal edge. State lists
internal edges and clears the selection; select chooses an edge without moving
it; move adjusts an edge; reset restores the session's original proportions.


--edge
type=choices
choices=none,left,right,top,bottom
default=none
The pane edge. Outside edges cannot be selected or moved.


--increment -i
type=int
default=2
Number of cells to move the divider. Can be negative.


--fraction
type=float
default=0
Take this fraction of the remaining resize steps, rounding up. Zero uses an
ordinary step. Must be between zero and one.


--divider
default=
Only move the divider with this identity, as returned by select.


--self
type=bool-set
Use the window this command is run in, rather than the active window.
"""
    )

    def __init__(self) -> None:
        super().__init__()
        # Each overlay has its own snapshot, released when that overlay closes.
        self.sessions: WeakKeyDictionary[Window, EdgeResizeSession] = WeakKeyDictionary()

    def message_to_kitty(self, global_opts: RCOptions, opts: 'CLIOptions', args: ArgsType) -> PayloadType:
        resize_window.validate_fraction(opts.fraction)
        return {name: getattr(opts, name) for name in ('match', 'self', 'operation', 'edge', 'increment', 'fraction', 'divider')}

    def start_session(self, window: Window, layout: object) -> EdgeResizeSession | None:
        if not isinstance(layout, Splits):
            return None
        session = EdgeResizeSession(layout, tuple((p, p.bias) for p in layout.pairs_root.self_and_descendants()), topology(layout))
        self.sessions[window] = session
        return session

    def restore_session(self, window: Window) -> tuple[bool, str]:
        session = self.sessions.get(window)
        if session is None:
            return False, ''
        tab = window.tabref()
        if tab is None or tab.current_layout is not session.layout or topology(session.layout) != session.topology:
            status = 'Split structure changed; original sizes cannot be restored'
        else:
            for pair, bias in session.biases:
                pair.bias = bias
            tab.relayout()
            status = 'Restored sizes from when resize mode opened'
        session.selected, session.divider = '', None
        return True, status

    def response_from_kitty(self, boss: Boss, window: Window | None, payload_get: PayloadGetType) -> ResponseType:
        windows = self.windows_for_match_payload(boss, window, payload_get)
        window = windows[0] if windows else None
        if window is None or (tab := window.tabref()) is None:
            raise ValueError('Window no longer exists')
        operation = payload_get('operation')
        edge = payload_get('edge')
        fraction = payload_get('fraction')
        resize_window.validate_fraction(fraction)
        if operation not in ('start', 'state', 'select', 'move', 'reset') or edge not in ('none', 'left', 'right', 'top', 'bottom'):
            raise ValueError('Invalid edge resize operation')
        layout = tab.current_layout
        if not isinstance(layout, Splits):
            return json.dumps({'edges': [], 'selected': '', 'divider': '', 'status': 'Edge resizing requires the Splits layout'})
        session = self.sessions.get(window)
        if session is None:
            session = self.start_session(window, layout)
            assert session is not None
        status = ''
        if operation == 'reset':
            _, status = self.restore_session(window)
        elif operation == 'state':
            session.selected, session.divider = '', None
        elif operation in ('select', 'move'):
            pair = layout.pair_for_window_edge(tab.windows, window.id, edge)
            if pair is None:
                session.selected, session.divider = '', None
                status = 'Outside edge: choose an internal edge'
            elif operation == 'select':
                session.selected, session.divider = edge, pair
                session.horizontal = pair.horizontal
            elif (token := payload_get('divider')) and (
                token != str(id(pair)) or session.divider is not pair or layout is not session.layout or session.horizontal != pair.horizontal
            ):
                session.selected, session.divider = '', None
                status = 'Layout changed; choose an edge again'
            else:
                session.selected, session.divider = edge, pair
                session.horizontal = pair.horizontal
                if layout.modify_size_of_window_edge(tab.windows, window.id, edge, payload_get('increment'), fraction):
                    tab.relayout()
                else:
                    status = 'At size limit; move the other way'
        edges = [e for e in ('left', 'bottom', 'top', 'right') if layout.pair_for_window_edge(tab.windows, window.id, e) is not None]
        if operation == 'start':
            session.selected, session.divider = '', None
            if len(edges) == 1:
                session.selected = edges[0]
                session.divider = layout.pair_for_window_edge(tab.windows, window.id, edges[0])
                assert session.divider is not None
                session.horizontal = session.divider.horizontal
        return json.dumps(
            {'edges': edges, 'selected': session.selected, 'divider': str(id(session.divider)) if session.divider is not None else '', 'status': status}
        )


resize_window_edge = ResizeWindowEdge()
