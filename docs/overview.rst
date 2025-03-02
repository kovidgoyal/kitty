Overview
==============

Design philosophy
-------------------

|kitty| is designed for power keyboard users. To that end all its controls work
with the keyboard (although it fully supports mouse interactions as well). Its
configuration is a simple, human editable, single file for easy reproducibility
(I like to store configuration in source control).

The code in |kitty| is designed to be simple, modular and hackable. It is
written in a mix of C (for performance sensitive parts), Python (for easy
extensibility and flexibility of the UI) and Go (for the command line
:term:`kittens`).  It does not depend on any large and complex UI toolkit,
using only OpenGL for rendering everything.

Finally, |kitty| is designed from the ground up to support all modern terminal
features, such as Unicode, true color, bold/italic fonts, text formatting, etc.
It even extends existing text formatting escape codes, to add support for
features not available elsewhere, such as colored and styled (curly) underlines.
One of the design goals of |kitty| is to be easily extensible so that new
features can be added in the future with relatively little effort.

.. include:: basic.rst


Configuring kitty
-------------------

|kitty| is highly configurable, everything from keyboard shortcuts to painting
frames-per-second. Press :sc:`edit_config_file` in kitty to open its fully
commented sample config file in your text editor. For details see the
:doc:`configuration docs <conf>`.

.. toctree::
   :hidden:

   conf


.. _layouts:

Layouts
----------

A :term:`layout` is an arrangement of multiple :term:`kitty windows <window>`
inside a top-level :term:`OS window <os_window>`. The layout manages all its
windows automatically, resizing and moving them as needed. You can create a new
:term:`window` using the :sc:`new_window` key combination.

Currently, there are seven layouts available:

* **Fat** -- One (or optionally more) windows are shown full width on the top,
  the rest of the windows are shown side-by-side on the bottom

* **Grid** -- All windows are shown in a grid

* **Horizontal** -- All windows are shown side-by-side

* **Splits** -- Windows arranged in arbitrary patterns created using horizontal
  and vertical splits

* **Stack** -- Only a single maximized window is shown at a time

* **Tall** -- One (or optionally more) windows are shown full height on the
  left, the rest of the windows are shown one below the other on the right

* **Vertical** -- All windows are shown one below the other

By default, all layouts are enabled and you can switch between layouts using
the :sc:`next_layout` key combination. You can also create shortcuts to select
particular layouts, and choose which layouts you want to enable, see
:ref:`conf-kitty-shortcuts.layout` for examples. The first layout listed in
:opt:`enabled_layouts` becomes the default layout.

For more details on the layouts and how to use them see :doc:`the documentation
<layouts>`.

.. toctree::
   :hidden:

   layouts

Extending kitty
------------------

kitty has a powerful framework for scripting. You can create small terminal
programs called :doc:`kittens <kittens_intro>`. These can be used to add features
to kitty, for example, :doc:`editing remote files <kittens/remote_file>` or
:doc:`inputting Unicode characters <kittens/unicode_input>`. They can also be
used to create programs that leverage kitty's powerful features, for example,
:doc:`viewing images <kittens/icat>` or :doc:`diffing files with image support
<kittens/diff>`.

You can :doc:`create your own kittens to scratch your own itches
<kittens/custom>`.

For a list of all the builtin kittens, :ref:`see here <kittens>`.

Additionally, you can use the :ref:`watchers <Watchers>` framework
to create Python scripts that run in response to various events such as windows
being resized, closing, having their titles changed, etc.

.. toctree::
   :hidden:

   kittens_intro


Remote control
------------------

|kitty| has a very powerful system that allows you to control it from the
:doc:`shell prompt, even over SSH <remote-control>`. You can change colors,
fonts, open new :term:`windows <window>`, :term:`tabs <tab>`, set their titles,
change window layout, get text from one window and send text to another, etc.
The possibilities are endless. See the :doc:`tutorial <remote-control>` to get
started.

.. toctree::
   :hidden:

   remote-control


.. _sessions:

Startup Sessions
------------------

You can control the :term:`tabs <tab>`, :term:`kitty window <window>` layout,
working directory, startup programs, etc. by creating a *session* file and using
the :option:`kitty --session` command line flag or the :opt:`startup_session`
option in :file:`kitty.conf`. An example, showing all available commands:

.. code-block:: session

    # Set the layout for the current tab
    layout tall
    # Set the working directory for windows in the current tab
    cd ~
    # Create a window and run the specified command in it
    launch zsh
    # Create a window with some environment variables set and run vim in it
    launch --env FOO=BAR vim
    # Set the title for the next window
    launch --title "Chat with x" irssi --profile x
    # Run a short lived command and see its output
    launch --hold message-of-the-day

    # Create a new tab
    # The part after new_tab is the optional tab title which will be displayed in
    # the tab bar, if omitted, the title of the active window will be used instead.
    new_tab my tab
    cd ~/somewhere
    # Set the layouts allowed in this tab
    enabled_layouts tall,stack
    # Set the current layout
    layout stack
    launch zsh

    # Create a new OS window
    # Any definitions specified before the first new_os_window will apply to first OS window.
    new_os_window
    # Set new window size to 80x24 cells
    os_window_size 80c 24c
    # Set the --class for the new OS window
    os_window_class mywindow
    # Set the --name for the new OS window
    os_window_name myname
    # Change the OS window state to normal, fullscreen, maximized or minimized
    os_window_state normal
    launch sh
    # Resize the current window (see the resize_window action for details)
    resize_window wider 2
    # Make the current window the active (focused) window in its tab
    focus
    # Make the current OS Window the globally active window (not supported on Wayland)
    focus_os_window
    launch emacs

    # Create a complex layout using multiple splits. Creates two columns of
    # windows with two windows in each column. The windows in the first column are
    # split 50:50. In the second column the windows are not evenly split.
    new_tab complex tab
    layout splits
    # First window, set a user variable on it so we can focus it later
    launch --var window=first
    # Create the second column by splitting the first window vertically
    launch --location=vsplit
    # Create the third window in the second column by splitting the second window horizontally
    # Make it take 40% of the height instead of 50%
    launch --location=hsplit --bias=40
    # Go back to focusing the first window, so that we can split it
    focus_matching_window var:window=first
    # Create the final window in the first column
    launch --location=hsplit


