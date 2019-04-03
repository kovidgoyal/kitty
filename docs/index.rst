:tocdepth: 2

==========================================================
kitty - the fast, featureful, GPU based terminal emulator
==========================================================

.. container:: major-features

    * Offloads rendering to the GPU for :doc:`lower system load <performance>` and
      buttery smooth scrolling.  Uses threaded rendering to minimize input latency.

    * Supports all modern terminal features: :doc:`graphics (images)
      <graphics-protocol>`, unicode, true-color, OpenType ligatures, mouse
      protocol, focus tracking, `bracketed paste
      <https://cirw.in/blog/bracketed-paste>`_ and several :doc:`new terminal
      protocol extensions <protocol-extensions>`.

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


.. _quickstart:

Quickstart
--------------

Pre-built binaries of |kitty| are available for both macOS and Linux.
See the :doc:`binary install instructions </binary>`. You can also
:doc:`build from source </build>`.

If you are on Linux, you can also use your distribution's |kitty| package.
|kitty| packages are available for:
`Debian <https://packages.debian.org/buster/kitty>`_,
`openSUSE <https://build.opensuse.org/package/show/X11:terminals/kitty>`_,
`Arch Linux <https://www.archlinux.org/packages/community/x86_64/kitty/>`_,
`NixOS <https://github.com/NixOS/nixpkgs/blob/master/pkgs/applications/misc/kitty/default.nix>`_,
`Gentoo <https://packages.gentoo.org/packages/x11-terms/kitty>`_,
`Fedora <https://copr.fedorainfracloud.org/coprs/gagbo/kitty-latest/>`_,
`Void Linux <https://github.com/void-linux/void-packages/blob/master/srcpkgs/kitty/template>`_.

See :doc:`Configuring kitty <conf>` for help on configuring |kitty| and
:doc:`Invocation <invocation>` for the command line arguments |kitty| supports.


.. contents::


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
relatively less effort.

Tabs and Windows
-------------------

|kitty| is capable of running multiple programs organized into tabs and
windows. The top level of organization is the *Tab*. Each tab consists
of one or more *windows*. The windows can be arranged in multiple
different layouts, like windows are organized in a tiling window
manager. The keyboard controls (which are all customizable) for tabs and
windows are:

Scrolling
~~~~~~~~~~~~~~

========================    =======================
Action                      Shortcut
========================    =======================
Scroll line up              :sc:`scroll_line_up` (also :kbd:`⌥+⌘+⇞` and :kbd:`⌘+↑` on macOS)
Scroll line down            :sc:`scroll_line_down` (also :kbd:`⌥+⌘+⇟` and :kbd:`⌘+↓` on macOS)
Scroll page up              :sc:`scroll_page_up` (also :kbd:`⌘+⇞` on macOS)
Scroll page down            :sc:`scroll_page_down` (also :kbd:`⌘+⇟` on macOS)
Scroll to top               :sc:`scroll_home` (also :kbd:`⌘+↖` on macOS)
Scroll to bottom            :sc:`scroll_end` (also :kbd:`⌘+↘` on macOS)
========================    =======================

Tabs
~~~~~~~~~~~

========================    =======================
Action                      Shortcut
========================    =======================
New tab                     :sc:`new_tab` (also :kbd:`⌘+t` on macOS)
Close tab                   :sc:`close_tab` (also :kbd:`⌘+w` on macOS)
Next tab                    :sc:`next_tab` (also :kbd:`^+⇥` and :kbd:`⇧+⌘+]` on macOS)
Previous tab                :sc:`previous_tab` (also :kbd:`⇧+^+⇥` and :kbd:`⇧+⌘+[` on macOS)
Next layout                 :sc:`next_layout`
Move tab forward            :sc:`move_tab_forward`
Move tab backward           :sc:`move_tab_backward`
Set tab title               :sc:`set_tab_title` (also :kbd:`⇧+⌘+i` on macOS)
========================    =======================


Windows
~~~~~~~~~~~~~~~~~~

========================    =======================
Action                      Shortcut
========================    =======================
New window                  :sc:`new_window` (also :kbd:`⌘+↩` on macOS)
New OS window               :sc:`new_os_window` (also :kbd:`⌘+n` on macOS)
Close window                :sc:`close_window` (also :kbd:`⇧+⌘+d` on macOS)
Next window                 :sc:`next_window`
Previous window             :sc:`previous_window`
Move window forward         :sc:`move_window_forward`
Move window backward        :sc:`move_window_backward`
Move window to top          :sc:`move_window_to_top`
Focus specific window       :sc:`first_window`, :sc:`second_window` ... :sc:`tenth_window`
                            (also :kbd:`⌘+1`, :kbd:`⌘+2` ... :kbd:`⌘+9` on macOS)
                            (clockwise from the top-left)
========================    =======================

Additionally, you can define shortcuts in :file:`kitty.conf` to focus neighboring
windows and move windows around (similar to window movement in vim)::

   map ctrl+left neighboring_window left
   map shift+left move_window right
   map ctrl+down neighboring_window down
   map shift+down move_window up
   ...

You can also define a shortcut to switch to the previously active window::

   map ctrl+p nth_window -1

``nth_window`` will focus the nth window for positive numbers and the
previously active windows for negative numbers.


Other keyboard shortcuts
----------------------------------

