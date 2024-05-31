Changelog
==============

|kitty| is a feature-rich, cross-platform, *fast*, GPU based terminal.
To update |kitty|, :doc:`follow the instructions <binary>`.

.. recent major features {{{

Recent major new features
---------------------------

Wayland goodies [0.34]
~~~~~~~~~~~~~~~~~~~~~~~

Wayland users should rejoice as kitty now comes with major Wayland
quality-of-life improvements:

* Draw GPU accelerated :doc:`desktop panels and background </kittens/panel>`
  running arbitrary terminal programs. For example, run `btop
  <https://github.com/aristocratos/btop/>`__ as your desktop background

* Background blur for transparent windows is now supported under KDE
  using a custom KDE specific protocol

* The kitty window decorations in GNOME are now fully functional with buttons
  and they follow system dark/light mode automatically

* kitty now supports fractional scaling in Wayland which means pixel perfect
  rendering when you use a fractional scale with no wasted performance on
  resizing an overdrawn pixmap in the compositor

With this release kitty's Wayland support is now on par with X11, provided
you use a decent Wayland compositor.

Cheetah speed 🐆 [0.33]
~~~~~~~~~~~~~~~~~~~~~~~~~

kitty has grown up and become a cheetah. It now parses data it receives in
parallel :iss:`using SIMD vector CPU instructions <7005>` for a 2x speedup in
benchmarks and a 10%-50% real world speedup depending on workload. There is a
new benchmarking kitten ``kitten __benchmark__`` that can be used to measure
terminal throughput. There is also :ref:`a table <throughput>` showing kitty is
much faster than other terminal emulators based on the benchmark kitten. While
kitty was already so fast that its performance was never a bottleneck, this
improvement makes it even faster and more importantly reduces the energy
consumption to do the same tasks.

.. }}}

Detailed list of changes
-------------------------------------

0.35.1 [2024-05-31]
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

- Wayland: Fix a regression in 0.34 that caused the tab bar to not render in second and subsequent OS Windows under Hyprland (:iss:`7413`)

- Fix a regression in the previous release that caused horizontal scrolling via touchpad in fullscreen applications to be reversed on non-Wayland platforms (:iss:`7475`, :iss:`7481`)

- Fix a regression in the previous release causing an error when setting background_opacity to zero (:iss:`7483`)

- Image display: Fix cursor movement and image hit region incorrect for image placements that specify only a number of rows or columns to display in (:iss:`7479`)


0.35.0 [2024-05-25]
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

- kitten @ run: A new remote control command to run a process on the machine kitty is running on and get its output (:iss:`7429`)

- :opt:`notify_on_cmd_finish`: Show the actual command that was finished (:iss:`7420`)

- hints kitten: Allow clicking on matched text to select it in addition to typing the hint

- Shell integration: Make the currently executing cmdline available as a window variable in kitty

- :opt:`paste_actions`: Fix ``replace-newline`` not working with ``confirm`` (:iss:`7374`)

- Graphics: Fix aspect ratio of images not being preserved when only a single
  dimension of the destination rectangle is specified (:iss:`7380`)

- :ac:`focus_visible_window`: Fix selecting with mouse click leaving keyboard in unusable state (:iss:`7390`)

- Wayland: Fix infinite loop causing bad performance when using IME via fcitx5 due to a change in fcitx5 (:iss:`7396`)

- Desktop notifications protocol: Add support for specifying urgency

- Improve rendering of Unicode shade character to avoid Moire patterns (:pull:`7401`)

- kitten @ send-key: Fix some keys being sent in kitty keyboard protocol encoding when not using socket for remote control

- Dont clear selections on erase in screen commands unless the erased region intersects a selection (:iss:`7408`)

- Wayland: save energy by not rendering "suspended" windows on compositors that support that

- Allow more types of alignment for :opt:`placement_strategy` (:pull:`7419`)

- Add some more box-drawing characters from the "Geometric shapes" Unicode block (:iss:`7433`)

- Linux: Run all child processes in their own systemd scope to prevent the OOM killer from harvesting kitty when a child process misbehaves (:iss:`7427`)

- Mouse reporting: Fix horizontal scroll events inverted (:iss:`7439`)

- Remote control: @ action: Fix some actions being performed on the active window instead of the matched window (:iss:`7438`)

- Scrolling with mouse wheel when a selection is active should update the selection (:iss:`7453`)

- Fix kitten @ set-background-opacity limited to min opacity of 0.1 instead of 0 (:iss:`7463`)

- launch --hold: Fix hold not working if kernel signals process group with SIGINT (:iss:`7466`)

- macOS: Fix --start-as=fullscreen not working when another window is already fullscreen (:iss:`7448`)

- Add option :option:`kitten @ detach-window --stay-in-tab` to keep focus in the currently active tab when moving windows (:iss:`7468`)

- macOS: Fix changing window chrome/colors while in traditional fullscreen causing the titlebar to become visible (:iss:`7469`)

0.34.1 [2024-04-19]
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

- Wayland KDE: Fix window background blur not adapting when window is grown. Also fix turning it on and off not working. (:iss:`7351`)

- Wayland GNOME: Draw the titlebar buttons without using a font (:iss:`7349`)

- Fix a regression in the previous release that caused incorrect font selection when using variable fonts on Linux (:iss:`7361`)

0.34.0 [2024-04-15]
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

- Wayland: :doc:`panel kitten <kittens/panel>`: Add support for drawing desktop background and bars
  using the panel kitten for all compositors that support the `requisite Wayland
  protocol <https://wayland.app/protocols/wlr-layer-shell-unstable-v1>`__ which is practically speaking all of them but GNOME (:pull:`2590`)

- Show a small :opt:`scrollback indicator <scrollback_indicator_opacity>` along the right window edge when viewing
  the scrollback to keep track of scroll position (:iss:`2502`)

- Wayland: Support fractional scales so that there is no wasted drawing at larger scale followed by resizing in the compositor

- Wayland KDE: Support :opt:`background_blur`

- Wayland GNOME: The window titlebar now has buttons to minimize/maximize/close the window

- Wayland GNOME: The window titlebar color now follows the system light/dark color scheme preference, see :opt:`wayland_titlebar_color`

- Wayland KDE: Fix mouse cursor hiding not working in Plasma 6 (:iss:`7265`)

- Wayland IME: Fix a bug with handling synthetic keypresses generated by ZMK keyboard + fcitx (:pull:`7283`)

- A new option :opt:`terminfo_type` to allow passing the terminfo database embedded into the :envvar:`TERMINFO` env var directly instead of via a file

- Mouse reporting: Fix drag release event outside the window not being reported in legacy mouse reporting modes (:iss:`7244`)

- macOS: Fix a regression in the previous release that broke rendering of some symbols on some systems (:iss:`7249`)

- Fix handling of tab character when cursor is at end of line and wrapping is enabled (:iss:`7250`)

- Splits layout: Fix :ac:`move_window_forward` not working (:iss:`7264`)

- macOS: Fix an abort due to an assertion when a program tries to set an invalid window title (:iss:`7271`)

- fish shell integration: Fix clicking at the prompt causing autosuggestions to be accepted, needs fish >= 3.8.0 (:iss:`7168`)

- Linux: Fix for a regression in 0.32.0 that caused some CJK fonts to not render glyphs (:iss:`7263`)

- Wayland: Support preferred integer scales

- Wayland: A new option :opt:`wayland_enable_ime` to turn off Input Method Extensions which add latency and create bugs

- Wayland: Fix :opt:`hide_window_decorations` not working on non GNOME desktops

- When asking for quit confirmation because of a running program, mention the program name (:iss:`7331`)

- Fix flickering of prompt during window resize (:iss:`7324`)

0.33.1 [2024-03-21]
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

- Fix a regression in the previous release that caused requesting data from the clipboard via OSC 52 to instead return data from the primary selection (:iss:`7213`)

- Splits layout: Allow resizing until one of the halves in a split is minimally sized (:iss:`7220`)

- macOS: Fix text rendered with fallback fonts not respecting bold/italic styling (:disc:`7241`)

- macOS: When CoreText fails to find a fallback font for a character in the first Private Use Unicode Area, preferentially use the NERD font, if available, for it (:iss:`6043`)


0.33.0 [2024-03-12]
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

- :ref:`Cheetah speed <throughput>` with a redesigned render loop and a 2x faster escape code
  parser that uses SIMD CPU vector instruction to parse data in parallel
  (:iss:`7005`)

- A new benchmark kitten (``kitten __benchmark__``) to measure terminal
  throughput performance

- Graphics protocol: Add a new delete mode for deleting images whose ids fall within a range. Useful for bulk deletion (:iss:`7080`)

- Keyboard protocol: Fix the :kbd:`Enter`, :kbd:`Tab` and :kbd:`Backspace` keys
  generating spurious release events even when report all keys as escape codes
  is not set (:iss:`7136`)

- macOS: The command line args from :file:`macos-launch-services-cmdline` are now
  prefixed to any args from ``open --args`` rather than overwriting them (:iss:`7135`)

- Allow specifying where the new tab is created for :ac:`detach_window` (:pull:`7134`)

- hints kitten: The option to set the text color for hints now allows arbitrary
  colors (:pull:`7150`)

- icat kitten: Add a command line argument to override terminal window size detection (:iss:`7165`)

- A new action :ac:`toggle_tab` to easily switch to and back from a tab with a single shortcut (:iss:`7203`)

- When :ac:`clearing terminal <clear_terminal>` add a new type ``to_cursor_scroll`` which can be
  used to clear to prompt while moving cleared lines into the scrollback

- Fix a performance bottleneck when dealing with thousands of small images
  (:iss:`7080`)

- kitten @ ls: Return the timestamp at which the window was created (:iss:`7178`)

- hints kitten: Use default editor rather than hardcoding vim to open file at specific line (:iss:`7186`)

- Remote control: Fix ``--match`` argument not working for @ls, @send-key,
  @set-background-image (:iss:`7192`)

- Keyboard protocol: Do not deliver a fake key release events on OS window focus out for engaged modifiers (:iss:`7196`)

- Ignore :opt:`startup_session` when kitty is invoked with command line options specifying a command to run (:pull:`7198`)

- Box drawing: Specialize rendering for the Fira Code progress bar/spinner glyphs

0.32.2 [2024-02-12]
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

- kitten @ load-config: Allow (re)loading kitty.conf via remote control

- Remote control: Allow running mappable actions via remote control (`kitten @ action`)

- kitten @ send-text: Add a new option to automatically wrap the sent text in
  bracketed paste escape codes if the program in the destination window has
  turned on bracketed paste.

- Fix a single key mapping not overriding a previously defined multi-key mapping

- macOS: Fix :code:`kitten @ select-window` leaving the keyboard in a partially functional state (:iss:`7074`)

- Graphics protocol: Improve display of images using Unicode placeholders or
  row/column boxes by resizing them using linear instead of nearest neighbor
  interpolation on the GPU (:iss:`7070`)

- When matching URLs use the definition of legal characters in URLs from the
  `WHATWG spec <https://url.spec.whatwg.org/#url-code-points>`__ rather than older standards (:iss:`7095`)

- hints kitten: Respect the kitty :opt:`url_excluded_characters` option
  (:iss:`7075`)

- macOS: Fix an abort when changing OS window chrome for a full screen window via remote control or the themes kitten (:iss:`7106`)

- Special case rendering of some more box drawing characters using shades from the block of symbols for legacy computing (:iss:`7110`)

- A new action :ac:`close_other_os_windows` to close non active OS windows (:disc:`7113`)

0.32.1 [2024-01-26]
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

- macOS: Fix a regression in the previous release that broke overriding keyboard shortcuts for actions present in the global menu bar (:iss:`7016`)

- Fix a regression in the previous release that caused multi-key sequences to not abort when pressing an unknown key (:iss:`7022`)

- Fix a regression in the previous release that caused `kitten @ launch --cwd=current` to fail over SSH (:iss:`7028`)

- Fix a regression in the previous release that caused `kitten @ send-text` with a match tab parameter to send text twice to the active window (:iss:`7027`)

- Fix a regression in the previous release that caused overriding of existing multi-key mappings to fail (:iss:`7044`, :iss:`7058`)

- Wayland+NVIDIA: Do not request an sRGB output buffer as a bug in Wayland causes kitty to not start (:iss:`7021`)

0.32.0 [2024-01-19]
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

- :ref:`conditional_mappings`

- Support for :ref:`modal_mappings` such as in modal editors like vim

- A new option :opt:`notify_on_cmd_finish` to show a desktop notification when a long running command finishes (:pull:`6817`)

- A new action :ac:`send_key` to simplify mapping key presses to other keys without needing :ac:`send_text`

- Allow focusing previously active OS windows via :ac:`nth_os_window` (:pull:`7009`)

- Wayland: Fix a regression in the previous release that broke copying to clipboard under wl-roots based compositors in some circumstances
  (:iss:`6890`)

- macOS: Fix some combining characters not being rendered (:iss:`6898`)

- macOS: Fix returning from full screen via the button when the titlebar is hidden not hiding the buttons (:iss:`6883`)

- macOS: Fix newly created OS windows not always appearing on the "active" monitor (:pull:`6932`)

- Font fallback: Fix the font used to render a character sometimes dependent on the order in which characters appear on screen (:iss:`6865`)

- panel kitten: Fix rendering with non-zero margin/padding in kitty.conf (:iss:`6923`)

- kitty keyboard protocol: Specify the behavior of the modifier bits during modifier key events (:iss:`6913`)

- Wayland: Enable support for the new cursor-shape protocol so that the mouse cursor is always rendered at the correct size in compositors that support this protocol (:iss:`6914`)

- GNOME Wayland: Fix remembered window size smaller than actual size (:iss:`6946`)

- Mouse reporting: Fix incorrect position reported for windows with padding (:iss:`6950`)

- Fix :ac:`focus_visible_window` not switching to other window in stack layout
  when only two windows are present (:iss:`6970`)


0.31.0 [2023-11-08]
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

- Allow :ac:`easily running arbitrarily complex remote control scripts <remote_control_script>` without needing to turn on remote control (:iss:`6712`)

- A new option :opt:`menu_map` that allows adding entries to the global menubar on macOS (:disc:`6680`)

- A new :doc:`escape code <pointer-shapes>` that can be used by programs running in the terminal to change the shape of the mouse pointer (:iss:`6711`)

- Graphics protocol: Support for positioning :ref:`images relative to other images <relative_image_placement>` (:iss:`6400`)

- A new option :opt:`single_window_padding_width` to use a different padding when only a single window is visible (:iss:`6734`)

