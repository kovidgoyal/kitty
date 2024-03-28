icat
========================================

.. only:: man

    Overview
    --------------


*Display images in the terminal*

The ``icat`` kitten can be used to display arbitrary images in the |kitty|
terminal. Using it is as simple as::

    kitten icat image.jpeg

It supports all image types supported by `ImageMagick
<https://www.imagemagick.org>`__. It even works over SSH. For details, see the
:doc:`kitty graphics protocol </graphics-protocol>`.

You might want to create an alias in your shell's configuration files::

   alias icat="kitten icat"

Then you can simply use ``icat image.png`` to view images.

.. note::

    `ImageMagick <https://www.imagemagick.org>`__ must be installed for the
    full range of image types. Without it only PNG/JPG/GIF/BMP/TIFF/WEBP are
    supported.

.. note::

    kitty's image display protocol may not work when used within a terminal
    multiplexer such as :program:`screen` or :program:`tmux`, depending on
    whether the multiplexer has added support for it or not.


.. program:: kitty +kitten icat


The ``icat`` kitten has various command line arguments to allow it to be used
from inside other programs to display images. In particular, :option:`--place`,
:option:`--detect-support` and :option:`--print-window-size`.

If you are trying to integrate icat into a complex program like a file manager
or editor, there are a few things to keep in mind. icat normally works by communicating
over the TTY device, it both writes to and reads from the TTY. So it is
imperative that while it is running the host program does not do any TTY I/O.
Any key presses or other input from the user on the TTY device will be
discarded. If you would instead like to use it just as a backend to generate
the escape codes for image display, you need to pass it options to tell it the
window dimensions, where to place the image in the window and the transfer mode
to use. If you do that, it will not try to communicate with the TTY device at
all. The requisite options are: :option:`--use-window-size`, :option:`--place`
and :option:`--transfer-mode`, :option:`--stdin=no`.
For example, to demonstrate usage without access to the TTY:

.. code:: sh

   zsh -c 'setsid kitten icat --stdin=no --use-window-size $COLUMNS,$LINES,3000,2000 --transfer-mode=file myimage.png'

Here, ``setsid`` ensures icat has no access to the TTY device.
The values, 3000, 2000 are made up. They are the window width and height in
pixels, to obtain which access to the TTY is needed.

To be really robust you should consider writing proper support for the
:doc:`kitty graphics protocol </graphics-protocol>` in the program instead.
Nowadays there are many libraries that have support for it.


.. include:: /generated/cli-kitten-icat.rst
