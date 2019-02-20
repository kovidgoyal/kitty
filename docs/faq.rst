Frequently Asked Questions
==============================

.. highlight:: sh

.. contents::

Some special symbols are rendered small/truncated in kitty?
-----------------------------------------------------------

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
non POSIX compliant shell), you can use the following one-liner instead (it
is slower as it needs to ssh into the server twice, but will work with most
servers)::

    infocmp xterm-kitty | ssh myserver tic -x -o \~/.terminfo /dev/stdin

If you are behind a proxy (like Balabit) that prevents this, you must redirect the
1st command to a file, copy that to the server and run ``tic`` manually.  If you
connect to a server, embedded or Android system that doesn't have ``tic``, copy over
your local file terminfo to the other system as :file:`~/.terminfo/x/xterm-kitty`.

Really, the correct solution for this is to convince the OpenSSH maintainers to
have ssh do this automatically, if possible, when connecting to a server, so that
all terminals work transparently.


Keys such as arrow keys, backspace, delete, home/end, etc. do not work when using su or sudo?
-------------------------------------------------------------------------------------------------

Make sure the TERM environment variable, is ``xterm-kitty``.  And either the
TERMINFO environment variable points to a directory containing :file:`x/xterm-kitty`
or that file is under :file:`~/.terminfo/x/`.

Note that ``sudo`` might remove TERMINFO.  Then setting it at the shell prompt can
be too late, because command line editing may not be reinitialized.  In that case
you can either ask ``sudo`` to set it or if that is not supported, insert an ``env``
command before starting the shell, or, if not possible, after sudo start another
Shell providing the right terminfo path::

    sudo … TERMINFO=$HOME/.terminfo bash -i
    sudo … env TERMINFO=$HOME/.terminfo bash -i
    TERMINFO=/home/ORIGINALUSER/.terminfo exec bash -i

Alternatively, if you want to keep TERMINFO automatically whenever you run a ``sudo``
command, you can edit the `/etc/sudoers.d/visudo` file by executing this shell command:

    sudo visudo

Then add the following content:

    Defaults env_keep += "TERM TERMINFO"

Save the file and from now on `sudo` will correctly identify `xterm-kitty`.
This is based on the trick provided [here](https://stackoverflow.com/a/8636711/5715571),
and has been tested on Clear Linux (27910).

If you have double width characters in your prompt, you may also need to
explicitly set a UTF-8 locale, like::

    export LANG=en_US.UTF-8 LC_ALL=en_US.UTF-8


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