- A new mouse action ``mouse_selection word_and_line_from_point`` to select the current word under the mouse cursor and extend to end of line (:pull:`6663`)

- A new option :opt:`underline_hyperlinks` to control when hyperlinks are underlined (:iss:`6766`)

- Allow using the full range of standard mouse cursor shapes when customizing the mouse cursor

- macOS: When running the default shell with the login program fix :file:`~/.hushlogin` not being respected when opening windows not in the home directory (:iss:`6689`)

- macOS: Fix poor performance when using ligatures with some fonts, caused by slow harfbuzz shaping (:iss:`6743`)

- :option:`kitten @ set-background-opacity --toggle` - a new flag to easily switch opacity between the specified value and the default (:iss:`6691`)

- Fix a regression caused by rewrite of kittens to Go that made various kittens reset colors in a terminal when the colors were changed by escape code (:iss:`6708`)

- Fix trailing bracket not ignored when detecting a multi-line URL with the trailing bracket as the first character on the last line (:iss:`6710`)

- Fix the :option:`kitten @ launch --copy-env` option not copying current environment variables (:iss:`6724`)

- Fix a regression that broke :program:`kitten update-self` (:iss:`6729`)

- Two new event types for :ref:`watchers <watchers>`, :code:`on_title_change` and :code:`on_set_user_var`

- When pasting, if the text contains terminal control codes ask the user for permission. See :opt:`paste_actions` for details. Thanks to David Leadbeater for discovering this.

- Render Private Use Unicode symbols using two cells if the second cell contains an en-space as well as a normal space

- macOS: Fix a regression in the previous release that caused kitten @ ls to not report the environment variables for the default shell (:iss:`6749`)

- :doc:`Desktop notification protocol </desktop-notifications>`: Allow applications sending notifications to specify that the notification should only be displayed if the window is currently unfocused (:iss:`6755`)

- :doc:`unicode_input kitten </kittens/unicode_input>`: Fix a regression that broke the "Emoticons" tab (:iss:`6760`)

- Shell integration: Fix ``sudo --edit`` not working and also fix completions for sudo not working in zsh (:iss:`6754`, :iss:`6771`)

- A new action :ac:`set_window_title` to interactively change the title of the active window

- ssh kitten: Fix a regression that broken :kbd:`ctrl+space` mapping in zsh (:iss:`6780`)

- Wayland: Fix primary selections not working with the river compositor (:iss:`6785`)


0.30.1 [2023-10-05]
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

- Shell integration: Automatically alias sudo to make the kitty terminfo files available in the sudo environment. Can be turned off via :opt:`shell_integration`

- ssh kitten: Fix a regression in 0.28.0 that caused using ``--kitten`` to
  override :file:`ssh.conf` not inheriting settings from :file:`ssh.conf`
  (:iss:`6639`)

- themes kitten: Allow absolute paths for ``--config-file-name`` (:iss:`6638`)

- Expand environment variables in the :opt:`shell` option (:iss:`6511`)

- macOS: When running the default shell, run it via the login program so that calls to ``getlogin()`` work (:iss:`6511`)

- X11: Fix a crash on startup when the ibus service returns errors and the GLFW_IM_MODULE env var is set to ibus (:iss:`6650`)


0.30.0 [2023-09-18]
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

- A new :doc:`transfer kitten </kittens/transfer>` that can be used to transfer files efficiently over the TTY device

- ssh kitten: A new configuration directive :opt:`to automatically forward the kitty remote control socket <kitten-ssh.forward_remote_control>`

- Allow :doc:`easily building kitty from source </build>` needing the installation of only C and Go compilers.
  All other dependencies are automatically vendored

- kitten @ set-user-vars: New remote control command to set user variables on a
  window (:iss:`6502`)

- kitten @ ls: Add user variables set on windows to the output (:iss:`6502`)

- kitten @ ls: Allow limiting output to matched windows/tabs (:iss:`6520`)

- kitten icat: Fix image being displayed one cell to the right when using both ``--place`` and ``--unicode-placeholder`` (:iss:`6556`)

- kitten run-shell: Make kitty terminfo database available if needed before starting the shell

- macOS: Fix keyboard shortcuts in the Apple global menubar not being changed when reloading the config

- Fix a crash when resizing an OS Window that is displaying more than one image and the new size is smaller than the image needs (:iss:`6555`)

- Remote control: Allow using a random TCP port as the remote control socket and also allow using TCP sockets in :opt:`listen_on`

- unicode_input kitten: Add an option to specify the startup tab (:iss:`6552`)

- X11: Print an error to :file:`STDERR` instead of refusing to start when the user sets a custom window icon larger than 128x128 (:iss:`6507`)

- Remote control: Allow matching by neighbor of active window. Useful for navigation plugins like vim-kitty-navigator

- Fix a regression that caused changing :opt:`text_fg_override_threshold` or :opt:`text_composition_strategy` via config reload causing incorrect rendering (:iss:`6559`)

- When running a shell for ``--hold`` set the env variable ``KITTY_HOLD=1`` to allow users to customize what happens (:disc:`6587`)

- When multiple confirmable close requests are made focus the existing close confirmation window instead of opening a new one for each request (:iss:`6601`)

- Config file format: allow splitting lines by starting subsequent lines with a backslash (:pull:`6603`)

- ssh kitten: Fix a regression causing hostname directives in :file:`ssh.conf` not matching when username is specified (:disc:`6609`)

- diff kitten: Add support for files that are identical apart from mode changes (:iss:`6611`)

- Wayland: Do not request idle inhibition for full screen windows (:iss:`6613`)

- Adjust the workaround for non-linear blending of transparent pixels in
  compositors to hopefully further reduce fringing around text with certain
  color issues (:iss:`6534`)


0.29.2 [2023-07-27]
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

- macOS: Fix a performance regression on M1 machines using outdated macOS versions (:iss:`6479`)

- macOS: Disable OS window shadows for transparent windows as they cause rendering artifacts due to Cocoa bugs (:iss:`6439`)

- Detect .tex and Makefiles as plain text files (:iss:`6492`)

- unicode_input kitten: Fix scrolling over multiple screens not working (:iss:`6497`)

0.29.1 [2023-07-17]
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

- A new value for :opt:`background_image_layout` to scale the background image while preserving its aspect ratio. Also have centered images work even for images larger than the window size (:pull:`6458`)

- Fix a regression that caused using unicode placeholders to display images to break and also partially offscreen images to sometimes be slightly distorted (:iss:`6467`)

- macOS: Fix a regression that caused rendering to hang when transitioning to full screen with :opt:`macos_colorspace` set to ``default`` (:iss:`6435`)

- macOS: Fix a regression causing *burn-in* of text when resizing semi-transparent OS windows (:iss:`6439`)

- macOS: Add a new value ``titlebar-and-corners`` for :opt:`hide_window_decorations` that emulates the behavior of ``hide_window_decorations yes`` in older versions of kitty

- macOS: Fix a regression in the previous release that caused :opt:`hide_window_decorations` = ``yes`` to prevent window from being resizable (:iss:`6436`)

- macOS: Fix a regression that caused the titlebar to be translucent even for non-translucent windows (:iss:`6450`)

- GNOME: Fix :opt:`wayland_titlebar_color` not being applied until the color is changed at least once (:iss:`6447`)

- Remote control launch: Fix ``--env`` not implemented when using ``--cwd=current`` with the SSH kitten (:iss:`6438`)

- Allow using a custom OS window icon on X11 as well as macOS (:pull:`6475`)

0.29.0 [2023-07-10]
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

