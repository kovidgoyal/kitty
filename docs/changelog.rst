Changelog
==============

|kitty| is a feature full, cross-platform, *fast*, GPU based terminal emulator.
To update |kitty|, :doc:`follow the instructions <binary>`.

0.14.0 [future]
---------------------

- macOS: The default behavior of the Option key has changed. It now generates
  unicode characters rather than acting as the Alt modifier. See
  :opt:`macos_option_as_alt`.

- Support for an arbitrary number of internal clipboard buffers to copy/paste
  from, see (:ref:`cpbuf`)

- Allow using the new private internal clipboard buffers with the
  :opt:`copy_on_select` option (:iss:`1390`)

- macOS: Allow opening new kitty tabs/top-level windows from Finder
  (:pull:`1350`)

- Add an option :opt:`disable_ligatures_under_cursor` to disable
  multi-character ligatures under the cursor to make editing easier
  (:iss:`461`)

- Allow creating new OS windows in session files (:iss:`1514`)

- Allow setting OS window size in session files

- Add an option :opt:`tab_switch_strategy` to control which
  tab becomes active when the current tab is closed (:pull:`1524`)

- Allow specifying a value of ``none`` for the :opt:`selection_foreground`
  which will cause kitty to not change text color in selections (:iss:`1358`)

- Make live resizing of OS windows smoother and show the size in cells
  while the resize is in progress.

- When a window is closed, switch focus to the previously active window (if
  any) instead of picking the previous window in the layout (:iss:`1450`)

- icat kitten: Add support for displaying images at http(s) URLs (:iss:`1340`)

- A new option :opt:`strip_trailing_spaces` to optionally remove trailing
  spaces from lines when copying to clipboard.

- A new option :opt:`tab_bar_min_tabs` to control how many tabs must be
  present before the tab-bar is shown (:iss:`1382`)

- Automatically check for new releases and notify when an update is available,
  via the system notification facilities. Can be controlled by
  :opt:`update_check_interval` (:iss:`1342`)

- macOS: Fix :kbd:`cmd+period` key not working (:iss:`1318`)

- macOS: Add an option :opt:`macos_show_window_title_in_menubar` to not
  show the current window title in the menu-bar (:iss:`1066`)

- macOS: Workaround for cocoa bug that could cause the mouse cursor to become
  hidden in other applications in rare circumstances (:iss:`1218`)

- macOS: Allow assigning only the left or right :kbd:`Option` key to work as the
  :kbd:`Alt` key. See :opt:`macos_option_as_alt` for details (:iss:`1022`)

- Fix using remote control to set cursor text color causing errors when
  creating new windows (:iss:`1326`)

- Fix window title for minimized windows not being updated (:iss:`1332`)

- macOS: Fix using multi-key sequences to input text ignoring the
  first few key presses if the sequence is aborted (:iss:`1311`)

- macOS: Add a number of common macOS keyboard shortcuts

- macOS: Reduce energy consumption by not rendering occluded windows

- Fix scrollback pager history not being cleared when clearing the
  main scrollback buffer (:iss:`1387`)

- macOS: When closing a top-level window only switch focus to the previous kitty
  window if it is on the same workspace (:iss:`1379`)

- macOS: Fix :opt:`sync_to_monitor` not working on Mojave.

- macOS: Use the system cursor blink interval by default
  :opt:`cursor_blink_interval`.

- Wayland: Use the kitty Wayland backend by default. Can be switched back
  to using XWayland by setting the environment variable:
  ``KITTY_DISABLE_WAYLAND=1``

- Add a ``no-append`` setting to :opt:`clipboard_control` to disable
  the kitty copy concatenation protocol extension for OSC 52.

- Update to using the Unicode 12 standard

- macOS: Fix specifying initial window size in cells not working correctly on
  Retina screens (:iss:`1444`)

- Fix a regression in version 0.13.0 that caused background colors of space
  characters after private use unicode characters to not be respected
  (:iss:`1455`)

- Only update the selected text to clipboard when the selection is finished,
  not continuously as it is updated. (:iss:`1460`)

- Allow setting :opt:`active_border_color` to ``none`` to not draw a border
  around the active window (:iss:`805`)


0.13.3 [2019-01-19]
------------------------------

- icat kitten: Add a ``--stdin`` option to control if image data is read from
  STDIN (:iss:`1308`)

- hints kitten: Start hints numbering at one instead of zero by default. Added
  an option ``--hints-offset`` to control it. (:iss:`1289`)

- Fix a regression in the previous release that broke using ``background`` for
  :opt:`cursor_text_color` (:iss:`1288`)

- macOS: Fix dragging kitty window tabs in traditional full screen mode causing
  crashes (:iss:`1296`)

