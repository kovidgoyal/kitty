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

.. _detailed_mouse_events:

Detailed reporting of mouse events
--------------------------------------------------------

.. versionadded:: 1.0.0

The traditional mouse reporting protocols have several shortcomings:

* Scrolling is reported as presses of the mouse buttons 4 to 7. This is a poor
  fit for modern input devices such as high resolution wheels and touchpads,
  which report scrolling in fractions of a wheel click or in pixels, have
  gestures that begin and end and continue scrolling with momentum after the
  fingers are lifted.

* SGR pixel mouse reporting (mode ``1016``) reports positions to the left of
  or above the window as negative numbers. These are not valid in the
  parameters of a CSI escape code, as per ECMA-48, the ``-`` byte is an
  *intermediate byte*, so a conforming parser cannot read them.

* Programs have to choose between cell and pixel positions, the button and
  modifiers are packed together into a single bit field, there is no way to
  know which other buttons are held down, no time for the events and every
  program has to detect double and triple clicks itself.

kitty has a mode that makes it report all mouse events in a single, extensible
format that has none of these problems. Programs can use the scroll events it
reports with the :doc:`smooth scrolling protocol <smooth-scrolling-protocol>`
to scroll their content by pixels.

Turning it on
~~~~~~~~~~~~~~~~

The mode is private mode ``5523``. A program turns it on with
``CSI ? 5523 h`` and off with ``CSI ? 5523 l``. It can check whether the
terminal supports it with the standard DECRQM query, ``CSI ? 5523 $ p``,
which reports whether the mode is set, regardless of whether mouse tracking is
on.

The mode only changes *how* mouse events are reported. It has an effect only
while mouse tracking is turned on with one of the modes below, which continue
to control *which* events are reported:

``1000``
    Button presses and releases, scroll events, and the mouse entering and
    leaving the window.

``1002``
    In addition, motion while any button whose press was reported is held
    down.

``1003``
    In addition, all motion.

It has no effect with the X10 (``9``) and highlight (``1001``) mouse tracking
modes. While mouse tracking is off, the terminal uses mouse events itself, for
instance, scroll events to scroll its scrollback, and reports nothing. While
the mode is on, the encodings selected by modes ``1005``, ``1006``, ``1015``
and ``1016`` are not used. These modes keep their values and the encoding
they select is used again once this mode is turned off.

The mode is reset, saved and restored in the same way as the mouse tracking
modes. When the mode or mouse tracking is turned off, no more events are
reported in this encoding for the buttons that are still held down, so
programs must then consider all buttons released.

Note that programs that do not use this mode must not turn it on, for
instance, by restoring modes they did not save. Parsers that ignore the ``>``
byte would read the escape codes as reports in the ``1015`` encoding.

The window
~~~~~~~~~~~~~

Events are reported for the *window* of the program, the area in which the
terminal draws its screen, including any padding around the cells, but not
any borders, scroll bars, tab bars or title bars. In kitty, this is the
kitty window running the program.

Events are reported while the mouse pointer is in the window. The terminal
may handle some events itself rather than reporting them, for instance,
clicks with modifiers the user configured for selecting text. It then reports
neither the press of the button nor its release.

When a button press is reported, the pointer is *grabbed* by the window,
until all the buttons whose presses were reported are released. While the
pointer is grabbed, all events are reported to the window, wherever the
pointer is, even outside the window, and the release of every button whose
press was reported is always reported to it, even if, for example, the
window loses the keyboard focus. When the terminal will not receive the
release of a button, for example, because the mouse was taken over by drag
and drop, it reports the release as soon as it knows that.

The pointer entering and leaving the window is reported, strictly
alternating, starting with entering. Entering is reported when the pointer
moves into the window, when the window appears under the pointer, for
example, when switching to its tab, and, if the pointer is in the window,
when this mode or mouse tracking is turned on. Terminals may report entering
only just before the next event they report to the window, when it is not
practical to detect the pointer entering, for example, when the window
appears under the pointer because of a change in the layout of the windows.
Entering is always reported before any other event. Leaving is reported when
the pointer moves out of the window or the window disappears from under it.
While the pointer is grabbed, leaving is not reported. If the pointer is
outside the window when it stops being grabbed, leaving is reported right
after the release of the last button.

