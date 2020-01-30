Layouts
============

kitty has the ability to define its own windows that can be tiled next to each
other in arbitrary arrangements, based on *Layouts*, see below for examples:


.. figure:: screenshots/screenshot.png
    :alt: Screenshot, showing three programs in the 'Tall' layout
    :align: center
    :scale: 100%

    Screenshot, showing vim, tig and git running in |kitty| with the 'Tall' layout


.. figure:: screenshots/splits.png
    :alt: Screenshot, showing windows in the 'Splits' layout
    :align: center
    :scale: 100%

    Screenshot, showing windows with arbitrary arrangement in the 'Splits'
    layout


You can resize windows inside layouts. Press :sc:`start_resizing_window` (also :kbd:`⌘+r` on macOS) to
enter resizing mode and follow the on-screen instructions.  In a given window
layout only some operations may be possible for a particular window. For
example, in the Tall layout you can make the first window wider/narrower, but
not taller/shorter. Note that what you are resizing is actually not a window,
but a row/column in the layout, all windows in that row/column will be resized.

You can also define shortcuts in :file:`kitty.conf` to make the active window
wider, narrower, taller, or shorter by mapping to the ``resize_window``
action, for example::

   map ctrl+left resize_window narrower
   map ctrl+right resize_window wider
   map ctrl+up resize_window taller
   map ctrl+down resize_window shorter 3

The ``resize_window`` action has a second, optional argument to control
the resizing increment (a positive integer that defaults to 1).


Some layouts take options to control their behavior. For example, the ``fat``
and ``tall`` layouts accept the ``bias`` and ``full_size`` options to control
how the available space is split up.
To specify the option, in :opt:`kitty.conf <enabled_layouts>` use::

    enabled_layouts tall:bias=70;full_size=2

This will have ``2`` instead of a single tall window, that occupy ``70%``
instead of ``50%`` of available width. ``bias`` can be any number between 10
and 90.

Writing a new layout only requires about a hundred lines of code, so if there
is some layout you want, take a look at `layout.py
<https://github.com/kovidgoyal/kitty/blob/master/kitty/layout.py>`_  and submit
a pull request!