- macOS: Ensure that when running from a bundle, the bundle kitty exe is
  preferred over any kitty in PATH (:iss:`1280`)

- macOS: Fix a regression that broke mapping of :kbd:`ctrl+tab` (:iss:`1304`)

- Add a list of user-created kittens to the docs

- Fix a regression that broke changing mouse wheel scroll direction with
  negative :opt:`wheel_scroll_multiplier` values in full-screen applications
  like vim (:iss:`1299`)

- Fix :opt:`background_opacity` not working with pure white backgrounds
  (:iss:`1285`)

- macOS: Fix "New OS Window" dock action not working when kitty is not focused
  (:iss:`1312`)

- macOS: Add aliases for close window and new tab actions that conform to common
  Apple shortcuts for these actions (:iss:`1313`)

- macOS: Fix some kittens causing 100% CPU usage


0.13.2 [2019-01-04]
------------------------------

- Add a new option :opt:`tab_title_template` to control how tab titles
  are formatted. In particular the template can be used to display
  the tab number next to the title (:iss:`1223`)

- Report the current foreground processes as well as the original child process,
  when using `kitty @ ls`

- Use the current working directory of the foreground process for the
  `*_with_cwd` actions that open a new window with the current working
  directory.

- Add a new ``copy_or_interrupt`` action that can be mapped to kbd:`ctrl+c`. It
  will copy if there is a selection and interrupt otherwise (:iss:`1286`)

- Fix setting :opt:`background_opacity` causing window margins/padding to be slightly
  different shade from background (:iss:`1221`)

- Handle keyboards with a "+" key (:iss:`1224`)

- Fix Private use Unicode area characters followed by spaces at the end of text
  not being rendered correctly (:iss:`1210`)

- macOS: Add an entry to the dock menu to open a new OS window (:iss:`1242`)

- macOS: Fix scrolling very slowly with wheel mice not working (:iss:`1238`)

- Fix changing :opt:`cursor_text_color` via remote control not working
  (:iss:`1229`)

- Add an action to resize windows that can be mapped to shortcuts in :file:`kitty.conf`
  (:pull:`1245`)

- Fix using the ``new_tab !neighbor`` action changing the order of the
  non-neighboring tabs (:iss:`1256`)

- macOS: Fix momentum scrolling continuing when changing the active window/tab
  (:iss:`1267`)


0.13.1 [2018-12-06]
------------------------------

- Fix passing input via the pipe action to a program without a window not
  working.

- Linux: Fix a regression in the previous release that caused automatic
  selection of bold/italic fonts when using aliases such as "monospace" to not
  work (:iss:`1209`)

- Fix resizing window smaller and then restoring causing some wrapped lines to not
  be properly unwrapped (:iss:`1206`)

0.13.0 [2018-12-05]
------------------------------

- Add an option :opt:`scrollback_pager_history_size` to tell kitty to store
  extended scrollback to use when viewing the scrollback buffer in a pager
  (:iss:`970`)

- Modify the kittens sub-system to allow creating custom kittens without any
  user interface. This is useful for creating more complex actions that can
  be bound to key presses in :file:`kitty.conf`. See
  doc:`kittens/custom`. (:iss:`870`)

- Add a new ``nth_window`` action that can be used to go to the nth window and
  also previously active windows, using negative numbers. Similarly,
  ``goto_tab`` now accepts negative numbers to go to previously active tabs
  (:iss:`1040`)

- Allow hiding the tab bar completely, by setting :opt:`tab_bar_style` to
  ``hidden``. (:iss:`1014`)

- Allow private use unicode characters to stretch over more than a single
  neighboring space (:pull:`1036`)

- Add a new :opt:`touch_scroll_multiplier` option to modify the amount
  scrolled by high precision scrolling devices such as touchpads (:pull:`1129`)

- icat kitten: Implement reading image data from STDIN, if STDIN is not
  connected to a terminal (:iss:`1130`)

- hints kitten: Insert trailing spaces after matches when using the
  ``--multiple`` option. Also add a separate ``--add-trailing-space``
  option to control this behavior (:pull:`1132`)

- Fix the ``*_with_cwd`` actions using the cwd of the overlay window rather
  than the underlying window's cwd (:iss:`1045`)

- Fix incorrect key repeat rate on wayland (:pull:`1055`)

- macOS: Fix drag and drop of files not working on Mojave (:iss:`1058`)

- macOS: Fix IME input for East Asian languages (:iss:`910`)

- macOS: Fix rendering frames-per-second very low when processing
  large amounts of input in small chunks (:pull:`1082`)

- macOS: Fix incorrect text sizes calculated when using an external display
  that is set to mirror the main display (:iss:`1056`)

- macOS: Use the system default double click interval (:pull:`1090`)

- macOS: Fix touch scrolling sensitivity low on retina screens (:iss:`1112`)

