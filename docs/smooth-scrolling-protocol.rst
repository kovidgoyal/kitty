The smooth scrolling protocol
==============================================

.. versionadded:: 1.0.0

Terminal programs scroll their content by whole lines. With high resolution
scroll wheels and touchpads, which report scrolling in pixels, this looks
jerky: the content jumps by a full line, after the fingers have moved some
distance, instead of following them. This protocol allows programs to scroll
rectangular regions of the screen smoothly, by any number of pixels,
vertically or horizontally.

The program designates a rectangle of the screen as a *smooth scroll region*
and then tells the terminal to scroll it by some number of pixels. The terminal
moves the cells in the rectangle by whole rows (or columns) and draws the
rectangle shifted by the remaining fraction of a row. The program draws only
the rows that move into the rectangle, exactly as it would when scrolling by
whole lines. Everything else, including keeping the rows that move out of the
rectangle so that they can be drawn partially and restored when the user
scrolls back, is done by the terminal.

This protocol is designed to be used together with :ref:`detailed reporting of
scroll events <detailed_wheel_events>`, which reports scrolling in pixels, in
the same units as used by this protocol.

Quickstart
--------------

In the examples below, ``<OSC>`` is the bytes ``ESC ]``, ``<ST>`` is the bytes
``ESC \`` (``BEL`` is also accepted) and ``<CSI>`` is the bytes ``ESC [``.

Define a region covering rows 2 to 21, spanning the full width of the screen,
using the id ``1``, then scroll it, wrapping every scroll and the drawing of
the rows that move into the region in `synchronized output
<https://gitlab.com/gnachman/iterm2/-/wikis/synchronized-updates-spec>`__::

    <OSC>2254;a=d:i=1:y=2:h=20<ST>
    ...
    <CSI>?2026h<OSC>2254;a=s:i=1:d=7<ST>... draw the rows that moved in ...<CSI>?2026l

Here, ``d=7`` scrolls the region by seven pixels
towards the end of the content, that is, the content moves up. When the region
is no longer needed, remove it::

    <OSC>2254;a=r:i=1<ST>

To see smooth scrolling in action, run the following command inside kitty and
scroll the box of text with a touchpad or a high resolution mouse wheel::

    kitten mouse-demo

Its source code, in :file:`tools/cmd/mouse_demo/text_area.go`, is a complete
example of using this protocol.

The escape code
-----------------

All commands are of the form::

    <OSC>2254;key=value:key=value:...<ST>

Keys are single characters and values are either single characters or
integers, as described below. The keys can be in any order. Keys that are not
specified have their default values. Commands that are malformed, for example,
with an unknown key or an invalid value, are ignored in their entirety. There
is no payload.

The terminal never replies to commands, except to :ref:`queries
<smooth_scroll_queries>`. Commands that cannot be performed, for example,
defining a region that does not fit on the screen, are silently ignored.
Programs that need to know whether a feature is supported should use a
:ref:`feature query <smooth_scroll_queries>`.

.. list-table:: The keys
   :header-rows: 1
   :widths: 6 12 10 72

   * - Key
     - Value
     - Default
     - Meaning
   * - ``a``
     - ``d``, ``s``, ``r`` or ``q``
     - none
     - The action: define a region, scroll a region, remove regions or query
       the terminal. Commands without an action are ignored.
   * - ``i``
     - Integer, positive
     - none
     - The id of the region, chosen by the program. Required for defining and
       scrolling regions. When removing regions without an id, all regions are
       removed.
   * - ``x``, ``y``
     - Integer, positive
     - ``1``
     - The column and row of the top left cell of the region, starting from
       ``1``, as for the cursor position escape code (CUP).
   * - ``w``, ``h``
     - Integer, non-negative
     - ``0``
     - The width and height of the region, in cells. Zero means the region
       extends to the right or bottom edge of the screen.
   * - ``o``
     - ``v`` or ``h``
     - ``v``
     - The direction in which the region scrolls, vertically or horizontally.
   * - ``k``
     - Integer, positive
     - ``1``
     - The *capacity* of the region, the number of rows (columns for
       horizontally scrolling regions) that the terminal keeps on each side of
       the region, after they move out of it. See :ref:`smooth_scroll_overflow`.
   * - ``p``
     - ``0`` or ``1``
     - ``0``
     - When ``1``, a region spanning the full width of the main screen and
       starting at its top does not push the rows that move out of it into
       the scrollback. See :ref:`smooth_scroll_scrollback`.
   * - ``d``
     - Integer
     - ``0``
     - The amount to scroll by, in pixels. Positive values scroll towards the
       end of the content: the content moves up (or left).
   * - ``e``
     - Any letter
     - none
     - Only for :ref:`feature queries <smooth_scroll_queries>`, the action
       being queried.
   * - ``n``
     - Integer, positive
     - none
     - Only in replies to :ref:`queries <smooth_scroll_queries>`, the maximum
       number of regions that can be defined at a time.

All amounts in pixels are in the same pixel coordinate system as used for the
``CSI 14 t`` query, SGR pixel mouse reporting and :ref:`detailed scroll events
<detailed_wheel_events>`. The size of a cell in this coordinate system can be
queried with ``CSI 16 t``.

Defining regions
--------------------

Defining a region, with ``a=d``, designates a rectangle of the screen for
smooth scrolling::

    <OSC>2254;a=d:i=1:x=3:y=2:w=40:h=20:k=3<ST>

A region must be inside the screen and must not overlap other regions. The
number of regions that can be defined at a time is limited by the terminal
(four in kitty), use a :ref:`query <smooth_scroll_queries>` to find it out.
The direction in which a region scrolls is fixed when it is defined.

Defining a region with the id of an existing region replaces it, exactly as if
the existing region was :ref:`removed <smooth_scroll_remove>` first: its
offset is reset to zero and the rows kept on its sides are discarded. The new
rectangle may overlap the rectangle of the region it replaces. If the new
definition is invalid, the existing region is left unchanged.

Defining a region does not change the contents of the screen and while it is
not scrolled, it is drawn exactly as before, except for images extending out
of it in the direction of scrolling, which are :ref:`clipped to it
<smooth_scroll_images>`. The rectangle of a region is in
screen coordinates and does not move with the contents of the screen, so a
program normally defines its regions once, after drawing its user interface,
and redefines them when the layout of its user interface changes, for example,
when the terminal is resized.

Scrolling regions
--------------------

Scrolling a region, with ``a=s``, moves its contents by the specified number
of pixels::

    <OSC>2254;a=s:i=1:d=-12<ST>

The terminal keeps track of the *offset* of the region, the position of its
first row (or column) relative to its top (or left) edge, in pixels. The cells
of the region are drawn shifted by the offset: down (right) when it is
positive and up (left) when it is negative. Its magnitude is always less than
the height (or width) of a cell. When the
content has moved by a full row, the terminal moves the cells in the rectangle
by one row and adjusts the offset. The row that moves *into* the region, in
the direction of scrolling, is always moved into the rectangle before any part
of it becomes visible, so that the program can draw it. The partially visible
row at the other edge is drawn by the terminal from the rows it kept when they
moved out of the region.

A row that moves into the region is blank, unless the terminal kept it from
when it moved out of the region earlier, in which case it is restored. The
program must draw the rows that moved into the region. Restored rows can be
drawn again, if their contents might have changed.

To know which rows moved into the region, programs perform the same
calculation as the terminal. Let ``h`` be the height of a cell (the width, for
horizontally scrolling regions) and ``r`` be the offset, which is zero when
the region is defined. To scroll by ``d`` pixels:

.. code-block:: python

    m = r - d
    if d > 0:
        n = ceil(-m / h) if m < 0 else 0
    else:
        n = -ceil(m / h) if m > 0 else 0
    r = m + n * h

The cells in the rectangle are moved by ``n`` rows (columns), towards the top
(left) when ``n`` is positive and towards the bottom (right) when it is
negative. The ``|n|`` rows at the bottom (right) of the rectangle, when ``n``
is positive, or at its top (left), when ``n`` is negative, are the ones that
moved into the region. When ``|n|`` is larger than the number of rows in the
rectangle, all its rows moved into it.

Note that because the row moving into the region is moved into the rectangle
before it becomes visible, changing the direction of scrolling can move the
cells back by one row even when scrolling by a single pixel. For example,
after scrolling a region with a cell height of ``20`` by ``1``, its offset is
``19`` and scrolling it by ``-1`` moves its cells back down by one row,
leaving it with an offset of ``0``.

.. warning::
   Always send a scroll command together with the drawing of the rows that
   moved into the region, inside a single `synchronized output
   <https://gitlab.com/gnachman/iterm2/-/wikis/synchronized-updates-spec>`__ block, mode ``2026``::

        <CSI>?2026h<OSC>2254;a=s:i=1:d=7<ST>... draw the rows ...<CSI>?2026l

   Otherwise, the terminal can render a frame after moving the cells of the
   region but before the new rows are drawn, showing a blank or stale row at
   the edge of the region.

Programs can write to the cells of a region at any time, in the usual way.
This only changes its contents and does not affect its offset.

When the scroll amounts come from :ref:`detailed scroll events
<detailed_wheel_events>` in pixels, programs can use the deltas directly, as
positive deltas scroll towards the end of the content in both protocols. A
program can scroll a region by any amount, but should stop scrolling at the
beginning and end of its content.

.. _smooth_scroll_overflow:

Rows moving out of regions
------------------------------

The terminal keeps the rows (columns) that move out of a region, on each side
of it, up to the capacity of the region, specified with the ``k`` key. The
nearest one is drawn in the partially visible row at the edge of the region,
and they are restored when they move back into the region, so that programs
do not have to redraw them when the user changes the direction of scrolling.
Rows that move further away from the region than its capacity are discarded.
The capacity is at most the height (width) of the region, larger values are
reduced to it.

The terminal also discards these rows, and draws the region unshifted, when
the rows of the screen move under the region, as they no longer adjoin it:

* when the lines of the screen it intersects are scrolled, for example, by a
  line feed at the bottom of the screen or by the SU and SD escape codes,
  or when lines are inserted or deleted in them (IL and DL)
* when the screen is erased with ED 2, ED 3 or ED 22, or filled with the
  alignment test pattern (DECALN)
* for horizontally scrolling regions, when characters are inserted or
  deleted in their rows (ICH, DCH or insert mode), moving the cells of their
  rows sideways

.. _smooth_scroll_scrollback:

Regions and the scrollback
------------------------------

Smooth scroll regions can be used in both the main and the alternate screens.
When a vertically scrolling region spans the full width of the main screen and
starts at its top, the rows that move out of its top go into the scrollback,
exactly as when scrolling with the SU escape code, and are taken back from the
scrollback when scrolling in the other direction. Only the rows that moved
into the scrollback from the region are taken back, rows that were in the
scrollback before, for example, the output of commands run before the
program, are never taken. When there are no more rows to take back, blank
rows move into the region, for the program to draw. In this case, the
capacity only applies to the rows below the region.

For such a region, scrolling the screen into the scrollback, for example,
with a line feed at the bottom of the screen, moves the top row of the region
into the scrollback, as if the region was scrolled by a whole row. This row
can be taken back from the scrollback like the others, only the rows kept
below the region are discarded, as described :ref:`above
<smooth_scroll_overflow>`. To keep the rows that move out of
such a region private instead, define it with ``p=1``. This is useful, for
example, for a list at the top of the screen, whose rows should not be added
to the scrollback.

While the user views the scrollback, regions are drawn unshifted, as their
rectangles are in screen coordinates.

.. _smooth_scroll_remove:

Removing regions
--------------------

To remove a region, use ``a=r`` with its id. Without an id, all regions are
removed::

    <OSC>2254;a=r:i=1<ST>
    <OSC>2254;a=r<ST>

Removing a region discards the rows kept on its sides and it is drawn
unshifted. All regions are removed when the terminal is reset (RIS or DECSTR),
when switching between the main and alternate screens, when the terminal is
resized and when the font size changes, as the offsets of the regions are in
pixels.

Interactions with other features
------------------------------------

Images
   See :ref:`smooth_scroll_images`.

Characters occupying multiple cells
   Wide characters and characters drawn using the :doc:`text sizing protocol
   <text-sizing-protocol>` that cross the edges of the rectangle into cells
   outside it are removed when the region is scrolled, as moving the cells of
   the rectangle would tear them apart. Characters that are split by
   scrolling, with some of their cells inside the rectangle and the others in
   the rows kept by the terminal, are kept and drawn partially. Note that this
   is different from images, which are never removed because they cross the
   edges of the rectangle.

Selections
   Selections inside the rectangle of a region move with its cells.
   Selections crossing its edges, or moving out of it, are cleared.

The mouse
   Mouse events are reported for the cell drawn under the mouse pointer,
   taking the offset of the region into account. In the partially visible row
   at the edge of a region, events are reported for the row at the edge of
   the rectangle.

The cursor
   The cursor is not moved when a region is scrolled. When it is in the
   rectangle of a region, it is drawn shifted with the cells of the region.

.. _smooth_scroll_images:

Images
----------

The rules below are for vertically scrolling regions. For horizontally
scrolling regions, swap rows and columns, top and left, and bottom and right.
They apply to images displayed using the :doc:`graphics protocol
<graphics-protocol>`. Images displayed using Unicode placeholders are drawn
from their placeholder cells, which move like all other cells, see below.

An image *moves with* a region when it is entirely within the columns of the
rectangle of the region and either:

* it intersects the rows of the rectangle, or
* it moved with the region before and at least part of it is still in the
  rectangle or in the rows kept on its sides.

This is determined continuously, not only when the region is scrolled, so
images placed at any time, including while the region is shifted by a
non-zero offset, are immediately drawn correctly. Images that move with a
region move with its cells, are drawn shifted by its offset and are clipped to
its rectangle. Parts of them outside the rectangle, above or below it, are
treated as being in the rows beyond the rectangle: they are not drawn and
become visible when the region is scrolled to bring them into it. This means
that an image placed near the bottom of a region and extending below it is
clipped to the region and the rest of it is revealed by scrolling, without
the program having to draw it again. It also means that defining a region
clips the images extending out of it, above or below.

An image that moves with a region is kept whole, while any part of it is in
the rectangle or in the rows kept on its sides. When it moves entirely beyond
the rows kept on a side, it is deleted. As a result, scrolling back can bring
back an image whole, even though the text in the rows beyond the capacity of
the region was discarded and is blank, for the program to draw again. Programs
that draw images again with the rows that move into the region should use a
placement id (the ``p`` key of the graphics protocol), so that drawing an image
that is still there replaces it, instead of creating a second copy.

When the rows kept on the sides of a region are discarded, as described in
:ref:`smooth_scroll_overflow`, or the region is removed or redefined, images
moving with it are clipped to its rectangle, the parts outside it are deleted.
For a region that uses the :ref:`scrollback <smooth_scroll_scrollback>`, images
move into the scrollback with the rows they are in and are taken back with
them, and the parts of images in the scrollback are never clipped.

Images that extend out of the columns of the rectangle never move with it and
are drawn unshifted and unclipped, on top of or below the moving cells.

Images placed relative to another image, using the ``P`` key of the graphics
protocol, move with the region if the image at the root of their chain of
parents does, regardless of their own position. When the root is an image
displayed using Unicode placeholders, they move with the region if the
placeholder cell they are placed relative to is in its rectangle.

Images displayed using Unicode placeholders are drawn from the placeholder
cells on the screen, so they always follow their cells. The part of such an
image whose placeholder cells are inside the rectangle moves with it, while
the part whose cells are outside it does not. In kitty, these images are not
drawn in the partially visible column at the edge of a horizontally scrolling
region, only in its rectangle, as they are created from the placeholder cells
on the screen. They are drawn normally again once they move back into the
rectangle.

.. _smooth_scroll_queries:

Detecting support and features
-----------------------------------

To detect whether the terminal supports this protocol, send a query, with
``a=q``, followed by a request for the primary device attributes::

    <OSC>2254;a=q<ST><CSI>c

A terminal that supports the protocol replies with::

    <OSC>2254;a=q:n=4<ST>

before replying to the device attributes request. Here ``n`` is the maximum
number of regions that can be defined at a time. If the reply to the device
attributes request is received without a reply to the query, the protocol is
not supported. Queries have no other effect.

To find out whether a particular feature is supported, send a *feature query*:
a query with the ``e`` key set to the action you are interested in and the
other keys set to the values you intend to use with that action. The terminal
replies with ``e`` and every key from the query with a non-default value that
it supports for that action, with that value. For example, to check whether
horizontally scrolling regions with a capacity of three columns are
supported::

    <OSC>2254;a=q:e=d:o=h:k=3<ST>

to which a terminal that supports them replies::

    <OSC>2254;a=q:e=d:o=h:k=3<ST>

The reply always starts with ``a=q``. It contains ``e``, with the queried
action, when the action is supported, followed by every other key from the
query that has a non-default value and is supported with that value. Keys can
appear in the reply in any order. A key that is missing from the reply is not
supported, at least not with the specified value. If ``e`` is missing from
the reply, the action is not supported. The ``i`` key and keys with default
values are never included in the reply.

Future versions of this protocol may add new actions and new keys, for
example, to have the terminal animate scrolling by itself. As commands with
unknown keys are ignored entirely, programs must use a feature query to check
for support before using them.
