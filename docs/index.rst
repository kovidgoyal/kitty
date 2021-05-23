:tocdepth: 2

==========================================================
kitty - the fast, featureful, GPU based terminal emulator
==========================================================

.. container:: major-features

    * Offloads rendering to the GPU for :doc:`lower system load <performance>` and
      buttery smooth scrolling.  Uses threaded rendering to minimize input latency.

    * Supports all modern terminal features: :doc:`graphics (images)
      <graphics-protocol>`, unicode, `true-color
      <https://gist.github.com/XVilka/8346728>`_,
      OpenType ligatures, mouse protocol, :doc:`hyperlinks <open_actions>`,
      focus tracking, `bracketed paste <https://cirw.in/blog/bracketed-paste>`_
      and several :doc:`new terminal protocol extensions
      <protocol-extensions>`.

    * Supports tiling multiple terminal windows side by side in different
      :ref:`layouts <layouts>` without needing to use an extra program like tmux

    * Can be :doc:`controlled from scripts or the shell prompt <remote-control>`,
      even over SSH.

    * Has a framework for :ref:`kittens`, small terminal programs that can be used to
      extend |kitty|'s functionality.  For example, they are used for
      :doc:`Unicode input <kittens/unicode-input>`, :doc:`Hints <kittens/hints>` and
      :doc:`Side-by-side diff <kittens/diff>`.

    * Supports :ref:`startup sessions <sessions>` which allow you to specify
      the window/tab layout, working directories and programs to run on startup.

    * Cross-platform: |kitty| works on Linux and macOS, but because it uses only
      OpenGL for rendering, it should be trivial to port to other Unix-like platforms.

    * Allows you to open :ref:`the scrollback buffer <scrollback>` in a
      separate window using arbitrary programs of your choice. This is useful for
      browsing the history comfortably in a pager or editor.

    * Has :ref:`multiple copy/paste buffers <cpbuf>`, like vim.


.. figure:: screenshots/screenshot.png
    :alt: Screenshot, showing three programs in the 'Tall' layout
    :align: center
    :scale: 100%

    Screenshot, showing vim, tig and git running in |kitty| with the 'Tall' layout



.. contents::
   :local:
   :depth: 1


.. _quickstart:

Quickstart
--------------

Pre-built binaries of |kitty| are available for both macOS and Linux.
See the :doc:`binary install instructions </binary>`. You can also
:doc:`build from source </build>`.

Additionally, you can use your favorite package manager to install the |kitty|
package, but note that some Linux distribution packages are woefully outdated.
|kitty| is available in a vast number of package repositories for macOS
and Linux.

.. image:: https://repology.org/badge/tiny-repos/kitty.svg
   :target: https://repology.org/project/kitty/versions
   :alt: Number of repositories kitty is available in

See :doc:`Configuring kitty <conf>` for help on configuring |kitty| and
:doc:`Invocation <invocation>` for the command line arguments |kitty| supports.


Design philosophy
-------------------

|kitty| is designed for power keyboard users. To that end all its controls
work with the keyboard (although it fully supports mouse interactions as
well). Its configuration is a simple, human editable, single file for
easy reproducibility (I like to store configuration in source control).

The code in |kitty| is designed to be simple, modular and hackable. It is
written in a mix of C (for performance sensitive parts) and Python (for
easy hackability of the UI). It does not depend on any large and complex
UI toolkit, using only OpenGL for rendering everything.

Finally, |kitty| is designed from the ground up to support all modern
terminal features, such as unicode, true color, bold/italic fonts, text
formatting, etc. It even extends existing text formatting escape codes,
to add support for features not available elsewhere, such as colored and
styled (curly) underlines. One of the design goals of |kitty| is to be
easily extensible so that new features can be added in the future with
relatively little effort.

.. include:: basic.rst

.. _layouts:

Layouts
----------

A layout is an arrangement of multiple kitty *windows* inside a top-level OS window. You can create a new window
using the :sc:`new_window` key combination.

Currently, there are seven layouts available:

* **Fat** -- One (or optionally more) windows are shown full width on the top, the rest of the windows are shown side-by-side on the bottom
* **Grid** -- All windows are shown in a grid
* **Horizontal** -- All windows are shown side-by-side
* **Splits** -- Windows arranged in arbitrary patterns created using horizontal and vertical splits
* **Stack** -- Only a single maximized window is shown at a time
* **Tall** -- One (or optionally more) windows are shown full height on the left, the rest of the windows are shown one below the other on the right
* **Vertical** -- All windows are shown one below the other