- Linux: Fix incorrect rendering of some fonts when hinting is disabled at
  small sizes (:iss:`1173`)

- Linux: Fix match rules used as aliases in Fontconfig configuration not being
  respected (:iss:`1085`)

- Linux: Fix a crash when using the GNU Unifont as a fallback font
  (:iss:`1087`)

- Wayland: Fix copying from hidden kitty windows hanging (:iss:`1051`)

- Wayland: Add support for the primary selection protocol
  implemented by some compositors (:pull:`1095`)

- Fix expansion of env vars not working in the :opt:`env` directive
  (:iss:`1075`)

- Fix :opt:`mouse_hide_wait` only taking effect after an event such as cursor
  blink or key press (:iss:`1073`)

- Fix the ``set_background_opacity`` action not working correctly
  (:pull:`1147`)

- Fix second cell of emoji created using variation selectors not having
  the same attributes as the first cell (:iss:`1109`)

- Fix focusing neighboring windows in the grid layout with less than 4 windows
  not working (:iss:`1115`)

- Fix :kbd:`ctrl+shift+special` key not working in normal and application keyboard
  modes (:iss:`1114`)

- Add a terminfo entry for full keyboard mode.

- Fix incorrect text-antialiasing when using very low background opacity
  (:iss:`1005`)

- When double or triple clicking ignore clicks if they are "far" from each
  other (:iss:`1093`)

- Follow xterm's behavior for the menu key (:iss:`597`)

- Fix hover detection of URLs not working when hovering over the first colon
  and slash characters in short URLs (:iss:`1201`)

0.12.3 [2018-09-29]
------------------------------

- macOS: Fix kitty window not being rendered on macOS Mojave until the window is
  moved or resized at least once (:iss:`887`)

- Unicode input: Fix an error when searching for the string 'fir' (:iss:`1035`)


0.12.2 [2018-09-24]
------------------------------

- A new ``last_used_layout`` function that can be mapped to a shortcut to
  switch to the previously used window layout (:iss:`870`)

- New ``neighboring_window`` and ``move_window`` functions to switch to
  neighboring windows in the current layout, and move them around, similar to
  window movement in vim (:iss:`916`)

- A new ``pipe`` function that can be used to pipe the contents of the screen
  and scrollback buffer to any desired program running in a new window, tab or
  overlay window. (:iss:`933`)

- Add a new :option:`kitty --start-as` command line flag to start kitty
  full-screen/maximized/minimized. This replaces the ``--start-in-fullscreen``
  flag introduced in the previous release (:iss:`935`)

- When mapping the ``new_tab`` action allow specifying that the tab should open
  next to the current tab instead of at the end of the tabs list (:iss:`979`)

- macOS: Add a new :opt:`macos_thicken_font` to make text rendering
  on macs thicker, which makes it similar to the result of
  sub-pixel antialiasing (:pull:`950`)

- macOS: Add an option :opt:`macos_traditional_fullscreen` to make
  full-screening of kitty windows much faster, but less pretty. (:iss:`911`)

- Fix a bug causing incorrect line ordering when viewing the scrollback buffer
  if the scrollback buffer is full (:iss:`960`)

- Fix drag-scrolling not working when the mouse leaves the window confines
  (:iss:`917`)

- Workaround for broken editors like nano that cannot handle newlines in pasted text
  (:iss:`994`)

- Linux: Ensure that the python embedded in the kitty binary build uses
  UTF-8 mode to process command-line arguments (:iss:`924`)

- Linux: Handle fonts that contain monochrome bitmaps (such as the Terminus TTF
  font) (:pull:`934`)

- Have the :option:`kitty --title` flag apply to all windows created
  using :option:`kitty --session` (:iss:`921`)

- Revert change for backspacing of wide characters in the previous release,
  as it breaks backspacing in some wide character aware programs (:iss:`875`)

- Fix kitty @set-colors not working for tab backgrounds when using the `fade` tabbar style
  (:iss:`937`)

- macOS: Fix resizing semi-transparent windows causing the windows to be
  invisible during the resize (:iss:`941`)

- Linux: Fix window icon not set on X11 for the first OS window (:iss:`961`)

- macOS: Add an :opt:`macos_custom_beam_cursor` option to use a special
  mouse cursor image that can be seen on both light and dark backgrounds
  (:iss:`359`)

- Remote control: Fix the ``focus_window`` command not focusing the
  top-level OS window of the specified kitty window (:iss:`1003`)

- Fix using :opt:`focus_follows_mouse` causing text selection with the
  mouse to malfunction when using multiple kitty windows (:iss:`1002`)

0.12.1 [2018-09-08]
------------------------------

- Add a new ``--start-in-fullscreen`` command line flag to start
  kitty in full screen mode (:iss:`856`)

