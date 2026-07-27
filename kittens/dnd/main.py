#!/usr/bin/env python
# License: GPL v3 Copyright: 2018, Kovid Goyal <kovid at kovidgoyal.net>

import sys

OPTIONS = r"""
--drag
type=list
When starting a drag, use the specified file as the data source for the specified
MIME type. Syntax is: mime-type:path/to/file. For example image/jpeg:mypic.jpg
Can be specified multiple times to drag multiple MIME types.


--drop
type=list
When receiving a drop, use the specified file as the data destination for the specified
MIME type. Syntax is: mime-type:path/to/file. For example image/jpeg:mypic.jpg
Can be specified multiple times to enable receiving multiple MIME types. If no path is specified,
it will prevent that MIME type being dropped, useful to disable accepting text/plain and
text/uri-list.


--drop-dest
Path to the directory in which dropped data is saved. Defaults to the current working directory.


--confirm-drop-overwrite
type=bool-set
Ask for confirmation when dropping text/uri-list data if the drop will cause any existing
files to be overwritten. Note that confirmation is asked only for actual file conflicts, non
conflicting files are automatically created.


--drop-anywhere
choices=disallowed,copy,move
default=disallowed
type=choices
Allow dropping anywhere, not just on the Copy or Move drop regions. Dropping anywhere will perform
the specified action.


--drag-thumbnail
Path to an image to use as the drag icon when starting a drag. Must be in PNG/JPEG/GIF/WEBP formats.
Other formats will require the presence of ImageMagick on the system to load the image.
If not specified, an image is derived based on the data being dragged.


--drag-thumbnail-size
default=512
type=int
The thumbnail size for the image used as the drag icon. Images larger than this size are downscaled.
Note that the terminal may reject the drag if the image is too large.


--exit-on
default=esc-key
A comma separated list of events to exit on. Possible events are :code:`drag-finish`,
:code:`drop-finish` and :code:`esc-key`. The first two events refer to a successful
completion of a drag or a drop respectively. :code:`esc-key` means press the :kbd:`Esc`
key.
""".format


help_text = """\
Perform drag and drop operations, even over SSH.

Any arguments on the command line are assumed to be files and directories to drag.
They will be dragged as the text/uri-list MIME type which can then be dropped into any
file manager or similar program to copy the files.

If the text/uri-list MIME type is dropped onto this window, the files and directories in it are
copied into the current working directory. When dragging from this window, if a move operation is
performed when dropping and the drop is to a remote machine, the files and directories to drag and deleted.

If data is present on STDIN it is set as text/plain when dragging, unless text/plain is specified via --drag.
Any text/plain data that is dropped onto this window is output to STDOUT, if STDOUT is connected to a file, otherwise it
is discarded.

Press the Esc or Ctrl+C keys to quit the kitten at any time, cancelling any in progress drag.
"""

usage = '[files to drag]'
if __name__ == '__main__':
    raise SystemExit('This should be run as kitten dnd')
elif __name__ == '__doc__':
    from kitty.simple_cli_definitions import CompletionSpec

    cd = sys.cli_docs  # type: ignore
    cd['usage'] = usage
    cd['options'] = OPTIONS
    cd['help_text'] = help_text
    cd['short_desc'] = 'Perform drag and drop operations, even over SSH'
    cd['args_completion'] = CompletionSpec.from_string('type:file mime:* group:Files')
