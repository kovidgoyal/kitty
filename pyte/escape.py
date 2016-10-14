# -*- coding: utf-8 -*-
"""
    pyte.escape
    ~~~~~~~~~~~

    This module defines both CSI and non-CSI escape sequences, recognized
    by :class:`~pyte.streams.Stream` and subclasses.

    :copyright: (c) 2011-2012 by Selectel.
    :copyright: (c) 2012-2016 by pyte authors and contributors,
                    see AUTHORS for details.
    :license: LGPL, see LICENSE for more details.
"""

#: *Reset*.
RIS = b"c"

#: *Index*: Move cursor down one line in same column. If the cursor is
#: at the bottom margin, the screen performs a scroll-up.
IND = b"D"

#: *Next line*: Same as :data:`pyte.control.LF`.
NEL = b"E"

#: Tabulation set: Set a horizontal tab stop at cursor position.
HTS = b"H"

#: *Reverse index*: Move cursor up one line in same column. If the
#: cursor is at the top margin, the screen performs a scroll-down.
RI = b"M"

#: Save cursor: Save cursor position, character attribute (graphic
#: rendition), character set, and origin mode selection (see
#: :data:`DECRC`).
DECSC = b"7"

#: *Restore cursor*: Restore previously saved cursor position, character
#: attribute (graphic rendition), character set, and origin mode
#: selection. If none were saved, move cursor to home position.
DECRC = b"8"

# "Sharp" escape sequences.
# -------------------------

#: *Alignment display*: Fill screen with uppercase E's for testing
#: screen focus and alignment.
DECALN = b"8"


# ECMA-48 CSI sequences.
# ---------------------

#: *Insert character*: Insert the indicated # of blank characters.
ICH = b"@"

#: *Cursor up*: Move cursor up the indicated # of lines in same column.
#: Cursor stops at top margin.
CUU = b"A"

#: *Cursor down*: Move cursor down the indicated # of lines in same
#: column. Cursor stops at bottom margin.
CUD = b"B"

#: *Cursor forward*: Move cursor right the indicated # of columns.
#: Cursor stops at right margin.
CUF = b"C"

#: *Cursor back*: Move cursor left the indicated # of columns. Cursor
#: stops at left margin.
CUB = b"D"

#: *Cursor next line*: Move cursor down the indicated # of lines to
#: column 1.
CNL = b"E"

#: *Cursor previous line*: Move cursor up the indicated # of lines to
#: column 1.
CPL = b"F"

#: *Cursor horizontal align*: Move cursor to the indicated column in
#: current line.
CHA = b"G"

#: *Cursor position*: Move cursor to the indicated line, column (origin
#: at ``1, 1``).
CUP = b"H"

#: *Erase data* (default: from cursor to end of line).
ED = b"J"

#: *Erase in line* (default: from cursor to end of line).
EL = b"K"

#: *Insert line*: Insert the indicated # of blank lines, starting from
#: the current line. Lines displayed below cursor move down. Lines moved
#: past the bottom margin are lost.
IL = b"L"

#: *Delete line*: Delete the indicated # of lines, starting from the
#: current line. As lines are deleted, lines displayed below cursor
#: move up. Lines added to bottom of screen have spaces with same
#: character attributes as last line move up.
DL = b"M"

#: *Delete character*: Delete the indicated # of characters on the
#: current line. When character is deleted, all characters to the right
#: of cursor move left.
DCH = b"P"

#: *Erase character*: Erase the indicated # of characters on the
#: current line.
ECH = b"X"

#: *Horizontal position relative*: Same as :data:`CUF`.
HPR = b"a"

#: *Device Attributes*.
DA = b"c"

#: *Vertical position adjust*: Move cursor to the indicated line,
#: current column.
VPA = b"d"

#: *Vertical position relative*: Same as :data:`CUD`.
VPR = b"e"

#: *Horizontal / Vertical position*: Same as :data:`CUP`.
HVP = b"f"

#: *Tabulation clear*: Clears a horizontal tab stop at cursor position.
TBC = b"g"

#: *Set mode*.
SM = b"h"

#: *Reset mode*.
RM = b"l"

#: *Select graphics rendition*: The terminal can display the following
#: character attributes that change the character display without
#: changing the character (see :mod:`pyte.graphics`).
SGR = b"m"

#: *Device status report*.
DSR = b"n"

#: *Select top and bottom margins*: Selects margins, defining the
#: scrolling region; parameters are top and bottom line. If called
#: without any arguments, whole screen is used.
DECSTBM = b"r"

#: *Horizontal position adjust*: Same as :data:`CHA`.
HPA = b"'"
