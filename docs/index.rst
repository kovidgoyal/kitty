kitty
==========================================================

*The fast, feature-rich, GPU based terminal emulator*

.. toctree::
    :hidden:

    quickstart
    overview
    faq
    support
    performance
    changelog
    integrations
    protocol-extensions


.. tab:: Fast

   * Offloads rendering to the GPU for :doc:`lower system load <performance>`
   * Uses threaded rendering for absolutely minimal latency
   * Performance tradeoffs can be :ref:`tuned <conf-kitty-performance>`

.. tab:: Capable

   * Graphics, with :doc:`images and animations <graphics-protocol>`
   * Ligatures and emoji, with :opt:`per glyph font substitution <symbol_map>`
   * :term:`Hyperlinks<hyperlinks>`, with :doc:`configurable actions <open_actions>`

.. tab:: Scriptable

   * Control from :doc:`scripts or the shell <remote-control>`
   * Extend with :ref:`kittens <kittens>` using the Python language
   * Use :ref:`startup sessions <sessions>` to specify working environments

.. tab:: Composable

   * Programmble tabs, :ref:`splits <splits_layout>` and multiple :doc:`layouts <layouts>` to manage windows
   * Browse the :ref:`entire history <scrollback>` or the output from the last command comfortably in pagers and editors
   * Edit or download :doc:`remote files <kittens/remote_file>` in an existing SSH session

.. tab:: Cross-platform

   * Linux
   * macOS
   * Various BSDs

.. tab:: Innovative

   Pioneered various extensions to move the entire terminal ecosystem forward

   * :doc:`graphics-protocol`
   * :doc:`keyboard-protocol`
   * Lots more in :doc:`protocol-extensions`
=======
:doc:`Panel <kittens/panel>`
    Draw a GPU accelerated dock panel on your desktop showing the output
    from an arbitrary terminal program.


:doc:`Clipboard <kittens/clipboard>`
    Copy/paste to the clipboard from shell scripts, even over SSH.

You can also :doc:`Learn to create your own kittens <kittens/custom>`.


Configuring kitty
-------------------

|kitty| is highly configurable, everything from keyboard shortcuts to
painting frames-per-second. Press :sc:`edit_config_file` in kitty
to open its fully commented sample config file in your text editor.
For details see the :doc:`configuration docs <conf>`.


Remote control
------------------

|kitty| has a very powerful system that allows you to control it from the
:doc:`shell prompt, even over SSH <remote-control>`. You can change colors,
fonts, open new :term:`windows <window>`, :term:`tabs <tab>`, set their titles,
change window layout, get text
from one window and send text to another, etc, etc. The possibilities are
endless. See the :doc:`tutorial <remote-control>` to get started.

.. _sessions:

Startup Sessions
------------------

