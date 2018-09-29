Frequently Asked Questions
==============================

.. highlight:: sh

.. contents::

Some special symbols are rendered small/truncated in kitty?
-----------------------------------------------------------------

The number of cells a unicode character takes up are controlled by the unicode
standard.  All characters are rendered in a single cell unless the unicode
standard says they should be rendered in two cells. When a symbol does not fit,
it will either be rescaled to be smaller or truncated (depending on how much
extra space it needs). This is often different from other terminals which just
let the character overflow into neighboring cells, which is fine if the
neighboring cell is empty, but looks terrible if it is not.

Some programs, like powerline, vim with fancy gutter symbols/status-bar, etc.
misuse unicode characters from the private use area to represent symbols. Often
these symbols are square and should be rendered in two cells.  However, since
private use area symbols all have their width set to one in the unicode
standard, |kitty| renders them either smaller or truncated. The exception is if
these characters are followed by a space or empty cell in which case kitty
makes use of the extra cell to render them in two cells.


Using a color theme with a background color does not work well in vim?
-----------------------------------------------------------------------

First make sure you have not changed the TERM environment variable, it should
be ``xterm-kitty``. vim uses *background color erase* even if the terminfo file
does not contain the ``bce`` capability. This is a bug in vim. You can work around
it by adding the following to your vimrc::

    let &t_ut=''

See :ref:`here <ext_styles>` for why |kitty| does not support background color erase.


I get errors about the terminal being unknown or opening the terminal failing when SSHing into a different computer?
-----------------------------------------------------------------------------------------------------------------------

This happens because the |kitty| terminfo files are not available on the server.
You can ssh in using the following command which will automatically copy the
terminfo files to the server::

    kitty +kitten ssh myserver

If for some reason that does not work (typically because the server is using a
a non POSIX compliant shell), you can use the following one-liner instead (it
is slower as it needs to ssh into the server twice, but will work with most
servers)::

    infocmp xterm-kitty | ssh myserver tic -x -o \~/.terminfo /dev/stdin

Really, the correct solution for this is to convince the OpenSSH maintainers to
have ssh do this automatically when connecting to a server, so that all
terminals work transparently.


How do I change the colors in a running kitty instance?
------------------------------------------------------------

You can either use the
`OSC terminal escape codes <http://invisible-island.net/xterm/ctlseqs/ctlseqs.html#h2-Operating-System-Commands>`_
to set colors or you can enable :doc:`remote control <remote-control>`
for |kitty| and use :ref:`at_set-colors`.


How do I specify command line options for kitty on macOS?
---------------------------------------------------------------

Apple does not want you to use command line options with GUI applications. To
workaround that limitation, |kitty| will read command line options from the file
:file:`<kitty config dir>/macos-launch-services-cmdline` when it is launched
from the GUI, i.e. by clicking the |kitty| application icon or using ``open -a kitty``.
Note that this file is *only read* when running via the GUI.

You can, of course, also run |kitty| from a terminal with command line options, using:
:file:`/Applications/kitty.app/Contents/MacOS/kitty`.

And within |kitty| itself, you can always run |kitty| using just `kitty` as it
cleverly adds itself to the ``PATH``.


kitty is not able to use my favorite font?
---------------------------------------------

|kitty| achieves its stellar performance by caching alpha masks of each rendered
character on the GPU, so that every character needs to be rendered only once.
This means it is a strictly character cell based display.  As such it can use
only monospace fonts, since every cell in the grid has to be the same size. If
your font is not listed in ``kitty list-fonts`` it means that it is not
monospace. On Linux you can list all monospace fonts with::

    fc-list : family spacing | grep spacing=100


How can I assign a single global shortcut to bring up the kitty terminal?
-----------------------------------------------------------------------------

Bringing up applications on a single key press is the job of the window
manager/desktop environment. For ways to do it with kitty (or indeed any
terminal) in different environments,
see `here <https://github.com/kovidgoyal/kitty/issues/45>`_.
