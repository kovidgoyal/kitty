#!/usr/bin/env python
# License: GPL v3 Copyright: 2018, Kovid Goyal <kovid at kovidgoyal.net>

import os
import sys
from contextlib import suppress
from functools import partial
from typing import Iterable, Mapping, Sequence

from kitty.cli import parse_args
from kitty.cli_stub import PanelCLIOptions
from kitty.constants import is_macos, kitten_exe
from kitty.fast_data_types import (
    GLFW_EDGE_BOTTOM,
    GLFW_EDGE_CENTER,
    GLFW_EDGE_CENTER_SIZED,
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
    set_layer_shell_config,
    toggle_os_window_visibility,
)
from kitty.simple_cli_definitions import panel_options_spec
from kitty.types import LayerShellConfig
from kitty.typing_compat import BossType
from kitty.utils import log_error

args = PanelCLIOptions()
help_text = 'Use a command line program to draw a GPU accelerated panel on your desktop'
usage = '[cmdline-to-run ...]'


def panel_kitten_options_spec() -> str:
    if not hasattr(panel_kitten_options_spec, 'ans'):
           setattr(panel_kitten_options_spec, 'ans', panel_options_spec())
    ans: str = getattr(panel_kitten_options_spec, 'ans')
    return ans

def parse_panel_args(args: list[str]) -> tuple[PanelCLIOptions, list[str]]:
    return parse_args(args, panel_kitten_options_spec, usage, help_text, 'kitty +kitten panel', result_class=PanelCLIOptions)


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
        'top': GLFW_EDGE_TOP, 'bottom': GLFW_EDGE_BOTTOM, 'left': GLFW_EDGE_LEFT, 'right': GLFW_EDGE_RIGHT,
        'center': GLFW_EDGE_CENTER, 'none': GLFW_EDGE_NONE, 'center-sized': GLFW_EDGE_CENTER_SIZED,
    }.get(opts.edge, GLFW_EDGE_TOP)
    focus_policy = {
        'not-allowed': GLFW_FOCUS_NOT_ALLOWED, 'exclusive': GLFW_FOCUS_EXCLUSIVE, 'on-demand': GLFW_FOCUS_ON_DEMAND
    }.get(opts.focus_policy, GLFW_FOCUS_NOT_ALLOWED)
    if opts.hide_on_focus_loss:
        focus_policy = GLFW_FOCUS_ON_DEMAND
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
                            hide_on_focus_loss=opts.hide_on_focus_loss,
                            output_name=opts.output_name or '')


mtime_map: dict[str, float] = {}


def have_config_files_been_updated(config_files: Iterable[str]) -> bool:
    ans = False
    for cf in config_files:
        try:
            mtime = os.path.getmtime(cf)
        except OSError:
            mtime = 0
        if mtime_map.get(cf, 0) != mtime:
            ans = True
        mtime_map[cf] = mtime
    return ans


def handle_single_instance_command(boss: BossType, sys_args: Sequence[str], environ: Mapping[str, str], notify_on_os_window_death: str | None = '') -> None:
    global args
    from kitty.cli import parse_override
    from kitty.main import run_app
    from kitty.tabs import SpecialWindow
    try:
        new_args, items = parse_panel_args(list(sys_args[1:]))
    except BaseException as e:
        log_error(f'Invalid arguments received over single instance socket: {sys_args} with error: {e}')
        return
    lsc = layer_shell_config(new_args)
    layer_shell_config_changed = lsc != run_app.layer_shell_config
    config_changed = have_config_files_been_updated(new_args.config) or args.config != new_args.config or args.override != new_args.override
    args = new_args
    if config_changed:
        boss.load_config_file(*args.config, overrides=tuple(map(parse_override, new_args.override)))
    if args.toggle_visibility and boss.os_window_map:
        for os_window_id in boss.os_window_map:
            toggle_os_window_visibility(os_window_id)
            if layer_shell_config_changed:
                set_layer_shell_config(os_window_id, lsc)
        return
    items = items or [kitten_exe(), 'run-shell']
    os_window_id = boss.add_os_panel(lsc, args.cls, args.name)
    if notify_on_os_window_death:
        boss.os_window_death_actions[os_window_id] = partial(boss.notify_on_os_window_death, notify_on_os_window_death)
    tm = boss.os_window_map[os_window_id]
    tm.new_tab(SpecialWindow(cmd=items, env=dict(environ)))


def main(sys_args: list[str]) -> None:
    # run_kitten run using runpy.run_module which does not import into
    # sys.modules, which means the module will be re-imported later, causing
    # global variables to be duplicated, so do it now.
    from kittens.panel.main import actual_main
    actual_main(sys_args)
    return


def actual_main(sys_args: list[str]) -> None:
    global args
    args, items = parse_panel_args(sys_args[1:])
    have_config_files_been_updated(args.config)
    sys.argv = ['kitty']
    if args.debug_rendering:
        sys.argv.append('--debug-rendering')
    if args.debug_input:
        sys.argv.append('--debug-input')
    for config in args.config:
        sys.argv.extend(('--config', config))
    if not is_macos:
        sys.argv.extend(('--class', args.cls))
    if args.name:
        sys.argv.extend(('--name', args.name))
    if args.start_as_hidden:
        sys.argv.append('--start-as=hidden')
    if args.grab_keyboard:
        sys.argv.append('--grab-keyboard')
    for override in args.override:
        sys.argv.extend(('--override', override))
    sys.argv.append('--override=linux_display_server=auto')
    sys.argv.append('--override=macos_quit_when_last_window_closed=yes')
    sys.argv.append('--override=macos_hide_from_tasks=yes')
    sys.argv.append('--override=macos_window_resizable=no')
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
    real_main(called_from_panel=True)


if __name__ == '__main__':
    main(sys.argv)
elif __name__ == '__doc__':
    cd: dict = sys.cli_docs  # type: ignore
    cd['usage'] = usage
    cd['options'] = panel_kitten_options_spec
    cd['help_text'] = help_text
    cd['short_desc'] = help_text