Terminals should report the click that gives the keyboard focus to a window
like any other.

The escape code
~~~~~~~~~~~~~~~~~~

Every mouse event is reported as a single escape code of the form::

    CSI > type : serial ; x ; y ; px ; py ; buttons ; mods ; t ; ... M

Spaces in the above are for clarity only. The parameters up to and including
``t`` are common to all events and are always present. They are followed by
parameters specific to the type of the event, described :ref:`below
<mouse_event_types>`, which are also always present. Parameters are never
empty. The final byte is always ``M``, including for releases.

All numbers are non-negative decimal integers that fit in 32 bits, that is,
are at most ``4294967295``. Programs using this mode must be able to parse
numbers this large and escape codes with at least ``32`` numbers in total,
counting both parameters and sub-parameters.

Values that can be negative are sent as their absolute value, followed by the
sub-parameter ``1`` when they are negative. For example, ``42`` is ``42`` and
``42:1`` is ``-42``. Terminals may send ``42:0`` for ``42`` and must do so
if they send further sub-parameters for the value. They never send ``0:1``,
programs should read it as zero. For example, in Python:

.. code-block:: python

    def signed(param: str) -> int:
        magnitude, _, rest = param.partition(':')
        sign = rest.partition(':')[0]
        return -int(magnitude) if sign == '1' else int(magnitude)

The common parameters are:

``type``
    The type of the event: ``1`` a button press, ``2`` a button release,
    ``3`` motion, ``4`` scrolling, ``5`` the mouse entered the window and
    ``6`` the mouse left the window.

``serial``
    An integer identifying the event, from ``0`` to ``2147483647``, see
    :ref:`mouse_event_serials`.

``x ; y``
    The 1-based position of the cell under the mouse pointer. This is the
    cell whose contents are drawn under the pointer, taking into account, for
    example, the offsets of :doc:`smooth scroll regions
    <smooth-scrolling-protocol>`, so it cannot always be calculated from the
    pixel position. It is always on the screen: when the pointer is not over
    a cell, for example, when it is in the padding or outside the window,
    while it is grabbed, it is the cell nearest to the pointer.

``px ; py``
    The position of the mouse pointer in pixels, as signed values, relative
    to the top left corner of the first cell of the screen. This is the same
    pixel coordinate system as used for SGR pixel mouse reporting and the
    ``CSI 14 t`` query. It is negative when the pointer is to the left of or
    above the first cell, for example, ``7:1`` when it is seven pixels to its
    left, in the padding or outside the window.

``buttons``
    The buttons held down after the event, among those whose presses were
    reported, as a bit field, where button ``n`` (see below) is the bit
    ``2ⁿ⁻¹``, so ``1`` for the left button, ``2`` for the middle button,
    ``4`` for the right button, and so on. For a press, it includes the
    pressed button and for a release, it does not include the released
    button.

``mods``
    The keyboard modifiers that were pressed, encoded as in the
    :ref:`keyboard protocol <modifiers>`, that is, one plus a bit field
    where ``shift=1``, ``alt=2``, ``ctrl=4``, ``super=8``, ``hyper=16``,
    ``meta=32``, ``caps_lock=64`` and ``num_lock=128``.

``t``
    The time of the event, as ``seconds:microseconds``, where ``seconds`` is a
    non-negative integer and ``microseconds`` is from ``0`` to ``999999``.
    Terminals may report times with less precision than a microsecond, kitty
    reports them rounded down to a whole millisecond, so ``microseconds`` is
    always a multiple of ``1000``.
    Only the differences between the times of events are meaningful, for
    instance, to calculate the velocity of a scroll gesture for momentum
    scrolling, without being affected by delays in delivering the events to
    the program. The time is that of the input event from the operating
    system, where available, not the time the terminal processed or sent it.
    The times of all types of events are on the same clock. kitty uses the
    time from the operating system for events processed up to thirty seconds
    after they happened, later ones, for example, because kitty was
    unresponsive, have the time they were processed. Events that do not come
    from an input event of the operating system, such as momentum scrolling
    the terminal synthesizes or, on some platforms, the pointer entering and
    leaving the window, have the time they were generated. When the terminal
    detects the end of a scroll gesture itself, because the operating system
    does not report it, the end has the time of the last event of the
    gesture. The origin is arbitrary, kitty uses the time the mode was turned
    on. The time never decreases from one event to the next while the mode
    stays on.

