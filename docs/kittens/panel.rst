Draw a GPU accelerated dock panel on your desktop
====================================================================================================

.. highlight:: sh

.. only:: man

    Overview
    --------------


You can use this kitten to draw a GPU accelerated panel on the edge of your
screen or as the desktop wallpaper, that shows the output from an arbitrary
terminal program.

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

.. versionadded:: 0.34.0
   Support for Wayland

.. note::

    This kitten currently only works on X11 desktops and Wayland compositors
    that support the `wlr layer shell protocol
    <https://wayland.app/protocols/wlr-layer-shell-unstable-v1#compositor-support>`__
    (which is almost all of them except the, as usual, crippled GNOME).

Using this kitten is simple, for example::

    kitty +kitten panel sh -c 'printf "\n\n\nHello, world."; sleep 5s'

This will show ``Hello, world.`` at the top edge of your screen for five
seconds. Here, the terminal program we are running is :program:`sh` with a script
to print out ``Hello, world!``. You can make the terminal program as complex as
you like, as demonstrated in the screenshot above.

If you are on Wayland, you can, for instance run::

    kitty +kitten panel --edge=background htop

to display htop as your desktop background. Remember this works in everything
but GNOME and also, in sway, you have to disable the background wallpaper as
sway renders that over the panel kitten surface.


.. include:: ../generated/cli-kitten-panel.rst
