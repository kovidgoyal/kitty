#!/usr/bin/env python
# License: GPL v3 Copyright: 2018, Kovid Goyal <kovid at kovidgoyal.net>

import sys

OPTIONS = r"""
--horizontal-increment
default=2
type=int
The base horizontal increment.


--vertical-increment
default=2
type=int
The base vertical increment.


--fraction
default=1/3
The fraction of the remaining resize steps to take with the chosen modifier.
Can be a decimal or a ratio such as :code:`1/3`, and must be greater than zero
and at most one. The step count is rounded up, with at least one step when
space remains. When explicitly given, overrides the saved fraction for this
invocation. Use F inside the resize page to change and save the fraction.


--strategy
type=choices
choices=window,edge
default=window
Choose the initial resize strategy. Window changes pane width or height;
edge selects an internal pane edge with H/J/K/L or arrow keys, then moves its
divider along that axis. A sole available edge is selected automatically.
In Splits, either strategy uses R to restore the proportions saved when resize
mode opened. Switching strategies preserves this snapshot. Edge resizing uses
the Splits layout; other layouts retain Window's usual reset behavior.
When omitted, uses the strategy saved from the resize page. Inside the page,
1 and 2 choose a strategy, M switches its Alt/Shift modifier, and F changes
its fraction. Each strategy's settings are saved separately.
""".format
help_text = 'Resize the current window'
usage = ''


def main(args: list[str]) -> None:
    raise SystemExit('This should be run as kitten resize-window')


if __name__ == '__main__':
    main(sys.argv)
elif __name__ == '__doc__':
    cd = sys.cli_docs  # type: ignore
    cd['usage'] = usage
    cd['options'] = OPTIONS
    cd['help_text'] = help_text
    cd['short_desc'] = 'Resize the current window interactively'