- macOS: Fix a character that cannot be rendered in any font causing
  font fallback for all subsequent characters that cannot be rendered in the
  main font to fail (:iss:`799`)

- Linux: Do not enable IME input via ibus unless the ``GLFW_IM_MODULE=ibus``
  environment variable is set. IME causes key processing latency and even
  missed keystrokes for many people, so it is now off by default.

- Fix backspacing of wide characters in wide-character unaware programs not working (:iss:`875`)

- Linux: Fix number pad arrow keys not working when Numlock is off (:iss:`857`)

- Wayland: Implement support for clipboard copy/paste (:iss:`855`)

- Allow mapping shortcuts using the raw key code from the OS (:iss:`848`)

- Allow mapping of individual key-presses without modifiers as shortcuts

- Fix legacy invocation of icat as `kitty icat` not working (:iss:`850`)

- Improve rendering of wavy underline at small font sizes (:iss:`853`)

- Fix a regression in 0.12.0 that broke dynamic resizing of layouts (:iss:`860`)

- Wayland: Allow using the :option:`kitty --class` command line flag
  to set the app id (:iss:`862`)

- Add completion of the kitty command for the fish shell (:pull:`829`)

- Linux: Fix XCompose rules with no defined symbol not working (:iss:`880`)

- Linux: Fix crash with some Nvidia drivers when creating tabs in the first
  top level-window after creating a second top-level window. (:iss:`873`)

- macOS: Diff kitten: Fix syntax highlighting not working because of
  a bug in the 0.12.0 macOS package

0.12.0 [2018-09-01]
------------------------------

- Preserve the mouse selection even when the contents of the screen are
  scrolled or overwritten provided the new text does not intersect the
  selected lines.

- Linux: Implement support for Input Method Extensions (multilingual input
  using standard keyboards) via `IBus
  <https://github.com/ibus/ibus/wiki/ReadMe>`_ (:iss:`469`)

- Implement completion for the kitty command in bash and zsh. See
  :ref:`completion`.

- Render the text under the cursor in a fixed color, configurable via
  the option :opt:`cursor_text_color` (:iss:`126`)

- Add an option :opt:`env` to set environment variables in child processes
  from kitty.conf

- Add an action to the ``clear_terminal`` function to scroll the screen
  contents into the scrollback buffer (:iss:`1113`)

- Implement high precision scrolling with the trackpad on platforms such as
  macOS and Wayland that implement it. (:pull:`819`)

- macOS: Allow scrolling window contents using mouse wheel/trackpad even when the
  window is not the active window (:iss:`729`)

- Remote control: Allow changing the current window layout with a new
  :ref:`at_goto-layout` command (:iss:`845`)

- Remote control: Allow matching windows by the environment variables of their
  child process as well

- Allow running kittens via the remote control system (:iss:`738`)

- Allow enabling remote control in only some kitty windows

- Add a keyboard shortcut to reset the terminal (:sc:`reset_terminal`). It
  takes parameters so you can define your own shortcuts to clear the
  screen/scrollback also (:iss:`747`)

- Fix one-pixel line appearing at window edges at some window sizes when
  displaying images with background opacity enabled (:iss:`741`)

- diff kitten: Fix error when right hand side file is binary and left hand side
  file is text (:pull:`752`)

- kitty @ new-window: Add a new option :option:`kitty @ new-window --window-type`
  to create top-level OS windows (:iss:`770`)

- macOS: The :opt:`focus_follows_mouse` option now also works across top-level kitty OS windows
  (:iss:`754`)

- Fix detection of URLs in HTML source code (URLs inside quotes) (:iss:`785`)

- Implement support for emoji skin tone modifiers (:iss:`787`)

- Round-trip the zwj unicode character. Rendering of sequences containing zwj
  is still not implemented, since it can cause the collapse of an unbounded
  number of characters into a single cell. However, kitty at least preserves
  the zwj by storing it as a combining character.

- macOS: Disable the custom mouse cursor. Using a custom cursor fails on dual
  GPU machines. I give up, Apple users will just have to live with the
  limitations of their choice of OS. (:iss:`794`)

- macOS: Fix control+tab key combination not working (:iss:`801`)

- Linux: Fix slow startup on some systems caused by GLFW searching for
  joysticks. Since kitty does not use joysticks, disable joystick support.
  (:iss:`830`)


0.11.3 [2018-07-10]
------------------------------

- Draw only the minimum borders needed for inactive windows. That is only the borders
  that separate the inactive window from a neighbor. Note that setting
  a non-zero window margin overrides this and causes all borders to be drawn.
  The old behavior of drawing all borders can be restored via the
  :opt:`draw_minimal_borders` setting in kitty.conf. (:iss:`699`)

