Draw a GPU accelerated dock panel on your desktop
====================================================================================================

.. highlight:: sh

.. only:: man

    Overview
    --------------

.. include:: ../quake-screenshots.rst

Draw the desktop wallpaper or docks and panels using arbitrary
terminal programs, For example, have `btop
<https://github.com/aristocratos/btop>`__ or `cava
<https://github.com/karlstav/cava/>`__ be your desktop wallpaper.

It is useful for showing status information or notifications on your desktop
using terminal programs instead of GUI toolkits.


The screenshot to the side shows some uses of the panel kitten to draw various
desktop components such as the background, a quick access floating terminal and
a dock panel showing system information (Linux only).

.. versionadded:: 0.42.0

   Support for macOS, see :ref:`compatibility matrix <panel_compat>` for details.
   and X11 (background and overlay).

.. versionadded:: 0.34.0

   Support for Wayland. See :ref:`below <panel_compat>` for which
   Wayland compositors work.

Using this kitten is simple, for example::

    kitten panel sh -c 'printf "\n\n\nHello, world."; sleep 5s'

This will show ``Hello, world.`` at the top edge of your screen for five
seconds. Here, the terminal program we are running is :program:`sh` with a script
to print out ``Hello, world!``. You can make the terminal program as complex as
you like, as demonstrated in the screenshots.

If you are on Wayland or macOS, you can, for instance, run::

    kitten panel --edge=background htop

to display ``htop`` as your desktop background. Remember this works in everything
but GNOME and also, in sway, you have to disable the background wallpaper as
sway renders that over the panel kitten surface.

There are projects that make use of this facility to implement generalised
panels and desktop components:

.. _panel_projects:

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


.. _quake_ss:

How the screenshots were generated
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

The system statistics in the background were created using::

    kitten panel --edge=background -o background_opacity=0.2 -o background=black btop

This creates a kitty background window and inside it runs the `btop
<https://github.com/aristocratos/btop>`__ program to display the statistics.

The floating quick access window was created by running::

    kitten quick-access-terminal kitten run-shell \
       zsh -c 'printf "\e]66;s=4;Quick access kitty in Hyprland\a\n\n\n\nAlso uses kitty to draw desktop background\n"'

This starts the quick access window and inside it runs ``kitten run-shell``, which
in turn first runs ``zsh`` to print out the message and then starts the users login
shell.

The Linux dock panel was::

    wm bar

This is a custom program I wrote for my personal use. It uses kitty's kitten
infrastructure to implement the bar in a `few hundred lines of code
<https://github.com/kovidgoyal/wm/blob/master/bar/main.go>`__.
This was designed for my personal use only, but, there are :ref:`public projects implementing
general purpose panels using kitty <panel_projects>`.


.. _panel_compat:

Compatibility with various platforms
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

.. only:: man

   See the HTML documentation for the compatibility matrix.

.. only:: not man

    Generated with the help of the :file:`panels.py` test script.

    .. tab:: Wayland

        Below is a list of the status of various Wayland compositors. The panel kitten
        relies of the `wlr layer shell protocol
        <https://wayland.app/protocols/wlr-layer-shell-unstable-v1#compositor-support>`__,
        which is technically supported by almost all Wayland compositors, but the
        implementation in some of them is quite buggy.

        🟢 **Hyprland**
           Fully working, no known issues

        🟢 **labwc**
           Fully working, no known issues

        🟠 **KDE** (kwin)
           Mostly working, except that clicks outside background panels cause kwin to :iss:`erroneously hide the panel <8715>`. KDE uses an `undocumented mapping <https://invent.kde.org/plasma/kwin/-/blob/3dc5cee6b34792486b343098e55e7f2b90dfcd00/src/layershellv1window.cpp#L24>`__ under Wayland to set the window type from the :code:`kitten panel --app-id` flag. You might want to use :code:`--app-id=dock` so that KDE treats the window as a dock panel, and disables window appearing/disappearing animations for it.

        🟠 **Sway**
           Renders its configured background over the background window instead of
           under it. This is because it uses the wlr protocol for backgrounds itself.

        🟠 **river**
           Not all functionality has been tested, but the quick access terminal
           appears as it should and the keyboard focus is properly restored too.

        🟠 **niri**
           Hiding a dock panel (unmapping the window) does not release the space used
           by the dock.

        🔴 **GNOME** (mutter)
           Does not implement the wlr protocol at all, nothing works.

    .. tab:: macOS

        Mostly everything works, with the notable exception that dock panels do not
        prevent other windows from covering them. This is because Apple does not
        provide and way to do this in their APIs.

    .. tab:: X11

        Support is highly dependent on the quirks of individual window
        managers. See the matrix below:

        .. list-table:: Compatibility matrix
           :header-rows: 1
           :stub-columns: 1

           * - WM
             - Desktop
             - Dock
             - Quick
             - Notes

           * - KDE
             - 🟠
             - 🟢
             - 🟢
             - transparency does not work for :option:`--edge=background <--edge>`

           * - GNOME
             - 🟢
             - 🟢
             - 🟢
             -

           * - XFCE
             - 🟢
             - 🟢
             - 🟢
             -

           * - i3
             - 🔴
             - 🟠
             - 🔴
             - only top and bottom dock panels, without transparency

           * - xmonad
             - 🔴
             - 🔴
             - 🔴
             - doesn't support the needed NET_WM protocols
