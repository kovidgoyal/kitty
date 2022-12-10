Hyperlinked grep
=================

This kitten allows you to search your files using `ripgrep
<https://github.com/BurntSushi/ripgrep>`__ and open the results directly in your
favorite editor in the terminal, at the line containing the search result,
simply by clicking on the result you want.

.. versionadded:: 0.19.0

To set it up, first create :file:`~/.config/kitty/open-actions.conf` with the
following contents:

.. code:: conf

    # Open any file with a fragment in vim, fragments are generated
    # by the hyperlink_grep kitten and nothing else so far.
    protocol file
    fragment_matches [0-9]+
    action launch --type=overlay --cwd=current vim +${FRAGMENT} ${FILE_PATH}

    # Open text files without fragments in the editor
    protocol file
    mime text/*
    action launch --type=overlay --cwd=current ${EDITOR} ${FILE_PATH}

Now, run a search with::

    kitty +kitten hyperlinked_grep something

Hold down the :kbd:`Ctrl+Shift` keys and click on any of the result lines, to
open the file in :program:`vim` at the matching line. If you use some editor
other than :program:`vim`, you should adjust the :file:`open-actions.conf` file
accordingly.

Finally, add an alias to your shell's rc files to invoke the kitten as
:command:`hg`::

    alias hg="kitty +kitten hyperlinked_grep"


You can now run searches with::

    hg some-search-term

To learn more about kitty's powerful framework for customizing URL click
actions, see :doc:`here </open_actions>`.

By default, this kitten adds hyperlinks for several parts of ripgrep output:
the per-file header, match context lines, and match lines. You can control
which items are linked with a :code:`--kitten hyperlink` flag. For example,
:code:`--kitten hyperlink=matching_lines` will only add hyperlinks to the
match lines. :code:`--kitten hyperlink=file_headers,context_lines` will link
file headers and context lines but not match lines. :code:`--kitten
hyperlink=none` will cause the command line to be passed to directly to
:command:`rg` so no hyperlinking will be performed. :code:`--kitten hyperlink`
may be specified multiple times.

Hopefully, someday this functionality will make it into some `upstream grep
<https://github.com/BurntSushi/ripgrep/issues/665>`__ program directly removing
the need for this kitten.


.. note::
   While you can pass any of ripgrep's comand line options to the kitten and
   they will be forwarded to :program:`rg`, do not use options that change the
   output formatting as the kitten works by parsing the output from ripgrep.
   The unsupported options are: :code:`--context-separator`,
   :code:`--field-context-separator`, :code:`--field-match-separator`,
   :code:`--json`, :code:`-I --no-filename`, :code:`-0 --null`,
   :code:`--null-data`, :code:`--path-separator`. If you specify options via
   configuration file, then any changes to the default output format will not be
   supported, not just the ones listed.
