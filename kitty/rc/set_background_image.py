#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPLv3 Copyright: 2020, Kovid Goyal <kovid at kovidgoyal.net>

import imghdr
import tempfile
from base64 import standard_b64decode, standard_b64encode
from typing import IO, TYPE_CHECKING, Dict, Generator, Optional
from uuid import uuid4

from .base import (
    MATCH_WINDOW_OPTION, ArgsType, Boss, PayloadGetType, PayloadType,
    RCOptions, RemoteCommand, ResponseType, Window
)

if TYPE_CHECKING:
    from kitty.cli_stub import SetBackgroundImageRCOptions as CLIOptions


class SetBackgroundImage(RemoteCommand):

    '''
    data+: Chunk of at most 512 bytes of PNG data, base64 encoded. Must send an empty chunk to indicate end of image. \
    Or the special value - to indicate image must be removed.
    img_id+: Unique uuid (as string) used for chunking
    match: Window to change opacity in
    layout: The image layout
    all: Boolean indicating operate on all windows
    configured: Boolean indicating if the configured value should be changed
    '''

    short_desc = 'Set the background_image'
    desc = (
        'Set the background image for the specified OS windows. You must specify the path to a PNG image that'
        ' will be used as the background. If you specify the special value "none" then any existing image will'
        ' be removed.'
    )
    options_spec = '''\
--all -a
type=bool-set
By default, background image is only changed for the currently active OS window. This option will
cause the image to be changed in all windows.


--configured -c
type=bool-set
Change the configured background image which is used for new OS windows.


--layout
type=choices
choices=tiled,scaled,mirror-tiled,configured
How the image should be displayed. The value of configured will use the configured value.


--no-response
type=bool-set
default=false
Don't wait for a response from kitty. This means that even if setting the background image
failed, the command will exit with a success code.
''' + '\n\n' + MATCH_WINDOW_OPTION
    argspec = 'PATH_TO_PNG_IMAGE'
    args_count = 1
    args_completion = {'files': ('PNG Images', ('*.png',))}
    current_img_id: Optional[str] = None
    current_file_obj: Optional[IO[bytes]] = None

    def message_to_kitty(self, global_opts: RCOptions, opts: 'CLIOptions', args: ArgsType) -> PayloadType:
        if len(args) != 1:
            self.fatal('Must specify path to exactly one PNG image')
        if opts.no_response:
            global_opts.no_command_response = True
        path = args[0]
        ret = {
            'match': opts.match,
            'configured': opts.configured,
            'layout': opts.layout,
            'all': opts.all,
            'img_id': str(uuid4())
        }
        if path.lower() == 'none':
            ret['data'] = '-'
            return ret
        if imghdr.what(path) != 'png':
            self.fatal(f'{path} is not a PNG image')

        def file_pipe(path: str) -> Generator[Dict, None, None]:
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

    def response_from_kitty(self, boss: Boss, window: Optional[Window], payload_get: PayloadGetType) -> ResponseType:
        data = payload_get('data')
        if data != '-':
            img_id = payload_get('img_id')
            if img_id != set_background_image.current_img_id:
                set_background_image.current_img_id = img_id
                set_background_image.current_file_obj = tempfile.NamedTemporaryFile()
            if data:
                assert set_background_image.current_file_obj is not None
                set_background_image.current_file_obj.write(standard_b64decode(data))
                return None

        windows = self.windows_for_payload(boss, window, payload_get)
        os_windows = tuple({w.os_window_id for w in windows})
        layout = payload_get('layout')
        if data == '-':
            path = None
        else:
            assert set_background_image.current_file_obj is not None
            f = set_background_image.current_file_obj
            path = f.name
            set_background_image.current_file_obj = None
            f.flush()

        try:
            boss.set_background_image(path, os_windows, payload_get('configured'), layout)
        except ValueError as err:
            err.hide_traceback = True  # type: ignore
            raise


set_background_image = SetBackgroundImage()
