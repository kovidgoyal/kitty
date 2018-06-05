kitty-diff - A fast side-by-side diff tool with syntax highlighting and images
================================================================================

.. highlight:: sh

Major Features
-----------------

.. container:: major-features

    * Displays diffs side-by-side in the kitty terminal

    * Does syntax highlighting of the displayed diffs, asynchronously, for maximum
      speed

    * Displays images as well as text diffs, even over SSH

    * Does recursive directory diffing


.. figure:: ../screenshots/diff.png
   :alt: Screenshot, showing a sample diff
   :align: center
   :scale: 100%

   Screenshot, showing a sample diff

.. contents::


Installation
---------------

Simply install :ref:`kitty <quickstart>`.  You also need
to have either the `git <https://git-scm.com/>`_ program or the ``diff`` program
installed. Additionally, for syntax highlighting to work,
`pygments <http://pygments.org/>`_ must be installed (note that pygments is
included in the macOS kitty app).


Usage
--------

In the kitty terminal, run::

    kitty +kitten diff file1 file2

to see the diff between file1 and file2.

Create an alias in your shell's startup file to shorten the command, for example:

.. code-block:: sh

    alias d="kitty +kitten diff"

Now all you need to do to diff two files is::

    d file1 file2

You can also pass directories instead of files to see the recursive diff of the
directory contents.


Keyboard controls
----------------------

=========================   ===========================
Action                      Shortcut
=========================   ===========================
Quit                        ``q, Ctrl+c``
Scroll line up              ``k, up``
Scroll line down            ``j, down``
Scroll page up              ``PgUp``
Scroll page down            ``PgDn``
Scroll to top               ``Home``
Scroll to bottom            ``End``
Scroll to next page         ``Space, PgDn``
Scroll to previous page     ``PgUp``
Scroll to next change       ``n``
Scroll to previous change   ``p``
Increase lines of context   ``+``
Decrease lines of context   ``-``
All lines of context        ``a``
Restore default context     ``=``
=========================   ===========================



Configuration
------------------------

You can configure the colors used, keyboard shortcuts, the diff implementation,
the default lines of context, etc.  by creating a :file:`diff.conf` file in
your :ref:`kitty config folder <confloc>`. See below for the supported
configuration directives.


.. include:: /generated/conf-kitten-diff.rst


Integrating with git
-----------------------

Add the following to `~/.gitconfig`:

.. code-block:: ini

    [diff]
        tool = kitty
        guitool = kitty.gui
    [difftool]
        prompt = false
        trustExitCode = true
    [difftool "kitty"]
        cmd = kitty +kitten diff $LOCAL $REMOTE
    [difftool "kitty.gui"]
        cmd = kitty kitty +kitten diff $LOCAL $REMOTE

Now to use kitty-diff to view git diffs, you can simply do::

    git difftool --no-symlinks --dir-diff

Once again, creating an alias for this command is useful.

Command Line Interface
-------------------------

.. include:: /generated/cli-kitten-diff.rst


Why does this work only in kitty?
----------------------------------------

The diff kitten makes use of various features that are :doc:`kitty only
</protocol-extensions>`,  such as the :doc:`kitty graphics protocol
</graphics-protocol>`, the :ref:`extended keyboard protocol
<extended-key-protocol>`, etc. It also leverages terminal program
infrastructure I created for all of kitty's other kittens to reduce the amount
of code needed (the entire implementation is under 2000 lines of code).

And fundamentally, it's kitty only because I wrote it for myself, and I am
highly unlikely to use any other terminals :)


Sample diff.conf
-----------------

Below is a sample :file:`diff.conf` with all default settings.

.. include:: /generated/conf-kitten-diff-literal.rst
