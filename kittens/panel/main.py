#!/usr/bin/env python
# License: GPL v3 Copyright: 2018, Kovid Goyal <kovid at kovidgoyal.net>

import sys
from collections.abc import Callable
from contextlib import suppress
from functools import partial
from typing import Any, Mapping, Sequence

from kitty.cli import listen_on_defn, parse_args
from kitty.cli_stub import PanelCLIOptions
from kitty.constants import appname, is_macos, is_wayland, kitten_exe
from kitty.fast_data_types import (
    GLFW_EDGE_BOTTOM,
    GLFW_EDGE_CENTER,
    GLFW_EDGE_LEFT,
    GLFW_EDGE_NONE,
    GLFW_EDGE_RIGHT,
    GLFW_EDGE_TOP,
    GLFW_FOCUS_EXCLUSIVE,
    GLFW_FOCUS_NOT_ALLOWED,
    GLFW_FOCUS_ON_DEMAND,
    GLFW_LAYER_SHELL_BACKGROUND,
    GLFW_LAYER_SHELL_OVERLAY,
    GLFW_LAYER_SHELL_PANEL,
    GLFW_LAYER_SHELL_TOP,
    glfw_primary_monitor_size,
    make_x11_window_a_dock_window,
    toggle_os_window_visibility,
)
from kitty.os_window_size import WindowSizeData, edge_spacing
from kitty.types import LayerShellConfig
from kitty.typing import BossType, EdgeLiteral
from kitty.utils import log_error

OPTIONS = r'''
--lines
default=1
The number of lines shown in the panel. Ignored for background, centered, and vertical panels.
If it has the suffix :code:`px` then it sets the height of the panel in pixels instead of lines.


--columns
default=1
The number of columns shown in the panel. Ignored for background, centered, and horizontal panels.
If it has the suffix :code:`px` then it sets the width of the panel in pixels instead of columns.


--margin-top
type=int
default=0
Set the top margin for the panel, in pixels. Has no effect for bottom edge panels.
Only works on macOS and Wayland compositors that supports the wlr layer shell protocol.


--margin-left
type=int
default=0
Set the left margin for the panel, in pixels. Has no effect for right edge panels.
Only works on macOS and Wayland compositors that supports the wlr layer shell protocol.


--margin-bottom
type=int
default=0
Set the bottom margin for the panel, in pixels. Has no effect for top edge panels.
Only works on macOS and Wayland compositors that supports the wlr layer shell protocol.


--margin-right
type=int
default=0
Set the right margin for the panel, in pixels. Has no effect for left edge panels.
Only works on macOS and Wayland compositors that supports the wlr layer shell protocol.


--edge
choices=top,bottom,left,right,background,center,none
default=top
Which edge of the screen to place the panel on. Note that some window managers
(such as i3) do not support placing docked windows on the left and right edges.
The value :code:`background` means make the panel the "desktop wallpaper". This
is not supported on X11 and note that when using sway if you set
a background in your sway config it will cover the background drawn using this
kitten.
Additionally, there are two more values: :code:`center` and :code:`none`.
The value :code:`center` anchors the panel to all sides and covers the entire
display (on macOS the part of the display not covered by titlebar and dock).
The panel can be shrunk and placed using the margin parameters.
The value :code:`none` anchors the panel to the top left corner and should be
placed and using the margin parameters. It's size is set bye :option:`--lines`
and :option:`--columns`.


--layer
choices=background,bottom,top,overlay
default=bottom
On a Wayland compositor that supports the wlr layer shell protocol, specifies the layer
on which the panel should be drawn. This parameter is ignored and set to
:code:`background` if :option:`--edge` is set to :code:`background`. On macOS, maps
these to appropriate NSWindow *levels*.


--config -c
type=list
Path to config file to use for kitty when drawing the panel.


--override -o
type=list
Override individual kitty configuration options, can be specified multiple times.
Syntax: :italic:`name=value`. For example: :option:`kitty +kitten panel -o` font_size=20


--output-name
On Wayland, the panel can only be displayed on a single monitor (output) at a time. This allows
you to specify which output is used, by name. If not specified the compositor will choose an
output automatically, typically the last output the user interacted with or the primary monitor.


--class --app-id
dest=cls
default={appname}-panel
condition=not is_macos
Set the class part of the :italic:`WM_CLASS` window property. On Wayland, it sets the app id.


--name
condition=not is_macos
Set the name part of the :italic:`WM_CLASS` property (defaults to using the value from :option:`{appname} --class`)


--focus-policy
choices=not-allowed,exclusive,on-demand
default=not-allowed
On a Wayland compositor that supports the wlr layer shell protocol, specify the focus policy for keyboard
interactivity with the panel. Please refer to the wlr layer shell protocol documentation for more details.
On macOS, :code:`exclusive` and :code:`on-demand` are currently the same. Ignored on X11.


--exclusive-zone
type=int
default=-1
On a Wayland compositor that supports the wlr layer shell protocol, request a given exclusive zone for the panel.
Please refer to the wlr layer shell documentation for more details on the meaning of exclusive and its value.
If :option:`--edge` is set to anything other than :code:`center` or :code:`none`, this flag will not have any
effect unless the flag :option:`--override-exclusive-zone` is also set.
If :option:`--edge` is set to :code:`background`, this option has no effect.
Ignored on X11 and macOS.


--override-exclusive-zone
type=bool-set
On a Wayland compositor that supports the wlr layer shell protocol, override the default exclusive zone.
This has effect only if :option:`--edge` is set to :code:`top`, :code:`left`, :code:`bottom` or :code:`right`.
Ignored on X11 and macOS.


--single-instance -1
type=bool-set
If specified only a single instance of the panel will run. New
invocations will instead create a new top-level window in the existing
panel instance.


--instance-group
Used in combination with the :option:`--single-instance` option. All
panel invocations with the same :option:`--instance-group` will result
in new panels being created in the first panel instance within that group.


{listen_on_defn}


--toggle-visibility
type=bool-set
When set and using :option:`--single-instance` will toggle the visibility of the
existing panel rather than creating a new one.


--start-as-hidden
type=bool-set
Start in hidden mode, useful with :option:`--toggle-visibility`.


--detach
type=bool-set
Detach from the controlling terminal, if any, running in an independent child process,
the parent process exits immediately.


--detached-log
Path to a log file to store STDOUT/STDERR when using :option:`--detach`


--debug-rendering
type=bool-set
For internal debugging use.
'''.format(appname=appname, listen_on_defn=listen_on_defn).format


