#!/usr/bin/env python
# License: GPL v3 Copyright: 2018, Kovid Goyal <kovid at kovidgoyal.net>

import sys
from typing import Any, Callable, Dict, List, Tuple

from kitty.cli import parse_args
from kitty.cli_stub import PanelCLIOptions
from kitty.constants import appname, is_macos, is_wayland
from kitty.fast_data_types import (
    GLFW_EDGE_BOTTOM,
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
)
from kitty.os_window_size import WindowSizeData, edge_spacing
from kitty.types import LayerShellConfig
from kitty.typing import EdgeLiteral

OPTIONS = r'''
--lines
type=int
default=1
The number of lines shown in the panel. Ignored for background and vertical panels.


--columns
type=int
default=1
The number of columns shown in the panel. Ignored for background and horizontal panels.


--margin-top
type=int
default=0
Request a given top margin to the compositor.
Only works on a Wayland compositor that supports the wlr layer shell protocol.


--margin-left
type=int
default=0
Request a given left margin to the compositor.
Only works on a Wayland compositor that supports the wlr layer shell protocol.


--margin-bottom
type=int
default=0
Request a given bottom margin to the compositor.
Only works on a Wayland compositor that supports the wlr layer shell protocol.


--margin-right
type=int
default=0
Request a given right margin to the compositor.
Only works on a Wayland compositor that supports the wlr layer shell protocol.


--edge
choices=top,bottom,left,right,background,none
default=top
Which edge of the screen to place the panel on. Note that some window managers
(such as i3) do not support placing docked windows on the left and right edges.
The value :code:`background` means make the panel the "desktop wallpaper". This
is only supported on Wayland, not X11 and note that when using sway if you set
a background in your sway config it will cover the background drawn using this
kitten.
The value :code:`none` anchors the panel to the top left corner by default
and the panel should be placed using margins parameters.


--layer
choices=background,bottom,top,overlay
default=bottom
On a Wayland compositor that supports the wlr layer shell protocol, specifies the layer
on which the panel should be drawn. This parameter is ignored and set to
:code:`background` if :option:`--edge` is set to :code:`background`.


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


--class
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


--exclusive-zone
type=int
default=-1
On a Wayland compositor that supports the wlr layer shell protocol, request a given exclusive zone for the panel.
Please refer to the wlr layer shell documentation for more details on the meaning of exclusive and its value.
If :option:`--edge` is set to anything else than :code:`none`, this flag will not have any effect unless
the flag :option:`--override-exclusive-zone` is also set.
If :option:`--edge` is set to :code:`background`, this option has no effect.


--override-exclusive-zone
type=bool-set
On a Wayland compositor that supports the wlr layer shell protocol, override the default exclusive zone.
This has effect only if :option:`--edge` is set to :code:`top`, :code:`left`, :code:`bottom` or :code:`right`.


--debug-rendering
type=bool-set
For internal debugging use.
'''.format(appname=appname).format


args = PanelCLIOptions()
help_text = 'Use a command line program to draw a GPU accelerated panel on your X11 desktop'
usage = 'program-to-run'


def parse_panel_args(args: List[str]) -> Tuple[PanelCLIOptions, List[str]]:
    return parse_args(args, OPTIONS, usage, help_text, 'kitty +kitten panel', result_class=PanelCLIOptions)


Strut = Tuple[int, int, int, int, int, int, int, int, int, int, int, int]


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
    func = globals()[f'create_{args.edge}_strut']
    strut = func(win_id, window_width, window_height)
    make_x11_window_a_dock_window(win_id, strut)


def initial_window_size_func(opts: WindowSizeData, cached_values: Dict[str, Any]) -> Callable[[int, int, float, float, float, float], Tuple[int, int]]:

    def es(which: EdgeLiteral) -> float:
        return edge_spacing(which, opts)

    def initial_window_size(cell_width: int, cell_height: int, dpi_x: float, dpi_y: float, xscale: float, yscale: float) -> Tuple[int, int]:
        if not is_macos and not is_wayland():
            # Not sure what the deal with scaling on X11 is
            xscale = yscale = 1
        global window_width, window_height
        monitor_width, monitor_height = glfw_primary_monitor_size()

        if args.edge in {'top', 'bottom'}:
            spacing = es('top') + es('bottom')
            window_height = int(cell_height * args.lines / yscale + (dpi_y / 72) * spacing + 1)
            window_width = monitor_width
        elif args.edge == 'background':
            window_width, window_height = monitor_width, monitor_height
        else:
            spacing = es('left') + es('right')
            window_width = int(cell_width * args.lines / xscale + (dpi_x / 72) * spacing + 1)
            window_height = monitor_height
        return window_width, window_height

    return initial_window_size


def layer_shell_config(opts: PanelCLIOptions) -> LayerShellConfig:
    ltype = {'background': GLFW_LAYER_SHELL_BACKGROUND,
             'bottom': GLFW_LAYER_SHELL_PANEL,
             'top': GLFW_LAYER_SHELL_TOP,
             'overlay': GLFW_LAYER_SHELL_OVERLAY}.get(opts.layer, GLFW_LAYER_SHELL_PANEL)
    ltype = GLFW_LAYER_SHELL_BACKGROUND if opts.edge == 'background' else ltype
    edge = {
        'top': GLFW_EDGE_TOP, 'bottom': GLFW_EDGE_BOTTOM, 'left': GLFW_EDGE_LEFT, 'right': GLFW_EDGE_RIGHT, 'none': GLFW_EDGE_NONE
    }.get(opts.edge, GLFW_EDGE_TOP)
    focus_policy = {
        'not-allowed': GLFW_FOCUS_NOT_ALLOWED, 'exclusive': GLFW_FOCUS_EXCLUSIVE, 'on-demand': GLFW_FOCUS_ON_DEMAND
    }.get(opts.focus_policy, GLFW_FOCUS_NOT_ALLOWED)
    return LayerShellConfig(type=ltype,
                            edge=edge,
                            x_size_in_cells=max(1, opts.columns),
                            y_size_in_cells=max(1, opts.lines),
                            requested_top_margin=max(0, opts.margin_top),
                            requested_left_margin=max(0, opts.margin_left),
                            requested_bottom_margin=max(0, opts.margin_bottom),
                            requested_right_margin=max(0, opts.margin_right),
                            focus_policy=focus_policy,
                            requested_exclusive_zone=opts.exclusive_zone,
                            override_exclusive_zone=opts.override_exclusive_zone,
                            output_name=opts.output_name or '')


def main(sys_args: List[str]) -> None:
    global args
    if is_macos:
        raise SystemExit('Currently the panel kitten is not supported on macOS')
    args, items = parse_panel_args(sys_args[1:])
    if not items:
        raise SystemExit('You must specify the program to run')
    sys.argv = ['kitty']
    if args.debug_rendering:
        sys.argv.append('--debug-rendering')
    for config in args.config:
        sys.argv.extend(('--config', config))
    sys.argv.extend(('--class', args.cls))
    if args.name:
        sys.argv.extend(('--name', args.name))
    for override in args.override:
        sys.argv.extend(('--override', override))
    sys.argv.append('--override=linux_display_server=auto')
    sys.argv.extend(items)
    from kitty.main import main as real_main
    from kitty.main import run_app
    run_app.cached_values_name = 'panel'
    run_app.layer_shell_config = layer_shell_config(args)
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
