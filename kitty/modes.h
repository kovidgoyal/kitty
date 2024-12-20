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

// xterm mouse protocol
#define MOUSE_BUTTON_TRACKING (1000 << 5)
#define MOUSE_MOTION_TRACKING  (1002 << 5)
#define MOUSE_MOVE_TRACKING (1003 << 5)
#define FOCUS_TRACKING (1004 << 5)
#define MOUSE_UTF8_MODE (1005 << 5)
#define MOUSE_SGR_MODE (1006 << 5)
#define MOUSE_URXVT_MODE (1015 << 5)
#define MOUSE_SGR_PIXEL_MODE (1016 << 5)

// Save cursor (DECSC)
#define SAVE_CURSOR (1048 << 5)

// Alternate screen buffer
#define TOGGLE_ALT_SCREEN_1 (47 << 5)
#define TOGGLE_ALT_SCREEN_2 (1047 << 5)
#define ALTERNATE_SCREEN  (1049 << 5)

// Bracketed paste mode
// https://cirw.in/blog/bracketed-paste
#define BRACKETED_PASTE (2004 << 5)
#define BRACKETED_PASTE_START "200~"
#define BRACKETED_PASTE_END  "201~"

// Pending updates mode
#define PENDING_UPDATE (2026 << 5)

// Notification of color preference change
#define COLOR_PREFERENCE_NOTIFICATION (2031 << 5)

// In-band resize notification mode
#define INBAND_RESIZE_NOTIFICATION (2048 << 5)

// Handle Ctrl-C/Ctrl-Z mode
#define HANDLE_TERMIOS_SIGNALS (19997 << 5)
