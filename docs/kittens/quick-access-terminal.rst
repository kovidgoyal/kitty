.. _quake:

Make a Quake like quick access terminal
====================================================================================================

.. highlight:: sh

.. only:: man

    Overview
    --------------


.. include:: ../quake-screenshots.rst

.. versionadded:: 0.42.0
   See :ref:`here for what platforms it works on <panel_compat>`.

This kitten can be used to make a quick access terminal, that appears and
disappears at a key press. To do so use the following command:

.. code-block:: sh

    kitten quick-access-terminal

Run this command in a terminal, and a quick access kitty window will show up at
the top of your screen. Run it again, and the window will be hidden.

To make the terminal appear and disappear at a key press:

.. |macOs| replace:: :guilabel:`System Preferences->Keyboard->Keyboard Shortcuts->Services->General`

.. only:: not man

    .. tab:: Linux

        Simply bind the above command to some key press in your window manager or desktop
        environment settings and then you have a quick access terminal at a single key press.

    .. tab:: macOS

        In kitty, run the above command to show the quick access window, then close
        it by running the command again or pressing :kbd:`ctrl+d`. Now go to |macOS| and set a shortcut for
        the :guilabel:`Quick access to kitty` entry.

.. only:: man

    In Linux, simply assign the above command to a global shortcut in your
    window manager. In macOS, go to |macOS| and set a shortcut
    for the :guilabel:`Quick access to kitty` entry.

Configuration
------------------------

You can configure the appearance and behavior of the quick access window
by creating a :file:`quick-access-terminal.conf` file in your
:ref:`kitty config folder <confloc>`. In particular, you can use the
:opt:`kitty_conf <kitten-quick_access_terminal.kitty_conf>` option to change
various kitty settings, just for the quick access window.

.. note::

   This kitten uses the :doc:`panel kitten </kittens/panel>` under the
   hood. You can use the :ref:`techniques described there <remote_control_panel>`
   for remote controlling the quick access window, remember to add
   ``kitty_override allow_remote_control=socket-only`` and ``kitty_override
   listen_on=unix:/tmp/whatever`` to
   :file:`quick-access-terminal.conf`.

See below for the supported configuration directives:


.. include:: /generated/conf-kitten-quick_access_terminal.rst


.. include:: /generated/cli-kitten-quick_access_terminal.rst


Sample quick-access-terminal.conf
---------------------------------------

You can download a sample :file:`quick-access-terminal.conf` file with all default settings and
comments describing each setting by clicking: :download:`sample quick-access-terminal.conf
</generated/conf/quick_access_terminal.conf>`.
