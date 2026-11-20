Miscellaneous protocol extensions
==============================================

These are a few small protocol extensions kitty implements, primarily for use
by its own kitten, they are documented here for completeness.


Simple save/restore of all terminal modes
--------------------------------------------

XTerm has the XTSAVE/XTRESTORE escape codes to save and restore terminal
private modes. However, they require specifying an explicit list of modes to
save/restore. kitty extends this protocol to specify that when no modes are
specified, all side-effect free modes should be saved/restored. By side-effects
we mean things that can affect other terminal state such as cursor position or
screen contents. Examples of modes that have side effects are: `DECOM
<https://vt100.net/docs/vt510-rm/DECOM.html>`__ and `DECCOLM
<https://vt100.net/docs/vt510-rm/DECCOLM.html>`__.

This allows TUI applications to easily save and restore emulator state without
needing to maintain lists of modes.


Independent control of bold and faint SGR properties
-------------------------------------------------------

In common terminal usage, bold is set via SGR 1 and faint by SGR 2. However,
there is only one number to reset these attributes, SGR 22, which resets both.
There is no way to reset one and not the other. kitty uses 221 and 222 to reset
bold and faint independently.

.. _mouse_leave_window:

Reporting when the mouse leaves the window
----------------------------------------------

kitty extends the SGR Pixel mouse reporting protocol created by xterm to
also report when the mouse leaves the window. This event is delivered
encoded as a normal SGR pixel event except that the eight bit is set on the
first number. Additionally, bit 5 is set to indicate this is a motion related event.
The remaining bits 1-7 (except 5) are used to encode button and modifier information.
When bit 8 is set it means the event is a mouse has left the window event,
and all other bits should be ignored. The pixel position values must also
be ignored as they may not be accurate.

.. _detailed_wheel_events:

Detailed reporting of scroll wheel and touchpad events
--------------------------------------------------------

.. versionadded:: 1.0.0

Traditionally, terminals report scrolling to programs as presses of the mouse
buttons 4 to 7. This is a poor fit for modern input devices such as high
resolution wheels and touchpads, which report scrolling in fractions of a
wheel click or in pixels, have gestures that begin and end and continue scrolling
with momentum after the fingers are lifted. kitty has a mode that makes it
report scroll events with all this information instead.

The mode is private mode ``5523``. A program turns it on with
``CSI ? 5523 h`` and off with ``CSI ? 5523 l``. It can check whether the
terminal supports it with the standard DECRQM query, ``CSI ? 5523 $ p``. The
mode has an effect only while mouse tracking is turned on (one of the modes
``1000``, ``1002`` or ``1003``), as otherwise the terminal uses scroll events
itself, to scroll its scrollback. While both are on, scroll events are no
longer reported as button 4 to 7 presses. Instead, every scroll event from
the operating system is reported as a single escape code of the form::

    CSI > x ; y ; dx ; dy ; unit ; source ; phase ; flags ; mods M

Spaces in the above are for clarity only. All parameters are always present.
They are:

``x ; y``
    The position of the mouse pointer. This is a 1-based cell position,
    unless SGR pixel mouse reporting (mode ``1016``) is on, in which case it
    is the position in pixels, exactly as for other mouse events.

``dx ; dy``
    The amount scrolled, as signed integers. A positive ``dy`` means scrolling
    towards the end of the content, that is, the direction of the
    traditional button 5 (wheel down). A positive ``dx`` means scrolling to
    the right, the direction of button 7. The deltas have any natural
    scrolling preference of the user already applied, see ``flags`` below.
    Events that carry only a change of ``phase`` have both deltas zero.

``unit``
    The unit of ``dx`` and ``dy``:

    ``1``
        Fractions of a wheel click, with one click being ``120``. High
        resolution wheels report parts of a click, for example, ``30`` for a
        quarter of a click. Wheels that report only whole clicks or lines,
        report multiples of ``120``.

    ``2``
        Pixels, in the same pixel coordinate system as used for SGR pixel
        mouse reporting and the ``CSI 14 t`` query. Fractions of a pixel are
        accumulated by the terminal and reported in a later event, so nothing
        is lost over a gesture.

    This parameter can have an optional sub-parameter, the scroll multiplier
    the user has configured in the terminal for this kind of scrolling, as a
    positive decimal number, for example, ``1:5`` or ``2:1.5``. It is a hint
    that programs can use to make their scrolling match that of the terminal,
    for instance, by scrolling ``5`` lines per wheel click. Terminals are not
    required to send it and programs are free to ignore it. The deltas
    themselves are never scaled by the multiplier.

