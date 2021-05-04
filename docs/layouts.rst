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


There are many different layouts available. They are all enabled by default,
you can switch layouts using :sc:`next_layout`. To control which layouts
are available use :opt:`enabled_layouts`, the first listed layout becomes
the default. Individual layouts and how to use them are described below.

.. contents::
   :local:


The Stack Layout
------------------

This is the simplest layout it displays a single window using all available
space, other windows are hidden behind it. It has no options::

    enabled_layouts stack


The Tall Layout
------------------

Displays one (or optionally more) full height windows on the left half of the
screen. Remaining windows are tiled vertically on the right half of the screen.
There are options to control how the screen is split horizontally ``bias``
(an integer between ``10`` and ``90``) and options to control how many
full-height windows there are ``full_size`` (a positive integer). The
``mirrored`` option when set to ``true`` will cause the short windows to be
on the left side of the screen instead of the right. The syntax
for the options is shown below::

    enabled_layouts tall:bias=50;full_size=1;mirrored=false

    ┌──────────────┬───────────────┐
    │              │               │
    │              │               │
    │              │               │
    │              ├───────────────┤
    │              │               │
    │              │               │
    │              │               │
    │              ├───────────────┤
    │              │               │
    │              │               │
    │              │               │
    └──────────────┴───────────────┘

In addition, you can map keys to increase or decrease the number of full size
windows, for example::

   map ctrl+[ layout_action decrease_num_full_size_windows
   map ctrl+] layout_action increase_num_full_size_windows


The Fat Layout
----------------

Displays one (or optionally more) full width windows on the top half of the
screen. Remaining windows are tiled horizontally on the bottom half of the screen.
There are options to control how the screen is split vertically ``bias``
(an integer between ``10`` and ``90``) and options to control how many
full-height windows there are ``full_size`` (a positive integer). The
``mirrored`` option when set to ``true`` will cause the narrow windows to be
on the top of the screen instead of the bottom. The syntax for the options is
shown below::

    enabled_layouts fat:bias=50;full_size=1;mirrored=false

    ┌──────────────────────────────┐
    │                              │
    │                              │
    │                              │
    │                              │
    ├─────────┬──────────┬─────────┤
    │         │          │         │
    │         │          │         │
    │         │          │         │
    │         │          │         │
    │         │          │         │
    └─────────┴──────────┴─────────┘


The Grid Layout
--------------------

Display windows in a balanced grid with all windows the same size except the
last column if there are not enough windows to fill the grid. Has no options::

    enabled_layouts grid

    ┌─────────┬──────────┬─────────┐
    │         │          │         │
    │         │          │         │
    │         │          │         │
    │         │          │         │
    ├─────────┼──────────┼─────────┤
    │         │          │         │
    │         │          │         │
    │         │          │         │
    │         │          │         │
    └─────────┴──────────┴─────────┘


.. _splits_layout:

The Splits Layout
--------------------

This is the most flexible layout. You can create any arrangement of windows
by splitting exiting windows repeatedly. To best use this layout you should
define a few extra keybindings in :file:`kitty.conf`::

    map F5 launch --location=hsplit
    map F6 launch --location=vsplit
    map F7 layout_action rotate

    map shift+up move_window up
    map shift+left move_window left
    map shift+right move_window right
    map shift+down move_window down

    map ctrl+left neighboring_window left
    map ctrl+right neighboring_window right
    map ctrl+up neighboring_window up
    map ctrl+down neighboring_window down

Now you can create horizontal and vertical splits by using :kbd:`F5` and
:kbd:`F6`. You can move them around using :kbd:`shift+arrow keys`
and you can move focus to neighboring windows using :kbd:`ctrl+arrow keys`.
You can switch an existing split from horizontal to vertical and vice versa
using :kbd:`F7`. Finally, windows can be resized using :ref:`window_resizing`.

This layout takes one option, ``split_axis`` that controls whether new windows
are placed into vertical or horizontal splits, by default::

    enabled_layouts splits:split_axis=horizontal

    ┌──────────────┬───────────────┐
    │              │               │
    │              │               │
    │              │               │
    │              ├───────┬───────┤
    │              │       │       │
    │              │       │       │
    │              │       │       │
    │              ├───────┴───────┤
    │              │               │
    │              │               │
    │              │               │
    └──────────────┴───────────────┘

.. versionadded:: 0.17.0
    The Splits layout


The Horizontal Layout
------------------------

All windows are shown side by side. Has no options::

    enabled_layouts horizontal

    ┌─────────┬──────────┬─────────┐
    │         │          │         │
    │         │          │         │
    │         │          │         │
    │         │          │         │
    │         │          │         │
    │         │          │         │
    │         │          │         │
    │         │          │         │
    │         │          │         │
    └─────────┴──────────┴─────────┘


The Vertical Layout
-----------------------

All windows are shown one below the other. Has no options::

    enabled_layouts vertical

    ┌──────────────────────────────┐
    │                              │
    │                              │
    │                              │
    ├──────────────────────────────┤
    │                              │
    │                              │
    │                              │
    ├──────────────────────────────┤
    │                              │
    │                              │
    │                              │
    └──────────────────────────────┘


.. _window_resizing:

Resizing windows
------------------

You can resize windows inside layouts. Press :sc:`start_resizing_window` (also
:kbd:`⌘+r` on macOS) to enter resizing mode and follow the on-screen
instructions.  In a given window layout only some operations may be possible
for a particular window. For example, in the Tall layout you can make the first
window wider/narrower, but not taller/shorter. Note that what you are resizing
is actually not a window, but a row/column in the layout, all windows in that
row/column will be resized.

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

Writing a new layout only requires about two hundred lines of code, so if there
is some layout you want, take a look at one of the existing layouts in the
`layout <https://github.com/kovidgoyal/kitty/tree/master/kitty/layout>`_
package and submit a pull request!
