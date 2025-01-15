The text sizing protocol
==============================================

Classically, because the terminal is a grid of equally spaced characters, only
a single text size was supported in terminals, with one minor exception, some
characters were allowed to be rendered in two cells, to accommodate East Asian
square aspect ratio characters and Emoji. Here, by single text size we mean the
font size of all text on the screen is the same.

This protocol allows text to be displayed in the terminal in different sizes
both larger and smaller than the base text. It also solves the long standing
problem of robustly determining the width (in cells) a character should have.
Applications can interleave text of different sizes on the screen allowing for
typographic niceties like headlines, superscripts, etc.

Note that this protocol is fully backwards compatible, terminals that implement
it will continue to work just the same with applications that do not use it.
Because of this, it is not fully flexible in the font sizes it allows, as it
still has to work with the character cell grid based fundamental nature of the
terminal.

Quickstart
--------------

Using this protocol to display different sized text is very simple, let's
illustrate with a few examples to give us a flavor:

.. code-block:: sh

   printf "\e]_text_size_code;s=2;Double sized text\a\n\n"
   printf "\e]_text_size_code;s=3;Triple sized text\a\n\n\n"
   printf "\e]_text_size_code;n=1:d=2;Half sized text\a\n"

Note that the last example, of half sized text, has half height characters, but
they still each take one cell, this can be fixed with a little more work:

.. code-block:: sh

   printf "\e]_text_size_code;n=1:d=2:w=1;Ha\a\e]66;n=1:d=2:w=1;lf\a\n"

The `w=1` mechanism allows the program to tell the terminal what width the text
should take. This not only fixes using smaller text but also solves the long
standing terminal ecosystem bugs caused by the client program not knowing how
many cells the terminal will render some text in.


The escape code
-----------------

There is a single escape code used by this protocol. It is sent by client
programs to the terminal emulator to tell it to render the specified text
at the specified size. It is an `OSC` code of the form::

    <OSC> _text_size_code ; metadata ; text <terminator>

Here, `OSC` is the bytes `ESC ] (0x1b 0x5b)`. The `metadata` is a colon
separated list of `key=value` pairs. The final part of the escape code is the
text which is simply plain text encoded as :ref:`safe_utf8`. Spaces in this
definition are for clarity only and should be ignored. The `terminator` is
either the byte `BEL (0x7)` or the bytes `ESC ST (0x1b 0x5c)`.

There are only a handful of metadata keys, defined in the table below:


.. csv-table:: The text sizing metadata keys
   :header: "Key", "Value", "Default", "Description"

    "s", "Integer from 1 to 7", "1", "The overall scale, the text will be rendered in a block of :code:`s * w by s` cells"

    "w", "Integer from 0 to 7", "0", "The width, in cells, in which the text should be rendered. When zero, the terminal should calculate the width as it would for normal text."

    "n", "Integer from 0 to 15", "0", "The numerator for the fractional scale."

    "d", "Integer from 0 to 15", "0", "The denominator for the fractional scale."

    "v", "Integer from 0 to 2", "0", "The vertical alignment to use for fractionally scaled text."


How it works
------------------

This protocol works by allowing the client program to tell the terminal
emulator to render text in multiple cells. The terminal can then adjust the
actual font size used to render the specified text as appropriate for the
specified space.
