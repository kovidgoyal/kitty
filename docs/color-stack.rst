Color control
====================

Saving and restoring colors
------------------------------

It is often useful for a full screen application with its own color themes to
set the default foreground, background, selection and cursor colors and the ANSI
color table. This allows for various performance optimizations when drawing the
screen. The problem is that if the user previously used the escape codes to
change these colors themselves, then running the full screen application will
lose those changes even after it exits. To avoid this, kitty introduces a new
pair of *OSC* escape codes to push and pop the current color values from a
stack::

    <ESC>]30001<ESC>\  # push onto stack
    <ESC>]30101<ESC>\  # pop from stack

These escape codes save/restore the colors, default background, default
foreground, selection background, selection foreground and cursor color and the
256 colors of the ANSI color table.

.. note:: In July 2020, after several years, xterm copied this protocol
   extension, without acknowledgement, and using incompatible escape codes
   (XTPUSHCOLORS, XTPOPCOLORS, XTREPORTCOLORS). And they decided to save not
   just the dynamic colors but the entire ANSI color table. In the interests of
   promoting interoperability, kitty added support for xterm's escape codes as
   well, and changed this extension to also save/restore the entire ANSI color
   table.

.. _color_control:

Setting and querying colors
-------------------------------

While there exists a legacy protocol developed by XTerm for querying and
setting colors, as with most XTerm protocols it suffers from the usual design
limitations of being under specified and in-sufficient. XTerm implements
querying of colors using OSC 4,5,6,10-19,104,105,106,110-119. This absurd
profusion of numbers is completely unnecessary, redundant and requires adding
two new numbers for every new color. Also XTerm's protocol doesn't handle the
case of colors that are unknown to the terminal or that are not a set value,
for example, many terminals implement selection as a reverse video effect not a
fixed color. The XTerm protocol has no way to query for this condition. The
protocol also doesn't actually specify the format in which colors are reported,
deferring to a man page for X11!

Instead kitty has developed a single number based protocol that addresses all
these shortcomings and is future proof by virtue of using string keys rather
than numbers. The syntax of the escape code is::

    <OSC> 21 ; key=value ; key=value ; ... <ST>

The spaces in the above definition are for reading clarity and should be ignored.
Here, ``<OSC>`` is the two bytes ``0x1b (ESC)`` and ``0x5d (])``. ``ST`` is
either ``0x7 (BEL)`` or the two bytes ``0x1b (ESC)`` and ``0x5c (\\)``.

``key`` is a number from 0-255 to query or set the color values from the
terminals ANSI color table, or one of the strings in the table below for
special colors:

================================= =============================================== ===============================
key                               meaning                                         dynamic
================================= =============================================== ===============================
foreground                        The default foreground text color               Not applicable
background                        The default background text color               Not applicable
selection_background              The background color of selections              Reverse video
selection_foreground              The foreground color of selections              Reverse video
cursor                            The color of the text cursor                    Foreground color
cursor_text                       The color of text under the cursor              Background color
visual_bell                       The color of a visual bell                      Automatic color selection based on current screen colors
transparent_background_color1..7  A background color that is rendered             Unset
                                  with the specified opacity in cells that have
                                  the specified background color. An opacity
                                  value less than zero means, use the
                                  :opt:`background_opacity` value.
================================= =============================================== ===============================

In this table the third column shows what effect setting the color to *dynamic*
has in kitty and many other terminal emulators. It is advisory only, terminal
emulators may not support dynamic colors for these or they may have other
effects. Setting the ANSI color table colors to dynamic is not allowed.

Querying current color values
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

To query colors values, the client program sends this escape code with the
``value`` field set to ``?`` (the byte ``0x3f``). The terminal then responds
with the same escape code, but with the ``?`` replaced by the :ref:`encoded
color value <color_control_color_encoding>`. If the queried color is one that
does not have a defined value, for example, if the terminal is using a reverse
video effect or a gradient or similar, then the value must be empty, that is
the response contains only the key and ``=``, no value. For example, if the
client sends::

    <OSC> 21 ; foreground=? ; cursor=? <ST>

The terminal responds::

    <OSC> 21 ; foreground=rgb:ff/00/00 ; cursor= <ST>

This indicates that the foreground color is red and the cursor color is
undefined (typically the cursor takes the color of the text under it and the
text takes the color of the background).

If the terminal does not know a field that a client send to it for a query it
must respond back with the ``field=?``, that is, it must send back a question
mark as the value.


Setting color values
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

To set a color value, the client program sends this escape code with the
``value`` field set to either an :ref:`encoded color value
<color_control_color_encoding>` or the empty value. The empty value means
the terminal should use a dynamic color for example reverse video for
selections or similar. To reset a color to its default value (i.e. the value it
would have if it was never set) the client program should send just the key
name with no ``=`` and no value. For example::

    <OSC> 21 ; foreground=green ; cursor= ; background <ST>

This sets the foreground to the color green, sets the cursor color to dynamic
(usually meaning the cursor takes the color of the text under it) and resets
the background color to its default value.

To check if setting succeeded, the client can simply query the color, in fact
the two can be combined into a single escape code, for example::

    <OSC> 21 ; foreground=white ; foreground=? <ST>

The terminal will change the foreground color and reply with the new foreground
color.


.. _color_control_color_encoding:

Color value encoding
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

The color encoding is inherited from the scheme used by XTerm, for
compatibility, but a sane, rigorously specified subset is chosen.

RGB colors are encoded in one of three forms:

``rgb:<red>/<green>/<blue>``
    | <red>, <green>, <blue> := h | hh | hhh | hhhh
    | h := single hexadecimal digits (case insignificant)
    | Note that h indicates the value scaled in 4 bits, hh the value scaled in 8 bits,
      hhh the value scaled in 12 bits, and hhhh the value scaled in 16 bits, respectively.

``#<h...>``
    | h := single hexadecimal digits (case insignificant)
    | #RGB            (4 bits each)
    | #RRGGBB         (8 bits each)
    | #RRRGGGBBB      (12 bits each)
    | #RRRRGGGGBBBB   (16 bits each)
    | The R, G, and B represent single hexadecimal digits.  When fewer than 16 bits
      each are specified, they represent the most significant bits of the value
      (unlike the “rgb:” syntax, in which values are scaled). For example,
      the string ``#3a7`` is the same as ``#3000a0007000``.

``rgbi:<red>/<green>/<blue>``
    red, green, and blue are floating-point values between 0.0 and 1.0, inclusive. The input format for these values is an optional
    sign, a string of numbers possibly containing a decimal point, and an optional exponent field containing an E or e followed by a possibly
    signed integer string. Values outside the ``0 - 1`` range must be clipped to be within the range.

If a color should have an alpha component, it must be suffixed to the color
specification in the form :code:`@number between zero and one`. For example::

    red@0.5 rgb:ff0000@0.1 #ff0000@0.3

The syntax for the floating point alpha component is the same as used for the
components of ``rgbi`` defined above. When not specified, the default alpha
value is ``1.0``. Values outside the range ``0 - 1`` must be clipped
to be within the range, negative values may have special context dependent
meaning.

In addition, the following color names are accepted (case-insensitively) corresponding to the
specified RGB values.

.. include:: generated/color-names.rst