- macOS: Add an option :opt:`macos_window_resizable` to control if kitty
  top-level windows are resizable using the mouse or not (:iss:`698`)

- macOS: Use a custom mouse cursor that shows up well on both light and dark backgrounds
  (:iss:`359`)

- macOS: Workaround for switching from fullscreen to windowed mode with the
  titlebar hidden causing window resizing to not work. (:iss:`711`)

- Fix triple-click to select line not working when the entire line is filled
  (:iss:`703`)

- When dragging to select with the mouse "grab" the mouse so that if it strays
  into neighboring windows, the selection is still updated (:pull:`624`)

- When clicking in the margin/border area of a window, map the click to the
  nearest cell in the window. Avoids selection with the mouse failing when
  starting the selection just outside the window.

- When drag-scrolling stop the scroll when the mouse button is released.

- Fix a regression in the previous release that caused pasting large amounts
  of text to be duplicated (:iss:`709`)


0.11.2 [2018-07-01]
------------------------------

- Linux: Allow using XKB key names to bind shortcuts to keys not supported by GLFW (:pull:`665`)

- kitty shell: Ignore failure to read readline history file. Happens if the
  user migrates their kitty cache directory between systems with incompatible
  readline implementations.

- macOS: Fix an error in remote control when using --listen-on (:iss:`679`)

- hints kitten: Add a :option:`kitty +kitten hints --multiple` option to select
  multiple items (:iss:`687`)

- Fix pasting large amounts of text very slow (:iss:`682`)

- Add an option :opt:`single_window_margin_width` to allow different margins
  when only a single window is visible in the layout (:iss:`688`)

- Add a :option:`kitty --hold` command line option to stay open after the child process exits (:iss:`667`)

- diff kitten: When triggering a search scroll to the first match automatically

- :option:`kitty --debug-font-fallback` also prints out what basic fonts were matched

- When closing a kitty window reset the mouse cursor to its default shape and ensure it is visible (:iss:`655`).

- Remote control: Speed-up reading of command responses

- Linux installer: Fix installer failing on systems with python < 3.5

- Support "-T" as an alias for "--title" (:pull:`659`)

- Fix a regression in the previous release that broke using :option:`kitty
  --debug-config` with custom key mappings (:iss:`695`)


0.11.1 [2018-06-17]
------------------------------

- diff kitten: Implement searching for text in the diff (:iss:`574`)

- Add an option :opt:`startup_session` to :file:`kitty.conf` to specify a
  default startup session (:iss:`641`)

- Add a command line option :option:`kitty --wait-for-single-instance-window-close`
  to make :option:`kitty --single-instance` wait for the closing of the newly opened
  window before quitting (:iss:`630`)

- diff kitten: Allow theming the selection background/foreground as well

- diff kitten: Display CRLF line endings using the unicode return symbol
  instead of <d> as it is less intrusive (:iss:`638`)

- diff kitten: Fix default foreground/background colors not being restored when
  kitten quits (:iss:`637`)

- Fix :option:`kitty @ set-colors --all` not working when more than one window
  present (:iss:`632`)

- Fix a regression that broke the legacy increase/decrease_font_size actions

- Clear scrollback on reset (:iss:`631`)


0.11.0 [2018-06-12]
------------------------------

- A new tab bar style "fade" in which each tab's edges fade into the background.
  See :opt:`tab_bar_style` and :opt:`tab_fade` for details. The old look can be
  restored by setting :opt:`tab_bar_style` to :code:`separator`.

- :doc:`Pre-compiled binaries <binary>` with all bundled dependencies for Linux
  (:iss:`595`)

- A :doc:`new kitten <kittens/panel>` to create dock panels on X11 desktops
  showing the output from arbitrary terminal programs.

- Reduce data sent to the GPU per render by 30% (:commit:`8dea5b3`)

- Implement changing the font size for individual top level (OS) windows
  (:iss:`408`)

- When viewing the scrollback in less using :sc:`show_scrollback` and kitty
  is currently scrolled, position the scrollback in less to match kitty's
  scroll position. (:iss:`148`)

- ssh kitten: Support all SSH options. It can now be aliased directly to ssh
  for convenience. (:pull:`591`)

- icat kitten: Add :option:`kitty +kitten icat --print-window-size` to easily
  detect the window size in pixels from scripting languages (:iss:`581`)

- hints kitten: Allow selecting hashes from the terminal with
  :sc:`insert_selected_hash` useful for git commits. (:pull:`604`)

- Allow specifying initial window size in number of cells in addition to pixels
  (:iss:`436`)

- Add a setting to control the margins to the left and right of the tab-bar
  (:iss:`584`)

- When closing a tab switch to the last active tab instead of the right-most
  tab (:iss:`585`)

- Wayland: Fix kitty not starting when using wl_roots based compositors
  (:iss:`157`)

