:orphan:

Working with the screen and history buffer contents
======================================================

.. warning::
    The pipe action has been deprecated in favor of the
    :doc:`launch <launch>` action which is more powerful.

You can pipe the contents of the current screen and history buffer as
:file:`STDIN` to an arbitrary program using the ``pipe`` function. The program
can be displayed in a kitty window or overlay.

For example, the following in :file:`kitty.conf` will open the scrollback
buffer in less in an overlay window, when you press :kbd:`F1`::

    map f1 pipe @ansi overlay less +G -R

The syntax of the ``pipe`` function is::

   pipe <input placeholder> <destination window type> <command line to run>


The piping environment
--------------------------

The program to which the data is piped has a special environment variable
declared, ``KITTY_PIPE_DATA`` whose contents are::

   KITTY_PIPE_DATA={scrolled_by}:{cursor_x},{cursor_y}:{lines},{columns}

where ``scrolled_by`` is the number of lines kitty is currently scrolled by,
``cursor_(x|y)`` is the position of the cursor on the screen with ``(1,1)``
being the top left corner and ``{lines},{columns}`` being the number of rows
and columns of the screen.

You can choose where to run the pipe program:

``overlay``
   An overlay window over the current kitty window

``window``
   A new kitty window

``os_window``
   A new top-level window

``tab``
   A new window in a new tab

``clipboard, primary``
   Copy the text directly to the clipboard. In this case the specified program
   is not run, so use some dummy program name for it.

``none``
   Run it in the background


Input placeholders
--------------------

There are various different kinds of placeholders

``@selection``
   Plain text, currently selected text

``@text``
   Plain text, current screen + scrollback buffer

``@ansi``
   Text with formatting, current screen + scrollback buffer

``@screen``
   Plain text, only current screen

``@ansi_screen``
   Text with formatting, only current screen

``@alternate``
   Plain text, secondary screen. The secondary screen is the screen not currently displayed. For
   example if you run a fullscreen terminal application, the secondary screen will
   be the screen you return to when quitting the application.

``@ansi_alternate``
   Text with formatting, secondary screen.

``@alternate_scrollback``
   Plain text, secondary screen + scrollback, if any.

``@ansi_alternate_scrollback``
   Text with formatting, secondary screen + scrollback, if any.

``none``
   No input


You can also add the suffix ``_wrap`` to the placeholder, in which case kitty
will insert the carriage return at every line wrap location (where long lines
are wrapped at screen edges). This is useful if you want to pipe to program
that wants to duplicate the screen layout of the screen.
