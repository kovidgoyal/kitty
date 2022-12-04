#!/usr/bin/env python3
# License: GPL v3 Copyright: 2018, Kovid Goyal <kovid at kovidgoyal.net>

import sys

OPTIONS = r'''
--get-clipboard -g
type=bool-set
Output the current contents of the clipboard to STDOUT. Note that by default
kitty will prompt for permission to access the clipboard. Can be controlled
by :opt:`clipboard_control`.


--use-primary -p
type=bool-set
Use the primary selection rather than the clipboard on systems that support it,
such as Linux.


--mime -m
type=list
The mimetype of the specified file. Useful when the auto-detected mimetype is
likely to be incorrect or the filename has no extension and therefore no mimetype
can be detected. If more than one file is specified, this option should be specified multiple
times, once for each specified file. When copying data from the clipboard, you can use wildcards
to match MIME types. For example: :code:`--mime 'text/*'` will match any textual MIME type
available on the clipboard, usually the first matching MIME type is copied.


--alias -a
type=list
Specify aliases for MIME types. Aliased MIME types are considered equivalent.
When copying to clipboard both the original and alias are made available on the
clipboard. When copying from clipboard if the original is not found, the alias
is used, as a fallback. Can be specified multiple times to create multiple
aliases. For example: :code:`--alias text/plain=text/x-rst` makes :code:`text/plain` an alias
of :code:`text/rst`. Aliases are not used in filter mode.


--wait-for-completion
type=bool-set
Wait till the copy to clipboard is complete before exiting. Useful if running
the kitten in a dedicated, ephemeral window. Only needed in filter mode.
'''.format
help_text = '''\
Read or write to the system clipboard.

This kitten operates most simply in :italic:`filter mode`.
To set the clipboard text, pipe in the new text on :file:`STDIN`. Use the
:option:`--get-clipboard` option to output the current clipboard text content to
:file:`STDOUT`. Note that copying from the clipboard will cause a permission
popup, see :opt:`clipboard_control` for details.

For more control, specify filename arguments. Then, different MIME types can be copied to/from
the clipboard. Some examples:

.. code:: sh

    # Copy an image to the clipboard:
    kitty +kitten clipboard picture.png

    # Copy an image and some text to the clipboard:
    kitty +kitten clipboard picture.jpg text.txt

    # Copy text from STDIN and an image to the clipboard:
    echo hello | kitty +kitten clipboard picture.png /dev/stdin

    # Copy any raster image available on the clipboard to a PNG file:
    kitty +kitten clipboard -g picture.png

    # Copy an image to a file and text to STDOUT:
    kitty +kitten clipboard -g picture.png /dev/stdout
'''

usage = '[files to copy to/from]'
if __name__ == '__main__':
    raise SystemExit('This should be run as kitty-tool clipboard')
elif __name__ == '__doc__':
    cd = sys.cli_docs  # type: ignore
    cd['usage'] = usage
    cd['options'] = OPTIONS
    cd['help_text'] = help_text
    cd['short_desc'] = 'Copy/paste with the system clipboard, even over SSH'
