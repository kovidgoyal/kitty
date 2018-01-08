/*
 * modes.h
 * Copyright (C) 2016 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#pragma once

/* *Line Feed/New Line Mode*: When enabled, causes a received
   LF, FF, or VT to move the cursor to the first column of
   the next line.
*/
#define LNM 20

/* *Insert/Replace Mode*: When enabled, new display characters move
   old display characters to the right. Characters moved past the
   right margin are lost. Otherwise, new display characters replace
   old display characters at the cursor position.
*/
#define IRM 4


// Private modes.

// Arrow keys send application sequences or cursor movement commands
#define DECCKM (1 << 5)

// *Column Mode*: selects the number of columns per line (80 or 132)
// on the screen.
#define DECCOLM (3 << 5)

// Scroll speed
#define DECSCLM (4 << 5)

// *Screen Mode*: toggles screen-wide reverse-video mode.
#define DECSCNM  (5 << 5)

// Auto-repeat of keys
#define DECARM (8 << 5)

/* *Origin Mode*: allows cursor addressing relative to a user-defined
   origin. This mode resets when the terminal is powered up or reset.
   It does not affect the erase in display (ED) function.
*/
#define DECOM  (6 << 5)

// *Auto Wrap Mode*: selects where received graphic characters appear
// when the cursor is at the right margin.
#define DECAWM (7 << 5)

// Toggle cursor blinking
#define CONTROL_CURSOR_BLINK (12 << 5)

// *Text Cursor Enable Mode*: determines if the text cursor is visible.
#define DECTCEM (25 << 5)

// National Replacement Character Set Mode
#define DECNRCM (42 << 5)

// Xterm mouse protocol
#define MOUSE_BUTTON_TRACKING (1000 << 5)
#define MOUSE_MOTION_TRACKING  (1002 << 5)
#define MOUSE_MOVE_TRACKING (1003 << 5)
#define FOCUS_TRACKING (1004 << 5)
#define MOUSE_UTF8_MODE (1005 << 5)
#define MOUSE_SGR_MODE (1006 << 5)
#define MOUSE_URXVT_MODE (1015 << 5)

// Alternate screen buffer
#define ALTERNATE_SCREEN  (1049 << 5)

// Bracketed paste mode
// http://cirw.in/blog/bracketed-paste
#define BRACKETED_PASTE (2004 << 5)
#define BRACKETED_PASTE_START "200~"
#define BRACKETED_PASTE_END  "201~"

// Styled underlines
#define STYLED_UNDERLINES (2016 << 5)

// Extended keyboard protocol
#define EXTENDED_KEYBOARD (2017 << 5)