==================================  =======================
Action                              Shortcut
==================================  =======================
Copy to clipboard                   :sc:`copy_to_clipboard` (also :kbd:`⌘+c` on macOS)
Paste from clipboard                :sc:`paste_from_clipboard` (also :kbd:`⌘+v` on macOS)
Paste from selection                :sc:`paste_from_selection`
Increase font size                  :sc:`increase_font_size` (also :kbd:`⌘++` on macOS)
Decrease font size                  :sc:`decrease_font_size` (also :kbd:`⌘+-` on macOS)
Restore font size                   :sc:`reset_font_size` (also :kbd:`⌘+0` on macOS)
Toggle fullscreen                   :sc:`toggle_fullscreen` (also :kbd:`^+⌘+f` on macOS)
Input unicode character             :sc:`input_unicode_character`
Click URL using the keyboard        :sc:`open_url`
Reset the terminal                  :sc:`reset_terminal`
Pass current selection to program   :sc:`pass_selection_to_program`
Edit |kitty| config file            :sc:`edit_config_file`
Open a |kitty| shell                :sc:`kitty_shell`
Increase background opacity         :sc:`increase_background_opacity`
Decrease background opacity         :sc:`decrease_background_opacity`
Full background opacity             :sc:`full_background_opacity`
Reset background opacity            :sc:`reset_background_opacity`
==================================  =======================


.. _layouts:

Layouts
----------

A layout is an arrangement of multiple *windows*. You can create a new window
using the :sc:`new_window` key combination.

Currently, there are five layouts available,

* **Stack** -- Only a single maximized window is shown at a time
* **Tall** -- One window is shown full height on the left, the rest of the windows are shown one below the other on the right
* **Fat** -- One window is shown full width on the top, the rest of the windows are shown side-by-side on the bottom
* **Grid** -- All windows are shown in a grid
* **Horizontal** -- All windows are shown side-by-side
* **Vertical** -- All windows are shown one below the other

You can switch between layouts using the :sc:`next_layout` key combination. You can
also create shortcuts to select particular layouts, and choose which layouts
you want to enable/disable, see :ref:`conf-kitty-shortcuts.layout` for examples.

You can resize windows inside layouts. Press :sc:`start_resizing_window` (also :kbd:`⌘+r` on macOS) to
enter resizing mode and follow the on-screen instructions.  In a given window
layout only some operations may be possible for a particular window. For
example, in the Tall layout you can make the first window wider/narrower, but
not taller/shorter. Note that what you are resizing is actually not a window,
but a row/column in the layout, all windows in that row/column will be resized.

You can also define shortcuts in :file:`kitty.conf` to make the active window
wider, narrower, taller, or shorter by mapping to the ``resize_window``
action, for example::

   map ctrl+left resize_window narrower
   map ctrl+right resize_window wider
   map ctrl+up resize_window taller
   map ctrl+down resize_window shorter 3

The ``resize_window`` action has a second, optional argument to control
the resizing increment (a positive integer that defaults to 1).


Some layouts take options to control their behavior. For example, the ``fat``
and ``tall`` layouts accept the ``bias`` option to control how the available
space is split up. To specify the option, in :opt:`kitty.conf <enabled_layouts>` use::

    enabled_layouts tall:bias=70

This will make the tall window occupy ``70%`` of available width. ``bias`` can be
any number between 10 and 90.

Writing a new layout only requires about a hundred lines of code, so if there
is some layout you want, take a look at `layout.py
<https://github.com/kovidgoyal/kitty/blob/master/kitty/layout.py>`_  and submit
a pull request!

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
    filenames, words, lines, etc from the terminal screen.


:doc:`Panel <kittens/panel>`
    Draw a GPU accelerated dock panel on your desktop showing the output
    from an arbitrary terminal program.

:doc:`Clipboard <kittens/clipboard>`
    Copy/paste to the clipboard from shell scripts, even over SSH.

You can also :doc:`Learn to create your own kittens <kittens/custom>`.


Configuring kitty
-------------------

|kitty| is highly configurable, everything from keyboard shortcuts to
painting frames-per-second. For details and a sample :file:`kitty.conf`,
see the :doc:`configuration docs <conf>`.


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
    launch env FOO=BAR vim
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
    launch sh
    # Make the current window the active (focused) window
    focus
    launch emacs


Mouse features
-------------------

* You can hold down :kbd:`ctrl+shift` and click on a URL to open it in a browser.
* You can double click to select a word and then drag to select more words.
* You can triple click to select a line and then drag to select more lines.
* You can right click to extend a previous selection.
* You can hold down :kbd:`ctrl+alt` and drag with the mouse to select in
  columns.
* Selecting text automatically copies it to the primary clipboard (on
  platforms with a primary clipboard).


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

   map f1 pipe @ansi window less +G -R

Would open the scrollback buffer in a new window when you press the :kbd:`F1`
key. See :sc:`show_scrollback` for details.

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

Frequently Asked Questions
---------------------------------

The list of Frequently Asked Questions (*FAQ*) is :doc:`available here <faq>`.

.. _completion:

Completion for kitty
---------------------------------

|kitty| comes with completion for the ``kitty`` command for popular shells.


bash
~~~~~~~~

Add the following to your :file:`~/.bashrc`

.. code-block:: sh

   source <(kitty + complete setup bash)


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

Add the following to your :file:`~/.config/fish/config.fish`

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
