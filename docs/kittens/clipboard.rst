clipboard
==================================================

*Copy/paste to the system clipboard from shell scripts*

.. highlight:: sh


The ``clipboard`` kitten can be used to read or write to the system clipboard
from the shell. It even works over SSH. Using it is as simple as::

    echo hooray | kitty +kitten clipboard

All text received on :file:`stdin` is copied to the clipboard.

To get text from the clipboard you have to enable reading of the clipboard
in :opt:`clipboard_control` in :file:`kitty.conf`. Once you do that, you can
use::

    kitty +kitten clipboard --get-clipboard


.. program:: kitty +kitten clipboard


.. include:: /generated/cli-kitten-clipboard.rst
