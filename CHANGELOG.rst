Changelog
==============

kitty is a feature full, cross-platform, *fast*, GPU based terminal emulator.

version 0.7.1 [future]
---------------------------

- Add an option to adjust the width of character cells

- Fix selecting text with the mouse in the scrollback buffer selecting text
  from the line above the actually selected line

- Fix some italic fonts having the right edge of characters cut-off,
  unnecessarily


version 0.7.0 [2018-01-24]
---------------------------

- Allow controlling kitty from the shell prompt/scripts. You can
  open/close/rename windows and tabs and even send input to specific windows.
  See the README for details.

- Add option to put tab bar at the top instead of the bottom

- Add option to override the default shell

- Add "Horizontal" and "Vertical" window layouts

- Sessions: Allow setting titles and working directories for individual windows 

- Option to copy to clipboard on mouse select

- Fix incorrect reporting of mouse move events when using the SGR protocol

- Make alt+backspace delete the previous word

- Take the mouse wheel multiplier option in to account when generating fake key
  scroll events

- macOS: Fix closing top-level window does not transfer focus to other
  top-level windows.

- macOS: Fix alt+arrow keys not working when disabling the macos_option_as_alt
  config option.

- kitty icat: Workaround for bug in ImageMagick that would cause some images
  to fail to display at certain sizes.

- Fix rendering of text with ligature fonts that do not use dummy glyphs

- Fix a regression that caused copying of the selection to clipboard to only
  copy the visible part of the selection

- Fix incorrect handling of some unicode combining marks that are not re-ordered

- Fix handling on non-BMP combining characters

- Drop the dependency on libunistring


version 0.6.1 [2017-12-28]
---------------------------

- Add an option to fade the text in inactive windows

- Add new actions to open windows/tabs/etc. with the working directory set to 
  the working directory of the current window.

- Automatically adjust cell size when DPI changes, for example when kitty is
  moved from one monitor to another with a different DPI

- Ensure underlines are rendered even for fonts with very poor metrics

- Fix some emoji glyphs not colored on Linux

- Internal wcwidth() implementation is now auto-generated from the unicode
  standard database

- Allow configuring the modifiers to use for rectangular selection with the
  mouse.

- Fix incorrect minimum wayland version in the build script

- Fix a crash when detecting a URL that ends at the end of the line

- Fix regression that broke drawing of hollow cursor when window loses focus


version 0.6.0 [2017-12-18]
---------------------------

- Support background transparency via the background_opacity option. Provided
  that your OS/window manager supports transparency, you can now have kitty
  render pixels that have only the default background color as
  semi-transparent.

- Support multiple top level (OS) windows. These windows all share the sprite
  texture cache on the GPU, further reducing overall resource usage. Use
  the shortcut `ctrl+shift+n` to open a new top-level window.

- Add support for a *daemon* mode using the `--single-instance` command line
  option. With this option you can have only a single kitty instance running.
  All future invocations simply open new top-level windows in the existing
  instance.

- Support colored emoji

- Use CoreText instead of FreeType to render text on macOS

- Support running on the "low power" GPU on dual GPU macOS machines

- Add a new "grid" window layout

- Drop the dependency on glfw (kitty now uses a modified, bundled copy of glfw)

- Add an option to control the audio bell volume on X11 systems

- Add a command line switch to set the name part of the WM_CLASS window
  property independently.

- Add a command line switch to set the window title.

- Add more options to customize the tab-bar's appearance (font styles and
  separator)

- Allow drag and drop of files into kitty. On drop kitty will paste the
  file path to the running program.

- Add an option to control the underline style for URL highlighting on hover

- X11: Set the WINDOWID environment variable 

- Fix middle and right buttons swapped when sending mouse events to child
  processes

- Allow selecting in a rectangle by holding down Ctrl+Alt while dragging with
  the mouse.


version 0.5.1 [2017-12-01]
---------------------------

- Add an option to control the thickness of lines in box drawing characters

- Increase max. allowed ligature length to nine characters

- Fix text not vertically centered when adjusting line height

- Fix unicode block characters not being rendered properly

- Fix shift+up/down not generating correct escape codes

- Image display: Fix displaying images taller than two screen heights not
  scrolling properly


version 0.5.0 [2017-11-19]
---------------------------

- Add support for ligature fonts such as Fira Code, Hasklig, etc. kitty now
  uses harfbuzz for text shaping which allow it to support advanced OpenType
  features such as contextual alternates/ligatures/combining glyphs/etc.

- Make it easy to select fonts by allowing listing of monospace fonts using:
  kitty list-fonts

- Add an option to have window focus follow mouse

- Add a keyboard shortcut (ctrl+shift+f11) to toggle fullscreen mode

- macOS: Fix handling of option key. It now behaves just like the alt key on
  Linux. There is an option to make it type unicode characters instead.

- Linux: Add support for startup notification on X11 desktops. kitty will
  now inform the window manager when its startup is complete.

- Fix shell prompt being duplicated when window is resized

- Fix crash when displaying more than 64 images in the same session

- Add support for colons in SGR color codes. These are generated by some
  applications such as neovim when they mistakenly identify kitty as a libvte
  based terminal.

- Fix mouse interaction not working in apps using obsolete mouse interaction
  protocols

- Linux: no longer require glew as a dependency


version 0.4.2 [2017-10-23]
---------------------------

- Fix a regression in 0.4.0 that broke custom key mappings

- Fix a regression in 0.4.0 that broke support for non-QWERTY keyboard layouts 

- Avoid using threads to reap zombie child processes. Also prevent kitty from
  hanging if the open program hangs when clicking on a URL.


version 0.4.0 [2017-10-22]
---------------------------

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
