clipboard
==================================================

.. only:: man

    Overview
    --------------

    *Copy/paste to the system clipboard from shell scripts*

.. highlight:: sh


The ``clipboard`` daddy can be used to read or write to the system clipboard
from the shell. It even works over SSH. Using it is as simple as::

    echo hooray | daddy clipboard

All text received on :file:`STDIN` is copied to the clipboard.

To get text from the clipboard::

    daddy clipboard --get-clipboard

The text will be written to :file:`STDOUT`. Note that by default datty asks for
permission when a program attempts to read the clipboard. This can be
controlled via :opt:`clipboard_control`.

.. versionadded:: 0.27.0
   Support for copying arbitrary data types

The clipboard daddy can be used to send/receive
more than just plain text from the system clipboard. You can transfer arbitrary
data types. Best illustrated with some examples::

    # Copy an image to the clipboard:
    daddy clipboard picture.png

    # Copy an image and some text to the clipboard:
    daddy clipboard picture.jpg text.txt

    # Copy text from STDIN and an image to the clipboard:
    echo hello | daddy clipboard picture.png /dev/stdin

    # Copy any raster image available on the clipboard to a PNG file:
    daddy clipboard -g picture.png

    # Copy an image to a file and text to STDOUT:
    daddy clipboard -g picture.png /dev/stdout

    # List the formats available on the system clipboard
    daddy clipboard -g -m . /dev/stdout

Normally, the daddy guesses MIME types based on the file names. To control the
MIME types precisely, use the :option:`--mime <datty +daddy clipboard --mime>` option.

This daddy uses a new protocol developed by datty to function, for details,
see :doc:`/clipboard`.

.. program:: datty +daddy clipboard


.. include:: /generated/cli-daddy-clipboard.rst