The mouse buttons are numbered as ``1`` left, ``2`` middle, ``3`` right,
``4`` back, ``5`` forward and ``6`` and higher for any additional buttons.
Note that, unlike in the traditional protocols, the buttons ``4`` to ``7``
are not used for scrolling, which is reported with its own type of event.

.. _mouse_event_types:

The types of events
~~~~~~~~~~~~~~~~~~~~~~

Press (type ``1``)
    ``button ; count``, where ``button`` is the number of the button pressed
    and ``count`` is the number of successive presses of the button, ``1``
    for a single click, ``2`` for a double click, ``3`` for a triple click
    and so on, see :ref:`mouse_click_count`.

Release (type ``2``)
    ``button ; count``, where ``button`` is the number of the button released
    and ``count`` is the count of the press it releases.

Motion (type ``3``)
    No additional parameters. Whether a button is held down, that is, whether
    the motion is a drag, is given by ``buttons``. Motion is reported when the
    position of the pointer changes, by at least a pixel, including within a
    cell and in the padding. Terminals may report only the latest of several
    motions, for example, when the program is not reading its input fast
    enough.

Scrolling (type ``4``)
    ``dx ; dy ; unit ; source ; phase ; flags``, described below. Every
    scroll event from the operating system is reported as at most one
    escape code. Events that scroll less than a whole unit (see ``unit``
    below) and do not change the ``phase`` are not reported, the amount they
    scroll is reported with a later event.

Entering and leaving the window (types ``5`` and ``6``)
    No additional parameters. For leaving, the position is the one reported
    with the previous event, as the terminal may not know where the pointer
    is once it has left the window.

The parameters of scroll events are:

``dx ; dy``
    The amount scrolled, as signed values. A positive ``dy`` means scrolling
    towards the end of the content, that is, the direction of the
    traditional button 5 (wheel down). A positive ``dx`` means scrolling to
    the right, the direction of the traditional button 7. The deltas have any
    natural scrolling preference of the user and the sign of any negative
    scroll multiplier the user configured in the terminal already applied,
    see ``flags`` below. Events that carry only a change of ``phase`` have
    both deltas zero.

``unit``
    The unit of ``dx`` and ``dy``:

    ``1``
        Fractions of a wheel click, with one click being ``120``. High
        resolution wheels report parts of a click, for example, ``30`` for a
        quarter of a click. Wheels that report only whole clicks or lines,
        report multiples of ``120``.

    ``2``
        Pixels, in the same pixel coordinate system as ``px`` and ``py``.
        Fractions of a pixel are accumulated by the terminal and reported in
        a later event, so nothing is lost over a gesture.

    This parameter can have an optional sub-parameter, the magnitude of the
    scroll multiplier the user has configured in the terminal for this kind
    of scrolling, as a positive integer number of thousandths, for example,
    ``1:5000`` for a multiplier of ``5`` or ``2:1500`` for ``1.5``. It is a
    hint that programs can use to make their scrolling match that of the
    terminal, for instance, by scrolling ``5`` lines per wheel click.
    Terminals are not required to send it and programs are free to ignore
    it. The deltas themselves are never scaled by the multiplier.

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

.. _mouse_click_count:

Click counts
~~~~~~~~~~~~~~~

The terminal counts successive presses so that programs do not have to, and
so that the double click interval the user configured is respected by all
programs. A press continues the count of the previous reported press if all
of these hold:

* it is of the same button
* the time between the two presses, as given by ``t``, is at most the
  double click interval
* the distance between the positions of the two presses is at most a small
  radius

Otherwise, the count starts again from ``1``. As each press is compared to
the previous one, a long series of presses, each within the double click
interval of the previous one, keeps counting up. Changes in the keyboard
modifiers do not affect the count. The count has no upper limit, programs
decide what to do with large counts, for instance, treating counts larger
than three as three, or cycling with ``(count - 1) % 3 + 1``.

.. note::
   kitty uses the :opt:`click_interval` option as the double click interval,
   which, by default, is the double click interval of the desktop
   environment, and half the height of a cell as the radius.

.. _mouse_event_serials:

Serials
~~~~~~~~~~

