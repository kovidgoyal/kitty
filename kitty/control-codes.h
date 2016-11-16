/*
 * control_codes.h
 * Copyright (C) 2016 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#pragma once

// Space
#define SP  ' '

// *Null*: Does nothing.
#define NUL 0

// *Bell*: Beeps.
#define BEL 0x07

// *Backspace*: Backspace one column, but not past the begining of the
// line.
#define BS 0x08

// *Horizontal tab*: Move cursor to the next tab stop, or to the end
// of the line if there is no earlier tab stop.
#define HT 0x09

// *Linefeed*: Give a line feed, and, if :data:`pyte.modes.LNM` (new
// line mode) is set also a carriage return.
#define LF 10

// *Vertical tab*: Same as :data:`LF`.
#define VT 0x0b
// *Form feed*: Same as :data:`LF`.
#define FF 0x0c

// *Carriage return*: Move cursor to left margin on current line.
#define CR 13

// *Shift out*: Activate G1 character set.
#define SO 0x0e

// *Shift in*: Activate G0 character set.
#define SI 0x0f

// *Cancel*: Interrupt escape sequence. If received during an escape or
// control sequence, cancels the sequence and displays substitution
// character.
#define CAN 0x18
// *Substitute*: Same as :data:`CAN`.
#define SUB 0x1a

// *Escape*: Starts an escape sequence.
#define ESC 0x1b

// *Delete*: Is ignored.
#define DEL 0x7f

// *Control sequence introducer*: An equivalent for ``ESC [``.
#define CSI 0x9b

// *String terminator*.
#define ST 0x9c

// *Operating system command*.
#define OSC 0x9d

// Sharp control codes

// Align display 
#define DECALN '8'

// Esc control codes

// *Reset*.
#define RIS 'c'

// *Index*: Move cursor down one line in same column. If the cursor is
// at the bottom margin, the screen performs a scroll-up.
#define IND 'D'

// *Next line*: Same as :data:`pyte.control.LF`.
#define NEL 'E'

// Tabulation set: Set a horizontal tab stop at cursor position.
#define HTS 'H'

// *Reverse index*: Move cursor up one line in same column. If the
// cursor is at the top margin, the screen performs a scroll-down.
#define RI 'M'

// Save cursor: Save cursor position, character attribute (graphic
// rendition), character set, and origin mode selection (see
// :data:`DECRC`).
#define DECSC '7'

// *Restore cursor*: Restore previously saved cursor position, character
// attribute (graphic rendition), character set, and origin mode
// selection. If none were saved, move cursor to home position.
#define DECRC '8'

// Set normal keypad mode
#define DECPNM '>'

// Set alternate keypad mode
#define DECPAM  '='