- Wayland: Fix mouse wheel/touchpad scrolling in opposite direction to other apps (:iss:`594`)

- macOS: Fix the new OS window keyboard shortcut (:sc:`new_os_window`) not
  working if no kitty window currently has focus. (:iss:`524`)

- macOS: Keep kitty running even when the last window is closed. This is in
  line with how applications are supposed to behave on macOS (:iss:`543`).
  There is a new option (:opt:`macos_quit_when_last_window_closed`) to control
  this.

- macOS: Add macOS standard shortcuts for copy, paste and new OS window
  (⌘+C, ⌘+V, ⌘+N)

- Add a config option (:opt:`editor`) to set the EDITOR kitty uses (:iss:`580`)

- Add a config option (``x11_hide_window_decorations``) to hide window
  decorations under X11/Wayland (:iss:`607`)

- Add an option to @set-window-title to make the title change non-permanent
  (:iss:`592`)

- Add support for the CSI t escape code to query window and cell sizes
  (:iss:`581`)

- Linux: When using layouts that map the keys to non-ascii characters,
  map shortcuts using the ascii equivalents, from the default layout.
  (:iss:`606`)

- Linux: Fix fonts not being correctly read from TrueType Collection
  (.ttc) files (:iss:`577`)

- Fix :opt:`inactive_text_alpha` also applying to the tab bar (:iss:`612`)

- :doc:`hints kitten <kittens/hints>`: Fix a regression that caused some blank lines to be not
  be displayed.

- Linux: Include a man page and the HTML docs when building the linux-package

- Remote control: Fix kitty @ sometimes failing to read the response from
  kitty. (:iss:`614`)

- Fix `kitty @ set-colors` not working with the window border colors.
  (:iss:`623`)

- Fix a regression in 0.10 that caused incorrect rendering of the status bar in
  irssi when used inside screen. (:iss:`621`)


0.10.1 [2018-05-24]
------------------------------

- Add a kitten to easily ssh into servers that automatically copies the
  terminfo files over. ``kitty +kitten ssh myserver``.

- diff kitten: Make the keyboard shortcuts configurable (:iss:`563`)

- Allow controlling *background_opacity* via either keyboard shortcuts or
  remote control. Note that you must set *dynamic_background_opacity yes* in
  kitty.conf first. (:iss:`569`)

- diff kitten: Add keybindings to scroll by page

- diff kitten: Fix incorrect syntax highlighting for a few file formats such as
  yaml

- macOS: Fix regression that caused the *macos_option_as_alt* setting to always
  be disabled for all OS windows in a kitty instance after the first window
  (:iss:`571`)

- Fix Ctrl+Alt+Space not working in normal and application keyboard modes
  (:iss:`562`)


0.10.0 [2018-05-21]
------------------------------

- A diff kitten to show side-by-side diffs with syntax highlighting and support
  for images. See :doc:`diff kitten <kittens/diff>`.

- Make windows in the various kitty layouts manually resizable. See
  :ref:`layouts` for details.

- Implement support for the SGR *faint* escape code to make text blend
  into the background (:iss:`446`).

- Make the hints kitten a little smarter (:commit:`ad1109b`)
  so that URLs that stretch over multiple lines are detected. Also improve
  detection of surrounding brackets/quotes.

- Make the kitty window id available as the environment variable
  ``KITTY_WINDOW_ID`` (:iss:`532`).

- Add a "fat" layout that is similar to the "tall" layout but vertically
  oriented.

- Expand environment variables in config file include directives

- Allow programs running in kitty to read/write from the clipboard (:commit:`889ca77`).
  By default only writing is allowed. This feature is supported in many
  terminals, search for `OSC 52 clipboard` to find out more about using it.

- Fix moving cursor outside a defined page area incorrectly causing the cursor
  to be placed inside the page area. Caused incorrect rendering in neovim, in
  some situations (:iss:`542`).

- Render a couple more powerline symbols directly, bypassing the font
  (:iss:`550`).

- Fix ctrl+alt+<special> not working in normal and application keyboard (:iss:`548`).

- Partial fix for rendering Right-to-left languages like Arabic. Rendering of
  Arabic is never going to be perfect, but now it is at least readable.

- Fix Ctrl+backspace acting as plain backspace in normal and application
  keyboard modes (:iss:`538`).

- Have the paste_from_selection action paste from the clipboard on platforms
  that do not have a primary selection such as Wayland and macOS
  (:iss:`529`)

- Fix cursor_stop_blinking_after=0 not working (:iss:`530`)


0.9.1 [2018-05-05]
------------------------------

- Show a bell symbol on the tab if a bell occurs in one of the windows in the tab and
  the window is not the currently focused window