``source``
    The kind of device the event comes from: ``0`` unknown, ``1`` a wheel,
    ``2`` a finger on a touchpad or trackpad, ``3`` a continuous device, for
    example, a trackpoint or a knob, ``4`` a wheel tilt, that is, sideways
    clicks of a wheel.

``phase``
    Where the event is in a scroll gesture. ``0`` means the device has no
    concept of gestures, as for wheel clicks. Otherwise, ``1`` means a
    gesture began, ``2`` that it continued, ``3`` that it ended, for example,
    the fingers were lifted from the touchpad, ``4`` that it was cancelled and
    ``5`` that a gesture may begin, for example, because the fingers are
    resting on the touchpad. When ``flags`` indicates momentum, the phase
    refers to the momentum scrolling rather than to the physical gesture.

``flags``
    A bit field. The bit ``1`` is set when the event is momentum, also called
    inertial or kinetic scrolling, that is, scrolling generated after the
    fingers were lifted, which slows down over time. Programs that do their
    own momentum scrolling should ignore these events. The bit ``2`` is set
    when the direction of the deltas is the reverse of the physical movement
    of the device, for example, because the user has turned on natural
    scrolling. Programs that need the physical direction, for example, to
    move a slider, can use it to undo the reversal.

``mods``
    The keyboard modifiers that were pressed, encoded as in the
    :ref:`keyboard protocol <modifiers>`, that is, one plus a bit field
    where ``shift=1``, ``alt=2``, ``ctrl=4``, ``super=8``, ``hyper=16``,
    ``meta=32``, ``caps_lock=64`` and ``num_lock=128``.

More parameters may be added at the end in the future, and sub-parameters
(separated by colons) may be added to any parameter. Programs must ignore any
parameters and sub-parameters they do not recognise.

A few examples, with the escape code introducer ``CSI >`` and the final ``M``
omitted::

    10;5;0;120;1:5;1;0;0;1     one click of a wheel, downwards
    10;5;0;-30;1:5;1;0;0;1     a quarter click of a high resolution wheel, upwards
    10;5;0;0;2:1;2;1;0;1       two fingers start a scroll on a touchpad
    10;5;3;-42;2:1;2;2;0;1     the fingers move upwards by 42 pixels
    10;5;0;0;2:1;2;3;0;1       the fingers are lifted
    10;5;0;-35;2:1;2;1;1;1     momentum scrolling begins
    10;5;0;0;2:1;2;3;1;1       momentum scrolling ends
    10;5;0;120;1:5;1;0;0;5     a wheel click downwards with ctrl pressed

.. _bidi_support:

Bidirectional text
-------------------------------------------------------------------------------------

By default kitty leaves the layout of bidirectional text to the program, as
described in the :opt:`force_ltr` option. A program can instead ask kitty to
lay out the lines it writes afterwards, following the Unicode bidirectional
algorithm (using FriBidi), by setting the ECMA-48 *Bi-Directional Support
Mode* (BDSM), ``CSI 8 h``, the implicit mode. ``CSI 8 l`` returns to the
default. Two more controls set the direction of a paragraph, the lines joined
by soft wraps:

``CSI ? 2501 h``
    A private mode from the `BiDi in Terminal Emulators
    <https://terminal-wg.pages.freedesktop.org/bidi/recommendation/escape-sequences.html>`__
    recommendation, as implemented by VTE. Takes the direction of each
    paragraph from its first strong character. ``CSI ? 2501 l`` turns this off.
    It has no effect unless ``CSI 8 h`` is set.

``CSI Ps SP k``
    ECMA-48 *Select Character Path* (SCP), in the form ``CSI Ps ; Ps SP k``.
    ``Ps`` of ``2`` makes paragraphs written afterwards right to left, ``1``
    or ``0`` left to right. When ``CSI ? 2501 h`` is set it only sets the
    direction of paragraphs that have no strong character. The second
    parameter is accepted and ignored, as are values of ``3`` or more.

A line keeps the settings in effect when its text was first written, until an
erase leaves the line blank, which clears them. A line cleared by writing
spaces over it keeps them.

To detect support, query the modes (``CSI 8 $ p`` and ``CSI ? 2501 $ p``). A
kitty without this feature answers ``0`` (unknown), and one with it ``2``
(reset) or ``1`` (set). While the :opt:`force_ltr` option is set the answer is
``4`` (permanently reset), as :opt:`force_ltr` turns all of this off wherever
the modes are used. The modes keep what the program set, so after a
configuration reload that clears :opt:`force_ltr` the answer goes back from
``4`` to ``1`` or ``2`` and the program's settings apply again.

