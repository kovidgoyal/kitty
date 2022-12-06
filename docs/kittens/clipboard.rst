clipboard
==================================================

*Copy/paste to the system clipboard from shell scripts*

.. highlight:: sh


The ``clipboard`` kitten can be used to read or write to the system clipboard
from the shell. It even works over SSH. Using it is as simple as::

    echo hooray | kitty +kitten clipboard

All text received on :file:`STDIN` is copied to the clipboard.

To get text from the clipboard::

    kitty +kitten clipboard --get-clipboard

The text will be written to :file:`STDOUT`. Note that by default kitty asks for
permission when a program attempts to read the clipboard. This can be
controlled via :opt:`clipboard_control`.

.. versionadded:: 0.27.0
   Support for copying arbitrary data types

The clipboard kitten can be used to send/receive
more than just plain text from the system clipboard. You can transfer arbitrary
data types. Best illustrated with some examples::

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

    # List the formats available on the system clipboard
    kitty +kitten clipboard -g -m . /dev/stdout

Normally, the kitten guesses MIME types based on the file names. To control the
MIME types precisely, use the :option:`--mime <kitty +kitten clipboard --mime>` option.

This kitten uses a new protocol developed by kitty to function, for details,
see :doc:`/clipboard`.

.. program:: kitty +kitten clipboard


.. include:: /generated/cli-kitten-clipboard.rst