- Change the window border color if a bell occurs in an unfocused window. Can
  be disabled by setting the bell_border_color to be the same as the
  inactive_border_color.

- macOS: Add support for dead keys

- Unicode input: When searching by name search for prefix matches as well as
  whole word matches

- Dynamically allocate the memory used for the scrollback history buffer.
  Reduces startup memory consumption when using very large scrollback
  buffer sizes.

- Add an option to not request window attention on bell.

- Remote control: Allow matching windows by number (visible position).

- macOS: Fix changing tab title and kitty shell not working

- When triple-clicking select all wrapped lines belonging to a single logical line.

- hints kitten: Detect bracketed URLs and don't include the closing bracket in the URL.

- When calling pass_selection_to_program use the current directory of the child
  process as the cwd of the program.

- Add macos_hide_from_tasks option to hide kitty from the macOS task switcher

- macOS: When the macos_titlebar_color is set to background change the titlebar
  colors to match the current background color of the active kitty window

- Add a setting to clear all shortcuts defined up to that point in the config
  file(s)

- Add a setting (kitty_mod) to change the modifier used by all the default
  kitty shortcuts, globally

- Fix Shift+function key not working

- Support the F13 to F25 function keys

- Don't fail to start if the user deletes the hintstyle key from their
  fontconfig configuration.

- When rendering a private use unicode codepoint and a space as a two cell
  ligature, set the foreground colors of the space cell to match the colors of
  the first cell. Works around applications like powerline that use different
  colors for the two cells.

- Fix passing @text to other programs such as when viewing the scrollback
  buffer not working correctly if kitty is itself scrolled up.

- Fix window focus gained/lost events not being reported to child programs when
  switching windows/tabs using the various keyboard shortcuts.

- Fix tab title not changing to reflect the window title when switching between different windows in a tab

- Ignore -e if it is specified on the command line. This is for compatibility
  with broken software that assumes terminals should run with an -e option to
  execute commands instead of just passing the commands as arguments.


0.9.0 [2018-04-15]
------------------------------

- A new kitty command shell to allow controlling kitty via commands. Press
  `ctrl+shift+escape` to run the shell.

- The hints kitten has become much more powerful. Now in addition to URLs you
  can use it to select word, paths, filenames, lines, etc. from the screen.
  These can be inserted into the terminal, copied to clipboard or sent to
  external programs.

- Linux: Switch to libxkbcommon for keyboard handling. It allows kitty to
  support XCompose and dead keys and also react to keyboard remapping/layout
  change without needing a restart.

- Add support for multiple-key-sequence shortcuts

- A new remote control command `set-colors` to change the current and/or
  configured colors.

- When double-clicking to select a word, select words that continue onto the
  next/prev line as well.

- Add an `include` directive for the config files to read multiple config files

- Improve mouse selection for windows with padding. Moving the mouse into the
  padding area now acts as if the mouse is over the nearest cell.

- Allow setting all 256 terminal colors in the config file

- Fix using `kitty --single-instance` to open a new window in a running kitty
  instance, not respecting the `--directory` flag

- URL hints: Exclude trailing punctuation from URLs

- URL hints: Launch the browser from the kitty parent process rather than the
  hints kitten. Fixes launching on some systems where xdg-open doesn't like
  being run from a kitten.

- Allow using rectangle select mode by pressing shift in addition to the
  rectangle select modifiers even when the terminal program has grabbed the
  mouse.


0.8.4 [2018-03-31]
-----------------------------

- Fix presence of XDG_CONFIG_DIRS and absence of XDG_CONFIG_HOME preventing
  kitty from starting

- Revert change in last release to cell width calculation. Instead just clip
  the right edges of characters that overflow the cell by at most two pixels


0.8.3 [2018-03-29]
-----------------------------

- Fix a regression that broke the visual bell and invert screen colors escape
  code

- Allow double-click and triple-click + drag to extend selections word at a
  time or line at a time

- Add a keyboard shortcut to set the tab title

- Fix setting window title to empty via OSC escape code not working correctly

- Linux: Fix cell width calculation incorrect for some fonts (cell widths are
  now calculated by actually rendering bitmaps, which is slower but more
  accurate)

- Allow specifying a system wide kitty config file, for all users

- Add a --debug-config command line flag to output data about the system and
  kitty configuration.

- Wayland: Fix auto-repeat of keys not working


0.8.2 [2018-03-17]
-----------------------------

- Allow extending existing selections by right clicking

- Add a configurable keyboard shortcut and remote command to set the font size to a specific value

- Add an option to have kitty close the window when the main processes running in it exits, even if there are still background processes writing to that terminal

- Add configurable keyboard shortcuts to switch to a specific layout

- Add a keyboard shortcut to edit the kitty config file easily

- macOS: Fix restoring of window size not correct on Retina screens