By default, all layouts are enabled and you can switch between layouts using
the :sc:`next_layout` key combination. You can also create shortcuts to select
particular layouts, and choose which layouts you want to enable/disable, see
:ref:`conf-kitty-shortcuts.layout` for examples. The first layout listed in
:opt:`enabled_layouts` becomes the default layout.

For more details on the layouts and how to use them see :doc:`layouts`.

.. _kittens:

Kittens
------------------

|kitty| has a framework for easily creating terminal programs that make use of
its advanced features. These programs are called kittens. They are used both
to add features to |kitty| itself and to create useful standalone programs.
Some prominent kittens:

:doc:`icat <kittens/icat>`
    Display images in the terminal


:doc:`diff <kittens/diff>`
    A fast, side-by-side diff for the terminal with syntax highlighting and
    images


:doc:`Unicode Input <kittens/unicode-input>`
    Easily input arbitrary unicode characters in |kitty| by name or hex code.


:doc:`Hints <kittens/hints>`
    Select and open/paste/insert arbitrary text snippets such as URLs,
    filenames, words, lines, etc. from the terminal screen.


:doc:`Remote file <kittens/remote_file>`
    Edit, open, or download remote files over SSH easily, by simply clicking on
    the filename.


:doc:`Hyperlinked grep <kittens/hyperlinked_grep>`
    Search your files using `ripgrep <https://github.com/BurntSushi/ripgrep>`_
    and open the results directly in your favorite editor in the terminal,
    at the line containing the search result, simply by clicking on the result you want.


:doc:`Broadcast <kittens/broadcast>`
    Type in one kitty window and have it broadcast to all (or a subset) of
    other kitty windows.


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
fonts, open new windows, tabs, set their titles, change window layout, get text
from one window and send text to another, etc, etc. The possibilities are
endless. See the :doc:`tutorial <remote-control>` to get started.

.. _sessions:

Startup Sessions
------------------

You can control the tabs, window layout, working directory, startup programs,
etc. by creating a "session" file and using the :option:`kitty --session`
command line flag or the :opt:`startup_session` option in :file:`kitty.conf`.
For example:

.. code-block:: session

    # Set the window layout for the current tab
    layout tall
    # Set the working directory for windows in the current tab
    cd ~
    # Create a window and run the specified command in it
    launch zsh
    # Create a window with some environment variables set and run
    # vim in it
    launch --env FOO=BAR vim
    # Set the title for the next window
    title Chat with x
    launch irssi --profile x

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
arbitrary, command running in a new window, tab or overlay, for example::

   map f1 launch --stdin-source=@screen_scrollback --stdin-add-formatting less +G -R

Would open the scrollback buffer in a new window when you press the :kbd:`F1`
key. See :sc:`show_scrollback` for details.

If you want to use it with an editor such as vim to get more powerful features,
you can see tips for doing so, in
`this thread <https://github.com/kovidgoyal/kitty/issues/719>`_.

If you wish to store very large amounts of scrollback to view using the piping or
:sc:`show_scrollback` features, you can use the :opt:`scrollback_pager_history_size`
option.

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

.. _completion:


Cool integrations for kitty with other CLI tools
--------------------------------------------------

kitty provides extremely powerful interfaces such as :doc:`remote-control` and
:doc:`kittens/custom` and :doc:`kittens/icat`
that allow it to be integrated with other tools seamlessly. For a list of such
user created integrations, see: :doc:`integrations`.

Completion for kitty
---------------------------------

|kitty| comes with completion for the ``kitty`` command for popular shells.


bash
~~~~~~~~

Add the following to your :file:`~/.bashrc`

.. code-block:: sh

   source <(kitty + complete setup bash)

Older versions of bash (for example, v3.2) do not support
process substitution with the source command, in which
case you can try an alternative:

.. code-block:: sh

    source /dev/stdin <<<"$(kitty + complete setup bash)"


zsh
~~~~~~~~~

Add the following to your :file:`~/.zshrc`

.. code-block:: sh

    autoload -Uz compinit
    compinit
    # Completion for kitty
    kitty + complete setup zsh | source /dev/stdin

The important thing above is to make sure the call to |kitty| to load the zsh
completions happens after the call to :file:`compinit`.


fish
~~~~~~~~

For versions of fish earlier than 3.0.0, add the following to your
:file:`~/.config/fish/config.fish`. Later versions source completions by default.

.. code-block:: sh

   kitty + complete setup fish | source


Changelog
------------------

See :doc:`changelog`.

.. toctree::
    :hidden:
    :glob:

    *
    kittens/*
    generated/rc
