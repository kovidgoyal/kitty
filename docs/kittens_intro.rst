.. _kittens:

Extend with kittens
-----------------------

.. toctree::
   :hidden:
   :glob:

   kittens/icat
   kittens/diff
   kittens/unicode_input
   kittens/themes
   kittens/hints
   kittens/remote_file
   kittens/hyperlinked_grep
   kittens/transfer
   kittens/ssh
   kittens/custom
   kittens/*

|kitty| has a framework for easily creating terminal programs that make use of
its advanced features. These programs are called kittens. They are used both to
add features to |kitty| itself and to create useful standalone programs.
Some prominent kittens:

:doc:`icat <kittens/icat>`
    Display images in the terminal.


:doc:`diff <kittens/diff>`
    A fast, side-by-side diff for the terminal with syntax highlighting and
    images.


:doc:`Unicode input <kittens/unicode_input>`
    Easily input arbitrary Unicode characters in |kitty| by name or hex code.


:doc:`Themes <kittens/themes>`
    Preview and quick switch between over three hundred color themes.


:doc:`Hints <kittens/hints>`
    Select and open/paste/insert arbitrary text snippets such as URLs,
    filenames, words, lines, etc. from the terminal screen.


:doc:`Remote file <kittens/remote_file>`
    Edit, open, or download remote files over SSH easily, by simply clicking on
    the filename.


:doc:`Transfer files <kittens/transfer>`
    Transfer files and directories seamlessly and easily from remote machines
    over your existing SSH sessions with a simple command.


:doc:`Hyperlinked grep <kittens/hyperlinked_grep>`
    Search your files using `ripgrep <https://github.com/BurntSushi/ripgrep>`__
    and open the results directly in your favorite editor in the terminal,
    at the line containing the search result, simply by clicking on the result
    you want.


:doc:`Broadcast <kittens/broadcast>`
    Type in one :term:`kitty window <window>` and have it broadcast to all (or a
    subset) of other :term:`kitty windows <window>`.


:doc:`SSH <kittens/ssh>`
    SSH with automatic :ref:`shell integration <shell_integration>`, connection
    re-use for low latency and easy cloning of local shell and editor
    configuration to the remote host.


:doc:`Panel <kittens/panel>`
    Draw a GPU accelerated dock panel on your desktop showing the output from an
    arbitrary terminal program.


:doc:`Clipboard <kittens/clipboard>`
    Copy/paste to the clipboard from shell scripts, even over SSH.

You can also :doc:`Learn to create your own kittens <kittens/custom>`.