The settings are per screen, like other per-screen modes. They are not carried
into the alternate screen, which starts with them off, and the main screen's
settings are restored on leaving it.

Only the display is reordered. Text stays in logical order, so selecting and
copying work on logical cells, and cell-based mouse reports carry logical
columns. SGR-pixel mouse reports carry the pointer's pixel position as drawn.

The text cursor is drawn at the visual column of its cell. A beam cursor on a
right-to-left cell is drawn past the cell, on its left edge in the last column.
The input method editor is anchored at the left edge of the cursor cell, and
the pre-edit text is drawn left to right.

kitty honours isolates (LRI, RLI, FSI and PDI) and the marks LRM, RLM and ALM
written after a character. Of the isolates in a paragraph the first 32 are
honoured and later ones are treated as neutral. A bracket pair whose opening
bracket is more than 32 characters after the previous strong character is not
paired. Embeddings and overrides (LRE, RLE, LRO, RLO and PDF) are treated as
neutral.

An escape code to move the contents of the screen into the scrollback
-------------------------------------------------------------------------------------

The escape code is ``\x1b [ 22 J`` (ignoring spaces present for clarity). It
moves all screen contents (text and images) into the scrollback leaving the
screen in the same state as it would be if the standard screen clear escape
code had been used ``\x1b [ 2 J``.


.. _program_status:

Reporting the status of a program
-------------------------------------

kitty supports the `Program Status Protocol (OSC 7501)
<https://www.superlogical.com/rex/docs/build/program-status>`__, revision 0.4,
which lets a program tell the terminal what it is doing: idle, working,
finished, blocked waiting on the user or failed, and why. For example::

    printf '\e]7501;state=working:app=rsync:progress=40\e\\'

kitty keeps the records reported by programs per window and applies the
lifetime rules of the specification:

* :code:`working`, :code:`blocked` and :code:`idle` records are dropped when a
  new shell prompt starts (needs :ref:`shell_integration`) or when a program
  run with :option:`launch --hold` exits

* :code:`done` and :code:`error` records are kept until the window is focused
  or a key is pressed in it

* a full reset removes every record

The limit on the length of an :code:`id` is 263 bytes rather than the 128 bytes
in the specification, as 263 bytes is what the limits on the length and number
of its segments allow.

The status is shown in the tab bar via the :code:`tab.program_status` field of
:opt:`tab_title_template`, is reported in the output of ``kitten @ ls``, and
:ref:`watchers <watchers>` can react to it via
:code:`on_program_status_change`.


Glyphs registered by programs
---------------------------------

kitty implements the `Glyph Protocol
<https://github.com/raphamorim/rio/blob/main/specs/glyph-protocol.md>`__,
which lets programs register vector glyphs for the codepoints
:code:`U+100000` to :code:`U+1003FF` and then use them as icons in their
output, without needing a font. kitty implements it as follows:

* Only the :code:`vg` payload format, SVG path data with fills, strokes,
  gradients and clips, is supported. The font based :code:`glyf`,
  :code:`colrv0` and :code:`colrv1` formats are not.

* The :code:`width` key is ignored. A glyph is rendered into the cells its
  character occupies. Use the :doc:`text sizing protocol <text-sizing-protocol>`
  to render glyphs in more than one cell or at a larger size. As with other
  private use characters, a glyph followed by a space is rendered in two cells,
  when the width of its viewBox, scaled to the height of a cell, is more than
  one cell.

* Queries for grapheme clusters are not supported. Queries for codepoints
  outside the registration block are answered with :code:`reason=unknown`, as
  kitty does not perform font lookups while parsing input. Queries for
  codepoints in the registration block are answered from the registrations.

* The glyph registered for a codepoint is bound to the text when it is
  printed. Changing or clearing a registration affects only text printed
  afterwards, so programs using the same codepoints for different glyphs do not
  change each other's output, in the scrollback or on screen. Colors that use
  the foreground color are applied when the glyph is drawn, so they follow
  changes to the foreground color, such as selection and the cursor.

* Each window can keep alive a limited number of glyphs, whether registered or
  used by its text, including text in the scrollback. Beyond that, new
  registrations fail with :code:`no_space` until text using glyphs is erased
  or scrolls out of the scrollback. Glyphs and the GPU memory used to draw
  them are released when no longer used by any text.


kitty specific private escape codes
---------------------------------------

These are a family of escape codes used by kitty for various things including
remote control. They are all DCS (Device Control String) escape codes starting
with ``\x1b P @ kitty-`` (ignoring spaces present for clarity).
