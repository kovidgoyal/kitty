Hints
==========

|kitty| has a *hints mode* to select and act on arbitrary text snippets currently
visible on the screen.  For example, you can press :sc:`open_url`
to choose any URL visible on the screen and then open it using your system
browser.

.. figure:: ../screenshots/hints_mode.png
    :alt: URL hints mode
    :align: center
    :scale: 100%

    URL hints mode

Similarly, you can press :sc:`insert_selected_path` to
select anything that looks like a path or filename and then insert it into the
terminal, very useful for picking files from the output of a ``git`` or ``ls`` command and
adding them to the command line for the next command.

The hints kitten is very powerful to see more detailed help on its various
options and modes of operation, see below. You can use these options to
create mappings in :file:`kitty.conf` to select various different text
snippets. See :sc:`insert_selected_path` for examples.

Command Line Interface
-------------------------

.. include:: ../generated/cli-kitten-hints.rst
