Changelog
==============

kitty is a feature full, hackable, OpenGL based terminal emulator.

version 0.4.0 [future]
-----------------------

- Support for drawing arbitrary raster graphics (images) in the terminal via a
  new graphics protocol. kitty can draw images with full 32-bit color using both
  ssh connections and files/shared memory (when available) for better
  performance. The drawing primitives support alpha blending and z-index.
  Images can be drawn both above and below text. See
  https://github.com/kovidgoyal/kitty/blob/master/graphics-protocol.asciidoc
  for details. 

- Refactor kitty's internals to make it even faster and more efficient. The CPU
  usage of kitty + X server while doing intensive tasks such as scrolling a
  file continuously in less has been reduced by 50%. There are now two
  configuration options ``repaint_delay`` and ``input_delay`` you can use to
  fine tune kitty's performance vs CPU usage profile. The CPU usage of kitty +
  X when scrolling in less is now significantly better than most (all?) other
  terminals. See https://github.com/kovidgoyal/kitty#performance

- Hovering over URLs with the mouse now underlines them to indicate they
  can be clicked. Hold down Ctrl+Shift while clicking to open the URL.

- Selection using the mouse is now more intelligent. It does not add
  blank cells (i.e. cells that have no content) after the end of text in a
  line to the selection.

- The block cursor in now fully opaque but renders the character under it in
  the background color, for enhanced visibility.

- Allow combining multiple independent actions into a single shortcut

- Add a new shortcut to pass the current selection to an external program

- Allow creating shortcuts to open new windows running arbitrary commands. You
  can also pass the current selection to the command as an arguments and the
  contents of the screen + scrollback buffer as stdin to the command.