- macOS: Add a facility to specify command line arguments when running kitty from the GUI

- Add a focus-tab remote command

- Fix screen not being refreshed immediately after moving a window.

- Fix a crash when getting the contents of the scrollback buffer as text

0.8.1 [2018-03-09]
-----------------------------

- Extend kitty's remote control feature to work over both UNIX and TCP sockets,
  so now you can control kitty from across the internet, if you want to.

- Render private use unicode characters that are followed by a space as a two
  character ligature. This fixes rendering for applications that misuse
  private-use characters to display square symbols.

- Fix Unicode emoji presentation variant selector causing new a fallback font
  instance to be created

- Fix a rare error that prevented the Unicode input kitten from working
  sometimes

- Allow using Ctrl+Alt+letter in legacy keyboard modes by outputting them as Ctrl+letter and Alt+letter.
  This matches other terminals' behavior.

- Fix cursor position off-by-one on horizontal axis when resizing the terminal

- Wayland: Fix auto-repeat of keys not working

- Wayland: Add support for window decorations provided by the Wayland shell

- macOS: Fix URL hints not working

- macOS: Fix shell not starting in login mode on some computers

- macOS: Output errors into console.app when running as a bundle


0.8.0 [2018-02-24]
-----------------------------

- A framework for kittens, that is, small terminal programs designed to run
  inside kitty and extend its capabilities. Examples include unicode input and
  selecting URLs with the keyboard.

- Input arbitrary unicode characters by pressing Ctrl+Shift+u. You can choose
  characters by name, by hex code, by recently used, etc. There is even and
  editable Favorites list.

- Open URLs using only the keyboard. kitty has a new "hints mode". Press
  Ctrl+Shift+e and all detected URLs on the screen are highlighted with a key
  to press to open them. The facility is customizable so you can change
  what is detected as a URL and which program is used to open it.

- Add an option to change the titlebar color of kitty windows on macOS

- Only consider Emoji characters with default Emoji presentation to be two
  cells wide. This matches the standard. Also add support for the Unicode Emoji
  variation presentation selector.

- Prevent video tearing during high speed scrolling by syncing draws
  to the monitor's refresh rate. There is a new configuration option to
  control this ``sync_to_monitor``.

- When displaying only a single window, use the default background color of the
  window (which can be changed via escape codes) as the color for the margin
  and padding of the window.

- Add some non standard terminfo capabilities used by neovim and tmux.

- Fix large drop in performance when using multiple top-level windows on macOS

- Fix save/restore of window sizes not working correctly.

- Remove option to use system wcwidth(). Now always use a wcwidth() based on
  the Unicode standard. Only sane way.

- Fix a regression that caused a few ligature glyphs to not render correctly in
  rare circumstances.

- Browsing the scrollback buffer now happens in an overlay window instead of a
  new window/tab.

0.7.1 [2018-01-31]
---------------------------

- Add an option to adjust the width of character cells

- Fix selecting text with the mouse in the scrollback buffer selecting text
  from the line above the actually selected line

- Fix some italic fonts having the right edge of characters cut-off,
  unnecessarily


0.7.0 [2018-01-24]
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


0.6.1 [2017-12-28]
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


0.6.0 [2017-12-18]
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


0.5.1 [2017-12-01]
---------------------------

- Add an option to control the thickness of lines in box drawing characters

- Increase max. allowed ligature length to nine characters

- Fix text not vertically centered when adjusting line height

- Fix unicode block characters not being rendered properly

- Fix shift+up/down not generating correct escape codes

- Image display: Fix displaying images taller than two screen heights not
  scrolling properly


0.5.0 [2017-11-19]
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


0.4.2 [2017-10-23]
---------------------------

- Fix a regression in 0.4.0 that broke custom key mappings

- Fix a regression in 0.4.0 that broke support for non-QWERTY keyboard layouts

- Avoid using threads to reap zombie child processes. Also prevent kitty from
  hanging if the open program hangs when clicking on a URL.


0.4.0 [2017-10-22]
---------------------------

- Support for drawing arbitrary raster graphics (images) in the terminal via a
  new graphics protocol. kitty can draw images with full 32-bit color using both
  ssh connections and files/shared memory (when available) for better
  performance. The drawing primitives support alpha blending and z-index.
  Images can be drawn both above and below text. See :doc:`graphics-protocol`.
  for details.

- Refactor kitty's internals to make it even faster and more efficient. The CPU
  usage of kitty + X server while doing intensive tasks such as scrolling a
  file continuously in less has been reduced by 50%. There are now two
  configuration options ``repaint_delay`` and ``input_delay`` you can use to
  fine tune kitty's performance vs CPU usage profile. The CPU usage of kitty +
  X when scrolling in less is now significantly better than most (all?) other
  terminals. See :doc:`performance`.

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