.. note::
    The :doc:`launch <launch>` command when used in a session file cannot create
    new OS windows, or tabs.

.. note::
   Environment variables of the form :code:`${NAME}` or :code:`$NAME` are
   expanded in the session file, except in the *arguments* (not options) to the
   launch command.


Creating tabs/windows
-------------------------------

kitty can be told to run arbitrary programs in new :term:`tabs <tab>`,
:term:`windows <window>` or :term:`overlays <overlay>` at a keypress.
To learn how to do this, see :doc:`here <launch>`.

.. toctree::
   :hidden:

   launch


Mouse features
-------------------

* You can click on a URL to open it in a browser.
* You can double click to select a word and then drag to select more words.
* You can triple click to select a line and then drag to select more lines.
* You can triple click while holding :kbd:`Ctrl+Alt` to select from clicked
  point to end of line.
* You can right click to extend a previous selection.
* You can hold down :kbd:`Ctrl+Alt` and drag with the mouse to select in
  columns.
* Selecting text automatically copies it to the primary clipboard (on platforms
  with a primary clipboard).
* You can middle click to paste from the primary clipboard (on platforms with a
  primary clipboard).
* You can right click while holding :kbd:`Ctrl+Shift` to open the output of the
  clicked on command in a pager (requires :ref:`shell_integration`)
* You can select text with kitty even when a terminal program has grabbed the
  mouse by holding down the :kbd:`Shift` key

All these actions can be customized in :file:`kitty.conf` as described
:ref:`here <conf-kitty-mouse.mousemap>`.

You can also customize what happens when clicking on :term:`hyperlinks` in
kitty, having it open files in your editor, download remote files, open things
in your browser, etc. For details, see :doc:`here <open_actions>`.

.. toctree::
   :hidden:

   open_actions

Font control
-----------------

|kitty| has extremely flexible and powerful font selection features. You can
specify individual families for the regular, bold, italic and bold+italic fonts.
You can even specify specific font families for specific ranges of Unicode
characters. This allows precise control over text rendering. It can come in
handy for applications like powerline, without the need to use patched fonts.
See the various font related configuration directives in
:ref:`conf-kitty-fonts`.


.. _scrollback:

The scrollback buffer
-----------------------

|kitty| supports scrolling back to view history, just like most terminals. You
can use either keyboard shortcuts or the mouse scroll wheel to do so. While
you are browsing the scrollback a :opt:`small indicator <scrollback_indicator_opacity>`
is displayed along the right edge of the window to show how far back you are.

However, |kitty| has an extra, neat feature. Sometimes you need to explore the scrollback
buffer in more detail, maybe search for some text or refer to it side-by-side
while typing in a follow-up command. |kitty| allows you to do this by pressing
the :sc:`show_scrollback` shortcut, which will open the scrollback buffer in
your favorite pager program (which is :program:`less` by default). Colors and
text formatting are preserved. You can explore the scrollback buffer comfortably
within the pager.

Additionally, you can pipe the contents of the scrollback buffer to an
arbitrary, command running in a new :term:`window`, :term:`tab` or
:term:`overlay`. For example::

   map f1 launch --stdin-source=@screen_scrollback --stdin-add-formatting less +G -R

Would open the scrollback buffer in a new :term:`window` when you press the
:kbd:`F1` key. See :sc:`show_scrollback <show_scrollback>` for details.

If you want to use it with an editor such as :program:`vim` to get more powerful
features, see for example, `kitty-scrollback.nvim
<https://github.com/mikesmithgh/kitty-scrollback.nvim>`__ or `kitty-grab <https://github.com/yurikhan/kitty_grab>`__
or see more tips for using various editor programs, in :iss:`this thread <719>`.

If you wish to store very large amounts of scrollback to view using the piping
or :sc:`show_scrollback <show_scrollback>` features, you can use the
:opt:`scrollback_pager_history_size` option.


Integration with shells
---------------------------------

kitty has the ability to integrate closely within common shells, such as `zsh
<https://www.zsh.org/>`__, `fish <https://fishshell.com>`__ and `bash
<https://www.gnu.org/software/bash/>`__ to enable features such as jumping to
previous prompts in the scrollback, viewing the output of the last command in
:program:`less`, using the mouse to move the cursor while editing prompts, etc.
See :doc:`shell-integration` for details.

.. toctree::
   :hidden:

   shell-integration

.. _cpbuf:

Multiple copy/paste buffers
-----------------------------

In addition to being able to copy/paste from the system clipboard, in |kitty|
you can also setup an arbitrary number of copy paste buffers. To do so, simply
add something like the following to your :file:`kitty.conf`::

   map f1 copy_to_buffer a
   map f2 paste_from_buffer a

This will allow you to press :kbd:`F1` to copy the current selection to an
internal buffer named ``a`` and :kbd:`F2` to paste from that buffer. The buffer
names are arbitrary strings, so you can define as many such buffers as you need.


Marks
-------------

kitty has the ability to mark text on the screen based on regular expressions.
This can be useful to highlight words or phrases when browsing output from long
running programs or similar. To learn how this feature works, see :doc:`marks`.

.. toctree::
   :hidden:

   marks
