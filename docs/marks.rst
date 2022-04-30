Mark text on screen
---------------------


kitty has the ability to mark text on the screen based on regular expressions.
This can be useful to highlight words or phrases when browsing output from long
running programs or similar. Lets start with a few examples:

Examples
----------

Suppose we want to be able to highlight the word :code:`ERROR` in the current
window. Add the following to :file:`kitty.conf`::

    map f1 toggle_marker text 1 ERROR

Now when you press :kbd:`F1`, all instances of the word :code:`ERROR` will be
highlighted. To turn off the highlighting, press :kbd:`F1` again.
If you want to make it case-insensitive, use::

    map f1 toggle_marker itext 1 ERROR

To make it match only complete words, use::

    map f1 toggle_marker regex 1 \\bERROR\\b

Suppose you want to highlight both :code:`ERROR` and :code:`WARNING`, case
insensitively::

    map f1 toggle_marker iregex 1 \\bERROR\\b 2 \\bWARNING\\b

kitty supports up to 3 mark groups (the numbers in the commands above). You
can control the colors used for these groups in :file:`kitty.conf` with::

    mark1_foreground red
    mark1_background gray
    mark2_foreground green
    ...


.. note::
    For performance reasons, matching is done per line only, and only when that
    line is altered in any way. So you cannot match text that stretches across
    multiple lines.


Creating markers dynamically
---------------------------------

If you want to create markers dynamically rather than pre-defining them in
:file:`kitty.conf`, you can do so as follows::

    map f1 create_marker
    map f2 remove_marker

Then pressing :kbd:`F1` will allow you to enter the marker definition and set it
and pressing :kbd:`F2` will remove the marker. :ac:`create_marker` accepts the
same syntax as :ac:`toggle_marker` above. Note that while creating markers, the
prompt has history so you can easily re-use previous marker expressions.

You can also use the facilities for :doc:`remote-control` to dynamically add or
remove markers.


Scrolling to marks
--------------------

kitty has a :ac:`scroll_to_mark` action to scroll to the next line that contains
a mark. You can use it by mapping it to some shortcut in :file:`kitty.conf`::

    map ctrl+p scroll_to_mark prev
    map ctrl+n scroll_to_mark next

Then pressing :kbd:`Ctrl+P` will scroll to the first line in the scrollback
buffer above the current top line that contains a mark. Pressing :kbd:`Ctrl+N`
will scroll to show the first line below the current last line that contains
a mark. If you wish to jump to a mark of a specific type, you can add that to
the mapping::

    map ctrl+1 scroll_to_mark prev 1

Which will scroll only to marks of type 1.


The full syntax for creating marks
-------------------------------------

The syntax of the :ac:`toggle_marker` action is::

    toggle_marker <marker-type> <specification>

Here :code:`marker-type` is one of:

* :code:`text` - Simple substring matching
* :code:`itext` - Case-insensitive substring matching
* :code:`regex` - A Python regular expression
* :code:`iregex` - A case-insensitive Python regular expression
* :code:`function` - An arbitrary function defined in a Python file, see :ref:`marker_funcs`.

.. _marker_funcs:

Arbitrary marker functions
-----------------------------

You can create your own marker functions. Create a Python file named
:file:`mymarker.py` and in it create a :code:`marker` function. This function
receives the text of the line as input and must yield three numbers,
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

If you save the file in the :ref:`kitty config directory <confloc>`, you can
use::

    map f1 toggle_marker function mymarker.py