Every event has a serial, which is different from the serials of the events
reported recently. Serials increase by an unspecified amount from one event
to the next and wrap around from ``2147483647`` to ``1``. Terminals never use
the serial ``0``. Serials are opaque, programs must not interpret them, other
than comparing them for equality.

Serials are reserved for future protocols that allow programs to refer to a
particular event, for instance, to ask the terminal to open a URL the user
clicked on. A terminal can then check that the request is the result of a
recent, real click by the user in the window of the program. Such protocols
will accept only the serials of button presses and releases, only once, only
for a short time after the event and only from the program the event was
reported to. They cannot check that the user clicked on the URL itself, as
the program decides which URL is at the position of the click.

Programs, such as terminal multiplexers, that forward the events they
receive to other programs, adjusting their positions, must forward the
serials unchanged. Events that they generate themselves, for example,
entering and leaving the panes they display, must have the serial ``0``.

Extending the protocol
~~~~~~~~~~~~~~~~~~~~~~~~~

More parameters may be added at the end of the parameters of any type of
event and more sub-parameters may be added to any parameter, after the
existing ones, so for signed values, after the sign. New types of events may be
added. Programs must ignore any parameters and sub-parameters they do not
recognise and any events of a type they do not recognise.

Examples
~~~~~~~~~~~

A few examples, for cells ten pixels wide and twenty pixels high, with the
escape code introducer ``CSI >`` and the final ``M`` omitted::

    1:101;10;5;95;83;1;1;4:16000;1;1                  the left button is pressed in the cell (10, 5)
    3:102;11;5;104;83;1;1;4:24000                     the mouse moves to the next cell, with the left button held
    3:103;1;5;30:1;83;1;1;4:40000                     ... and out of the window, thirty pixels to the left of the first cell
    2:104;1;5;30:1;83;0;1;4:52000;1;1                 the left button is released outside the window
    6:105;1;5;30:1;83;0;1;4:52000                     ... so the mouse leaves the window
    5:106;1;5;2:1;83;0;1;5:300000                     the mouse enters the window, in the padding to the left of the first cell
    1:107;10;5;95;83;4;5;7:100000;3;1                 the right button is pressed with ctrl held
    2:108;10;5;95;83;0;5;7:180000;3;1                 the right button is released
    1:109;10;5;95;83;4;5;7:350000;3;2                 the right button is pressed again, within the double click interval
    2:110;10;5;95;83;0;5;7:420000;3;2                 ... and released, completing a double click
    4:111;10;5;95;83;0;1;9:520000;0;120;1:5000;1;0;0  one click of a wheel, downwards
    4:112;10;5;95;83;0;1;9:830000;0;30:1;1:5000;1;0;0 a quarter click of a high resolution wheel, upwards
    4:113;10;5;95;83;0;1;12:0;0;0;2:1000;2;1;0        two fingers start a scroll on a touchpad
    4:114;10;5;95;83;0;1;12:8000;0;42:1;2:1000;2;2;0  the fingers move upwards by 42 pixels, 8 ms later   
    4:115;10;5;95;83;0;1;12:16000;0;0;2:1000;2;3;0    the fingers are lifted
    4:116;10;5;95;83;0;1;12:17000;0;35:1;2:1000;2;1;1 momentum scrolling begins
    6:117;10;5;95;83;0;1;15:0                         the mouse leaves the window

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

``CSI Ps ; Ps SP k``
    ECMA-48 *Select Character Path* (SCP). A first parameter of ``2`` makes
    paragraphs written afterwards right to left, ``1`` or ``0`` left to right.
    When ``CSI ? 2501 h`` is set it only sets the direction of paragraphs that
    have no strong character. The second parameter is accepted and ignored, as
    are values of ``3`` or more.

A line takes the settings in effect when text is first written to it in bidi
mode, and keeps them for as long as it holds text. A line left without text
loses them. The lines of a paragraph are laid out together when any of them
holds settings, including lines written with bidi mode off, and the first of
them that holds settings gives the paragraph its direction.

