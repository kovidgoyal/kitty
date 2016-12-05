kitty - A terminal emulator
============================

[![Build Status](https://travis-ci.org/kovidgoyal/kitty.svg?branch=master)](https://travis-ci.org/kovidgoyal/kitty)

Major features:

  * Uses OpenGL+FreeType for rendering
  * Supports tiling multiple terminal windows side by side in different layouts
    without needing to use an extra program like tmux
  * Supports all modern terminal features: unicode, true-color, mouse protocol,
    focus tracking, bracketed paste and so on.
  * Easily hackable (UI layer written in python, inner loops in C for speed).
    Less than ten thousand lines of code.
  * Rendering of text is done in an actual character grid, so the common
    problems with most Terminals when using wide characters/complex scripts do
    not occur. The downside is that scripts with complex glyph layout, such as
    Arabic do not render well.


Resources on terminal behavior
------------------------------------------

http://invisible-island.net/xterm/ctlseqs/ctlseqs.html

https://en.wikipedia.org/wiki/C0_and_C1_control_codes

http://vt100.net/
