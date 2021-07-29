:orphan:

Glossary
=========

.. glossary::

   os_window
     kitty has two kinds of windows. Operating System windows, refered to as :term:`OS
     Window <os_window>`, and *kitty windows*. An OS Window consists of one or more kitty
     :term:`tabs <tab>`. Each tab in turn consists of one or more *kitty
     windows* organized in a :term:`layout`.

   tab
     A *tab* refers to a group of :term:`kitty windows <window>`, organized in
     a :term:`layout`. Every :term:`OS Window <os_window>` contains one or more tabs.

   layout
     A *layout* is a system of organizing :term:`kitty windows <window>` in
     groups inside a tab. The layout automatically maintains the size and
     position of the windows, think of a layout as a tiling window manager for
     the terminal. See :doc:`layouts` for details.

   window
     kitty has two kinds of windows. Operating System windows, refered to as :term:`OS
     Window <os_window>`, and *kitty windows*. An OS Window consists of one or more kitty
     :term:`tabs <tab>`. Each tab in turn consists of one or more *kitty
     windows* organized in a :term:`layout`.

   overlay
      An *overlay window* is a :term:`kitty window <window>` that is placed on
      top of an existing kitty window, entirely covering it. Overlays are used
      throught kitty, for example, to display the :ref:`the scrollback buffer <scrollback>`,
      to display :doc:`hints </kittens/hints>`, for :doc:`unicode input
      </kittens/unicode-input>` etc.

   hyperlinks
      Terminals can have hyperlinks, just like the internet. In kitty you can
      :doc:`control exactly what happens <open_actions>` when clicking on a
      hyperlink, based on the type of link and its URL.

.. _env_vars:

Environment variables
------------------------

Variables that influence kitty behavior

.. envvar:: KITTY_CONFIG_DIRECTORY

   Controls where kitty looks for :file:`kitty.conf` and other configuration
   files. Defaults to :file:`~/.config/kitty`. For full details of the config
   directory lookup mechanism see, :option:`kitty --config`.


.. envvar:: VISUAL

   Controls what program kitty uses as an editor, when, for instance, opening
   kitty.conf in response to :sc:`edit_config_file`


.. envvar:: EDITOR

   Same as :envvar:`VISUAL`. Used if :envvar:`VISUAL` is not set.


Variables that kitty sets when running child programs

.. envvar:: KITTY_WINDOW_ID

   An integer that is the id for the kitty :term:`window` the program is running in.
   Can be used with the :doc:`kitty remote control facility <remote-control>`.


.. envvar:: WINDOWID

   The id for the :term:`OS Window <os_window>` the program is running in. Only available
   on platforms that have ids for their windows, such as X11 and macOS.


.. envvar:: TERM

   The name of the terminal, defaults to ``xterm-kitty``. See :opt:`term`.


.. envvar:: TERMINFO

   Path to a directory containing the kitty terminfo database.


.. envvar:: COLORTERM

   Set to the value ``truecolor`` to indicate that kitty supports 16 million
   colors.


.. envvar:: KITTY_LISTEN_ON

   Set when the :doc:`remote control <remote-control>` facility is enabled and
   the a socket is used for control via :option:`kitty --listen-on` or :opt:`listen_on`.
   Contains the path to the socket. Avoids needs to use :option:`kitty @ --to` when
   issuing remote control commands.


.. envvar:: KITTY_PIPE_DATA

   Set to data describing the layout of the screen when running child
   programs using :option:`launch --stdin-source` with the contents of the
   screen/scrollback piped to them.


.. envvar:: KITTY_CHILD_CMDLINE

   Set to the command line of the child process running in the kitty
   window when calling the notification callback program on terminal bell, see
   :opt:`command_on_bell`.


.. envvar:: KITTY_COMMON_OPTS

   Set with the values of some common kitty options when running
   kittens, so kittens can use them without needing to load kitty.conf.
