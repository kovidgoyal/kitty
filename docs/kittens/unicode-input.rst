Unicode input
================

You can input unicode characters by name, hex code, recently used and even an editable favorites list.
Press :sc:`input_unicode_character` to start the unicode input widget, shown below.

.. figure:: ../screenshots/unicode.png
    :alt: A screenshot of the unicode input widget
    :align: center
    :scale: 100%

    A screenshot of the unicode input widget

In :guilabel:`Code` mode, you enter a unicode character by typing in the hex code for the
character and pressing enter, for example, type in ``2716`` and press enter to get
✖. You can also choose a character from the list of recently used characters by
typing a leading period and then the two character index and pressing Enter.
The up and down arrow keys can be used to choose the previous and next unicode
symbol respectively.

In :guilabel:`Name` mode you instead type words from the character name and use
the arrow keys/tab to select the character from the displayed matches. You can
also type a space followed by a period and the index for the match if you don't
like to use arrow keys.

You can switch between modes using either the function keys or by pressing
:kbd:`Ctrl+[` and :kbd:`Ctrl+]`.


Command Line Interface
-------------------------

.. include:: ../generated/cli-kitten-unicode_input.rst
