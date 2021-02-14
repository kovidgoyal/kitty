#!/usr/bin/env python3
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2018, Kovid Goyal <kovid at kovidgoyal.net>

import os
import shutil
import subprocess
import sys
from typing import Callable, Dict, List, Tuple

from kitty.cli import parse_args
from kitty.cli_stub import PanelCLIOptions
from kitty.constants import is_macos, appname
from kitty.os_window_size import WindowSizeData

OPTIONS = r'''
--lines
type=int
default=1
The number of lines shown in the panel (the height of the panel). Applies to horizontal panels.


--columns
type=int
default=20
The number of columns shown in the panel (the width of the panel). Applies to vertical panels.


--edge
choices=top,bottom,left,right
default=top
Which edge of the screen to place the panel on. Note that some window managers
(such as i3) do not support placing docked windows on the left and right edges.


--config -c
type=list
Path to config file to use for kitty when drawing the panel.


--override -o
type=list
Override individual kitty configuration options, can be specified multiple times.
Syntax: :italic:`name=value`. For example: :option:`kitty +kitten panel -o` font_size=20


--class
dest=cls
default={appname}-panel
condition=not is_macos
Set the class part of the :italic:`WM_CLASS` window property. On Wayland, it sets the app id.


--name
condition=not is_macos
Set the name part of the :italic:`WM_CLASS` property (defaults to using the value from :option:`{appname} --class`)
'''.format(appname=appname).format


args = PanelCLIOptions()
help_text = 'Use a command line program to draw a GPU accelerated panel on your X11 desktop'
usage = 'program-to-run'


def parse_panel_args(args: List[str]) -> Tuple[PanelCLIOptions, List[str]]:
    return parse_args(args, OPTIONS, usage, help_text, 'kitty +kitten panel', result_class=PanelCLIOptions)


def call_xprop(*cmd: str, silent: bool = False) -> None:
    cmd_ = ['xprop'] + list(cmd)
    try:
        cp = subprocess.run(cmd_, stdout=subprocess.DEVNULL if silent else None)
    except FileNotFoundError:
        raise SystemExit('You must have the xprop program installed')
    if cp.returncode != 0:
        raise SystemExit(cp.returncode)


def create_strut(
    win_id: int,
    left: int = 0, right: int = 0, top: int = 0, bottom: int = 0, left_start_y: int = 0, left_end_y: int = 0,
    right_start_y: int = 0, right_end_y: int = 0, top_start_x: int = 0, top_end_x: int = 0,
    bottom_start_x: int = 0, bottom_end_x: int = 0
) -> None:
    call_xprop(
            '-id',
            str(int(win_id)), '-format', '_NET_WM_STRUT_PARTIAL', '32cccccccccccc',
            '-set', '_NET_WM_STRUT_PARTIAL',
            '{left},{right},{top},{bottom},'
            '{left_start_y},{left_end_y},{right_start_y},{right_end_y},'
            '{top_start_x},{top_end_x},{bottom_start_x},{bottom_end_x}'.format(**locals())
    )


def create_top_strut(win_id: int, width: int, height: int) -> None:
    create_strut(win_id, top=height, top_end_x=width)


def create_bottom_strut(win_id: int, width: int, height: int) -> None:
    create_strut(win_id, bottom=height, bottom_end_x=width)


def create_left_strut(win_id: int, width: int, height: int) -> None:
    create_strut(win_id, left=width, left_end_y=height)


def create_right_strut(win_id: int, width: int, height: int) -> None:
    create_strut(win_id, right=width, right_end_y=height)


window_width = window_height = 0


def setup_x11_window(win_id: int) -> None:
    call_xprop(
            '-id', str(win_id), '-format', '_NET_WM_WINDOW_TYPE', '32a',
            '-set', '_NET_WM_WINDOW_TYPE', '_NET_WM_WINDOW_TYPE_DOCK'
    )
    func = globals()['create_{}_strut'.format(args.edge)]
    func(win_id, window_width, window_height)


def initial_window_size_func(opts: WindowSizeData, cached_values: Dict) -> Callable[[int, int, float, float, float, float], Tuple[int, int]]:
    from kitty.fast_data_types import glfw_primary_monitor_size

    def initial_window_size(cell_width: int, cell_height: int, dpi_x: float, dpi_y: float, xscale: float, yscale: float) -> Tuple[int, int]:
        global window_width, window_height
        monitor_width, monitor_height = glfw_primary_monitor_size()
        if args.edge in {'top', 'bottom'}:
            window_height = cell_height * args.lines + 1
            window_width = monitor_width
        else:
            window_width = cell_width * args.columns + 1
            window_height = monitor_height
        return window_width, window_height

    return initial_window_size


def main(sys_args: List[str]) -> None:
    global args
    if is_macos or not os.environ.get('DISPLAY'):
        raise SystemExit('Currently the panel kitten is supported only on X11 desktops')
    if not shutil.which('xprop'):
        raise SystemExit('The xprop program is required for the panel kitten')
    args, items = parse_panel_args(sys_args[1:])
    if not items:
        raise SystemExit('You must specify the program to run')
    sys.argv = ['kitty']
    for config in args.config:
        sys.argv.extend(('--config', config))
    sys.argv.extend(('--class', args.cls))
    if args.name:
        sys.argv.extend(('--name', args.name))
    for override in args.override:
        sys.argv.extend(('--override', override))
    sys.argv.extend(items)
    from kitty.main import run_app, main as real_main
    run_app.cached_values_name = 'panel'
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
