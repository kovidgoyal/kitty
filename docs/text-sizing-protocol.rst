The text sizing protocol
==============================================

.. versionadded:: 0.40.0

Classically, because the terminal is a grid of equally sized characters, only
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
terminal. Public discussion of this protocol is :iss:`here <8226>`.

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

The ``w=1`` mechanism allows the program to tell the terminal what width the text
should take. This not only fixes using smaller text but also solves the long
standing terminal ecosystem bugs caused by the client program not knowing how
many cells the terminal will render some text in.


The escape code
-----------------

There is a single escape code used by this protocol. It is sent by client
programs to the terminal emulator to tell it to render the specified text
at the specified size. It is an ``OSC`` code of the form::

    <OSC> _text_size_code ; metadata ; text <terminator>

Here, ``OSC`` is the bytes ``ESC ] (0x1b 0x5b)``. The ``metadata`` is a colon
separated list of ``key=value`` pairs. The final part of the escape code is the
text which is simply plain text encoded as :ref:`safe_utf8`. Spaces in this
definition are for clarity only and should be ignored. The ``terminator`` is
either the byte ``BEL (0x7)`` or the bytes ``ESC ST (0x1b 0x5c)``.

There are only a handful of metadata keys, defined in the table below:


.. csv-table:: The text sizing metadata keys
   :header: "Key", "Value", "Default", "Description"

    "s", "Integer from 1 to 7",  "1", "The overall scale, the text will be rendered in a block of ``s * w`` by ``s`` cells"

    "w", "Integer from 0 to 7",  "0", "The width, in cells, in which the text should be rendered. When zero, the terminal should calculate the width as it would for normal text, splitting it up into scaled cells."

    "n", "Integer from 0 to 15", "0", "The numerator for the fractional scale."

    "d", "Integer from 0 to 15", "0", "The denominator for the fractional scale. Must be ``> n`` when non-zero."

    "v", "Integer from 0 to 2",  "0", "The vertical alignment to use for fractionally scaled text. ``0`` - top, ``1`` - bottom, ``2`` - centered"


How it works
------------------

This protocol works by allowing the client program to tell the terminal to
render text in multiple cells. The terminal can then adjust the actual font
size used to render the specified text as appropriate for the specified space.

The space to render is controlled by four metadata keys, ``s (scale)``, ``w (width)``, ``n (numerator)``
and ``d (denominator)``. The most important are the ``s`` and ``w`` keys. The text
will be rendered in a block of ``s * w`` by ``s`` cells. A special case is ``w=0``
(the default), which means the terminal splits up the text into cells as it
would normally without this protocol, but now each cell is an ``s by s`` block of
cells instead. So, for example, if the text is ``abc`` and ``s=2`` the terminal would normally
split it into three cells::

    │a│b│c│

But, because ``s=2`` it instead gets split as::

    │a░│b░│c░│
    │░░│░░│░░│

The terminal multiplies the font size by ``s`` when rendering these
characters and thus ends up rendering text at twice the base size.

When ``w`` is a non-zero value, it specifies the width in scaled cells of the
following text. Note that **all** the text in that escape code must be rendered
in ``s * w`` cells. If it does not fit, the terminal is free to do whatever it
feels is best, including truncating the text or downsizing the font size when
rendering it. It is up to client applications to use the ``w`` key wisely and not
try to render too much text in too few cells. When sending a string of text
with non zero ``w`` to the terminal emulator, the way to do it is to split up the
text into chunks that fit in ``w`` cells and send one escape code per chunk. So
for the string: ``cool-🐈`` the actual escape codes would be (ignoring the header
and trailers)::

   w=1;c w=1;o w=1;o w=1;l w=1;- w=2:🐈

Note, in particular, how the last character, the cat emoji, ``🐈`` has ``w=2``.
In practice client applications can assume that terminal emulators get the
width of all ASCII characters correct and use the ``w=0`` form for efficient
transmission, so that the above becomes::

   cool- w=2:🐈

The use of non-zero ``w`` should mainly be restricted to non-ASCII characters and
when using fractional scaling, as described below.

Fractional scaling
^^^^^^^^^^^^^^^^^^^^^^^

