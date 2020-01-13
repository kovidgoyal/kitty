Marks
=================


kitty has the ability to mark text on the screen based on regular expressions.
This can be useful to highlight words or phrases when browsing output from long
running programs or similar. Lets start with a few examples:

Suppose we want to be able to highlight the word ERROR in the current window.
Add the following to :file:`kitty.conf`::

    map f1 toggle_marker text 1 ERROR

Now when you press :kbd:`F1` all instances of the word :code:`ERROR` will be
highlighted. To turn off the highlighting, press :kbd:`F1` again.
If you want to make it case-insensitive, use::

    map f1 toggle_marker itext 1 ERROR

To make it match only complete words, use::

    map f1 toggle_marker regex 1 \bERROR\b

Suppose you want to highlight both :code:`ERROR` and :code:`WARNING`, case
insensitively::

    map f1 toggle_marker iregex 1 \bERROR\b 2 \bWARNING\b

kitty supports up to 3 mark groups (the numbers in the commands above). You
can control the colors used for these groups in :file:`kitty.conf` with::

    mark1_foreground red
    mark1_background gray
    mark2_foreground green
    ...


.. note::
    For performance reasons, matching is done per line only, and only when that line is
    altered in anyway. So you cannot match text that stretches across multiple
    lines.


The full syntax for creating marks
-------------------------------------

The syntax of the :code:`toggle_marker` command is::

    toggle_marker <marker-type> <specification>

Here :code:`marker-type` is one of:

    * :code:`text` - simple substring matching
    * :code:`itext` - case-insensitive substring matching
    * :code:`regex` - A python regular expression
    * :code:`iregex` - A case-insensitive python regular expression
    * :code:`function` - An arbitrary function defined in a python file, see
      :ref:`marker_funcs`.

.. _marker_funcs:

Arbitrary marker functions
-----------------------------

You can create your own marker functions. Create a python file named
:file:`mymarker.py` and in it create a :code:`marker` function. This
function receives the text of the line as input and must yield three numbers,
the starting character position, the ending character position and the mark
group (1-3). For example:

.. code-block::

    def marker(text):
        # Function to highlight the letter X
        for i, ch in enumerate(text):
            if ch.lower() == 'x':
                yield i, i, 3


Save this file somewhere and in :file:`kitty.conf`, use::

    map f1 toggle_marker function /path/to/mymarker.py

If you save the file in the kitty config directory, you can use::

    map f1 toggle_marker function mymarker.py
