#!/usr/bin/env python
# License: GPLv3 Copyright: 2020, Kovid Goyal <kovid at kovidgoyal.net>

from typing import TYPE_CHECKING

from .base import (
    MATCH_WINDOW_OPTION,
    ArgsType,
    Boss,
    PayloadGetType,
    PayloadType,
    RCOptions,
    RemoteCommand,
    RemoteControlErrorWithoutTraceback,
    ResponseType,
    Window,
)

if TYPE_CHECKING:
    from kitty.cli_stub import ResizeOSWindowRCOptions as CLIOptions


class ResizeOSWindow(RemoteCommand):
    protocol_spec = __doc__ = '''
    match/str: Which window to resize
    self/bool: Boolean indicating whether to close the window the command is run in
    incremental/bool: Boolean indicating whether to adjust the size incrementally
    action/choices.resize.toggle-fullscreen.toggle-maximized.toggle-visibility.hide.show.os-panel: The action to perform
    unit/choices.cells.pixels: One of :code:`cells` or :code:`pixels`
    width/int: Integer indicating desired window width
    height/int: Integer indicating desired window height
    os_panel/list.str: Settings for modifying the OS Panel
    '''

    short_desc = 'Resize/show/hide/etc. the specified OS Windows'
    desc = (
        'Resize (or other operations) on the specified OS Windows.'
        ' Note that some window managers/environments do not allow applications to resize'
        ' their windows, for example, tiling window managers.\n\nTo modify OS Panels created with the'
        ' panel kitten, use :option:`--action`=:code:`os-panel`. Specify the modifications in the same syntax as used'
        ' by the panel kitten, without the leading dashes. Use the :option:`--incremental` option to only change'
        ' the specified panel settings. For example, move the panel to bottom edge and make it two lines tall:'
        ' :code:`--action=os-panel --incremental lines=2 edge=bottom`'
    )
    args = RemoteCommand.Args(spec='[OS Panel settings ...]', json_field='os_panel', special_parse='escape_list_of_strings(args), nil')
    options_spec = MATCH_WINDOW_OPTION + '''\n
--action
default=resize
choices=resize,toggle-fullscreen,toggle-maximized,toggle-visibility,hide,show,os-panel
The action to perform.


--unit
default=cells
choices=cells,pixels
The unit in which to interpret specified sizes.


--width
default=0
type=int
Change the width of the window. Zero leaves the width unchanged.


--height
default=0
type=int
Change the height of the window. Zero leaves the height unchanged.


--incremental
type=bool-set
Treat the specified sizes as increments on the existing window size
instead of absolute sizes. When using :option:`--action`=:code:`os-panel`,
only the specified settings are changed, otherwise non-specified settings
are reset to default.


--self
type=bool-set
Resize the window this command is run in, rather than the active window.


--no-response
type=bool-set
default=false
Don't wait for a response indicating the success of the action. Note that
using this option means that you will not be notified of failures.
'''

    def message_to_kitty(self, global_opts: RCOptions, opts: 'CLIOptions', args: ArgsType) -> PayloadType:
        return {
            'match': opts.match, 'action': opts.action, 'unit': opts.unit,
            'width': opts.width, 'height': opts.height, 'self': opts.self,
            'incremental': opts.incremental, 'os_panel': args,
        }

    def response_from_kitty(self, boss: Boss, window: Window | None, payload_get: PayloadGetType) -> ResponseType:
        from kitty.fast_data_types import (
            get_os_window_size,
            layer_shell_config_for_os_window,
            set_layer_shell_config,
            toggle_fullscreen,
            toggle_os_window_visibility,
        )
        windows = self.windows_for_match_payload(boss, window, payload_get)
        if windows:
            ac = payload_get('action')
            for os_window_id in {w.os_window_id for w in windows if w}:
                metrics = get_os_window_size(os_window_id)
                if metrics is None:
                    raise RemoteControlErrorWithoutTraceback(f'The OS Window {os_window_id} does not exist')
                panels = payload_get('os_panel')
                is_panel = metrics['is_layer_shell']
                if ac == 'os-panel':
                    if not is_panel:
                        raise RemoteControlErrorWithoutTraceback(
                            f'The OS Window {os_window_id} is not a panel you should not use the --action=resize option to resize it')
                    if not panels:
                        raise RemoteControlErrorWithoutTraceback('Must specify at least one panel setting')
                    from kitty.launch import layer_shell_config_from_panel_opts
                    try:
                        lsc = layer_shell_config_from_panel_opts(panels)
                    except Exception as e:
                        raise RemoteControlErrorWithoutTraceback(
                            f'Invalid panel options specified: {e}')
                    if payload_get('incremental'):
                        defaults = layer_shell_config_from_panel_opts(())
                        changed_fields = {f for f in lsc._fields if getattr(lsc, f) != getattr(defaults, f)}
                        existing = layer_shell_config_for_os_window(os_window_id)
                        if existing is None:
                            raise RemoteControlErrorWithoutTraceback(
                                f'The OS Window {os_window_id} has no panel configuration')
                        replacements = {}
                        for x in lsc._fields:
                            if x not in changed_fields:
                                replacements[x] = existing[x]
                        lsc = lsc._replace(**replacements)
                    if not set_layer_shell_config(os_window_id, lsc):
                        raise RemoteControlErrorWithoutTraceback(f'Failed to change panel configuration for OS Window {os_window_id}')
                elif ac == 'toggle-visibility':
                    toggle_os_window_visibility(os_window_id)
                elif ac == 'hide':
                    toggle_os_window_visibility(os_window_id, False)
                elif ac == 'show':
                    toggle_os_window_visibility(os_window_id, True)
                elif ac == 'toggle-fullscreen':
                    if not toggle_fullscreen(os_window_id):
                        raise RemoteControlErrorWithoutTraceback(
                            f'The OS Window {os_window_id} is a desktop panel that cannot be made fullscreen')
                elif is_panel:
                    raise RemoteControlErrorWithoutTraceback(
                        f'The OS Window {os_window_id} is a desktop panel, no actions other than resizing are supported for it')
                elif ac == 'resize':
                    boss.resize_os_window(
                        os_window_id, width=payload_get('width'), height=payload_get('height'),
                        unit=payload_get('unit'), incremental=payload_get('incremental'), metrics=metrics,
                    )
                elif ac == 'toggle-maximized':
                    boss.toggle_maximized(os_window_id)
        return None


resize_os_window = ResizeOSWindow()