Using the main scale parameter (``s``) gives us only 7 font sizes. Fortunately,
this protocol allows specifying fractional scaling, fractional scaling is
applied on top of the main scale specified by ``s``. It allows niceties like:

* Normal sized text but with half a line of blank space above and half a line below (``s=2:n=1:d=2:v=2``)
* Superscripts (``n=1:d=2``)
* Subscripts (``n=1:d=2:v=1``)
* ...

The fractional scale **does not** affect the number of cells the text occupies,
instead, it just adjust the rendered font size within those cells.
The fraction is specified using an integer numerator and denominator (``n`` and
``d``). In addition, by using the ``v`` key one can vertically align the
fractionally scaled text at top, bottom or middle.

When using fractional scaling one often wants to fit more than a single
character per cell. To accommodate that, there is the ``w`` key. This specifies
the number of cells in which to render the text. For example, for a superscript
one would typically split the string into pairs of characters and use the
following for each pair::

    OSC _text_size_code ; n=1:d=2:w=1 ; ab <terminator>
    ... repeat for each pair of characters


Fixing the character width issue for the terminal ecosystem
---------------------------------------------------------------------

Terminals create user interfaces using text displayed in a cell grid. For
terminal software that creates sophisticated user interfaces it is particularly
important that the client program running in the terminal and the terminal
itself agree on how many cells a particular string should be rendered in. If
the two disagree, then the entire user interface can be broken, leading to
catastrophic failures.

Fundamentally, this is a co-ordination problem. Both the client program and the
terminal have to somehow share the same database of character properties and
the same algorithm for computing string lengths in cells based on that shared
database. Sadly, there is no such shared database in reality. The closest we
have is the Unicode standard. Unfortunately, the Unicode standard has a new
version almost every year and actually changes the width assigned to some
characters in different versions. Furthermore, to actually get the "correct"
width for a string using that standard one has to do grapheme segmentation,
which is an `extremely complex algorithm
<https://www.unicode.org/reports/tr29/#Grapheme_Cluster_Boundaries>`__.
Expecting all terminals and all terminal programs to have both up-to-date
character databases and a bug free implementation of this algorithm is not
realistic.

So instead, this protocol solves the issue robustly by removing the
co-ordination problem and putting only one actor in charge of determining
string width. The client becomes responsible for doing whatever level of
grapheme segmentation it is comfortable with using whatever Unicode database is
at its disposal and then it can transmit the segmented string to the terminal
with the appropriate ``w`` values so that the terminal renders the text in the
exact number of cells the client expects.

.. note::
   It is possible for a terminal to implement only the width part of this spec
   and ignore the scale part. This escape code works with only the `w` key as
   well as a means of specifying how many cells each piece of text occupies.
   See the section on :ref:`detect_text_sizing` on how client applications can
   query for terminal emulator support.


Wrapping and overwriting behavior
-------------------------------------

If the multicell block (``s * w by s`` cells) is larger than the screen size in either
dimension, the terminal must discard the character. Note that in particular
this means that resizing a terminal screen so that it is too small to fit a
multicell character can cause the character to be lost.

When drawing a multicell character, if wrapping is enabled (DECAWM is set) and
the character's width (``s * w``) does not fit on the current line, the cursor is
moved to the start of the next line and the character is drawn there.
If wrapping is disabled and the character's width does not fit on the current
line, the cursor is moved back as far as needed to fit ``s * w`` cells and then
the character is drawn, following the overwriting rules described below.

When drawing text either normal text or text specified via this escape code,
and this text would overwrite an existing multicell character, the following
rules must be followed, in decreasing order of precedence:

#. If the text is a combining character it is added to the existing multicell
   character
#. If the text will overwrite the top-left cell of the multicell character, the
   entire multicell character must be erased
#. If the text will overwrite any cell in the topmost row of the multicell
   character, the entire multicell character must be replaced by spaces (this
   rule is present for backwards compatibility with how overwriting works for
   wide characters)
#. If the text will overwrite cells from a row after the first row, then cursor should be moved past the
   cells of the multicell character on that row and only then the text should be
   written. Note that this behavior is independent of the value of DECAWM. This
   is done for simplicity of implementation.

