kitty - A terminal emulator
============================

[![Build Status](https://travis-ci.org/kovidgoyal/kitty.svg?branch=master)](https://travis-ci.org/kovidgoyal/kitty)

Major features:

  * Uses OpenGL+FreeType for rendering, does not depend on any GUI toolkits.
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

Installation
--------------

kitty is designed to run from source, for easy hackability. Make sure the
following dependencies are installed first:

    * python >= 3.5
    * glew >= 2.0
    * glfw-dev >= 3.2
    * freetype
    * fontconfig
    * gcc (required for building, clang should also work, but it is not tested)
    * pkg-config (required for building)

Now build the C parts of kitty with the following command:

    python3 setup.py build

You can run kitty, as:

    python3 /path/to/kitty/folder

Configuration
---------------

kitty is highly customizable, everything from keyboard shortcuts, to painting
frames-per-second. See the heavily commented [default config file](kitty/kitty.conf).
By default kitty looks for a config file in the OS
config directory (usually `~/.config/kitty/kitty.conf` on linux) but you can pass
a specific path via the `--config` option.


Resources on terminal behavior
------------------------------------------

http://invisible-island.net/xterm/ctlseqs/ctlseqs.html

https://en.wikipedia.org/wiki/C0_and_C1_control_codes

http://vt100.net/
