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

There are projects that make use of this facility to implement generalised
panels and desktop components:

    * `kitty panel <https://github.com/5hubham5ingh/kitty-panel>`__
    * `pawbar <https://github.com/codelif/pawbar>`__


.. _quake:

Make a Quake like quick access terminal
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

.. versionadded:: 0.42.0
   Support for quake mode, works only on Wayland, except for GNOME.

This kitten can be used to make a quick access terminal, that appears and
disappears at a key press. To do so use the following command::

    kitty +kitten panel --edge=top --layer=overlay --lines=15 \
        --focus-policy=exclusive --exclusive-zone=0 --override-exclusive-zone \
        -o background_opacity=0.8 --toggle-visibility --single-instance \
        --instance-group=quake kitten run-shell

Run this command in a terminal, and a quick access kitty panel will show up at
the top of your screen. Run it again, and the panel will be hidden.

Simply bind this command to some key press in your window manager or desktop
environment settings and then you have a quick access terminal at a single key press.
You can use the various panel options to configure the size, appearance and
position of the quick access panel. In particular, the :option:`kitty +kitten panel --config` and
:option:`kitty +kitten panel --override` options can be used to theme the terminal appropriately,
making it look different from regular kitty terminal instances.

.. note::
   If you want to start the quake terminal hidden, use
   :option:`kitty +kitten panel --start-as-hidden`, useful if you are starting it in the background
   during computer startup.


Controlling panels via remote control
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

You can control panels via the kitty :doc:`remote control </remote-control>` facility. Create a panel
with remote control enabled::

    kitty +kitten panel -o allow_remote_control=socket-only --lines=2 \
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