The skipping behavior of the last rule can be complex requiring the terminal to
skip over lots of cells, but it is needed to allow wrapping in the presence of
multicell characters that extend over more than a single line.

.. _detect_text_sizing:

Detecting if the terminal supports this protocol
-----------------------------------------------------

To detect support for this protocol use the `CPR (Cursor Position Report)
<https://vt100.net/docs/vt510-rm/CPR.html>`__ escape code. Send a ``CPR``
followed by ``\e]_text_size_code;w=2; \a`` which will draw a space character in
two cells, followed by another ``CPR``. Then send ``\e]_text_size_code;s=2; \a``
which will draw a space in a ``2 by 2`` block of cells, followed by another
``CPR``.

Then wait for the three responses from the terminal to the three CPR queries.
If the cursor position in the three responses is the same, the terminal does
not support this protocol at all, if the second response has a different cursor
position then the width part is supported and if the third response has yet
another position, the scale part is supported.


Interaction with other terminal controls
--------------------------------------------------

This protocol does not change the character grid based nature of the terminal.
Most terminal controls assume one character per cell so it is important to
specify how these controls interact with the multicell characters created by
this protocol.

Cursor movement
^^^^^^^^^^^^^^^^^^^

Cursor movement is unaffected by multicell characters, all cursor movement
commands move the cursor position by single cell increments, as has always been
the case for terminals. This means that the cursor can be placed at any
individual single cell inside a larger multicell character.

When a multicell character is created using this protocol, the cursor moves
`s * w` cells to the right, in the same row it was in.

Terminals *should* display a large cursor covering the entire multicell block
when the actual cursor position is on any cell within the block. Block cursors
cover all the cells of the multicell character, bar cursors appear in all the
cells in the first column of the character and so on.


Editing controls
^^^^^^^^^^^^^^^^^^^^^^^^^

There are many controls used to edit existing screen content such as
inserting characters, deleting characters and lines, etc. These were all
originally specified for the one character per cell paradigm. Here we specify
their interactions with multicell characters.

**Insert characters** (``CSI @`` aka ``ICH``)
    When inserting ``n`` characters at cursor position ``x, y`` all characters
    after ``x`` on line ``y`` are supposed to be right shifted. This means
    that any multi-line character that intersects with the cells on line ``y`` at ``x``
    and beyond must be erased. Any single line multicell character that is
    split by the cells at ``x`` and ``x + n - 1`` must also be erased.

**Delete characters** (``CSI P`` aka ``DCH``)
    When deleting ``n`` characters at cursor position ``x, y`` all characters
    after ``x`` on line ``y`` are supposed to be left shifted. This means
    that any multi-line character that intersects with the cells on line ``y`` at ``x``
    and beyond must be erased. Any single line multicell character that is
    split by the cells at ``x`` and ``x + n - 1`` must also be erased.

**Erase characters** (``CSI X`` aka ``ECH``)
    When erasing ``n`` characters at cursor position ``x, y`` the ``n`` cells
    starting at ``x`` are supposed to be cleared. This means that any multicell
    character that intersects with the ``n`` cells starting at ``x`` must be
    erased.

**Erase display** (``CSI J`` aka ``ED``)
    Any multicell character intersecting with the erased region of the screen
    must be erased. When using mode ``22`` the contents of the screen are first
    copied into the history, including all multicell characters.

**Erase in line** (``CSI K`` aka ``EL``)
    Works just like erase characters above. Any multicell character
    intersecting with the erased cells in the line is erased.

**Insert lines** (``CSI L`` aka ``IL``)
    When inserting ``n`` lines at cursor position ``y`` any multi-line
    characters that are split at the line ``y`` must be erased. A split happens
    when the second or subsequent row of the multi-line character is on the line
    ``y``. The insertion causes ``n`` lines to be removed from the bottom of
    the screen, any multi-line characters are split at the bottom of the screen
    must be erased. A split is when any row of the multi-line character except
    the last row is on the last line of the screen after the insertion of ``n``
    lines.

**Delete lines** (``CSI M`` aka ``DL``)
    When deleting ``n`` lines at cursor position ``y`` any multicell character
    that intersects the deleted lines must be erased.
