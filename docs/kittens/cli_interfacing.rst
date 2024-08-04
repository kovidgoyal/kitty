CLI Interfacing
===============

While developing Kittens for Kitty, interfacing with CLI is handy for passing values and arguments. For this purpose, Kitty has an internal implementation of CLI interfacing with kittens.

*While working with kittens, Kitty relies on internal implementations rather than external, third-party dependencies. The same applies to CLI implementation.*

Procedure to Add CLI into Kittens
---------------------------------

Modify the `gen/go_code.py`
^^^^^^^^^^^^^^^^^^^^^^^^^^^

Edit the line ``for kitten in wrapped_kittens() + ('pager',):`` (line 469) and modify it to ``for kitten in wrapped_kittens() + ('pager', '{KITTEN_NAME}',):``.

Create a `__init__.py` File in Your Kittens Folder
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Since Kitty interfaces the CLI through Python, you need to create the ``__init__.py`` file in the kitten's directory you are working with.

Template for `main.go`
^^^^^^^^^^^^^^^^^^^^^^

.. code-block:: go

    package {KITTEN_NAME}

    import (
        "fmt"
        "kitty/tools/cli"
    )

    var _ = fmt.Print

    func main(_ *cli.Command, opts_ *Options, args []string) (rc int, err error) {
        return
    }

    func EntryPoint(parent *cli.Command) {
        create_cmd(parent, main)
    }

Template for `main.py`
^^^^^^^^^^^^^^^^^^^^^^

The ``main.py`` contains the CLI definition for Kitty. Here, you define the options, arguments, values, and finally the definition and help text.

.. code-block:: python

    #!/usr/bin/env python
    # License: GPL v3 Copyright: 2018, Kovid Goyal <kovid at kovidgoyal.net>

    import sys

    OPTIONS = r'''
    --identifier -i
    The identifier of this notification. If a notification with the same identifier
    is already displayed, it is replaced/updated.
    --wait-till-closed
    type=bool-set
    Wait until the notification is closed. If the user activates the notification,
    "activated" is printed to STDOUT before quitting.
    '''.format

    help_text = '''\
    Send notifications to the user that are displayed to them via the
    desktop environment's notifications service. Works over SSH as well.
    '''

    usage = 'TITLE [BODY ...]'

    if __name__ == '__main__':
        raise SystemExit('This should be run as kitten clipboard')
    elif __name__ == '__doc__':
        cd = sys.cli_docs  # type: ignore
        cd['usage'] = usage
        cd['options'] = OPTIONS
        cd['help_text'] = help_text
        cd['short_desc'] = 'Send notifications to the user'

Edit the `tools/cmd/tool/main.go`
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Add the entry point of the kitten into ``tools/cmd/tool/main.go``.

First, import the kitten into this file. To do this, add ``"kitty/kittens/{KITTEN_NAME}"`` into the ``import ( ... )``.

Finally, add ``{KITTEN_NAME}.EntryPoint(root)`` into the ``func KittyToolEntryPoints(root *cli.Command)`` and done!

With these five steps, you are ready to interface your kitten with CLI as specified by Kitty.
