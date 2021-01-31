Hyperlinked grep
=================


This kitten allows you to search your files using `ripgrep
<https://www.google.com/search?q=ripgrep>`_ and open the results
directly in your favorite editor in the terminal, at the line containing
the search result, simply by clicking on the result you want.

.. versionadded:: 0.19.0

To set it up, first create :file:`~/.config/kitty/open-actions.conf` with the
following contents:

.. code:: conf

    # Open any file with a fragment in vim, fragments are generated
    # by the hyperlink_grep kitten and nothing else so far.
    protocol file
    fragment_matches [0-9]+
    action launch --type=overlay vim +${FRAGMENT} ${FILE_PATH}

    # Open text files without fragments in the editor
    protocol file
    mime text/*
    action launch --type=overlay ${EDITOR} ${FILE_PATH}


Now, run a search with::

    kitty +kitten hyperlinked_grep something

Hold down the :kbd:`ctrl+shift` keys and click on any of the
result lines, to open the file in vim at the matching line. If
you use some editor other than vim, you should adjust the
:file:`open-actions.conf` file accordingly.

Finally, add an alias to your shell's rc files to invoke the kitten as ``hg``::

    alias hg='kitty +kitten hyperlinked_grep'


You can now run searches with::

    hg some-search-term

If you want to enable completion, for the kitten, you can delegate completion
to rg. For that, instead of using an alias create a simple wrapper script named
:file:`hg` somewhere in your ``PATH``:

.. code-block:: sh

    #!/bin/sh
    exec kitty +kitten hyperlinked_grep "$@"

Then, for example, for ZSH, add the following to :file:`.zshrc`::

    compdef _rg hg

To learn more about kitty's powerful framework for customizing URL click
actions, :doc:`see here <../open_actions>`.

Hopefully, someday this functionality will make it into some `upstream grep
<https://github.com/BurntSushi/ripgrep/issues/665>`_
program directly removing the need for this kitten.


.. note::
   While you can pass any of ripgrep's comand line options to the kitten and
   they will be forwarded to rg, do not use options that change the output
   formatting as the kitten works by parsing the output from ripgrep.
