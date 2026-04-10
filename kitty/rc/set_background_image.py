#!/usr/bin/env python
# License: GPLv3 Copyright: 2020, Kovid Goyal <kovid at kovidgoyal.net>

import os
from base64 import standard_b64decode, standard_b64encode
from io import BytesIO
from typing import TYPE_CHECKING

from kitty.types import AsyncResponse
from kitty.utils import is_png

from .base import (
    MATCH_WINDOW_OPTION,
    SUPPORTED_IMAGE_FORMATS,
    ArgsType,
    Boss,
    CmdGenerator,
    ImageCompletion,
    PayloadGetType,
    PayloadType,
    RCOptions,
    RemoteCommand,
    ResponseType,
    Window,
)

if TYPE_CHECKING:
    from kitty.cli_stub import SetBackgroundImageRCOptions as CLIOptions


layout_choices = 'tiled,scaled,mirror-tiled,clamped,centered,cscaled,configured'


class SetBackgroundImage(RemoteCommand):

    protocol_spec = __doc__ = '''
    data+/str: Chunk of at most 512 bytes of PNG data, base64 encoded. Must send an empty chunk to indicate end of image. \
    Or the special value - to indicate image must be removed.
    match/str: Window to change opacity in
    layout/choices.{layout_choices.replace(",", ".")}: The image layout
    all/bool: Boolean indicating operate on all windows
    configured/bool: Boolean indicating if the configured value should be changed
    '''

    short_desc = 'Set the background image'
    desc = (
        'Set the background image for the specified OS windows. You must specify the path to an image that'
        ' will be used as the background. If you specify the special value :code:`none` then any existing image will'
        ' be removed. You can also specify :code:`+N` or :code:`-N` to cycle forward/backward through the'
        ' background image list (wraps around), or a plain integer :code:`N` to jump to an absolute index.'
        ' When setting by path, the current list index is unaffected. Supported image formats are: '
    ) + ', '.join(SUPPORTED_IMAGE_FORMATS)
    options_spec = f'''\
--all -a
type=bool-set
By default, background image is only changed for the currently active OS window. This option will
cause the image to be changed in all windows.


--configured -c
type=bool-set
Change the configured background image which is used for new OS windows.


--layout
type=choices
choices={layout_choices}
default=configured
How the image should be displayed. A value of :code:`configured` will use the configured value.


--no-response
type=bool-set
default=false
Don't wait for a response from kitty. This means that even if setting the background image
failed, the command will exit with a success code.
''' + '\n\n' + MATCH_WINDOW_OPTION
    args = RemoteCommand.Args(spec='PATH_TO_PNG_IMAGE', count=1, json_field='data', special_parse='!read_background_image(io_data, args[0])',
                              completion=ImageCompletion)
    reads_streaming_data = True

    def message_to_kitty(self, global_opts: RCOptions, opts: 'CLIOptions', args: ArgsType) -> PayloadType:
        if len(args) != 1:
            self.fatal('Must specify path to exactly one PNG image, or an index (+N, -N, N)')
        path = os.path.expanduser(args[0])
        import re
        import secrets
        ret = {
            'match': opts.match,
            'configured': opts.configured,
            'layout': opts.layout,
            'all': opts.all,
            'stream_id': secrets.token_urlsafe(),
        }
        # Handle index arguments (+N, -N, or N)
        if re.match(r'^[+-]?\d+$', path):
            ret['data'] = f'index:{path}'
            return ret
        if path.lower() == 'none':
            ret['data'] = '-'
            return ret
        if not is_png(path):
            self.fatal(f'{path} is not a PNG image')

        def file_pipe(path: str) -> CmdGenerator:
            with open(path, 'rb') as f:
                while True:
                    data = f.read(512)
                    if not data:
                        break
                    ret['data'] = standard_b64encode(data).decode('ascii')
                    yield ret
            ret['data'] = ''
            yield ret
        return file_pipe(path)

    def response_from_kitty(self, boss: Boss, window: Window | None, payload_get: PayloadGetType) -> ResponseType:
        data = payload_get('data')
        windows = self.windows_for_payload(boss, window, payload_get, window_match_name='match')
        os_windows = tuple({w.os_window_id for w in windows if w})
        layout = payload_get('layout')
        if isinstance(data, str) and data.startswith('index:'):
            from kitty.fast_data_types import change_bg_image
            index_str = data[6:]
            is_delta = index_str[0] in '+-'
            value = int(index_str)
            for osw_id in os_windows:
                change_bg_image(osw_id, value, is_delta)
            return None
        if data == '-':
            path = None
            tfile = BytesIO()
        else:
            q = self.handle_streamed_data(standard_b64decode(data) if data else b'', payload_get)
            if isinstance(q, AsyncResponse):
                return q
            path = '/image/from/remote/control'
            tfile = q

        try:
            boss.set_background_image(path, os_windows, payload_get('configured'), layout, tfile.getvalue())
        except ValueError as err:
            err.hide_traceback = True  # type: ignore
            raise
        return None


set_background_image = SetBackgroundImage()
