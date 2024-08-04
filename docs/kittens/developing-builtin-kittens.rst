Developing builtin kittens
=============================

Builtin kittens in kitty are written in the Go language, with small Python
wrapper scripts to define command line options and handle UI integration.

Getting started
-----------------------

To get started with creating a builtin kitten, one that will become part of kitty
and be available as ``kitten my-kitten``, create a directory named
:file:`my_kitten` in the :file:`kittens` directory. Then, in this directory
add three, files: :file:`__init__.py` (an empty file), :file:`__main__.py` and
:file:`main.go`.

Template for `main.py`
^^^^^^^^^^^^^^^^^^^^^^

The file :file:`main.py` contains the command line option definitions for your kitten. Change the actual options and help text below as needed.

.. code-block:: python

    #!/usr/bin/env python
    # License: GPL v3 Copyright: 2018, Kovid Goyal <kovid at kovidgoyal.net>

    import sys

    # See the file kitty/cli.py in the kitty sourcecode for more examples of
    # the syntax for defining options
    OPTIONS = r'''
    --some-string-option -s
    default=my_default_value
    Help text for a simple option taking a string value.


    --some-boolean-option -b
    type=bool-set
    Help text for a boolean option defaulting to false.


    --some-inverted-boolean-option
    type=bool-unset
    Help text for a boolean option defaulting to true.


    --an-integer-option
    type=int
    default=13
    bla bla


    --an-enum-option
    choices=a,b,c,d
    default=a
    This option can only take the values a, b, c, or d
    '''.format

    help_text = '''\
    The introductory help text for your kitten.

    Can contain multiple paragraphs with :bold:`bold`
    :green:`colored`, :code:`code`, :link:`links <http://url>` etc.
    formatting.

    Option help strings can also use this formatting.
    '''

    # The usage string for your kitten
    usage = 'TITLE [BODY ...]'
    short_description = 'some short description of your kitten it will show up when running kitten without arguments to list all kittens`

    if __name__ == '__main__':
        raise SystemExit('This should be run as kitten my-kitten')
    elif __name__ == '__doc__':
        cd = sys.cli_docs  # type: ignore
        cd['usage'] = usage
        cd['options'] = OPTIONS
        cd['help_text'] = help_text
        cd['short_desc'] = short_description


Template for `main.go`
^^^^^^^^^^^^^^^^^^^^^^

.. code-block:: go

    package my_kitten

    import (
        "fmt"

        "kitty/tools/cli"
    )

    var _ = fmt.Print

    func main(_ *cli.Command, opts *Options, args []string) (rc int, err error) {
        // Here rc is the exit code for the kitten which should be 1 or higher if err is not nil
        fmt.Println("Hello world!")
        fmt.Println(args)
        fmt.Println(fmt.Sprintf("%#v", opts))
        return
    }

    func EntryPoint(parent *cli.Command) {
        create_cmd(parent, main)
    }

Edit :file:`tools/cmd/tool/main.go`
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Add the entry point of the kitten into :file:`tools/cmd/tool/main.go`.

First, import the kitten into this file. To do this, add :code:`"kitty/kittens/my_kitten"` into the :code:`import ( ... )` section at the top.
Then, add ``my_kitten.EntryPoint(root)`` into ``func KittyToolEntryPoints(root *cli.Command)`` and you are done. After running make you should
be able to test your kitten by running::

    kitten my-kitten