You can control the :term:`tabs <tab>`, `:term:`kitty window <window>` layout,
working directory, startup programs,
etc. by creating a "session" file and using the :option:`kitty --session`
command line flag or the :opt:`startup_session` option in :file:`kitty.conf`.
For example:

.. code-block:: session

    # Set the layout for the current tab
    layout tall
    # Set the working directory for windows in the current tab
    cd ~
    # Create a window and run the specified command in it
    launch zsh
    # Create a window with some environment variables set and run
    # vim in it
    launch --env FOO=BAR vim
    # Set the title for the next window
    launch --title "Chat with x" irssi --profile x

    # Create a new tab (the part after new_tab is the optional tab
    # name which will be displayed in the tab bar, if omitted, the
    # title of the active window will be used instead)
    new_tab my tab
    cd ~/somewhere
    # Set the layouts allowed in this tab
    enabled_layouts tall, stack
    # Set the current layout
    layout stack
    launch zsh

    # Create a new OS window
    new_os_window
    # set new window size to 80x25 cells
    os_window_size 80c 25c
    # set the --class for the new OS window
    os_window_class mywindow
    launch sh
    # Make the current window the active (focused) window
    focus
    launch emacs

.. note::
    The :doc:`launch <launch>` command when used in a session file
    cannot create new OS windows, or tabs.


Mouse features
-------------------

* You can click on a URL to open it in a browser.
* You can double click to select a word and then drag to select more words.
* You can triple click to select a line and then drag to select more lines.
* You can triple click while holding :kbd:`ctrl+alt` to select from clicked
  point to end of line.
* You can right click to extend a previous selection.
* You can hold down :kbd:`ctrl+alt` and drag with the mouse to select in
  columns.
* Selecting text automatically copies it to the primary clipboard (on
  platforms with a primary clipboard).
* You can middle click to paste from the primary clipboard (on platforms
  with a primary clipboard).
* You can select text with kitty even when a terminal program has grabbed
  the mouse by holding down the :kbd:`shift` key.

All these actions can be customized in :file:`kitty.conf` as described
:ref:`here <conf-kitty-mouse.mousemap>`.


Font control
-----------------

|kitty| has extremely flexible and powerful font selection features. You can
specify individual families for the regular, bold, italic and bold+italic
fonts. You can even specify specific font families for specific ranges of
unicode characters. This allows precise control over text rendering. It can
come in handy for applications like powerline, without the need to use patched
fonts. See the various font related configuration directives in
:ref:`conf-kitty-fonts`.


.. _scrollback:

The scrollback buffer
-----------------------

|kitty| supports scrolling back to view history, just like most terminals. You
can use either keyboard shortcuts or the mouse scroll wheel to do so.  However,
|kitty| has an extra, neat feature. Sometimes you need to explore the
scrollback buffer in more detail, maybe search for some text or refer to it
side-by-side while typing in a follow-up command. |kitty| allows you to do this
by pressing the :sc:`show_scrollback` key-combination, which will open the
scrollback buffer in your favorite pager program (which is ``less`` by default).
Colors and text formatting are preserved. You can explore the scrollback buffer
comfortably within the pager.

Additionally, you can pipe the contents of the scrollback buffer to an
arbitrary, command running in a new :term:`window`, :term:`tab` or :term:`overlay`,
for example::

   map f1 launch --stdin-source=@screen_scrollback --stdin-add-formatting less +G -R

Would open the scrollback buffer in a new :term:`window` when you press the :kbd:`F1`
key. See :sc:`show_scrollback` for details.

If you want to use it with an editor such as vim to get more powerful features,
you can see tips for doing so, in
`this thread <https://github.com/kovidgoyal/kitty/issues/719>`_.

If you wish to store very large amounts of scrollback to view using the piping or
:sc:`show_scrollback` features, you can use the :opt:`scrollback_pager_history_size`
option.

You can also view the output of the last command to run in the shell, by
pressing :sc:`show_last_command_output`. See :ref:`shell_integration` for
details.

.. _cpbuf:

Multiple copy/paste buffers
-----------------------------

In addition to being able to copy/paste from the system clipboard, in |kitty| you
can also setup an arbitrary number of copy paste buffers. To do so, simply add
something like the following to your :file:`kitty.conf`::

   map f1 copy_to_buffer a
   map f2 paste_from_buffer a

This will allow you to press :kbd:`F1` to copy the current selection to an
internal buffer named ``a`` and :kbd:`F2` to paste from that buffer. The buffer
names are arbitrary strings, so you can define as many such buffers as you
need.

Marks
-------------

kitty has the ability to mark text on the screen based on regular expressions.
This can be useful to highlight words or phrases when browsing output from long
running programs or similar. To learn how this feature works, see :doc:`marks`.


Frequently Asked Questions
---------------------------------

The list of Frequently Asked Questions (*FAQ*) is :doc:`available here <faq>`.


Cool integrations for kitty with other CLI tools
--------------------------------------------------

kitty provides extremely powerful interfaces such as :doc:`remote-control` and
:doc:`kittens/custom` and :doc:`kittens/icat`
that allow it to be integrated with other tools seamlessly. For a list of such
user created integrations, see: :doc:`integrations`.


>>>>>>> 1d167ada (Move shell integration docs into own file)


.. figure:: screenshots/screenshot.png
    :alt: Screenshot, showing three programs in the 'Tall' layout
    :align: center
    :width: 100%

    Screenshot, showing vim, tig and git running in |kitty| with the 'Tall' layout


To get started see :doc:`quickstart`.
