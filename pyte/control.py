# -*- coding: utf-8 -*-
"""
    pyte.control
    ~~~~~~~~~~~~

    This module defines simple control sequences, recognized by
    :class:`~pyte.streams.Stream`, the set of codes here is for
    ``TERM=linux`` which is a superset of VT102.

    :copyright: (c) 2011-2012 by Selectel.
    :copyright: (c) 2012-2016 by pyte authors and contributors,
                    see AUTHORS for details.
    :license: LGPL, see LICENSE for more details.
"""

#: *Space*: Not suprisingly -- ``" "``.
SP = b" "

#: *Null*: Does nothing.
NUL = b"\x00"

#: *Bell*: Beeps.
BEL = b"\x07"

#: *Backspace*: Backspace one column, but not past the begining of the
#: line.
BS = b"\x08"

#: *Horizontal tab*: Move cursor to the next tab stop, or to the end
#: of the line if there is no earlier tab stop.
HT = b"\x09"

#: *Linefeed*: Give a line feed, and, if :data:`pyte.modes.LNM` (new
#: line mode) is set also a carriage return.
LF = b"\n"
#: *Vertical tab*: Same as :data:`LF`.
VT = b"\x0b"
#: *Form feed*: Same as :data:`LF`.
FF = b"\x0c"

#: *Carriage return*: Move cursor to left margin on current line.
CR = b"\r"

#: *Shift out*: Activate G1 character set.
SO = b"\x0e"

#: *Shift in*: Activate G0 character set.
SI = b"\x0f"

#: *Cancel*: Interrupt escape sequence. If received during an escape or
#: control sequence, cancels the sequence and displays substitution
#: character.
CAN = b"\x18"
#: *Substitute*: Same as :data:`CAN`.
SUB = b"\x1a"

#: *Escape*: Starts an escape sequence.
ESC = b"\x1b"

#: *Delete*: Is ignored.
DEL = b"\x7f"

#: *Control sequence introducer*: An equivalent for ``ESC [``.
CSI = b"\x9b"

#: *String terminator*.
ST = b"\x9c"

#: *Operating system command*.
OSC = b"\x9d"