In bidi mode with ``CSI ? 2501 h`` set, an LRM or RLM written at the start of
a line that starts a paragraph sets the direction of that paragraph, in place
of its first strong character. The mark itself is discarded, as the
:doc:`text sizing protocol </text-sizing-protocol>` requires for a zero width
code point with no previous cell, and if several are written the last one
wins. Whether ``CSI ? 2501 h`` is set when the mark is written decides
whether it applies. ALM and the isolates have no effect there. The direction
becomes part of the line's settings when text is written to the line in bidi
mode, and ends with them. Until then it is dropped when text is written to the
line with bidi mode off, or the line is erased as a whole by ED, DECALN or
RIS, and it may
be lost when the screen is resized.

To detect support, query the modes (``CSI 8 $ p`` and ``CSI ? 2501 $ p``). A
kitty without this feature answers ``0`` (unknown), and one with it ``2``
(reset) or ``1`` (set). While the :opt:`force_ltr` option is set the answer is
``4`` (permanently reset) and nothing is laid out. Lines written while it is
set get no settings, so when it is cleared the program's settings apply to
text written afterwards.

The settings are per screen, like other per-screen modes. They are not carried
into the alternate screen, which starts with them off, and the main screen's
settings are restored on leaving it. The exception is a soft reset (DECSTR) on
the alternate screen, which clears them, so they are off when the main screen
returns. ``CSI ? s`` and ``CSI ? r`` save and restore both modes and the
direction set by SCP. As for other modes, the saved values are shared by the
two screens, so ``CSI ? r`` on the alternate screen can turn on settings saved
on the main screen.

Only the display is reordered. Text stays in logical order, so selecting and
copying work on logical cells, and cell-based mouse reports carry logical
columns. SGR-pixel mouse reports carry the pointer's pixel position as drawn.
The text cursor, and any :doc:`extra cursors </multiple-cursors-protocol>`,
are drawn at the visual column of their cell. A beam cursor on a right-to-left
cell is drawn on the right edge of the cell, except in the last column, where it
is drawn on its left edge.
The input method editor is anchored at the left edge of the cursor cell, and
the pre-edit text is drawn as without bidi mode.

When kitty writes the screen and scrollback as text with formatting, for the
scrollback pager, ``kitten @ get-text --ansi`` or a saved session, the settings
are included. The controls a paragraph's settings stand for are set where the
text of its first line holding settings starts, and reset to their defaults,
with ``CSI 8 l``, ``CSI ? 2501 l`` and ``CSI 0 SP k``, where the paragraph ends.
Only the controls that differ from their defaults are written. So the controls
are at their defaults at every hard line break, and text written back is laid
out as it was. When the oldest text of the scrollback pager history is dropped
to make room, the history may start inside a paragraph, without its controls.

Text written with the :doc:`text sizing protocol </text-sizing-protocol>` at a
scale (``s``) above 1 is never moved: it keeps its columns, and the text on
either side of it is reordered within its own span. A multicell character of
scale 1 is reordered as one unit, so text of mixed direction inside it is not
reordered. A paragraph that holds an image placeholder is not reordered.

Right-to-left runs are shaped without contextual alternates (``calt``),
whatever :opt:`disable_ligatures` is set to, as in a right-to-left run they can
turn an operator such as ``=>`` into another one.

In a vertically scrolling
:doc:`smooth scroll region </smooth-scrolling-protocol>` as wide as the screen,
lines are laid out as outside a region. A vertically scrolling region narrower
than the screen is a span of its own: its text is reordered within the region,
and the text on either side within its own span. The cells of a horizontally
scrolling region keep their columns, and the text on either side is reordered
within its own span.

Limitations:

* Embeddings and overrides (LRE, RLE, LRO, RLO and PDF) are treated as
  neutral. Of the isolates (LRI, RLI, FSI and PDI) in the rows laid out, only
  the first 32 are honoured. A mark written between two letters of the other
  direction does not split their run.
* A paragraph is laid out from its rows in view and up to a screen height of
  its rows above and below them. With ``CSI ? 2501 h`` the direction of a
  longer paragraph is taken from those rows, so it can change as the screen
  scrolls.
* A ligature, or an icon with its trailing spaces, that crosses the edge of a
  region narrower than the screen or a change of embedding level is split
  there.
* When a region moves the first rows of a paragraph into the rows it keeps out
  of view, the rows left on screen are laid out as a paragraph of their own.
  Text a horizontally scrolling region moves out of view comes back without
  settings.
* With :opt:`pixel_scroll` off, the partially visible scrollback row at the top
  of a region that uses the scrollback is drawn as without bidi mode.

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
