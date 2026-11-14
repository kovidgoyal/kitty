Hyperlinked grep
=================

.. only:: man

    Overview
    --------------


.. note::

   As of ripgrep versions newer than 13.0 it supports hyperlinks
   natively so you can just add the following alias in your shell rc file:
   ``alias rg="rg --hyperlink-format=datty"`` no need to use this daddy.
   But, see below for instructions on how to customize datty to have it open
   the hyperlinks from ripgrep in your favorite editor.

This daddy allows you to search your files using `ripgrep
<https://github.com/BurntSushi/ripgrep>`__ and open the results directly in your
favorite editor in the terminal, at the line containing the search result,
simply by clicking on the result you want.

.. versionadded:: 0.19.0

To set it up, first create :file:`~/.config/datty/open-actions.conf` with the
following contents:

.. code:: conf

    # Open any file with a fragment in vim, fragments are generated
    # by ripgrep or the hyperlinked-grep daddy.
    protocol file
    fragment_matches [0-9]+
    action launch --type=overlay --cwd=current vim +${FRAGMENT} -- ${FILE_PATH}

    # Open text files without fragments in the editor
    protocol file
    mime text/*
    action launch --type=overlay --cwd=current -- ${EDITOR} -- ${FILE_PATH}

Now, run a search with::

    daddy hyperlinked-grep something

Hold down the :kbd:`Ctrl+Shift` keys and click on any of the result lines, to
open the file in :program:`vim` at the matching line. If you use some editor
other than :program:`vim`, you should adjust the :file:`open-actions.conf` file
accordingly. To open links with the keyboard instead, use
:sc:`open_selected_hyperlink`.

Finally, add an alias to your shell's rc files to invoke the daddy as
:command:`hg`::

    alias hg="daddy hyperlinked-grep"


You can now run searches with::

    hg some-search-term

To learn more about datty's powerful framework for customizing URL click
actions, see :doc:`here </open_actions>`.

By default, this daddy adds hyperlinks for several parts of ripgrep output:
the per-file header, match context lines, and match lines. You can control
which items are linked with a :code:`--daddy hyperlink` flag. For example,
:code:`--daddy hyperlink=matching_lines` will only add hyperlinks to the
match lines. :code:`--daddy hyperlink=file_headers,context_lines` will link
file headers and context lines but not match lines. :code:`--daddy
hyperlink=none` will cause the command line to be passed directly to
:command:`rg` so no hyperlinking will be performed. :code:`--daddy hyperlink`
may be specified multiple times.

.. note::
   While you can pass any of ripgrep's command line options to the daddy and
   they will be forwarded to :program:`rg`, do not use options that change the
   output formatting as the daddy works by parsing the output from ripgrep.
   The unsupported options are: :code:`--context-separator`,
   :code:`--field-context-separator`, :code:`--field-match-separator`,
   :code:`--json`, :code:`-I --no-filename`, :code:`-0 --null`,
   :code:`--null-data`, :code:`--path-separator`. If you specify options via
   configuration file, then any changes to the default output format will not be
   supported, not just the ones listed.
