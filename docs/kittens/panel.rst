Draw a GPU accelerated dock panel on your desktop
====================================================================================================

.. highlight:: sh

.. only:: man

    Overview
    --------------

Draw the desktop wallpaper or docks and panels using arbitrary
terminal programs, For example, have `btop
<https://github.com/aristocratos/btop>`__ or `cava
<https://github.com/karlstav/cava/>`__ be your desktop wallpaper.

It is useful for showing status information or notifications on your desktop
using terminal programs instead of GUI toolkits.

.. figure:: ../screenshots/panel.png
   :alt: Screenshot, showing a sample panel
   :align: center
   :width: 100%

   Screenshot, showing a sample panel


The screenshot above shows a sample panel that displays the current desktop and
window title as well as miscellaneous system information such as network
activity, CPU load, date/time, etc.

.. versionadded:: 0.42.0
   Support for macOS and support for Wayland was added in 0.34.0

.. note::

    This kitten currently only works on macOS and Wayland compositors
    that support the `wlr layer shell protocol
    <https://wayland.app/protocols/wlr-layer-shell-unstable-v1#compositor-support>`__
    (which is almost all of them except GNOME). On macOS the panels do not
    prevent other windows from floating over them because of limitations in
    Cocoa. On X11, only the ``top`` and ``bottom`` panels are widely supported,
    the other types depend on the window manager used.

Using this kitten is simple, for example::

    kitten panel sh -c 'printf "\n\n\nHello, world."; sleep 5s'

This will show ``Hello, world.`` at the top edge of your screen for five
seconds. Here, the terminal program we are running is :program:`sh` with a script
to print out ``Hello, world!``. You can make the terminal program as complex as
you like, as demonstrated in the screenshot above.

If you are on Wayland or macOS, you can, for instance run::

    kitten panel --edge=background htop

to display ``htop`` as your desktop background. Remember this works in everything
but GNOME and also, in sway, you have to disable the background wallpaper as
sway renders that over the panel kitten surface.

There are projects that make use of this facility to implement generalised
panels and desktop components:

    * `kitty panel <https://github.com/5hubham5ingh/kitty-panel>`__
    * `pawbar <https://github.com/codelif/pawbar>`__


.. _remote_control_panel:

Controlling panels via remote control
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

You can control panels via the kitty :doc:`remote control </remote-control>` facility. Create a panel
with remote control enabled::

    kitten panel -o allow_remote_control=socket-only --lines=2 \
        --listen-on=unix:/tmp/panel kitten run-shell


Now you can control this panel using remote control, for example to show/hide
it, use::

    kitten @ --to=unix:/tmp/panel resize-os-window --action=toggle-visibility

To move the panel to the bottom of the screen and increase its height::

    kitten @ --to=unix:/tmp/panel resize-os-window --action=os-panel \
        --incremental edge=bottom lines=4

To create a new panel running the program top, in the same instance
(like creating a new OS window)::

    kitten @ --to=unix:/tmp/panel launch --type=os-panel --os-panel edge=top \
        --os-panel lines=8 top


.. include:: ../generated/cli-kitten-panel.rst
