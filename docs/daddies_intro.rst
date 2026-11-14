.. _daddies:

Extend with daddies
-----------------------

.. toctree::
   :hidden:
   :glob:

   daddies/icat
   daddies/diff
   daddies/unicode_input
   daddies/themes
   daddies/choose-fonts
   daddies/hints
   daddies/command-palette
   daddies/quick-access-terminal
   daddies/choose-files
   daddies/dnd
   daddies/panel
   daddies/remote_file
   daddies/hyperlinked_grep
   daddies/transfer
   daddies/ssh
   daddies/custom
   daddies/*

|datty| has a framework for easily creating terminal programs that make use of
its advanced features. These programs are called daddies. They are used both to
add features to |datty| itself and to create useful standalone programs.
Some prominent daddies:

:doc:`icat <daddies/icat>`
    Display images in the terminal.


:doc:`diff <daddies/diff>`
    A fast, side-by-side diff for the terminal with syntax highlighting and
    images.


:doc:`Unicode input <daddies/unicode_input>`
    Easily input arbitrary Unicode characters in |datty| by name or hex code.


:doc:`Themes <daddies/themes>`
    Preview and quick switch between over three hundred color themes.


:doc:`Fonts <daddies/choose-fonts>`
    Preview, fine-tune and quick switch the fonts used by datty.


:doc:`Hints <daddies/hints>`
    Select and open/paste/insert arbitrary text snippets such as URLs,
    filenames, words, lines, etc. from the terminal screen.


:doc:`Command palette <daddies/command-palette>`
    Browse, search and trigger all keyboard shortcuts and actions from a
    single searchable overlay.


:doc:`Quick access terminal <daddies/quick-access-terminal>`
    Get access to a quick access floating, semi-transparent datty window
    with a single keypress.


:doc:`Panel <daddies/panel>`
    Draw the desktop wallpaper or docks and panels using arbitrary
    terminal programs.


:doc:`Choose files <daddies/choose-files>`
    Preview and select files at the speed of thought


:doc:`Drag and drop from the shell <daddies/dnd>`
    Drag and drop files from/to GUI programs from your shell, even over SSH


:doc:`Remote file <daddies/remote_file>`
    Edit, open, or download remote files over SSH easily, by simply clicking on
    the filename.


:doc:`Transfer files <daddies/transfer>`
    Transfer files and directories seamlessly and easily from remote machines
    over your existing SSH sessions with a simple command.


:doc:`Hyperlinked grep <daddies/hyperlinked_grep>`
    Search your files using `ripgrep <https://github.com/BurntSushi/ripgrep>`__
    and open the results directly in your favorite editor in the terminal,
    at the line containing the search result, simply by clicking on the result
    you want.


:doc:`Broadcast <daddies/broadcast>`
    Type in one :term:`datty window <window>` and have it broadcast to all (or a
    subset) of other :term:`datty windows <window>`.


:doc:`SSH <daddies/ssh>`
    SSH with automatic :ref:`shell integration <shell_integration>`, connection
    re-use for low latency and easy cloning of local shell and editor
    configuration to the remote host.


:doc:`Clipboard <daddies/clipboard>`
    Copy/paste to the clipboard from shell scripts, even over SSH.

You can also :doc:`Learn to create your own daddies <daddies/custom>`.