- A new escape code ``<ESC>[22J`` that moves the current contents of the screen into the scrollback before clearing it

- A new kitten :ref:`run-shell <run_shell>` to allow creating sub-shells with shell integration enabled

- A new option :opt:`background_blur` to blur the background for transparent windows (:pull:`6135`)

- The :option:`--hold` flag now holds the window open at a shell prompt instead of asking the user to press a key

- A new option :opt:`text_fg_override_threshold` to force text colors to have high contrast regardless of color scheme (:pull:`6283`)

- When resizing OS Windows make the animation less jerky. Also show the window size in cells during the resize (:iss:`6341`)

- unicode_input kitten: Fix a regression in 0.28.0 that caused the order of recent and favorites entries to not be respected (:iss:`6214`)

- unicode_input kitten: Fix a regression in 0.28.0 that caused editing of favorites to sometimes hang

- clipboard kitten: Fix a bug causing the last MIME type available on the clipboard not being recognized when pasting

- clipboard kitten: Dont set clipboard when getting clipboard in filter mode (:iss:`6302`)

- Fix regression in 0.28.0 causing color fringing when rendering in transparent windows on light backgrounds (:iss:`6209`)

- show_key kitten: In kitty mode show the actual bytes sent by the terminal rather than a re-encoding of the parsed key event

- hints kitten: Fix a regression in 0.28.0 that broke using sub-groups in regexp captures (:iss:`6228`)

- hints kitten: Fix a regression in 0.28.0 that broke using lookahead/lookbehind in regexp captures (:iss:`6265`)

- diff kitten: Fix a regression in 0.28.0 that broke using relative paths as arguments to the kitten (:iss:`6325`)

- Fix re-using the image id of an animated image for a still image causing a crash (:iss:`6244`)

- kitty +open: Ask for permission before executing script files that are not marked as executable. This prevents accidental execution
  of script files via MIME type association from programs that unconditionally "open" attachments/downloaded files

- edit-in-kitty: Fix running edit-in-kitty with elevated privileges to edit a restricted file not working (:disc:`6245`)

- ssh kitten: Fix a regression in 0.28.0 that caused interrupt during setup to not be handled gracefully (:iss:`6254`)

- ssh kitten: Allow configuring the ssh kitten to skip some hosts via a new ``delegate`` config directive

- Graphics: Move images up along with text when the window is shrunk vertically (:iss:`6278`)

- Fix a regression in 0.28.0 that caused a buffer overflow when clearing the screen (:iss:`6306`, :pull:`6308`)

- Fix a regression in 0.27.0 that broke setting of specific edge padding/margin via remote control (:iss:`6333`)

- macOS: Fix window shadows not being drawn for transparent windows (:iss:`2827`, :pull:`6416`)

- Do not echo invalid DECRQSS queries back, behavior inherited from xterm (CVE-2008-2383). Similarly, fix an echo
  bug in the file transfer protocol due to insufficient sanitization of safe strings.


0.28.1 [2023-04-21]
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

- Fix a regression in the previous release that broke the remote file kitten (:iss:`6186`)

- Fix a regression in the previous release that broke handling of some keyboard shortcuts in some kittens on some keyboard layouts (:iss:`6189`)

- Fix a regression in the previous release that broke usage of custom themes (:iss:`6191`)

0.28.0 [2023-04-15]
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

- **Text rendering change**: Use sRGB correct linear gamma blending for nicer font
  rendering and better color accuracy with transparent windows.
  See the option :opt:`text_composition_strategy` for details.
  The obsolete :opt:`macos_thicken_font` will make the font too thick and needs to be removed manually
  if it is configured. (:pull:`5969`)

- icat kitten: Support display of images inside tmux >= 3.3 (:pull:`5664`)

- Graphics protocol: Add support for displaying images inside programs that do not support the protocol such as vim and tmux (:pull:`5664`)

- diff kitten: Add support for selecting multi-line text with the mouse

- Fix a regression in 0.27.0 that broke ``kitty @ set-font-size 0`` (:iss:`5992`)

- launch: When using ``--cwd=current`` for a remote system support running non shell commands as well (:disc:`5987`)

- When changing the cursor color via escape codes or remote control to a fixed color, do not reset cursor_text_color (:iss:`5994`)

- Input Method Extensions: Fix incorrect rendering of IME in-progress and committed text in some situations (:pull:`6049`, :pull:`6087`)

- Linux: Reduce minimum required OpenGL version from 3.3 to 3.1 + extensions (:iss:`2790`)

- Fix a regression that broke drawing of images below cell backgrounds (:iss:`6061`)

- macOS: Fix the window buttons not being hidden after exiting the traditional full screen (:iss:`6009`)

- When reloading configuration, also reload custom MIME types from :file:`mime.types` config file (:pull:`6012`)

- launch: Allow specifying the state (full screen/maximized/minimized) for newly created OS Windows (:iss:`6026`)

- Sessions: Allow specifying the OS window state via the ``os_window_state`` directive (:iss:`5863`)

- macOS: Display the newly created OS window in specified state to avoid or reduce the window transition animations (:pull:`6035`)

- macOS: Fix the maximized window not taking up full space when the title bar is hidden or when :opt:`resize_in_steps` is configured (:iss:`6021`)

- Linux: A new option :opt:`linux_bell_theme` to control which sound theme is used for the bell sound (:pull:`4858`)

- ssh kitten: Change the syntax of glob patterns slightly to match common usage
  elsewhere. Now the syntax is the same as "extendedglob" in most shells.

- hints kitten: Allow copying matches to named buffers (:disc:`6073`)

- Fix overlay windows not inheriting the per-window padding and margin settings
  of their parents (:iss:`6063`)

- Wayland KDE: Fix selecting in un-focused OS window not working correctly (:iss:`6095`)

- Linux X11: Fix a crash if the X server requests clipboard data after we have relinquished the clipboard (:iss:`5650`)

- Allow stopping of URL detection at newlines via :opt:`url_excluded_characters` (:iss:`6122`)

- Linux Wayland: Fix animated images not being animated continuously (:iss:`6126`)

- Keyboard input: Fix text not being reported as unicode codepoints for multi-byte characters in the kitty keyboard protocol (:iss:`6167`)


0.27.1 [2023-02-07]
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

- Fix :opt:`modify_font` not working for strikethrough position (:iss:`5946`)

- Fix a regression causing the ``edit-in-kitty`` command not working if :file:`kitten` is not added
  to PATH (:iss:`5956`)

- icat kitten: Fix a regression that broke display of animated GIFs over SSH (:iss:`5958`)

- Wayland GNOME: Fix for ibus not working when using XWayland (:iss:`5967`)

- Fix regression in previous release that caused incorrect entries in terminfo for modifier+F3 key combinations (:pull:`5970`)

- Bring back the deprecated and removed ``kitty +complete`` and delegate it to :program:`kitten` for backward compatibility (:pull:`5977`)

- Bump the version of Go needed to build kitty to ``1.20`` so we can use the Go stdlib ecdh package for crypto.


0.27.0 [2023-01-31]
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

- A new statically compiled, standalone executable, ``kitten`` (written in Go)
  that can be used on all UNIX-like servers for remote control (``kitten @``),
  viewing images (``kitten icat``), manipulating the clipboard (``kitten clipboard``), etc.

- :doc:`clipboard kitten </kittens/clipboard>`: Allow copying arbitrary data types to/from the clipboard, not just plain text

- Speed up the ``kitty @`` executable by ~10x reducing the time for typical
  remote control commands from ~50ms to ~5ms

- icat kitten: Speed up by using POSIX shared memory when possible to transfer
  image data to the terminal. Also support common image formats
  GIF/PNG/JPEG/WEBP/TIFF/BMP out of the box without needing ImageMagick.

- Option :opt:`show_hyperlink_targets` to show the target of terminal hyperlinks when hovering over them with the mouse (:pull:`5830`)

- Keyboard protocol: Remove ``CSI R`` from the allowed encodings of the :kbd:`F3` key as it conflicts with the *Cursor Position Report* escape code (:disc:`5813`)

- Allow using the cwd of the original process for :option:`launch --cwd` (:iss:`5672`)

- Session files: Expand environment variables (:disc:`5917`)

- Pass key events mapped to scroll actions to the program running in the terminal when the terminal is in alternate screen mode (:iss:`5839`)

- Implement :ref:`edit-in-kitty <edit_file>` using the new ``kitten`` static executable (:iss:`5546`, :iss:`5630`)

- Add an option :opt:`background_tint_gaps` to control background image tinting for window gaps (:iss:`5596`)

- A new option :opt:`undercurl_style` to control the rendering of undercurls (:pull:`5883`)

- Bash integration: Fix ``clone-in-kitty`` not working on bash >= 5.2 if environment variable values contain newlines or other special characters (:iss:`5629`)

- A new :ac:`sleep` action useful in combine based mappings to make kitty sleep before executing the next action

- Wayland GNOME: Workaround for latest mutter release breaking full screen for semi-transparent kitty windows (:iss:`5677`)

- A new option :opt:`tab_title_max_length` to limit the length of tab (:iss:`5718`)

- When drawing the tab bar have the default left and right margins drawn in a color matching the neighboring tab (:iss:`5719`)

- When using the :code:`include` directive in :file:`kitty.conf` make the environment variable :envvar:`KITTY_OS` available for OS specific config

- Wayland: Fix signal handling not working with some GPU drivers (:iss:`4636`)

- Remote control: When matching windows allow using negative id numbers to match recently created windows (:iss:`5753`)

- ZSH Integration: Bind :kbd:`alt+left` and :kbd:`alt+right` to move by word if not already bound. This mimics the default bindings in Terminal.app (:iss:`5793`)

- macOS: Allow to customize :sc:`Hide <hide_macos_app>`, :sc:`Hide Others <hide_macos_other_apps>`, :sc:`Minimize <minimize_macos_window>`, and :sc:`Quit <quit>` global menu shortcuts. Note that :opt:`clear_all_shortcuts` will remove these shortcuts now (:iss:`948`)

- When a multi-key sequence does not match any action, send all key events to the child program (:pull:`5841`)

- broadcast kitten: Allow pressing a key to stop echoing of input into the broadcast window itself (:disc:`5868`)

- When reporting unused activity in a window, ignore activity that occurs soon after a window resize (:iss:`5881`)

- Fix using :opt:`cursor` = ``none`` not working on text that has reverse video (:iss:`5897`)

- Fix ssh kitten not working on FreeBSD (:iss:`5928`)

- macOS: Export kitty selected text to the system for use with services that accept it (patch by Sertaç Ö. Yıldız)


0.26.5 [2022-11-07]
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

- Splits layout: Add a new mappable action to move the active window to the screen edge (:iss:`5643`)

- ssh kitten: Allow using absolute paths for the location of transferred data (:iss:`5607`)

- Fix a regression in the previous release that caused a ``resize_draw_strategy`` of ``static`` to not work (:iss:`5601`)

- Wayland KDE: Fix abort when pasting into Firefox (:iss:`5603`)

- Wayland GNOME: Fix ghosting when using :opt:`background_tint` (:iss:`5605`)

- Fix cursor position at x=0 changing to x=1 on resize (:iss:`5635`)

- Wayland GNOME: Fix incorrect window size in some circumstances when switching between windows with window decorations disabled (:iss:`4802`)

- Wayland: Fix high CPU usage when using some input methods (:pull:`5369`)

- Remote control: When matching window by `state:focused` and no window currently has keyboard focus, match the window belonging to the OS window that was last focused (:iss:`5602`)


0.26.4 [2022-10-17]
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

- macOS: Allow changing the kitty icon by placing a custom icon in the kitty config folder (:pull:`5464`)

- Allow centering the :opt:`background_image` (:iss:`5525`)

- X11: Fix a regression in the previous release that caused pasting from GTK based applications to have extra newlines (:iss:`5528`)

- Tab bar: Improve empty space management when some tabs have short titles, allocate the saved space to the active tab (:iss:`5548`)

- Fix :opt:`background_tint` not applying to window margins and padding (:iss:`3933`)

- Wayland: Fix background image scaling using tiled mode on high DPI screens

- Wayland: Fix an abort when changing background colors with :opt:`wayland_titlebar_color` set to ``background`` (:iss:`5562`)

- Update to Unicode 15.0 (:pull:`5542`)

- GNOME Wayland: Fix a memory leak in gnome-shell when using client side decorations


0.26.3 [2022-09-22]
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

- Wayland: Mark windows in which a bell occurs as urgent on compositors that support the xdg-activation protocol

- Allow passing null bytes through the system clipboard (:iss:`5483`)

- ssh kitten: Fix :envvar:`KITTY_PUBLIC_KEY` not being encoded properly when transmitting (:iss:`5496`)

- Sessions: Allow controlling which OS Window is active via the ``focus_os_window`` directive

- Wayland: Fix for bug in NVIDIA drivers that prevents transparency working (:iss:`5479`)

- Wayland: Fix for a bug that could cause kitty to become non-responsive when
  using multiple OS windows in a single instance on some compositors (:iss:`5495`)

- Wayland: Fix for a bug preventing kitty from starting on Hyprland when using a non-unit scale (:iss:`5467`)

- Wayland: Generate a XDG_ACTIVATION_TOKEN when opening URLs or running programs in the background via the launch action

- Fix a regression that caused kitty not to restore SIGPIPE after python nukes it when launching children. Affects bash which does not sanitize its signal mask. (:iss:`5500`)

- Fix a use-after-free when handling fake mouse clicks and the action causes windows to be removed/re-allocated (:iss:`5506`)


0.26.2 [2022-09-05]
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

- Allow creating :code:`overlay-main` windows, which are treated as the active window unlike normal overlays (:iss:`5392`)

- hints kitten: Allow using :doc:`launch` as the program to run, to open the result in a new kitty tab/window/etc. (:iss:`5462`)

- hyperlinked_grep kitten: Allow control over which parts of ``rg`` output are hyperlinked (:pull:`5428`)

- Fix regression in 0.26.0 that caused launching kitty without working STDIO handles to result in high CPU usage and prewarming failing (:iss:`5444`)

- :doc:`/launch`: Allow setting the margin and padding for newly created windows (:iss:`5463`)

- macOS: Fix regression in 0.26.0 that caused asking the user for a line of input such as for :ac:`set_tab_title` to not work (:iss:`5447`)

- hints kitten: hyperlink matching: Fix hints occasionally matching text on subsequent line as part of hyperlink (:pull:`5450`)

- Fix a regression in 0.26.0 that broke mapping of native keys whose key codes did not fit in 21 bits (:iss:`5452`)

- Wayland: Fix remembering window size not accurate when client side decorations are present

- Fix an issue where notification identifiers were not sanitized leading to
  code execution if the user clicked on a notification popup from a malicious
  source. Thanks to Carter Sande for discovering this vulnerability.


0.26.1 [2022-08-30]
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

- ssh kitten: Fix executable permission missing from kitty bootstrap script (:iss:`5438`)

- Fix a regression in 0.26.0 that caused kitty to no longer set the ``LANG`` environment variable on macOS (:iss:`5439`)

- Allow specifying a title when using the :ac:`set_tab_title` action (:iss:`5441`)


0.26.0 [2022-08-29]
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

- A new option :opt:`remote_control_password` to use fine grained permissions for what can be remote controlled (:disc:`5320`)

- Reduce startup latency by ~30 milliseconds when running kittens via key bindings inside kitty (:iss:`5159`)

- A new option :opt:`modify_font` to adjust various font metrics like underlines, cell sizes etc. (:pull:`5265`)

- A new shortcut :sc:`show_kitty_doc` to display the kitty docs in a browser

- Graphics protocol: Only delete temp files if they have the string
  :code:`tty-graphics-protocol` in their file paths. This prevents deletion of arbitrary files in :file:`/tmp`.

- Deprecate the ``adjust_baseline``, ``adjust_line_height`` and ``adjust_column_width`` options in favor of :opt:`modify_font`

- Wayland: Fix a regression in the previous release that caused mouse cursor
  animation and keyboard repeat to stop working when switching seats (:iss:`5188`)

- Allow resizing windows created in session files (:pull:`5196`)

- Fix horizontal wheel events not being reported to client programs when they grab the mouse (:iss:`2819`)

- macOS: Remote control: Fix unable to launch a new OS window or background process when there is no OS window (:iss:`5210`)

- macOS: Fix unable to open new tab or new window when there is no OS window (:iss:`5276`)

- kitty @ set-colors: Fix changing inactive_tab_foreground not working (:iss:`5214`)

- macOS: Fix a regression that caused switching keyboard input using Eisu and
  Kana keys not working (:iss:`5232`)

- Add a mappable action to toggle the mirrored setting for the tall and fat
  layouts (:pull:`5344`)

- Add a mappable action to switch between predefined bias values for the tall and fat
  layouts (:pull:`5352`)

- Wayland: Reduce flicker at startup by not using render frames immediately after a resize (:iss:`5235`)

- Linux: Update cursor position after all key presses not just pre-edit text
  changes (:iss:`5241`)

- ssh kitten: Allow ssh kitten to work from inside tmux, provided the tmux
  session inherits the correct KITTY env vars (:iss:`5227`)

- ssh kitten: A new option :code:`--symlink-strategy` to control how symlinks
  are copied to the remote machine (:iss:`5249`)

- ssh kitten: Allow pressing :kbd:`Ctrl+C` to abort ssh before the connection is
  completed (:iss:`5271`)

- Bash integration: Fix declare not creating global variables in .bashrc (:iss:`5254`)

- Bash integration: Fix the inherit_errexit option being set by shell integration (:iss:`5349`)

- :command:`kitty @ scroll-window` allow scrolling by fractions of a screen
  (:iss:`5294`)

- remote files kitten: Fix working with files whose names have characters that
  need to be quoted in shell scripts (:iss:`5313`)

- Expand ~ in paths configured in :opt:`editor` and :opt:`exe_search_path` (:disc:`5298`)

- Allow showing the working directory of the active window in tab titles
  (:pull:`5314`)

- ssh kitten: Allow completion of ssh options between the destination and command (:iss:`5322`)

- macOS: Fix speaking selected text not working (:iss:`5357`)

- Allow ignoring failure to close windows/tabs via rc commands (:disc:`5406`)

- Fix hyperlinks not present when fetching text from the history buffer
  (:iss:`5427`)


0.25.2 [2022-06-07]
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

- A new command :command:`edit-in-kitty` to :ref:`edit_file`

- Allow getting the last non-empty command output easily via an action or
  remote control (:pull:`4973`)

- Fix a bug that caused :opt:`macos_colorspace` to always be ``default`` regardless of its actual value (:iss:`5129`)

- diff kitten: A new option :opt:`kitten-diff.ignore_name` to exclude files and directories from being scanned (:pull:`5171`)

- ssh kitten: Fix bash not being executed as a login shell since kitty 0.25.0 (:iss:`5130`)

- macOS: When pasting text and the clipboard has a filesystem path, paste the
  full path instead of the text, which is sometimes just the file name (:pull:`5142`)

- macOS: Allow opening executables without a file extension with kitty as well
  (:iss:`5160`)

- Themes kitten: Add a tab to show user defined custom color themes separately
  (:pull:`5150`)

- Iosevka: Fix incorrect rendering when there is a combining char that does not
  group with its neighbors (:iss:`5153`)

- Weston: Fix client side decorations flickering on slow computers during
  window resize (:iss:`5162`)

- Remote control: Fix commands with large or asynchronous payloads like
  :command:`kitty @ set-backround-image`, :command:`kitty @ set-window-logo`
  and :command:`kitty @ select-window` not working correctly
  when using a socket (:iss:`5165`)

- hints kitten: Fix surrounding quotes/brackets and embedded carriage returns
  not being removed when using line number processing (:iss:`5170`)


0.25.1 [2022-05-26]
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

- Shell integration: Add a command to :ref:`clone_shell`

- Remote control: Allow using :ref:`Boolean operators <search_syntax>` when constructing queries to match windows or tabs

- Sessions: Fix :code:`os_window_size` and :code:`os_window_class` not applying to the first OS Window (:iss:`4957`)

- Allow using the cwd of the oldest as well as the newest foreground process for :option:`launch --cwd` (:disc:`4869`)

- Bash integration: Fix the value of :opt:`shell_integration` not taking effect if the integration script is sourced in bashrc (:pull:`4964`)

- Fix a regression in the previous release that caused mouse move events to be incorrectly reported as drag events even when a button is not pressed (:iss:`4992`)

- remote file kitten: Integrate with the ssh kitten for improved performance
  and robustness. Re-uses the control master connection of the ssh kitten to
  avoid round-trip latency.

- Fix tab selection when closing a new tab not correct in some scenarios (:iss:`4987`)

- A new action :ac:`open_url` to open the specified URL (:pull:`5004`)

- A new option :opt:`select_by_word_characters_forward` that allows changing
  which characters are considered part of a word to the right when double clicking to select
  words (:pull:`5103`)

- macOS: Make the global menu shortcut to open kitty website configurable (:pull:`5004`)

- macOS: Add the :opt:`macos_colorspace` option to control what color space colors are rendered in (:iss:`4686`)

- Fix reloading of config not working when :file:`kitty.conf` does not exist when kitty is launched (:iss:`5071`)

- Fix deleting images by row not calculating image bounds correctly (:iss:`5081`)

- Increase the max number of combining chars per cell from two to three, without increasing memory usage.

- Linux: Load libfontconfig at runtime to allow the binaries to work for
  running kittens on servers without FontConfig

- GNOME: Fix for high CPU usage caused by GNOME's text input subsystem going
  into an infinite loop when IME cursor position is updated after a done event
  (:iss:`5105`)


0.25.0 [2022-04-11]
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

- :doc:`kittens/ssh`: automatic shell integration when using SSH. Easily
  clone local shell and editor configuration on remote machines, and automatic
  re-use of existing connections to avoid connection setup latency.

- When pasting URLs at shell prompts automatically quote them. Also allow filtering pasted text and confirm pastes. See :opt:`paste_actions` for details. (:iss:`4873`)

- Change the default value of :opt:`confirm_os_window_close` to ask for confirmation when closing windows that are not sitting at shell prompts

- A new value :code:`last_reported` for :option:`launch --cwd` to use the current working directory last reported by the program running in the terminal

- macOS: When using Apple's less as the pager for viewing scrollback strip out OSC codes as it can't parse them (:iss:`4788`)

- diff kitten: Fix incorrect rendering in rare circumstances when scrolling after changing the context size (:iss:`4831`)

- icat kitten: Fix a regression that broke :option:`kitty +kitten icat --print-window-size` (:pull:`4818`)

- Wayland: Fix :opt:`hide_window_decorations` causing docked windows to be resized on blur (:iss:`4797`)

- Bash integration: Prevent shell integration code from running twice if user enables both automatic and manual integration

- Bash integration: Handle existing PROMPT_COMMAND ending with a literal newline

- Fix continued lines not having their continued status reset on line feed (:iss:`4837`)

- macOS: Allow the New kitty Tab/Window Here services to open multiple selected folders.  (:pull:`4848`)

- Wayland: Fix a regression that broke IME when changing windows/tabs (:iss:`4853`)

- macOS: Fix Unicode paths not decoded correctly when dropping files (:pull:`4879`)

- Avoid flicker when starting kittens such as the hints kitten (:iss:`4674`)

- A new action :ac:`scroll_prompt_to_top` to move the current prompt to the top (:pull:`4891`)

- :ac:`select_tab`: Use stable numbers when selecting the tab (:iss:`4792`)

- Only check for updates in the official binary builds. Distro packages or source builds will no longer check for updates, regardless of the
  value of :opt:`update_check_interval`.

- Fix :opt:`inactive_text_alpha` still being applied to the cursor hidden window after focus (:iss:`4928`)

- Fix resizing window that is extra tall/wide because of left-over cells not
  working reliably (:iss:`4913`)

- A new action :ac:`close_other_tabs_in_os_window` to close other tabs in the active OS window (:pull:`4944`)


0.24.4 [2022-03-03]
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

- Shell integration: Fix the default Bash :code:`$HISTFILE` changing to :file:`~/.sh_history` instead of :file:`~/.bash_history` (:iss:`4765`)

- Linux binaries: Fix binaries not working on systems with older Wayland client libraries (:iss:`4760`)

- Fix a regression in the previous release that broke kittens launched with :code:`STDIN` not connected to a terminal (:iss:`4763`)

- Wayland: Fix surface configure events not being acknowledged before commit
  the resized buffer (:pull:`4768`)


0.24.3 [2022-02-28]
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

- Bash integration: No longer modify :file:`~/.bashrc` to load :ref:`shell integration <shell_integration>`.
  It is recommended to remove the lines used to load the shell integration from :file:`~/.bashrc` as they are no-ops.

- macOS: Allow kitty to handle various URL types. Can be configured via
  :ref:`launch_actions` (:pull:`4618`)

- macOS: Add a new service ``Open with kitty`` to open file types that are not
  recognized by the system (:pull:`4641`)

- Splits layout: A new value for :option:`launch --location` to auto-select the split axis when splitting existing windows.
  Wide windows are split side-by-side and tall windows are split one-above-the-other

- hints kitten: Fix a regression that broke recognition of path:linenumber:colnumber (:iss:`4675`)

- Fix a regression in the previous release that broke :opt:`active_tab_foreground` (:iss:`4620`)

- Fix :ac:`show_last_command_output` not working when the output is stored
  partially in the scrollback pager history buffer (:iss:`4435`)

- When dropping URLs/files onto kitty at a shell prompt insert them appropriately quoted and space
  separated (:iss:`4734`)

- Improve CWD detection when there are multiple foreground processes in the TTY process group

- A new option :opt:`narrow_symbols` to turn off opportunistic wide rendering of private use codepoints

- ssh kitten: Fix location of generated terminfo files on NetBSD (:iss:`4622`)

- A new action to clear the screen up to the line containing the cursor, see
  :ac:`clear_terminal`

- A new action :ac:`copy_ansi_to_clipboard` to copy the current selection with ANSI formatting codes
  (:iss:`4665`)

- Linux: Do not rescale fallback fonts to match the main font cell height, instead just
  set the font size and let FreeType take care of it. This matches
  rendering on macOS (:iss:`4707`)

- macOS: Fix a regression in the previous release that broke switching input
  sources by keyboard (:iss:`4621`)

- macOS: Add the default shortcut :kbd:`cmd+k` to clear the terminal screen and
  scrollback up to the cursor (:iss:`4625`)

- Fix a regression in the previous release that broke strikethrough (:disc:`4632`)

- A new action :ac:`scroll_prompt_to_bottom` to move the current prompt
  to the bottom, filling in the window from the scrollback (:pull:`4634`)

- Add two special arguments ``@first-line-on-screen`` and ``@last-line-on-screen``
  for the :doc:`launch <launch>` command to be used for pager positioning.
  (:iss:`4462`)

- Linux: Fix rendering of emoji when using scalable fonts such as Segoe UI Emoji

- Shell integration: bash: Dont fail if an existing PROMPT_COMMAND ends with a semi-colon (:iss:`4645`)

- Shell integration: bash: Fix rendering of multiline prompts with more than two lines (:iss:`4681`)

- Shell integration: fish: Check fish version 3.3.0+ and exit on outdated versions (:pull:`4745`)

- Shell integration: fish: Fix pipestatus being overwritten (:pull:`4756`)

- Linux: Fix fontconfig alias not being used if the aliased font is dual spaced instead of monospaced (:iss:`4649`)

- macOS: Add an option :opt:`macos_menubar_title_max_length` to control the max length of the window title displayed in the global menubar (:iss:`2132`)

- Fix :opt:`touch_scroll_multiplier` also taking effect in terminal programs such as vim that handle mouse events themselves (:iss:`4680`)

- Fix symbol/PUA glyphs loaded via :opt:`symbol_map` instead of as fallbacks not using following spaces to render larger versions (:iss:`4670`)

- macOS: Fix regression in previous release that caused Apple's global shortcuts to not work if they had never been configured on a particular machine (:iss:`4657`)

- Fix a fast *click, move mouse, click* sequence causing the first click event to be discarded (:iss:`4603`)

- Wayland: Fix wheel mice with line based scrolling being incorrectly handled as high precision devices (:iss:`4694`)

- Wayland: Fix touchpads and high resolution wheels not scrolling at the same speed on monitors with different scales (:iss:`4703`)

- Add an option :opt:`wheel_scroll_min_lines` to set the minimum number of lines for mouse wheel scrolling when using a mouse with a wheel that generates very small offsets when slow scrolling (:pull:`4710`)

- macOS: Make the shortcut to toggle full screen configurable (:pull:`4714`)

- macOS: Fix the mouse cursor being set to arrow after switching desktops or toggling full screen (:pull:`4716`)

- Fix copying of selection after selection has been scrolled off history buffer raising an error (:iss:`4713`)


0.24.2 [2022-02-03]
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

- macOS: Allow opening text files, images and directories with kitty when
  launched using "Open with" in Finder (:iss:`4460`)

- Allow including config files matching glob patterns in :file:`kitty.conf`
  (:iss:`4533`)

- Shell integration: Fix bash integration not working when ``PROMPT_COMMAND``
  is used to change the prompt variables (:iss:`4476`)

- Shell integration: Fix cursor shape not being restored to default when
  running commands in the shell

- Improve the UI of the ask kitten (:iss:`4545`)

- Allow customizing the placement and formatting of the
  :opt:`tab_activity_symbol` and :opt:`bell_on_tab` symbols
  by adding them to the :opt:`tab_title_template` (:iss:`4581`, :pull:`4507`)

- macOS: Persist "Secure Keyboard Entry" across restarts to match the behavior
  of Terminal.app (:iss:`4471`)

- hints kitten: Fix common single letter extension files not being detected
  (:iss:`4491`)

- Support dotted and dashed underline styles (:pull:`4529`)

- For the vertical and horizontal layouts have the windows arranged on a ring
  rather than a plane. This means the first and last window are considered
  neighbors (:iss:`4494`)

- A new action to clear the current selection (:iss:`4600`)

- Shell integration: fish: Fix cursor shape not working with fish's vi mode
  (:iss:`4508`)

- Shell integration: fish: Dont override fish's native title setting functionality.
  See `discussion <https://github.com/fish-shell/fish-shell/issues/8641>`__.

- macOS: Fix hiding via :kbd:`cmd+h` not working on macOS 10.15.7 (:iss:`4472`)

- Draw the dots for braille characters more evenly spaced at all font sizes (:iss:`4499`)

- icat kitten: Add options to mirror images and remove their transparency
  before displaying them (:iss:`4513`)

- macOS: Respect the users system-wide global keyboard shortcut preferences
  (:iss:`4501`)

- macOS: Fix a few key-presses causing beeps from Cocoa's text input system
  (:iss:`4489`)

- macOS: Fix using shortcuts from the global menu bar as subsequent key presses
  in a multi key mapping not working (:iss:`4519`)

- Fix getting last command output not working correctly when the screen is
  scrolled (:pull:`4522`)

- Show number of windows per tab in the :ac:`select_tab` action (:pull:`4523`)

- macOS: Fix the shift key not clearing pre-edit text in IME (:iss:`4541`)

- Fix clicking in a window to focus it and typing immediately sometimes having
  unexpected effects if at a shell prompt (:iss:`4128`)

- themes kitten: Allow writing to a different file than :file:`kitty.conf`.


0.24.1 [2022-01-06]
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

- Shell integration: Work around conflicts with some zsh plugins (:iss:`4428`)

- Have the zero width space and various other characters from the *Other,
  formatting* Unicode category be treated as combining characters (:iss:`4439`)

- Fix using ``--shell-integration`` with :file:`setup.py` broken (:iss:`4434`)

- Fix showing debug information not working if kitty's :file:`STDIN` is not a tty
  (:iss:`4424`)

- Linux: Fix a regression that broke rendering of emoji with variation selectors
  (:iss:`4444`)


0.24.0 [2022-01-04]
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

- Integrate kitty closely with common shells such as zsh, fish and bash.
  This allows lots of niceties such as jumping to previous prompts, opening the
  output of the last command in a new window, etc. See :ref:`shell_integration`
  for details. Packagers please read :ref:`packagers`.

- A new shortcut :sc:`focus_visible_window` to visually focus a window using
  the keyboard. Pressing it causes numbers to appear over each visible window
  and you can press the number to focus the corresponding window (:iss:`4110`)

- A new facility :opt:`window_logo_path` to draw an arbitrary PNG image as
  logo in the corner of a kitty window (:pull:`4167`)

- Allow rendering the cursor with a *reverse video* effect. See :opt:`cursor`
  for details (:iss:`126`)

- Allow rendering the mouse selection with a *reverse video* effect. See
  :opt:`selection_foreground` (:iss:`646`)

- A new option :opt:`tab_bar_align` to draw the tab bar centered or right
  aligned (:iss:`3946`)

- Allow the user to supply a custom Python function to draw tab bar. See
  :opt:`tab_bar_style`

- A new remote control command to :program:`change the tab color <kitty @
  set-tab-color>` (:iss:`1287`)

- A new remote control command to :program:`visually select a window <kitty @
  select-window>` (:iss:`4165`)

- Add support for reporting mouse events with pixel coordinates using the
  ``SGR_PIXEL_PROTOCOL`` introduced in xterm 359

- When programs ask to read from the clipboard prompt, ask the user to allow
  the request by default instead of denying it by default. See
  :opt:`clipboard_control` for details (:iss:`4022`)

- A new mappable action ``swap_with_window`` to swap the current window with another window in the tab, visually

- A new :program:`remote control command <kitty @ set-enabled-layouts>` to change
  the enabled layouts in a tab (:iss:`4129`)

- A new option :opt:`bell_path` to specify the path to a sound file
  to use as the bell sound

- A new option :opt:`exe_search_path` to modify the locations kitty searches
  for executables to run (:iss:`4324`)

- broadcast kitten: Show a "fake" cursor in all windows being broadcast too
  (:iss:`4225`)

- Allow defining :opt:`aliases <action_alias>` for more general actions, not just kittens
  (:pull:`4260`)

- Fix a regression that caused :option:`kitty --title` to not work when
  opening new OS windows using :option:`kitty --single-instance` (:iss:`3893`)

- icat kitten: Fix display of JPEG images that are rotated via EXIF data and
  larger than available screen size (:iss:`3949`)

- macOS: Fix SIGUSR1 quitting kitty instead of reloading the config file (:iss:`3952`)

- Launch command: Allow specifying the OS window title

- broadcast kitten: Allow broadcasting :kbd:`ctrl+c` (:pull:`3956`)

- Fix space ligatures not working with Iosevka for some characters in the
  Enclosed Alphanumeric Supplement (:iss:`3954`)

- hints kitten: Fix a regression that caused using the default open program
  to trigger open actions instead of running the program (:iss:`3968`)

- Allow deleting environment variables in :opt:`env` by specifying
  just the variable name, without a value

- Fix :opt:`active_tab_foreground` not being honored when :opt:`tab_bar_style`
  is ``slant`` (:iss:`4053`)

- When a :opt:`tab_bar_background` is specified it should extend to the edges
  of the OS window (:iss:`4054`)

- Linux: Fix IME with fcitx5 not working after fcitx5 is restarted
  (:pull:`4059`)

- Various improvements to IME integration (:iss:`4219`)

- Remote file transfer: Fix transfer not working if custom ssh port or identity
  is specified on the command line (:iss:`4067`)

- Unicode input kitten: Implement scrolling when more results are found than
  the available display space (:pull:`4068`)

- Allow middle clicking on a tab to close it (:iss:`4151`)

- The command line option ``--watcher`` has been deprecated in favor of the
  :opt:`watcher` option in :file:`kitty.conf`. It has the advantage of
  applying to all windows, not just the initially created ones. Note that
  ``--watcher`` now also applies to all windows, not just initially created ones.

- **Backward incompatibility**: No longer turn on the kitty extended keyboard
  protocol's disambiguate mode when the client sends the XTMODKEYS escape code.
  Applications must use the dedicated escape code to turn on the protocol.
  (:iss:`4075`)

- Fix soft hyphens not being preserved when round tripping text through the
  terminal

- macOS: Fix :kbd:`ctrl+shift` with :kbd:`Esc` or :kbd:`F1` - :kbd:`F12` not working
  (:iss:`4109`)

- macOS: Fix :opt:`resize_in_steps` not working correctly on high DPI screens
  (:iss:`4114`)

- Fix the :program:`resize OS Windows <kitty @ resize-os-window>` setting a
  slightly incorrect size on high DPI screens (:iss:`4114`)

- :program:`kitty @ launch` - when creating tabs with the ``--match`` option create
  the tab in the OS Window containing the result of the match rather than
  the active OS Window (:iss:`4126`)

- Linux X11: Add support for 10bit colors (:iss:`4150`)

- Fix various issues with changing :opt:`tab_bar_background` by remote control
  (:iss:`4152`)

- A new option :opt:`tab_bar_margin_color` to control the color of the tab bar
  margins

- A new option :opt:`visual_bell_color` to customize the color of the visual bell
  (:pull:`4181`)

- Add support for OSC 777 based desktop notifications

- Wayland: Fix pasting from applications that use a MIME type of "text/plain"
  rather than "text/plain;charset=utf-8" not working (:iss:`4183`)

- A new mappable action to close windows with a confirmation (:iss:`4195`)

- When remembering OS window sizes for full screen windows use the size before
  the window became fullscreen (:iss:`4221`)

- macOS: Fix keyboard input not working after toggling fullscreen till the
  window is clicked in

- A new mappable action ``nth_os_window`` to focus the specified nth OS
  window. (:pull:`4316`)

- macOS: The kitty window can be scrolled by the mouse wheel when OS window not
  in focus. (:pull:`4371`)

- macOS: Light or dark system appearance can be specified in
  :opt:`macos_titlebar_color` and used in kitty themes. (:pull:`4378`)


0.23.1 [2021-08-17]
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

- macOS: Fix themes kitten failing to download themes because of missing SSL
  root certificates (:iss:`3936`)

- A new option :opt:`clipboard_max_size` to control the maximum size
  of data that kitty will transmit to the system clipboard on behalf of
  programs running inside it (:iss:`3937`)

- When matching windows/tabs in kittens or using remote control, allow matching
  by recency. ``recent:0`` matches the active window/tab, ``recent:1`` matches
  the previous window/tab and so on

- themes kitten: Fix only the first custom theme file being loaded correctly
  (:iss:`3938`)


0.23.0 [2021-08-16]
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

- A new :doc:`themes kitten </kittens/themes>` to easily change kitty themes.
  Choose from almost two hundred themes in the `kitty themes repository
  <https://github.com/kovidgoyal/kitty-themes>`_

- A new style for the tab bar that makes tabs looks like the tabs in a physical
  tabbed file, see :opt:`tab_bar_style`

- Make the visual bell flash more gentle, especially on dark themes
  (:pull:`2937`)

- Fix :option:`kitty --title` not overriding the OS Window title when multiple
  tabs are present. Also this option is no longer used as the default title for
  windows, allowing individual tabs/windows to have their own titles, even when
  the OS Window has a fixed overall title (:iss:`3893`)

- Linux: Fix some very long ligatures being rendered incorrectly at some font
  sizes (:iss:`3896`)

- Fix shift+middle click to paste sending a mouse press event but no release
  event which breaks some applications that grab the mouse but can't handle
  mouse events (:iss:`3902`)

- macOS: When the language is set to English and the country to one for which
  an English locale does not exist, set :envvar:`LANG` to ``en_US.UTF-8``
  (:iss:`3899`)

- terminfo: Fix "cnorm" the property for setting the cursor to normal using a
  solid block rather than a blinking block cursor (:iss:`3906`)

- Add :opt:`clear_all_mouse_actions` to clear all mouse actions defined to
  that point (:iss:`3907`)

- Fix the remote file kitten not working when using -- with ssh. The ssh kitten
  was recently changed to do this (:iss:`3929`)

- When dragging word or line selections, ensure the initially selected item is
  never deselected. This matches behavior in most other programs (:iss:`3930`)

- hints kitten: Make copy/paste with the :option:`kitty +kitten hints
  --program` option work when using the ``self``
  :option:`kitty +kitten hints --linenum-action` (:iss:`3931`)


0.22.2 [2021-08-02]
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

- macOS: Fix a long standing bug that could cause kitty windows to stop
  updating, that got worse in the previous release (:iss:`3890` and
  :iss:`2016`)

- Wayland: A better fix for compositors like sway that can toggle client side
  decorations on and off (:iss:`3888`)


0.22.1 [2021-07-31]
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

- Fix a regression in the previous release that broke ``kitty --help`` (:iss:`3869`)

- Graphics protocol: Fix composing onto currently displayed frame not updating the frame on the GPU (:iss:`3874`)

- Fix switching to previously active tab after detaching a tab not working (:pull:`3871`)

- macOS: Fix an error on Apple silicon when enumerating monitors (:pull:`3875`)

- detach_window: Allow specifying the previously active tab or the tab to the left/right of
  the active tab (:disc:`3877`)

- broadcast kitten: Fix a regression in ``0.20.0`` that broke sending of some
  keys, such as backspace

- Linux binary: Remove any RPATH build artifacts from bundled libraries

- Wayland: If the compositor turns off server side decorations after turning
  them on do not draw client side decorations (:iss:`3888`)


0.22.0 [2021-07-26]
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

- Add a new :ac:`toggle_layout` action to easily zoom/unzoom a window

- When right clicking to extend a selection, move the nearest selection
  boundary rather than the end of the selection. To restore previous behavior
  use ``mouse_map right press ungrabbed mouse_selection move-end``.

- When opening hyperlinks, allow defining open actions for directories
  (:pull:`3836`)

- When using the OSC 52 escape code to copy to clipboard allow large
  copies (up to 8MB) without needing a kitty specific chunking protocol.
  Note that if you used the chunking protocol in the past, it will no longer
  work and you should switch to using the unmodified protocol which has the
  advantage of working with all terminal emulators.

- Fix a bug in the implementation of the synchronized updates escape code that
  could cause incorrect parsing if either the pending buffer capacity or the
  pending timeout were exceeded (:iss:`3779`)

- A new remote control command to :program:`resize the OS Window <kitty @
  resize-os-window>`

- Graphics protocol: Add support for composing rectangles from one animation
  frame onto another (:iss:`3809`)

- diff kitten: Remove limit on max line length of 4096 characters (:iss:`3806`)

- Fix turning off cursor blink via escape codes not working (:iss:`3808`)

- Allow using neighboring window operations in the stack layout. The previous
  window is considered the left and top neighbor and the next window is
  considered the bottom and right neighbor (:iss:`3778`)

- macOS: Render colors in the sRGB colorspace to match other macOS terminal
  applications (:iss:`2249`)

- Add a new variable ``{num_window_groups}`` for the :opt:`tab_title_template`
  (:iss:`3837`)

- Wayland: Fix :opt:`initial_window_width/height <remember_window_size>` specified
  in cells not working on High DPI screens (:iss:`3834`)

- A new theme for the kitty website with support for dark mode.

- Render ┄ ┅ ┆ ┇ ┈ ┉ ┊ ┋ with spaces at the edges. Matches rendering in
  most other programs and allows long chains of them to look better
  (:iss:`3844`)

- hints kitten: Detect paths and hashes that appear over multiple lines.
  Note that this means that all line breaks in the text are no longer \n
  soft breaks are instead \r. If you use a custom regular expression that
  is meant to match over line breaks, you will need to match over both.
  (:iss:`3845`)

- Allow leading or trailing spaces in :opt:`tab_activity_symbol`

- Fix mouse actions not working when caps lock or num lock are engaged
  (:iss:`3859`)

- macOS: Fix automatic detection of bold/italic faces for fonts that
  use the family name as the full face name of the regular font not working
  (:iss:`3861`)

- clipboard kitten: fix copies to clipboard not working without the
  :option:`kitty +kitten clipboard --wait-for-completion` option


0.21.2 [2021-06-28]
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

- A new ``adjust_baseline`` option to adjust the vertical alignment of text
  inside a line (:pull:`3734`)

- A new :opt:`url_excluded_characters` option to exclude additional characters
  when detecting URLs under the mouse (:pull:`3738`)

- Fix a regression in 0.21.0 that broke rendering of private use Unicode symbols followed
  by spaces, when they also exist not followed by spaces (:iss:`3729`)

- ssh kitten: Support systems where the login shell is a non-POSIX shell
  (:iss:`3405`)

- ssh kitten: Add completion (:iss:`3760`)

- ssh kitten: Fix "Connection closed" message being printed by ssh when running
  remote commands

- Add support for the XTVERSION escape code

- macOS: Fix a regression in 0.21.0 that broke middle-click to paste from clipboard (:iss:`3730`)

- macOS: Fix shortcuts in the global menu bar responding slowly when cursor blink
  is disabled/timed out (:iss:`3693`)

- When displaying scrollback ensure that the window does not quit if the amount
  of scrollback is less than a screen and the user has the ``--quit-if-one-screen``
  option enabled for less (:iss:`3740`)

- Linux: Fix Emoji/bitmapped fonts not use able in symbol_map

- query terminal kitten: Allow querying font face and size information
  (:iss:`3756`)

- hyperlinked grep kitten: Fix context options not generating contextual output (:iss:`3759`)

- Allow using superscripts in tab titles (:iss:`3763`)

- Unicode input kitten: Fix searching when a word has more than 1024 matches (:iss:`3773`)


0.21.1 [2021-06-14]
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

- macOS: Fix a regression in the previous release that broke rendering of
  strikeout (:iss:`3717`)

- macOS: Fix a crash when rendering ligatures larger than 128 characters
  (:iss:`3724`)

- Fix a regression in the previous release that could cause a crash when
  changing layouts and mousing (:iss:`3713`)


0.21.0 [2021-06-12]
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

- Allow reloading the :file:`kitty.conf` config file by pressing
  :sc:`reload_config_file`. (:iss:`1292`)

- Allow clicking URLs to open them without needing to also hold
  :kbd:`ctrl+shift`

- Allow remapping all mouse button press/release events to perform arbitrary
  actions. :ref:`See details <conf-kitty-mouse.mousemap>` (:iss:`1033`)

- Support infinite length ligatures (:iss:`3504`)

- **Backward incompatibility**: The options to control which modifiers keys to
  press for various mouse actions have been removed, if you used these options,
  you will need to replace them with configuration using the new
  :ref:`mouse actions framework <conf-kitty-mouse.mousemap>` as they will be
  ignored. The options were: ``terminal_select_modifiers``,
  ``rectangle_select_modifiers`` and ``open_url_modifiers``.

- Add a configurable mouse action (:kbd:`ctrl+alt+triplepress` to select from the
  clicked point to the end of the line. (:iss:`3585`)

- Add the ability to un-scroll the screen to the ``kitty @ scroll-window``
  remote control command (:iss:`3604`)

- A new option, :opt:`tab_bar_margin_height` to add margins around the
  top and bottom edges of the tab bar (:iss:`3247`)

- Unicode input kitten: Fix a regression in 0.20.0 that broke keyboard handling
  when the NumLock or CapsLock modifiers were engaged. (:iss:`3587`)

- Fix a regression in 0.20.0 that sent incorrect bytes for the :kbd:`F1`-:kbd:`F4` keys
  in rmkx mode (:iss:`3586`)

- macOS: When the Apple Color Emoji font lacks an emoji glyph search for it in other
  installed fonts (:iss:`3591`)

- macOS: Fix rendering getting stuck on some machines after sleep/screensaver
  (:iss:`2016`)

- macOS: Add a new ``Shell`` menu to the global menubar with some commonly used
  actions (:pull:`3653`)

- macOS: Fix the baseline for text not matching other CoreText based
  applications for some fonts (:iss:`2022`)

- Add a few more special commandline arguments for the launch command. Now all
  ``KITTY_PIPE_DATA`` is also available via command line argument substitution
  (:iss:`3593`)

- Fix dynamically changing the background color in a window causing rendering
  artifacts in the tab bar (:iss:`3595`)

- Fix passing STDIN to launched background processes causing them to not inherit
  environment variables (:pull:`3603`)

- Fix deleting windows that are not the last window via remote control leaving
  no window focused (:iss:`3619`)

- Add an option :option:`kitten @ get-text --add-cursor` to also get the current
  cursor position and state as ANSI escape codes (:iss:`3625`)

- Add an option :option:`kitten @ get-text --add-wrap-markers` to add line wrap
  markers to the output (:pull:`3633`)

- Improve rendering of curly underlines on HiDPI screens (:pull:`3637`)

- ssh kitten: Mimic behavior of ssh command line client more closely by
  executing any command specified on the command line via the users' shell
  just as ssh does (:iss:`3638`)

- Fix trailing parentheses in URLs not being detected (:iss:`3688`)

- Tab bar: Use a lower contrast color for tab separators (:pull:`3666`)

- Fix a regression that caused using the ``title`` command in session files
  to stop working (:iss:`3676`)

- macOS: Fix a rare crash on exit (:iss:`3686`)

- Fix ligatures not working with the `Iosevka
  <https://github.com/be5invis/Iosevka>`_ font (requires Iosevka >= 7.0.4)
  (:iss:`297`)

- Remote control: Allow matching tabs by index number in currently active OS
  Window (:iss:`3708`)

- ssh kitten: Fix non-standard properties in terminfo such as the ones used for
  true color not being copied (:iss:`312`)


0.20.3 [2021-05-06]
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

- macOS: Distribute universal binaries with both ARM and Intel architectures

- A new ``show_key`` kitten to easily see the bytes generated by the terminal
  for key presses in the various keyboard modes (:pull:`3556`)

- Linux: Fix keyboard layout change keys defined via compose rules not being
  ignored

- macOS: Fix Spotlight search of global menu not working in non-English locales
  (:pull:`3567`)

- Fix tab activity symbol not appearing if no other changes happen in tab bar even when
  there is activity in a tab (:iss:`3571`)

- Fix focus changes not being sent to windows when focused window changes
  because of the previously focused window being closed (:iss:`3571`)


0.20.2 [2021-04-28]
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

- A new protocol extension to :ref:`unscroll <unscroll>` text from the
  scrollback buffer onto the screen. Useful, for example, to restore
  the screen after showing completions below the shell prompt.

- A new remote control command :ref:`at-env` to change the default
  environment passed to newly created windows (:iss:`3529`)

- Linux: Fix binary kitty builds not able to load fonts in WOFF2 format
  (:iss:`3506`)

- macOS: Prevent :kbd:`option` based shortcuts for being used for global menu
  actions (:iss:`3515`)

- Fix ``kitty @ close-tab`` not working with pipe based remote control
  (:iss:`3510`)

- Fix removal of inactive tab that is before the currently active tab causing
  the highlighted tab to be incorrect (:iss:`3516`)

- icat kitten: Respect EXIF orientation when displaying JPEG images
  (:iss:`3518`)

- GNOME: Fix maximize state not being remembered when focus changes and window
  decorations are hidden (:iss:`3507`)

- GNOME: Add a new :opt:`wayland_titlebar_color` option to control the color of the
  kitty window title bar

- Fix reading :option:`kitty --session` from ``STDIN`` not working when the
  :code:`kitty --detach` option is used (:iss:`3523`)

- Special case rendering of the few remaining Powerline box drawing chars
  (:iss:`3535`)

- Fix ``kitty @ set-colors`` not working for the :opt:`active_tab_foreground`.


0.20.1 [2021-04-19]
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

- icat: Fix some broken GIF images with no frame delays not being animated
  (:iss:`3498`)

- hints kitten: Fix sending hyperlinks to their default handler not working
  (:pull:`3500`)

- Wayland: Fix regression in previous release causing window decorations to
  be drawn even when compositor supports server side decorations (:iss:`3501`)


0.20.0 [2021-04-19]
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

- Support display of animated images ``kitty +kitten icat animation.gif``. See
  :ref:`animation_protocol` for details on animation support in the kitty
  graphics protocol.

- A new keyboard reporting protocol with various advanced features that can be
  used by full screen terminal programs and even games, see
  :doc:`keyboard-protocol` (:iss:`3248`)

- **Backward incompatibility**: Session files now use the full :doc:`launch <launch>`
  command with all its capabilities. However, the syntax of the command is
  slightly different from before. In particular watchers are now specified
  directly on launch and environment variables are set using ``--env``.

- Allow setting colors when creating windows using the :doc:`launch <launch>` command.

- A new option :opt:`tab_powerline_style` to control the appearance of the tab
  bar when using the powerline tab bar style.

- A new option :opt:`scrollback_fill_enlarged_window` to fill extra lines in
  the window when the window is expanded with lines from the scrollback
  (:pull:`3371`)

- diff kitten: Implement recursive diff over SSH (:iss:`3268`)

- ssh kitten: Allow using python instead of the shell on the server, useful if
  the shell used is a non-POSIX compliant one, such as fish (:iss:`3277`)

- Add support for the color settings stack that XTerm copied from us without
  acknowledgement and decided to use incompatible escape codes for.

- Add entries to the terminfo file for some user capabilities that are shared
  with XTerm (:pull:`3193`)

- The launch command now does more sophisticated resolving of executables to
  run. The system-wide PATH is used first, then system specific default paths,
  and finally the PATH inside the shell.

- Double clicking on empty tab bar area now opens a new tab (:iss:`3201`)

- kitty @ ls: Show only environment variables that are different for each
  window, by default.

- When passing a directory or a non-executable file as the program to run to
  kitty opens it with the shell or by parsing the shebang, instead of just failing.

- Linux: Fix rendering of emoji followed by the graphics variation selector not
  being colored with some fonts (:iss:`3211`)

- Unicode input: Fix using index in select by name mode not working for indices
  larger than 16. Also using an index does not filter the list of matches. (:pull:`3219`)

- Wayland: Add support for the text input protocol (:iss:`3410`)

- Wayland: Fix mouse handling when using client side decorations

- Wayland: Fix un-maximizing a window not restoring its size to what it was
  before being maximized

- GNOME/Wayland: Improve window decorations the titlebar now shows the window
  title. Allow running under Wayland on GNOME by default. (:iss:`3284`)

- Panel kitten: Allow setting WM_CLASS (:iss:`3233`)

- macOS: Add menu items to close the OS window and the current tab (:pull:`3240`, :iss:`3246`)

- macOS: Allow opening script and command files with kitty (:iss:`3366`)

- Also detect ``gemini://`` URLs when hovering with the mouse (:iss:`3370`)

- When using a non-US keyboard layout and pressing :kbd:`ctrl+key` when
  the key matches an English key, send that to the program running in the
  terminal automatically (:iss:`2000`)

- When matching shortcuts, also match on shifted keys, so a shortcut defined as
  :kbd:`ctrl+plus` will match a keyboard where you have to press
  :kbd:`shift+equal` to get the plus key (:iss:`2000`)

- Fix extra space at bottom of OS window when using the fat layout with the tab bar at the
  top (:iss:`3258`)

- Fix window icon not working on X11 with 64bits (:iss:`3260`)

- Fix OS window sizes under 100px resulting in scaled display (:iss:`3307`)

- Fix rendering of ligatures in the latest release of Cascadia code, which for
  some reason puts empty glyphs after the ligature glyph rather than before it
  (:iss:`3313`)

- Improve handling of infinite length ligatures in newer versions of FiraCode
  and CascadiaCode. Now such ligatures are detected based on glyph naming
  convention. This removes the gap in the ligatures at cell boundaries (:iss:`2695`)

- macOS: Disable the native operating system tabs as they are non-functional
  and can be confusing (:iss:`3325`)

- hints kitten: When using the linenumber action with a background action,
  preserve the working directory (:iss:`3352`)

- Graphics protocol: Fix suppression of responses not working for chunked
  transmission (:iss:`3375`)

- Fix inactive tab closing causing active tab to change (:iss:`3398`)

- Fix a crash on systems using musl as libc (:iss:`3395`)

- Improve rendering of rounded corners by using a rectircle equation rather
  than a cubic bezier (:iss:`3409`)

- Graphics protocol: Add a control to allow clients to specify that the cursor
  should not move when displaying an image (:iss:`3411`)

- Fix marking of text not working on lines that contain zero cells
  (:iss:`3403`)

- Fix the selection getting changed if the screen contents scroll while
  the selection is in progress (:iss:`3431`)

- X11: Fix :opt:`resize_in_steps` being applied even when window is maximized
  (:iss:`3473`)


0.19.3 [2020-12-19]
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

- Happy holidays to all kitty users!

- A new :doc:`broadcast <kittens/broadcast>` kitten to type in all kitty windows
  simultaneously (:iss:`1569`)

- Add a new mappable `select_tab` action to choose a tab to switch to even
  when the tab bar is hidden (:iss:`3115`)

- Allow specifying text formatting in :opt:`tab_title_template` (:iss:`3146`)

- Linux: Read :opt:`font_features` from the FontConfig database as well, so
  that they can be configured in a single, central location (:pull:`3174`)

- Graphics protocol: Add support for giving individual image placements their
  own ids and for asking the terminal emulator to assign ids for images. Also
  allow suppressing responses from the terminal to commands.
  These are backwards compatible protocol extensions. (:iss:`3133`,
  :iss:`3163`)

- Distribute extra pixels among all eight-blocks rather than adding them
  all to the last block (:iss:`3097`)

- Fix drawing of a few sextant characters incorrect (:pull:`3105`)

- macOS: Fix minimize not working for chromeless windows (:iss:`3112`)

- Preserve lines in the scrollback if a scrolling region is defined that
  is contiguous with the top of the screen (:iss:`3113`)

- Wayland: Fix key repeat being stopped by the release of an unrelated key
  (:iss:`2191`)

- Add an option, :opt:`detect_urls` to control whether kitty will detect URLs
  when the mouse moves over them (:pull:`3118`)

- Graphics protocol: Dont return filename in the error message when opening file
  fails, since filenames can contain control characters (:iss:`3128`)

- macOS: Partial fix for traditional fullscreen not working on Big Sur
  (:iss:`3100`)

- Fix one ANSI formatting escape code not being removed from the pager history
  buffer when piping it as plain text (:iss:`3132`)

- Match the save/restore cursor behavior of other terminals, for the sake of
  interoperability. This means that doing a DECRC without a prior DECSC is now
  undefined (:iss:`1264`)

- Fix mapping ``remote_control send-text`` not working (:iss:`3147`)

- Add a ``right`` option for :opt:`tab_switch_strategy` (:pull:`3155`)

- Fix a regression in 0.19.0 that caused a rare crash when using the optional
  :opt:`scrollback_pager_history_size` (:iss:`3049`)

- Full screen kittens: Fix incorrect cursor position after kitten quits
  (:iss:`3176`)


0.19.2 [2020-11-13]
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

- A new :doc:`kittens/query_terminal` kitten to easily query the running kitty
  via escape codes to detect its version, and the values of
  configuration options that enable or disable terminal features.

- Options to control mouse pointer shape, :opt:`default_pointer_shape`, and
  :opt:`pointer_shape_when_dragging` (:pull:`3041`)

- Font independent rendering for braille characters, which ensures they are properly
  aligned at all font sizes.

- Fix a regression in 0.19.0 that caused borders not to be drawn when setting
  :opt:`window_margin_width` and keeping :opt:`draw_minimal_borders` on
  (:iss:`3017`)

- Fix a regression in 0.19.0 that broke rendering of one-eight bar unicode
  characters at very small font sizes (:iss:`3025`)

- Wayland: Fix a crash under GNOME when using multiple OS windows
  (:pull:`3066`)

- Fix selections created by dragging upwards not being auto-cleared when
  screen contents change (:pull:`3028`)

- macOS: Fix kitty not being added to PATH automatically when using pre-built
  binaries (:iss:`3063`)

- Allow adding MIME definitions to kitty by placing a ``mime.types`` file in
  the kitty config directory (:iss:`3056`)

- Dont ignore :option:`--title` when using a session file that defines no
  windows (:iss:`3055`)

- Fix the send_text action not working in URL handlers (:iss:`3081`)

- Fix last character of URL not being detected if it is the only character on a
  new line (:iss:`3088`)

- Don't restrict the ICH,DCH,REP control codes to only the current scroll region  (:iss:`3090`, :iss:`3096`)


0.19.1 [2020-10-06]
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

- hints kitten: Add an ``ip`` type for easy selection of IP addresses
  (:pull:`3009`)

- Fix a regression that caused a segfault when using
  :opt:`scrollback_pager_history_size` and it needs to be expanded (:iss:`3011`)

- Fix update available notifications repeating (:pull:`3006`)


0.19.0 [2020-10-04]
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

- Add support for `hyperlinks from terminal programs
  <https://gist.github.com/egmontkob/eb114294efbcd5adb1944c9f3cb5feda>`_.
  Controlled via :opt:`allow_hyperlinks` (:iss:`68`)

- Add support for easily editing or downloading files over SSH sessions
  without the need for any special software, see :doc:`kittens/remote_file`

- A new :doc:`kittens/hyperlinked_grep` kitten to easily search files and open
  the results at the matched line by clicking on them.

- Allow customizing the :doc:`actions kitty takes <open_actions>` when clicking on URLs

- Improve rendering of borders when using minimal borders. Use less space and
  do not display a box around active windows

- Add a new extensible escape code to allow terminal programs to trigger
  desktop notifications. See :ref:`desktop_notifications` (:iss:`1474`)

- Implement special rendering for various characters from the set of "Symbols
  for Legacy Computing" from the Unicode 13 standard

- Unicode input kitten: Allow choosing symbols from the NERD font as well.
  These are mostly Private Use symbols not in any standard, however are common. (:iss:`2972`)

- Allow specifying border sizes in either pts or pixels. Change the default to
  0.5pt borders as this works best with the new minimal border style

- Add support for displaying correct colors with non-sRGB PNG files (Adds a
  dependency on liblcms2)

- hints kitten: Add a new :option:`kitty +kitten hints --type` of ``hyperlink`` useful
  for activating hyperlinks using just the keyboard

- Allow tracking focus change events in watchers (:iss:`2918`)

- Allow specifying watchers in session files and via a command line argument
  (:iss:`2933`)

- Add a setting :opt:`tab_activity_symbol` to show a symbol in the tab title
  if one of the windows has some activity after it was last focused
  (:iss:`2515`)

- macOS: Switch to using the User Notifications framework for notifications.
  The current notifications framework has been deprecated in Big Sur. The new
  framework only allows notifications from signed and notarized applications,
  so people using kitty from homebrew/source are out of luck. Complain to
  Apple.

- When in the main screen and a program grabs the mouse, do not use the scroll
  wheel events to scroll the scrollback buffer, instead send them to the
  program (:iss:`2939`)

- Fix unfocused windows in which a bell occurs not changing their border color
  to red until a relayout

- Linux: Fix automatic detection of bold/italic faces for fonts such as IBM
  Plex Mono that have the regular face with a full name that is the same as the
  family name (:iss:`2951`)

- Fix a regression that broke :opt:`kitten_alias` (:iss:`2952`)

- Fix a regression that broke the ``move_window_to_top`` action (:pull:`2953`)

- Fix a memory leak when changing font sizes

- Fix some lines in the scrollback buffer not being properly rendered after a
  window resize/font size change (:iss:`2619`)


0.18.3 [2020-08-11]
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

- hints kitten: Allow customizing hint colors (:pull:`2894`)

- Wayland: Fix a typo in the previous release that broke reading mouse cursor size (:iss:`2895`)

- Fix a regression in the previous release that could cause an exception during
  startup in rare circumstances (:iss:`2896`)

- Fix image leaving behind a black rectangle when switch away and back to
  alternate screen (:iss:`2901`)

- Fix one pixel misalignment of rounded corners when either the cell
  dimensions or the thickness of the line is an odd number of pixels
  (:iss:`2907`)

- Fix a regression that broke specifying OS window size in the session file
  (:iss:`2908`)


0.18.2 [2020-07-28]
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

- X11: Improve handling of multiple keyboards. Now pressing a modifier key in
  one keyboard and a normal key in another works (:iss:`2362`). Don't rebuild
  keymaps on new keyboard events that only change geometry (:iss:`2787`).
  Better handling of multiple keyboards with incompatible layouts (:iss:`2726`)

- Improve anti-aliasing of triangular box drawing characters, noticeable on
  low-resolution screens (:iss:`2844`)

- Fix ``kitty @ send-text`` not working reliably when using a socket for remote
  control (:iss:`2852`)

- Implement support for box drawing rounded-corners characters (:iss:`2240`)

- Allow setting the class for new OS windows in a session file

- When a character from the Unicode Dingbat block is followed by a space, use
  the extra space to render a larger version of the character (:iss:`2850`)

- macOS: Fix the LC_CTYPE env var being set to UTF-8 on systems in which the
  language and country code do not form a valid locale (:iss:`1233`)

- macOS: Fix :kbd:`cmd+plus` not changing font size (:iss:`2839`)

- Make neighboring window selection in grid and splits layouts more intelligent
  (:pull:`2840`)

- Allow passing the current selection to kittens (:iss:`2796`)

- Fix pre-edit text not always being cleared with ibus input (:iss:`2862`)

- Allow setting the :opt:`background_opacity` of new OS windows created via
  :option:`kitty --single-instance` using the :option:`kitty --override` command line
  argument (:iss:`2806`)

- Fix the CSI J (Erase in display ED) escape code not removing line continued
  markers (:iss:`2809`)

- hints kitten: In linenumber mode expand paths that starts with ~
  (:iss:`2822`)

- Fix ``launch --location=last`` not working (:iss:`2841`)

- Fix incorrect centering when a PUA or symbol glyph is followed by more than one space

- Have the :opt:`confirm_os_window_close` option also apply when closing tabs
  with multiple windows (:iss:`2857`)

- Add support for legacy DECSET codes 47, 1047 and 1048 (:pull:`2871`)

- macOS: no longer render emoji 20% below the baseline. This caused some emoji
  to be cut-off and also look misaligned with very high cells (:iss:`2873`)

- macOS: Make the window id of OS windows available in the ``WINDOWID``
  environment variable (:pull:`2877`)

- Wayland: Fix a regression in 0.18.0 that could cause crashes related to mouse
  cursors in some rare circumstances (:iss:`2810`)

- Fix change in window size that does not change number of cells not being
  reported to the kernel (:iss:`2880`)


0.18.1 [2020-06-23]
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

- macOS: Fix for diff kitten not working with python 3.8 (:iss:`2780`)


0.18.0 [2020-06-20]
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

- Allow multiple overlay windows per normal window

- Add an option :opt:`confirm_os_window_close` to ask for confirmation
  when closing an OS window with multiple kitty windows.

- Tall and Fat layouts: Add a ``mirrored`` option to put the full size window
  on the opposite edge of the screen (:iss:`2654`)

- Tall and Fat layouts: Add mappable actions to increase or decrease the number
  of full size windows (:iss:`2688`)

- Allow sending arbitrary signals to the current foreground process in a window
  using either a mapping in kitty.conf or via remote control (:iss:`2778`)

- Allow sending the back and forward mouse buttons to terminal applications
  (:pull:`2742`)

- **Backwards incompatibility**: The numbers used to encode mouse buttons
  for the ``send_mouse_event`` function that can be used in kittens have
  been changed (see :ref:`send_mouse_event`).

- Add a new mappable ``quit`` action to quit kitty completely.

- Fix marks using different colors with regexes using only a single color
  (:pull:`2663`)

- Linux: Workaround for broken Nvidia drivers for old cards (:iss:`456`)

- Wayland: Fix kitty being killed on some Wayland compositors if a hidden window
  has a lot of output (:iss:`2329`)

- BSD: Fix controlling terminal not being established (:pull:`2686`)

- Add support for the CSI REP escape code (:pull:`2702`)

- Wayland: Fix mouse cursor rendering on HiDPI screens (:pull:`2709`)

- X11: Recompile keymaps on XkbNewKeyboardNotify events (:iss:`2726`)

- X11: Reduce startup time by ~25% by only querying GLX for framebuffer
  configurations once (:iss:`2754`)

- macOS: Notarize the kitty application bundle (:iss:`2040`)

- Fix the kitty shell launched via a mapping needlessly requiring
  :opt:`allow_remote_control` to be turned on.


0.17.4 [2020-05-09]
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

- Allow showing the name of the current layout and the number of windows
  in tab titles (:iss:`2634`)

- macOS: Fix a regression in the previous release that caused ligatures to be
  not be centered horizontally (:iss:`2591`)

- By default, double clicking no longer considers the : as part of words, see
  :opt:`select_by_word_characters` (:iss:`2602`)

- Fix a regression that caused clicking in the padding/margins of windows in
  the stack layout to switch the window to the first window (:iss:`2604`)

- macOS: Fix a regression that broke drag and drop (:iss:`2605`)

- Report modifier key state when sending wheel events to the terminal program

- Fix kitty @ send-text not working with text larger than 1024 bytes when using
  :option:`kitty --listen-on` (:iss:`2607`)

- Wayland: Fix OS window title not updating for hidden windows (:iss:`2629`)

- Fix :opt:`background_tint` making the window semi-transparent (:iss:`2618`)


0.17.3 [2020-04-23]
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

- Allow individually setting margins and padding for each edge (left, right,
  top, bottom). Margins can also be controlled per window via remote control
  (:iss:`2546`)

- Fix reverse video not being rendered correctly when using transparency or a
  background image (:iss:`2419`)

- Allow mapping arbitrary remote control commands to key presses in
  :file:`kitty.conf`

- X11: Fix crash when doing drag and drop from some applications (:iss:`2505`)

- Fix :option:`launch --stdin-add-formatting` not working (:iss:`2512`)

- Update to Unicode 13.0 (:iss:`2513`)

- Render country flags designated by a pair of unicode codepoints
  in two cells instead of four.

- diff kitten: New option to control the background color for filler lines in
  the margin (:iss:`2518`)

- Fix specifying options for layouts in the startup session file not working
  (:iss:`2520`)

- macOS: Fix incorrect horizontal positioning of some full-width East Asian characters
  (:iss:`1457`)

- macOS: Render multi-cell PUA characters centered, matching behavior on other
  platforms

- Linux: Ignore keys if they are designated as layout/group/mode switch keys
  (:iss:`2519`)

- Marks: Fix marks not handling wide characters and tab characters correctly
  (:iss:`2534`)

- Add a new :opt:`listen_on` option in kitty.conf to set :option:`kitty --listen-on`
  globally. Also allow using environment variables in this option (:iss:`2569`).

- Allow sending mouse events in kittens (:pull:`2538`)

- icat kitten: Fix display of 16-bit depth images (:iss:`2542`)

- Add ncurses specific terminfo definitions for strikethrough (:pull:`2567`)

- Fix a regression in 0.17 that broke displaying graphics over SSH
  (:iss:`2568`)

- Fix :option:`--title` not being applied at window creation time (:iss:`2570`)


0.17.2 [2020-03-29]
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

- Add a :option:`launch --watcher` option that allows defining callbacks
  that are called for various events in the window's life-cycle (:iss:`2440`)

- Fix a regression in 0.17 that broke drawing of borders with non-minimal
  borders (:iss:`2474`)

- Hints kitten: Allow copying to primary selection as well as clipboard
  (:pull:`2487`)

- Add a new mappable action ``close_other_windows_in_tab`` to close all but the
  active window (:iss:`2484`)

- Hints kitten: Adjust the default regex used to detect line numbers to handle
  line+column numbers (:iss:`2268`)

- Fix blank space at the start of tab bar in the powerline style when first tab is
  inactive (:iss:`2478`)

- Fix regression causing incorrect rendering of separators in tab bar when
  defining a tab bar background color (:pull:`2480`)

- Fix a regression in 0.17 that broke the kitty @ launch remote command and
  also broke the --tab-title option when creating a new tab. (:iss:`2488`)

- Linux: Fix selection of fonts with multiple width variants not preferring
  the normal width faces (:iss:`2491`)


0.17.1 [2020-03-24]
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

- Fix :opt:`cursor_underline_thickness` not working (:iss:`2465`)

- Fix a regression in 0.17 that caused tab bar background to be rendered after
  the last tab as well (:iss:`2464`)

- macOS: Fix a regression in 0.17 that caused incorrect variants to be
  automatically selected for some fonts (:iss:`2462`)

- Fix a regression in 0.17 that caused kitty @ set-colors to require setting
  cursor_text_color (:iss:`2470`)


0.17.0 [2020-03-24]
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

- :ref:`splits_layout` to arrange windows in arbitrary splits
  (:iss:`2308`)

- Add support for specifying a background image, see :opt:`background_image`
  (:iss:`163` and :pull:`2326`; thanks to Fredrick Brennan.)

- A new :opt:`background_tint` option to darken the background under the text
  area when using background images and/or transparent windows.

- Allow selection of single cells with the mouse. Also improve mouse selection
  to follow semantics common to most programs (:iss:`945`)

- New options :opt:`cursor_beam_thickness` and :opt:`cursor_underline_thickness` to control the thickness of the
  beam and underline cursors (:iss:`2337` and :pull:`2342`)

- When the application running in the terminal grabs the mouse, pass middle
  clicks to the application unless `terminal_select_modifiers` are
  pressed (:iss:`2368`)

- A new ``copy_and_clear_or_interrupt`` function (:iss:`2403`)

- X11: Fix arrow mouse cursor using right pointing instead of the default left
  pointing arrow (:iss:`2341`)

- Allow passing the currently active kitty window id in the launch command
  (:iss:`2391`)

- unicode input kitten: Allow pressing :kbd:`ctrl+tab` to change the input mode
  (:iss:`2343`)

- Fix a bug that prevented using custom functions with the new marks feature
  (:iss:`2344`)

- Make the set of URL prefixes that are recognized while hovering with the
  mouse configurable (:iss:`2416`)

- Fix border/margin/padding sizes not being recalculated on DPI change
  (:iss:`2346`)

- diff kitten: Fix directory diffing with removed binary files failing
  (:iss:`2378`)

- macOS: Fix menubar title not updating on OS Window focus change (:iss:`2350`)

- Fix rendering of combining characters with fonts that have glyphs for
  precomposed characters but not decomposed versions (:iss:`2365`)

- Fix incorrect rendering of selection when using rectangular select and
  scrolling (:iss:`2351`)

- Allow setting WM_CLASS and WM_NAME when creating new OS windows with the
  launch command (:option:`launch --os-window-class`)

- macOS: When switching input method while a pending multi-key input is in
  progress, clear the pending input (:iss:`2358`)

- Fix a regression in the previous release that broke switching to neighboring windows
  in the Grid layout when there are less than four windows (:iss:`2377`)

- Fix colors in scrollback pager off if the window has redefined terminal
  colors using escape codes (:iss:`2381`)

- Fix selection not updating properly while scrolling (:iss:`2442`)

- Allow extending selections by dragging with right button pressed
  (:iss:`2445`)

- Workaround for bug in less that causes colors to reset at wrapped lines
  (:iss:`2381`)

- X11/Wayland: Allow drag and drop of text/plain in addition to text/uri-list
  (:iss:`2441`)

- Dont strip :code:`&` and :code:`-` from the end of URLs (:iss:`2436`)

- Fix ``@selection`` placeholder not working with launch command (:iss:`2417`)

- Drop support for python 3.5

- Wayland: Fix a crash when drag and dropping into kitty (:iss:`2432`)

- diff kitten: Fix images lingering as blank rectangles after the kitten quits
  (:iss:`2449`)

- diff kitten: Fix images losing position when scrolling using mouse
  wheel/touchpad


0.16.0 [2020-01-28]
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

- A new :doc:`marks` feature that allows highlighting and scrolling to arbitrary
  text in the terminal window.

- hints kitten: Allow pressing :sc:`goto_file_line` to quickly open
  the selected file at the selected line in vim or a configurable editor (:iss:`2268`)

- Allow having more than one full height window in the :code:`tall` layout
  (:iss:`2276`)

- Allow choosing OpenType features for individual fonts via the
  :opt:`font_features` option. (:pull:`2248`)

- Wayland: Fix a freeze in rare circumstances when having multiple OS Windows
  (:iss:`2307` and :iss:`1722`)

- Wayland: Fix window titles being set to very long strings on the order of 8KB
  causing a crash (:iss:`1526`)

- Add an option :opt:`force_ltr` to turn off the display of text in RTL scripts
  in right-to-left order (:pull:`2293`)

- Allow opening new tabs/windows before the current tab/window as well as after
  it with the :option:`launch --location` option.

- Add a :opt:`resize_in_steps` option that can be used to resize the OS window
  in steps as large as character cells (:pull:`2131`)

- When triple-click+dragging to select multiple lines, extend the selection
  of the first line to match the rest on the left (:pull:`2284`)

- macOS: Add a :code:`titlebar-only` setting to
  :opt:`hide_window_decorations` to only hide the title bar (:pull:`2286`)

- Fix a segfault when using ``--debug-config`` with maps (:iss:`2270`)

- ``goto_tab`` now maps numbers larger than the last tab to the last tab
  (:iss:`2291`)

- Fix URL detection not working for urls of the form scheme:///url
  (:iss:`2292`)

- When windows are semi-transparent and all contain graphics, correctly render
  them. (:iss:`2310`)


0.15.1 [2019-12-21]
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

- Fix a crash/incorrect rendering when detaching a window in some circumstances
  (:iss:`2173`)

- hints kitten: Add an option :option:`kitty +kitten hints --ascending` to
  control if the hints numbers increase or decrease from top to bottom

- Fix :opt:`background_opacity` incorrectly applying to selected text and
  reverse video text (:iss:`2177`)

- Add a new option :opt:`tab_bar_background` to specify a different color
  for the tab bar (:iss:`2198`)

- Add a new option :opt:`active_tab_title_template` to specify a different
  template for active tab titles (:iss:`2198`)

- Fix lines at the edge of the window at certain windows sizes when drawing
  images on a transparent window (:iss:`2079`)

- Fix window not being rendered for the first time until some input has been
  received from child process (:iss:`2216`)


0.15.0 [2019-11-27]
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

- Add a new action :ref:`detach_window <detach_window>` that can be used to move the current
  window into a different tab (:iss:`1310`)

- Add a new action :doc:`launch <launch>` that unifies launching of processes
  in new kitty windows/tabs.

- Add a new style ``powerline`` for tab bar rendering, see :opt:`tab_bar_style` (:pull:`2021`)

- Allow changing colors by mapping a keyboard shortcut to read a kitty config
  file with color definitions. See the :doc:`FAQ <faq>` for details
  (:iss:`2083`)

- hints kitten: Allow completely customizing the matching and actions performed
  by the kitten using your own script (:iss:`2124`)

- Wayland: Fix key repeat not being stopped when focus leaves window. This is
  expected behavior on Wayland, apparently (:iss:`2014`)

- When drawing unicode symbols that are followed by spaces, use multiple cells
  to avoid resized or cut-off glyphs (:iss:`1452`)

- diff kitten: Allow diffing remote files easily via ssh (:iss:`727`)

- unicode input kitten: Add an option :option:`kitty +kitten unicode_input
  --emoji-variation` to control the presentation variant of selected emojis
  (:iss:`2139`)

- Add specialised rendering for a few more box powerline and unicode symbols
  (:pull:`2074` and :pull:`2021`)

- Add a new socket only mode for :opt:`allow_remote_control`. This makes
  it possible for programs running on the local machine to control kitty
  but not programs running over ssh.

- hints kitten: Allow using named groups in the regular expression. The named
  groups are passed to the invoked program for further processing.

- Fix a regression in 0.14.5 that caused rendering of private use glyphs
  with and without spaces to be identical (:iss:`2117`)

- Wayland: Fix incorrect scale used when first creating an OS window
  (:iss:`2133`)

- macOS: Disable mouse hiding by default as getting it to work robustly
  on Cocoa is too much effort (:iss:`2158`)


0.14.6 [2019-09-25]
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

- macOS: Fix a regression in the previous release that caused a crash when
  pressing a unprintable key, such as the POWER key (:iss:`1997`)

- Fix a regression in the previous release that caused kitty to not always
  respond to DPI changes (:pull:`1999`)


0.14.5 [2019-09-23]
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

- Implement a hack to (mostly) preserve tabs when cat-ting a file with them and then
  copying the text or passing screen contents to another program (:iss:`1829`)

- When all visible windows have the same background color, use that as the
  color for the global padding, instead of the configured background color
  (:iss:`1957`)

- When resetting the terminal, also reset parser state, this allows easy
  recovery from incomplete escape codes (:iss:`1961`)

- Allow mapping keys commonly found on European keyboards (:pull:`1928`)

- Fix incorrect rendering of some symbols when followed by a space while using
  the PowerLine font which does not have a space glyph (:iss:`1225`)

- Linux: Allow using fonts with spacing=90 in addition to fonts with
  spacing=100 (:iss:`1968`)

- Use selection foreground color for underlines as well (:iss:`1982`)


0.14.4 [2019-08-31]
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

- hints kitten: Add a :option:`kitty +kitten hints --alphabet` option to
  control what alphabets are used for hints (:iss:`1879`)

- hints kitten: Allow specifying :option:`kitty +kitten hints --program`
  multiple times to run multiple programs  (:iss:`1879`)

- Add a :opt:`kitten_alias` option that can be used to alias kitten invocation
  for brevity and to change kitten option defaults globally (:iss:`1879`)

- macOS: Add an option :opt:`macos_show_window_title_in` to control
  showing the window title in the menubar/titlebar (:pull:`1837`)

- macOS: Allow drag and drop of text from other applications into kitty
  (:pull:`1921`)

- When running kittens, use the colorscheme of the current window
  rather than the configured colorscheme (:iss:`1906`)

- Don't fail to start if running the shell to read the EDITOR env var fails
  (:iss:`1869`)

- Disable the ``liga`` and ``dlig`` OpenType features for broken fonts
  such as Nimbus Mono.

- Fix a regression that broke setting background_opacity via remote control
  (:iss:`1895`)

- Fix piping PNG images into the icat kitten not working (:iss:`1920`)

- When the OS returns a fallback font that does not actually contain glyphs
  for the text, do not exhaust the list of fallback fonts (:iss:`1918`)

- Fix formatting attributes not reset across line boundaries when passing
  buffer as ANSI (:iss:`1924`)


0.14.3 [2019-07-29]
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

- Remote control: Add a command `kitty @ scroll-window` to scroll windows

- Allow passing a ``!neighbor`` argument to the new_window mapping to open a
  new window next to the active window (:iss:`1746`)

- Document the kitty remote control protocol (:iss:`1646`)

- Add a new option :opt:`pointer_shape_when_grabbed` that allows you to control
  the mouse pointer shape when the terminal programs grabs the pointer
  (:iss:`1808`)

- Add an option `terminal_select_modifiers` to control which modifiers
  are used to override mouse selection even when a terminal application has
  grabbed the mouse (:iss:`1774`)

- When piping data to a child in the pipe command do it in a thread so as not
  to block the UI (:iss:`1708`)

- unicode_input kitten: Fix a regression that broke using indices to select
  recently used symbols.

- Fix a regression that caused closing an overlay window to focus
  the previously focused window rather than the underlying window (:iss:`1720`)

- macOS: Reduce energy consumption when idle by shutting down Apple's display
  link thread after 30 second of inactivity (:iss:`1763`)

- Linux: Fix incorrect scaling for fallback fonts when the font has an
  underscore that renders out of bounds (:iss:`1713`)

- macOS: Fix finding fallback font for private use unicode symbols not working
  reliably (:iss:`1650`)

- Fix an out of bounds read causing a crash when selecting text with the mouse
  in the alternate screen mode (:iss:`1578`)

- Linux: Use the system "bell" sound for the terminal bell. Adds libcanberra
  as a new dependency to play the system sound.

- macOS: Fix a rare deadlock causing kitty to hang (:iss:`1779`)

- Linux: Fix a regression in 0.14.0 that caused the event loop to tick
  continuously, wasting CPU even when idle (:iss:`1782`)

- ssh kitten: Make argument parsing more like ssh (:iss:`1787`)

- When using :opt:`strip_trailing_spaces` do not remove empty lines
  (:iss:`1802`)

- Fix a crash when displaying very large number of images (:iss:`1825`)


0.14.2 [2019-06-09]
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

- Add an option :opt:`placement_strategy` to control how the cell area is
  aligned inside the window when the window size is not an exact multiple
  of the cell size (:pull:`1670`)

- hints kitten: Add a :option:`kitty +kitten hints --multiple-joiner` option to
  control how multiple selections are serialized when copying to clipboard
  or inserting into the terminal. You can have them on separate lines,
  separated by arbitrary characters, or even serialized as JSON (:iss:`1665`)

- macOS: Fix a regression in the previous release that broke using
  :kbd:`ctrl+shift+tab` (:iss:`1671`)

- panel kitten: Fix the contents of the panel kitten not being positioned
  correctly on the vertical axis

- icat kitten: Fix a regression that broke passing directories to icat
  (:iss:`1683`)

- clipboard kitten: Add a :option:`kitty +kitten clipboard --wait-for-completion`
  option to have the kitten wait till copying to clipboard is complete
  (:iss:`1693`)

- Allow using the :doc:`pipe <pipe>` command to send screen and scrollback
  contents directly to the clipboard (:iss:`1693`)

- Linux: Disable the Wayland backend on GNOME by default as GNOME has no
  support for server side decorations. Can be controlled by
  :opt:`linux_display_server`.

- Add an option to control the default :opt:`update_check_interval` when
  building kitty packages

- Wayland: Fix resizing the window on a compositor that does not provide
  server side window decorations, such a GNOME or Weston not working
  correctly (:iss:`1659`)

- Wayland: Fix crash when enabling disabling monitors on sway (:iss:`1696`)


0.14.1 [2019-05-29]
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

- Add an option :opt:`command_on_bell` to run an arbitrary command when
  a bell occurs (:iss:`1660`)

- Add a shortcut to toggle maximized window state :sc:`toggle_maximized`

- Add support for the underscore key found in some keyboard layouts
  (:iss:`1639`)

- Fix a missing newline when using the pipe command between the
  scrollback and screen contents (:iss:`1642`)

- Fix colors not being preserved when using the pipe command with
  the pager history buffer (:pull:`1657`)

- macOS: Fix a regression that could cause rendering of a kitty window
  to occasionally freeze in certain situations, such as moving it between
  monitors or transitioning from/to fullscreen (:iss:`1641`)

- macOS: Fix a regression that caused :kbd:`cmd+v` to double up in the dvorak
  keyboard layout (:iss:`1652`)

- When resizing and only a single window is present in the current layout,
  use that window's background color to fill in the blank areas.

- Linux: Automatically increase cell height if the font being used is broken
  and draws the underscore outside the bounding box (:iss:`690`)

- Wayland: Fix maximizing the window on a compositor that does not provide
  server side window decorations, such a GNOME or Weston not working
  (:iss:`1662`)


0.14.0 [2019-05-24]
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

- macOS: The default behavior of the Option key has changed. It now generates
  unicode characters rather than acting as the :kbd:`Alt` modifier. See
  :opt:`macos_option_as_alt`.

- Support for an arbitrary number of internal clipboard buffers to copy/paste
  from, see (:ref:`cpbuf`)

- Allow using the new private internal clipboard buffers with the
  :opt:`copy_on_select` option (:iss:`1390`)

- macOS: Allow opening new kitty tabs/top-level windows from Finder
  (:pull:`1350`)

- Add an option :opt:`disable_ligatures` to disable
  multi-character ligatures under the cursor to make editing easier
  or disable them completely (:iss:`461`)

- Allow creating new OS windows in session files (:iss:`1514`)

- Allow setting OS window size in session files

- Add an option :opt:`tab_switch_strategy` to control which
  tab becomes active when the current tab is closed (:pull:`1524`)

- Allow specifying a value of ``none`` for the :opt:`selection_foreground`
  which will cause kitty to not change text color in selections (:iss:`1358`)

- Make live resizing of OS windows smoother and add an option
  ``resize_draw_strategy`` to control what is drawn while a
  resize is in progress.

- macOS: Improve handling of IME extended input. Compose characters
  are now highlighted and the IME panel moves along with the text
  (:pull:`1586`). Also fixes handling of delete key in Chinese IME
  (:iss:`1461`)

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

- macOS: Add an option `macos_show_window_title_in_menubar` to not
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

- Unicode input kitten: Allow using the arrow keys in code mode to go to next
  and previous unicode symbol.

- macOS: Fix specifying initial window size in cells not working correctly on
  Retina screens (:iss:`1444`)

- Fix a regression in version 0.13.0 that caused background colors of space
  characters after private use unicode characters to not be respected
  (:iss:`1455`)

- Only update the selected text to clipboard when the selection is finished,
  not continuously as it is updated. (:iss:`1460`)

- Allow setting :opt:`active_border_color` to ``none`` to not draw a border
  around the active window (:iss:`805`)

- Use negative values for :opt:`mouse_hide_wait` to hide the mouse cursor
  immediately when pressing a key (:iss:`1534`)

- When encountering errors in :file:`kitty.conf` report them to the user
  instead of failing to start.

- Allow the user to control the resize debounce time via
  :opt:`resize_debounce_time`.

- Remote control: Make the :ref:`at-set-font-size` command more capable.
  It can now increment font size and reset it. It also only acts on the
  active top-level window, by default (:iss:`1581`)

- When launching child processes set the :code:`PWD` environment variable
  (:iss:`1595`)

- X11: use the window manager's native full-screen implementation when
  making windows full-screen (:iss:`1605`)

- Mouse selection: When extending by word, fix extending selection to non-word
  characters not working well (:iss:`1616`)


0.13.3 [2019-01-19]
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

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
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

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
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

- Fix passing input via the pipe action to a program without a window not
  working.

- Linux: Fix a regression in the previous release that caused automatic
  selection of bold/italic fonts when using aliases such as "monospace" to not
  work (:iss:`1209`)

- Fix resizing window smaller and then restoring causing some wrapped lines to not
  be properly unwrapped (:iss:`1206`)


0.13.0 [2018-12-05]
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

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
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

- macOS: Fix kitty window not being rendered on macOS Mojave until the window is
  moved or resized at least once (:iss:`887`)

- Unicode input: Fix an error when searching for the string 'fir' (:iss:`1035`)


0.12.2 [2018-09-24]
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

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
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

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

- Wayland: Allow using the :code:`kitty --class` command line flag
  to set the app id (:iss:`862`)

- Add completion of the kitty command for the fish shell (:pull:`829`)

- Linux: Fix XCompose rules with no defined symbol not working (:iss:`880`)

- Linux: Fix crash with some Nvidia drivers when creating tabs in the first
  top level-window after creating a second top-level window. (:iss:`873`)

- macOS: Diff kitten: Fix syntax highlighting not working because of
  a bug in the 0.12.0 macOS package


0.12.0 [2018-09-01]
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

- Preserve the mouse selection even when the contents of the screen are
  scrolled or overwritten provided the new text does not intersect the
  selected lines.

- Linux: Implement support for Input Method Extensions (multilingual input
  using standard keyboards) via `IBus
  <https://github.com/ibus/ibus/wiki/ReadMe>`_ (:iss:`469`)

- Implement completion for the kitty command in bash and zsh. See
  :ref:`shell_integration`.

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
  :ref:`at-goto-layout` command (:iss:`845`)

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

- kitty @ new-window: Add a new option :option:`kitten @ new-window --window-type`
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
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

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
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

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

- Fix a regression in the previous release that broke using
  ``--debug-config`` with custom key mappings (:iss:`695`)


0.11.1 [2018-06-17]
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

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

- Fix :option:`kitten @ set-colors --all` not working when more than one window
  present (:iss:`632`)

- Fix a regression that broke the legacy increase/decrease_font_size actions

- Clear scrollback on reset (:iss:`631`)


0.11.0 [2018-06-12]
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

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
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

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
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

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
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

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
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

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
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

- Fix presence of XDG_CONFIG_DIRS and absence of XDG_CONFIG_HOME preventing
  kitty from starting

- Revert change in last release to cell width calculation. Instead just clip
  the right edges of characters that overflow the cell by at most two pixels


0.8.3 [2018-03-29]
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

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
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

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
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

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
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

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
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

- Add an option to adjust the width of character cells

- Fix selecting text with the mouse in the scrollback buffer selecting text
  from the line above the actually selected line

- Fix some italic fonts having the right edge of characters cut-off,
  unnecessarily


0.7.0 [2018-01-24]
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

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
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

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
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

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
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

- Add an option to control the thickness of lines in box drawing characters

- Increase max. allowed ligature length to nine characters

- Fix text not vertically centered when adjusting line height

- Fix unicode block characters not being rendered properly

- Fix shift+up/down not generating correct escape codes

- Image display: Fix displaying images taller than two screen heights not
  scrolling properly


0.5.0 [2017-11-19]
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

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
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

- Fix a regression in 0.4.0 that broke custom key mappings

- Fix a regression in 0.4.0 that broke support for non-QWERTY keyboard layouts

- Avoid using threads to reap zombie child processes. Also prevent kitty from
  hanging if the open program hangs when clicking on a URL.


0.4.0 [2017-10-22]
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

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