args = PanelCLIOptions()
help_text = 'Use a command line program to draw a GPU accelerated panel on your desktop'
usage = '[cmdline-to-run ...]'


def parse_panel_args(args: list[str]) -> tuple[PanelCLIOptions, list[str]]:
    return parse_args(args, OPTIONS, usage, help_text, 'kitty +kitten panel', result_class=PanelCLIOptions)


Strut = tuple[int, int, int, int, int, int, int, int, int, int, int, int]


def create_strut(
    win_id: int,
    left: int = 0, right: int = 0, top: int = 0, bottom: int = 0, left_start_y: int = 0, left_end_y: int = 0,
    right_start_y: int = 0, right_end_y: int = 0, top_start_x: int = 0, top_end_x: int = 0,
    bottom_start_x: int = 0, bottom_end_x: int = 0
) -> Strut:
    return left, right, top, bottom, left_start_y, left_end_y, right_start_y, right_end_y, top_start_x, top_end_x, bottom_start_x, bottom_end_x


def create_top_strut(win_id: int, width: int, height: int) -> Strut:
    return create_strut(win_id, top=height, top_end_x=width)


def create_bottom_strut(win_id: int, width: int, height: int) -> Strut:
    return create_strut(win_id, bottom=height, bottom_end_x=width)


def create_left_strut(win_id: int, width: int, height: int) -> Strut:
    return create_strut(win_id, left=width, left_end_y=height)


def create_right_strut(win_id: int, width: int, height: int) -> Strut:
    return create_strut(win_id, right=width, right_end_y=height)


window_width = window_height = 0


def setup_x11_window(win_id: int) -> None:
    if is_wayland():
        return
    try:
        func = globals()[f'create_{args.edge}_strut']
    except KeyError:
        raise SystemExit(f'The value {args.edge} is not support for --edge on X11')
    strut = func(win_id, window_width, window_height)
    make_x11_window_a_dock_window(win_id, strut)


def initial_window_size_func(opts: WindowSizeData, cached_values: dict[str, Any]) -> Callable[[int, int, float, float, float, float], tuple[int, int]]:

    def es(which: EdgeLiteral) -> float:
        return edge_spacing(which, opts)

    def initial_window_size(cell_width: int, cell_height: int, dpi_x: float, dpi_y: float, xscale: float, yscale: float) -> tuple[int, int]:
        if not is_macos and not is_wayland():
            # Not sure what the deal with scaling on X11 is
            xscale = yscale = 1
        global window_width, window_height
        monitor_width, monitor_height = glfw_primary_monitor_size()
        x = dual_distance(args.columns, min_cell_value_if_no_pixels=1)
        rwidth = x[1] if x[1] else (x[0] * cell_width / xscale)
        x = dual_distance(args.lines, min_cell_value_if_no_pixels=1)
        rheight = x[1] if x[1] else (x[0] * cell_width / yscale)

        if args.edge in {'left', 'right'}:
            spacing = es('left') + es('right')
            window_width = int(rwidth + (dpi_x / 72) * spacing + 1)
            window_height = monitor_height
        elif args.edge in {'top', 'bottom'}:
            spacing = es('top') + es('bottom')
            window_height = int(rheight + (dpi_y / 72) * spacing + 1)
            window_width = monitor_width
        elif args.edge in {'background', 'center'}:
            window_width, window_height = monitor_width, monitor_height
        else:
            x_spacing = es('left') + es('right')
            window_width = int(rwidth + (dpi_x / 72) * x_spacing + 1)
            y_spacing = es('top') + es('bottom')
            window_height = int(rheight + (dpi_y / 72) * y_spacing + 1)
        return window_width, window_height

    return initial_window_size


