Changelog
==============

version 0.4.0 [future]
-----------------------

  - Refactor kitty's internals to make it even faster and more efficient. The
    CPU usage of kitty + X server while doing intensive tasks such as scrolling
    a file continuously in less has been reduced by 50%. There are now two
    configuration options ``repaint_delay`` and ``input_delay`` you can use to
    fine tune kitty's performance vs CPU usage profile. The CPU usage of kitty
    + X when scrolling in less is now better than most (all?) other terminals.

  - Hovering over URLs with the mouse now underlines them to indicate they
    can be clicked. Hold down Ctrl+Shift while clicking to open the URL.

  - Selection using the mouse is now more intelligent. It does not add
    blank cells (i.e. cells that have no content) after the end of text in a
    line to the selection.

  - The block cursor in now fully opaque but renders the character under it in
    the background color, for enhanced visibility.
