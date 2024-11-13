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

// *Backspace*: Backspace one column, but not past the beginning of the
// line.
#define BS 0x08

// *Horizontal tab*: Move cursor to the next tab stop, or to the end
// of the line if there is no earlier tab stop.
#define HT 0x09

// *Linefeed*: Give a line feed, and, if LNM (new
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

// Sharp control codes
// -------------------

// Align display
#define DECALN '8'

// Esc control codes
// ------------------

#define ESC_DCS 'P'
#define ESC_OSC ']'
#define ESC_CSI '['
#define ESC_ST '\\'
#define ESC_PM '^'
#define ESC_APC '_'
#define ESC_SOS 'X'

// *Reset*.
#define ESC_RIS 'c'

// *Index*: Move cursor down one line in same column. If the cursor is
// at the bottom margin, the screen performs a scroll-up.
#define ESC_IND 'D'

// *Next line*: Same as LF.
#define ESC_NEL 'E'

// Tabulation set: Set a horizontal tab stop at cursor position.
#define ESC_HTS 'H'

// *Reverse index*: Move cursor up one line in same column. If the
// cursor is at the top margin, the screen performs a scroll-down.
#define ESC_RI 'M'

// Save cursor: Save cursor position, character attribute (graphic
// rendition), character set, and origin mode selection (see
// :data:`DECRC`).
#define ESC_DECSC '7'

// *Restore cursor*: Restore previously saved cursor position, character
// attribute (graphic rendition), character set, and origin mode
// selection. If none were saved, move cursor to home position.
#define ESC_DECRC '8'

// Set normal keypad mode
#define ESC_DECKPNM '>'

// Set alternate keypad mode
#define ESC_DECKPAM  '='

// ECMA-48 CSI sequences.
// ---------------------

// *Insert character*: Insert the indicated # of blank characters.
#define ICH '@'

// *Cursor up*: Move cursor up the indicated # of lines in same column.
// Cursor stops at top margin.
#define CUU 'A'

// *Cursor down*: Move cursor down the indicated # of lines in same
// column. Cursor stops at bottom margin.
#define CUD 'B'

// *Cursor forward*: Move cursor right the indicated # of columns.
// Cursor stops at right margin.
#define CUF 'C'

// *Cursor back*: Move cursor left the indicated # of columns. Cursor
// stops at left margin.
#define CUB 'D'

// *Cursor next line*: Move cursor down the indicated # of lines to
// column 1.
#define CNL 'E'

// *Cursor previous line*: Move cursor up the indicated # of lines to
// column 1.
#define CPL 'F'

// *Cursor horizontal align*: Move cursor to the indicated column in
// current line.
#define CHA 'G'

// *Cursor position*: Move cursor to the indicated line, column (origin
// at ``1, 1``).
#define CUP 'H'

// *Erase data* (default: from cursor to end of line).
#define ED 'J'

// *Erase in line* (default: from cursor to end of line).
#define EL 'K'

// *Insert line*: Insert the indicated # of blank lines, starting from
// the current line. Lines displayed below cursor move down. Lines moved
// past the bottom margin are lost.
#define IL 'L'

// *Delete line*: Delete the indicated # of lines, starting from the
// current line. As lines are deleted, lines displayed below cursor
// move up. Lines added to bottom of screen have spaces with same
// character attributes as last line move up.
#define DL 'M'

// *Delete character*: Delete the indicated # of characters on the
// current line. When character is deleted, all characters to the right
// of cursor move left.
#define DCH 'P'

// Scroll up by the specified number of lines
#define SU 'S'

// Scroll down by the specified number of lines
#define SD 'T'

// *Erase character*: Erase the indicated # of characters on the
// current line.
#define ECH 'X'

// *Horizontal position relative*: Same as :data:`CUF`.
#define HPR 'a'

// Repeat the preceding graphic character Ps times.
#define REP 'b'

// *Device Attributes*.
#define DA 'c'

// *Vertical position adjust*: Move cursor to the indicated line,
// current column.
#define VPA 'd'

// *Vertical position relative*: Same as :data:`CUD`.
#define VPR 'e'

// *Horizontal / Vertical position*: Same as :data:`CUP`.
#define HVP 'f'

// *Tabulation clear*: Clears a horizontal tab stop at cursor position.
#define TBC 'g'

// *Set mode*.
#define SM 'h'

// *Reset mode*.
#define RM 'l'

// *Select graphics rendition*: The terminal can display the following
// character attributes that change the character display without
// changing the character
#define SGR 'm'

// *Device status report*.
#define DSR 'n'

// Soft reset
#define DECSTR 'p'

// *Horizontal position adjust*: Same as :data:`CHA`.
#define HPA '`'

// Back tab
#define CBT 'Z'

// Forward tab
#define CHT 'I'

// Misc sequences
// ----------------

// Change cursor shape/blink
#define DECSCUSR 'q'

// File transfer OSC number
#define FILE_TRANSFER_CODE 5113
// Pending mode CSI code
#define PENDING_MODE 2026
// Text size OSC number
#define TEXT_SIZE_CODE 66