def dual_distance(spec: str, min_cell_value_if_no_pixels: int = 0) -> tuple[int, int]:
    with suppress(Exception):
        return int(spec), 0
    if spec.endswith('px'):
        return min_cell_value_if_no_pixels, int(spec[:-2])
    if spec.endswith('c'):
        return int(spec[:-1]), 0
    return min_cell_value_if_no_pixels, 0


def layer_shell_config(opts: PanelCLIOptions) -> LayerShellConfig:
    ltype = {
        'background': GLFW_LAYER_SHELL_BACKGROUND,
        'bottom': GLFW_LAYER_SHELL_PANEL,
        'top': GLFW_LAYER_SHELL_TOP,
        'overlay': GLFW_LAYER_SHELL_OVERLAY
    }.get(opts.layer, GLFW_LAYER_SHELL_PANEL)
    ltype = GLFW_LAYER_SHELL_BACKGROUND if opts.edge == 'background' else ltype
    edge = {
        'top': GLFW_EDGE_TOP, 'bottom': GLFW_EDGE_BOTTOM, 'left': GLFW_EDGE_LEFT, 'right': GLFW_EDGE_RIGHT, 'center': GLFW_EDGE_CENTER, 'none': GLFW_EDGE_NONE
    }.get(opts.edge, GLFW_EDGE_TOP)
    focus_policy = {
        'not-allowed': GLFW_FOCUS_NOT_ALLOWED, 'exclusive': GLFW_FOCUS_EXCLUSIVE, 'on-demand': GLFW_FOCUS_ON_DEMAND
    }.get(opts.focus_policy, GLFW_FOCUS_NOT_ALLOWED)
    x, y = dual_distance(opts.columns, min_cell_value_if_no_pixels=1), dual_distance(opts.lines, min_cell_value_if_no_pixels=1)
    return LayerShellConfig(type=ltype,
                            edge=edge,
                            x_size_in_cells=x[0], x_size_in_pixels=x[1],
                            y_size_in_cells=y[0], y_size_in_pixels=y[1],
                            requested_top_margin=max(0, opts.margin_top),
                            requested_left_margin=max(0, opts.margin_left),
                            requested_bottom_margin=max(0, opts.margin_bottom),
                            requested_right_margin=max(0, opts.margin_right),
                            focus_policy=focus_policy,
                            requested_exclusive_zone=opts.exclusive_zone,
                            override_exclusive_zone=opts.override_exclusive_zone,
                            output_name=opts.output_name or '')


def handle_single_instance_command(boss: BossType, sys_args: Sequence[str], environ: Mapping[str, str], notify_on_os_window_death: str | None = '') -> None:
    from kitty.tabs import SpecialWindow
    try:
        args, items = parse_panel_args(list(sys_args[1:]))
    except BaseException as e:
        log_error(f'Invalid arguments received over single instance socket: {sys_args} with error: {e}')
        return
    if args.toggle_visibility and boss.os_window_map:
        for os_window_id in boss.os_window_map:
            toggle_os_window_visibility(os_window_id)
        return
    items = items or [kitten_exe(), 'run-shell']
    lsc = layer_shell_config(args)
    os_window_id = boss.add_os_panel(lsc, args.cls, args.name)
    if notify_on_os_window_death:
        boss.os_window_death_actions[os_window_id] = partial(boss.notify_on_os_window_death, notify_on_os_window_death)
    tm = boss.os_window_map[os_window_id]
    tm.new_tab(SpecialWindow(cmd=items, env=dict(environ)))


def main(sys_args: list[str]) -> None:
    global args
    args, items = parse_panel_args(sys_args[1:])
    sys.argv = ['kitty']
    if args.debug_rendering:
        sys.argv.append('--debug-rendering')
    for config in args.config:
        sys.argv.extend(('--config', config))
    if not is_macos:
        sys.argv.extend(('--class', args.cls))
    if args.name:
        sys.argv.extend(('--name', args.name))
    if args.start_as_hidden:
        sys.argv.append('--start-as=hidden')
    for override in args.override:
        sys.argv.extend(('--override', override))
    sys.argv.append('--override=linux_display_server=auto')
    sys.argv.append('--override=macos_quit_when_last_window_closed=yes')
    if args.single_instance:
        sys.argv.append('--single-instance')
    if args.instance_group:
        sys.argv.append(f'--instance-group={args.instance_group}')
    if args.listen_on:
        sys.argv.append(f'--listen-on={args.listen_on}')

    sys.argv.extend(items)
    from kitty.main import main as real_main
    from kitty.main import run_app
    run_app.cached_values_name = 'panel'
    run_app.layer_shell_config = layer_shell_config(args)
    if not is_macos:
        run_app.first_window_callback = setup_x11_window
        run_app.initial_window_size_func = initial_window_size_func
    real_main()


if __name__ == '__main__':
    main(sys.argv)
elif __name__ == '__doc__':
    cd: dict = sys.cli_docs  # type: ignore
    cd['usage'] = usage
    cd['options'] = OPTIONS
    cd['help_text'] = help_text
    cd['short_desc'] = help_text
