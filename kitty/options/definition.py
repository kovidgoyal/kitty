#!/usr/bin/env python
# License: GPLv3 Copyright: 2021, Kovid Goyal <kovid at kovidgoyal.net>

# After editing this file run ./gen-config.py to apply the changes

import string
from kitty.conf.types import Action, Definition


definition = Definition(
    'kitty',
    Action('map', 'parse_map', {'keymap': 'KeyMap', 'sequence_map': 'SequenceMap', 'alias_map': 'AliasMap'},
           ['KeyDefinition', 'kitty.types.SingleKey']),
    Action('mouse_map', 'parse_mouse_map', {'mousemap': 'MouseMap'}, ['MouseMapping']),
    has_color_table=True,
)
definition.add_deprecation('deprecated_hide_window_decorations_aliases', 'x11_hide_window_decorations', 'macos_hide_titlebar')
definition.add_deprecation('deprecated_macos_show_window_title_in_menubar_alias', 'macos_show_window_title_in_menubar')
definition.add_deprecation('deprecated_send_text', 'send_text')

agr = definition.add_group
egr = definition.end_group
opt = definition.add_option
map = definition.add_map
mma = definition.add_mouse_map

# fonts {{{
agr('fonts', 'Fonts', '''
kitty has very powerful font management. You can configure individual font faces
and even specify special fonts for particular characters.
''')

opt('font_family', 'monospace',
    long_text='''
You can specify different fonts for the bold/italic/bold-italic variants.
To get a full list of supported fonts use the `kitty list-fonts` command.
By default they are derived automatically, by the OSes font system. When
bold_font or bold_italic_font is set to :code:`auto` on macOS, the priority of
bold fonts is semi-bold, bold, heavy. Setting them manually is useful for font
families that have many weight variants like Book, Medium, Thick, etc.
For example::

    font_family      Operator Mono Book
    bold_font        Operator Mono Medium
    italic_font      Operator Mono Book Italic
    bold_italic_font Operator Mono Medium Italic
'''
    )

opt('bold_font', 'auto',
    )

opt('italic_font', 'auto',
    )

opt('bold_italic_font', 'auto',
    )

opt('font_size', '11.0',
    option_type='to_font_size', ctype='double',
    long_text='Font size (in pts)'
    )

opt('force_ltr', 'no',
    option_type='to_bool', ctype='bool',
    long_text='''
kitty does not support BIDI (bidirectional text), however, for RTL scripts,
words are automatically displayed in RTL. That is to say, in an RTL script, the
words "HELLO WORLD" display in kitty as "WORLD HELLO", and if you try to select
a substring of an RTL-shaped string, you will get the character that would be
there had the the string been LTR. For example, assuming the Hebrew word
ירושלים, selecting the character that on the screen appears to be ם actually
writes into the selection buffer the character י.  kitty's default behavior is
useful in conjunction with a filter to reverse the word order, however, if you
wish to manipulate RTL glyphs, it can be very challenging to work with, so this
option is provided to turn it off. Furthermore, this option can be used with the
command line program :link:`GNU FriBidi
<https://github.com/fribidi/fribidi#executable>` to get BIDI support, because it
will force kitty to always treat the text as LTR, which FriBidi expects for
terminals.
'''
    )

opt('adjust_line_height', '0',
    option_type='adjust_line_height', ctype='!adjust_line_height',
    long_text='''
Change the size of each character cell kitty renders. You can use either
numbers, which are interpreted as pixels or percentages (number followed by %),
which are interpreted as percentages of the unmodified values. You can use
negative pixels or percentages less than 100% to reduce sizes (but this might
cause rendering artifacts).
'''
    )

opt('adjust_column_width', '0',
    option_type='adjust_line_height', ctype='!adjust_column_width',
    )

opt('adjust_baseline', '0',
    option_type='adjust_baseline', ctype='!adjust_baseline',
    add_to_default=False,
    long_text='''
Adjust the vertical alignment of text (the height in the cell at which text is
positioned). You can use either numbers, which are interpreted as pixels or a
percentages (number followed by %), which are interpreted as the percentage of
the line height. A positive value moves the baseline up, and a negative value
moves them down. The underline and strikethrough positions are adjusted
accordingly.
'''
    )

opt('+symbol_map', 'U+E0A0-U+E0A3,U+E0C0-U+E0C7 PowerlineSymbols',
    option_type='symbol_map',
    add_to_default=False,
    long_text='''
Map the specified unicode codepoints to a particular font. Useful if you need
special rendering for some symbols, such as for Powerline. Avoids the need for
patched fonts. Each unicode code point is specified in the form :code:`U+<code point
in hexadecimal>`. You can specify multiple code points, separated by commas and
ranges separated by hyphens. :code:`symbol_map` itself can be specified multiple times.
Syntax is::

    symbol_map codepoints Font Family Name
'''
    )

opt('disable_ligatures', 'never',
    option_type='disable_ligatures', ctype='int',
    long_text='''
Choose how you want to handle multi-character ligatures. The default is to
always render them.  You can tell kitty to not render them when the cursor is
over them by using :code:`cursor` to make editing easier, or have kitty never
render them at all by using :code:`always`, if you don't like them. The ligature
strategy can be set per-window either using the kitty remote control facility
or by defining shortcuts for it in kitty.conf, for example::

    map alt+1 disable_ligatures_in active always
    map alt+2 disable_ligatures_in all never
    map alt+3 disable_ligatures_in tab cursor

Note that this refers to programming ligatures, typically implemented using the
:code:`calt` OpenType feature. For disabling general ligatures, use the
:opt:`font_features` setting.
'''
    )

opt('+font_features', 'none',
    option_type='font_features',
    add_to_default=False,
    long_text='''
Choose exactly which OpenType features to enable or disable. This is useful as
some fonts might have features worthwhile in a terminal. For example, Fira
Code Retina includes a discretionary feature, :code:`zero`, which in that font
changes the appearance of the zero (0), to make it more easily distinguishable
from Ø. Fira Code Retina also includes other discretionary features known as
Stylistic Sets which have the tags :code:`ss01` through :code:`ss20`.

For the exact syntax to use for individual features, see the
:link:`Harfbuzz documentation
<https://harfbuzz.github.io/harfbuzz-hb-common.html#hb-feature-from-string>`.

Note that this code is indexed by PostScript name, and not the font
family. This allows you to define very precise feature settings; e.g. you can
disable a feature in the italic font but not in the regular font.

On Linux, these are read from the FontConfig database first and then this,
setting is applied, so they can be configured in a single, central place.

To get the PostScript name for a font, use :code:`kitty + list-fonts --psnames`:

.. code-block:: sh

    $ kitty + list-fonts --psnames | grep Fira
    Fira Code
    Fira Code Bold (FiraCode-Bold)
    Fira Code Light (FiraCode-Light)
    Fira Code Medium (FiraCode-Medium)
    Fira Code Regular (FiraCode-Regular)
    Fira Code Retina (FiraCode-Retina)

The part in brackets is the PostScript name.

Enable alternate zero and oldstyle numerals::

    font_features FiraCode-Retina +zero +onum

Enable only alternate zero::

    font_features FiraCode-Retina +zero

Disable the normal ligatures, but keep the :code:`calt` feature which (in this
font) breaks up monotony::

    font_features TT2020StyleB-Regular -liga +calt

In conjunction with :opt:`force_ltr`, you may want to disable Arabic shaping
entirely, and only look at their isolated forms if they show up in a document.
You can do this with e.g.::

    font_features UnifontMedium +isol -medi -fina -init
'''
    )

opt('box_drawing_scale', '0.001, 1, 1.5, 2',
    option_type='box_drawing_scale',
    long_text='''
Change the sizes of the lines used for the box drawing unicode characters These
values are in pts. They will be scaled by the monitor DPI to arrive at a pixel
value. There must be four values corresponding to thin, normal, thick, and very
thick lines.
'''
    )
egr()  # }}}

# cursor {{{
agr('cursor', 'Cursor customization')

opt('cursor', '#cccccc',
    option_type='to_color_or_none', long_text='''
Default cursor color. If set to the special value :code:`none` the cursor will
be rendered with a "reverse video" effect. It's color will be the color of the
text in the cell it is over and the text will be rendered with the background
color of the cell.  Note that if the program running in the terminal sets a
cursor color, this takes precedence. Also, the cursor colors are modified if
the cell background and foreground colors have very low contrast.
'''
    )

opt('cursor_text_color', '#111111',
    option_type='cursor_text_color',
    long_text='''
Choose the color of text under the cursor. If you want it rendered with the
background color of the cell underneath instead, use the special keyword:
background. Note that if :opt:`cursor` is set to :code:`none` then this setting
is ignored.
'''
    )

opt('cursor_shape', 'block',
    option_type='to_cursor_shape', ctype='int',
    long_text='The cursor shape can be one of (block, beam, underline).'
    ' Note that when reloading the config this will be changed only if the'
    ' cursor shape has not been set by the program running in the terminal.'
    ' This sets the default cursor shape. Applications running in the terminal'
    ' can override it. In particular, :ref:`shell_integration` in kitty'
    ' sets the cursor shape to :code:`beam` at shell prompts. You can avoid this'
    ' by setting :opt:`shell_integration` to :code:`no-cursor`.'
    )

opt('cursor_beam_thickness', '1.5',
    option_type='positive_float', ctype='float',
    long_text='Defines the thickness of the beam cursor (in pts)'
    )

opt('cursor_underline_thickness', '2.0',
    option_type='positive_float', ctype='float',
    long_text='Defines the thickness of the underline cursor (in pts)'
    )

opt('cursor_blink_interval', '-1',
    option_type='float', ctype='time',
    long_text='''
The interval (in seconds) at which to blink the cursor. Set to zero to disable
blinking. Negative values mean use system default. Note that numbers smaller
than :opt:`repaint_delay` will be limited to :opt:`repaint_delay`.
'''
    )

opt('cursor_stop_blinking_after', '15.0',
    option_type='positive_float', ctype='time',
    long_text='''
Stop blinking cursor after the specified number of seconds of keyboard
inactivity.  Set to zero to never stop blinking.
'''
    )
egr()  # }}}

# scrollback {{{
agr('scrollback', 'Scrollback')

opt('scrollback_lines', '2000',
    option_type='scrollback_lines',
    long_text='''
Number of lines of history to keep in memory for scrolling back. Memory is
allocated on demand. Negative numbers are (effectively) infinite scrollback.
Note that using very large scrollback is not recommended as it can slow down
performance of the terminal and also use large amounts of RAM. Instead, consider
using :opt:`scrollback_pager_history_size`. Note that on config reload if this
is changed it will only affect newly created windows, not existing ones.
'''
    )

opt('scrollback_pager', 'less --chop-long-lines --RAW-CONTROL-CHARS +INPUT_LINE_NUMBER',
    option_type='to_cmdline',
    long_text='''
Program with which to view scrollback in a new window. The scrollback buffer is
passed as STDIN to this program. If you change it, make sure the program you use
can handle ANSI escape sequences for colors and text formatting.
INPUT_LINE_NUMBER in the command line above will be replaced by an integer
representing which line should be at the top of the screen. Similarly
CURSOR_LINE and CURSOR_COLUMN will be replaced by the current cursor position or
set to 0 if there is no cursor, for example, when showing the last command output.
'''
    )

opt('scrollback_pager_history_size', '0',
    option_type='scrollback_pager_history_size', ctype='uint',
    long_text='''
Separate scrollback history size, used only for browsing the scrollback buffer
(in MB). This separate buffer is not available for interactive scrolling but
will be piped to the pager program when viewing scrollback buffer in a separate
window. The current implementation stores the data in UTF-8, so approximatively
10000 lines per megabyte at 100 chars per line, for pure ASCII text, unformatted
text. A value of zero or less disables this feature. The maximum allowed size is
4GB. Note that on config reload if this
is changed it will only affect newly created windows, not existing ones.
'''
    )

opt('scrollback_fill_enlarged_window', 'no',
    option_type='to_bool', ctype='bool',
    long_text='Fill new space with lines from the scrollback buffer after enlarging a window.'
    )

opt('wheel_scroll_multiplier', '5.0',
    option_type='float', ctype='double',
    long_text='''
Modify the amount scrolled by the mouse wheel. Note this is only used for low
precision scrolling devices, not for high precision scrolling on platforms such
as macOS and Wayland. Use negative numbers to change scroll direction.
'''
    )

opt('touch_scroll_multiplier', '1.0',
    option_type='float', ctype='double',
    long_text='''
Modify the amount scrolled by a touchpad. Note this is only used for high
precision scrolling devices on platforms such as macOS and Wayland. Use negative
numbers to change scroll direction.
'''
    )
egr()  # }}}

# mouse {{{
agr('mouse', 'Mouse')

opt('mouse_hide_wait', '3.0',
    macos_default='0.0',
    option_type='float', ctype='time',
    long_text='''
Hide mouse cursor after the specified number of seconds of the mouse not being
used. Set to zero to disable mouse cursor hiding. Set to a negative value to
hide the mouse cursor immediately when typing text. Disabled by default on macOS
as getting it to work robustly with the ever-changing sea of bugs that is Cocoa
is too much effort.
'''
    )

opt('url_color', '#0087bd',
    option_type='to_color', ctype='color_as_int',
    long_text='''
The color and style for highlighting URLs on mouse-over. :code:`url_style` can
be one of: none, single, double, curly
'''
    )

opt('url_style', 'curly',
    option_type='url_style', ctype='uint',
    )

opt('open_url_with', 'default',
    option_type='to_cmdline',
    long_text='''
The program with which to open URLs that are clicked on. The special value
:code:`default` means to use the operating system's default URL handler.
'''
    )

opt('url_prefixes', 'http https file ftp gemini irc gopher mailto news git',
    option_type='url_prefixes', ctype='!url_prefixes',
    long_text='''
The set of URL prefixes to look for when detecting a URL under the mouse cursor.
'''
    )

opt('detect_urls', 'yes',
    option_type='to_bool', ctype='bool',
    long_text='''
Detect URLs under the mouse. Detected URLs are highlighted with an underline and
the mouse cursor becomes a hand over them. Even if this option is disabled, URLs
are still clickable.
'''
    )

opt('url_excluded_characters', '',
    ctype='!url_excluded_characters',
    long_text='''
Additional characters to be disallowed from URLs, when detecting URLs under the
mouse cursor. By default, all characters legal in URLs are allowed.
'''
    )

opt('copy_on_select', 'no',
    option_type='copy_on_select',
    long_text='''
Copy to clipboard or a private buffer on select. With this set to
:code:`clipboard`, simply selecting text with the mouse will cause the text to
be copied to clipboard. Useful on platforms such as macOS that do not have the
concept of primary selections. You can instead specify a name such as :code:`a1` to
copy to a private kitty buffer instead. Map a shortcut with the
:code:`paste_from_buffer` action to paste from this private buffer.
For example::

    map shift+cmd+v paste_from_buffer a1

Note that copying to the clipboard is a security risk, as all programs,
including websites open in your browser can read the contents of the
system clipboard.
'''
    )

opt('strip_trailing_spaces', 'never',
    choices=('always', 'never', 'smart'),
    long_text='''
Remove spaces at the end of lines when copying to clipboard. A value of
:code:`smart` will do it when using normal selections, but not rectangle
selections. :code:`always` will always do it.
'''
    )

opt('select_by_word_characters', '@-./_~?&=%+#',
    ctype='!select_by_word_characters',
    long_text='''
Characters considered part of a word when double clicking. In addition to these
characters any character that is marked as an alphanumeric character in the
unicode database will be matched.
'''
    )

opt('click_interval', '-1.0',
    option_type='float', ctype='time',
    long_text='''
The interval between successive clicks to detect double/triple clicks (in
seconds). Negative numbers will use the system default instead, if available, or
fallback to 0.5.
'''
    )

opt('focus_follows_mouse', 'no',
    option_type='to_bool', ctype='bool',
    long_text='''
Set the active window to the window under the mouse when moving the mouse around
'''
    )

opt('pointer_shape_when_grabbed', 'arrow',
    choices=('arrow', 'beam', 'hand'), ctype='pointer_shape',
    long_text='''
The shape of the mouse pointer when the program running in the terminal grabs
the mouse. Valid values are: :code:`arrow`, :code:`beam` and :code:`hand`
'''
    )

opt('default_pointer_shape', 'beam',
    choices=('arrow', 'beam', 'hand'), ctype='pointer_shape',
    long_text='''
The default shape of the mouse pointer. Valid values are: :code:`arrow`,
:code:`beam` and :code:`hand`
'''
    )

opt('pointer_shape_when_dragging', 'beam',
    choices=('arrow', 'beam', 'hand'), ctype='pointer_shape',
    long_text='''
The default shape of the mouse pointer when dragging across text. Valid values
are: :code:`arrow`, :code:`beam` and :code:`hand`
'''
    )


# mouse.mousemap {{{
agr('mouse.mousemap', 'Mouse actions', '''
Mouse buttons can be remapped to perform arbitrary actions. The syntax for
doing so is:

.. code-block:: none

    mouse_map button-name event-type modes action

Where ``button-name`` is one of ``left``, ``middle``, ``right`` or ``b1 ... b8``
with added keyboard modifiers, for example: ``ctrl+shift+left`` refers to holding
the :kbd:`ctrl+shift` keys while clicking with the left mouse button. The
number ``b1 ... b8`` can be used to refer to upto eight buttons on a mouse.

``event-type`` is one ``press``, ``release``, ``doublepress``, ``triplepress``,
``click`` and ``doubleclick``.  ``modes`` indicates whether the action is
performed when the mouse is grabbed by the program running in the terminal, or
not. It can have one or more or the values, ``grabbed,ungrabbed``. ``grabbed``
refers to when the program running in the terminal has requested mouse events.
Note that the click and double click events have a delay of
:opt:`click_interval` to disambiguate from double and triple presses.

You can run kitty with the :option:`kitty --debug-input` command line option
to see mouse events. See the builtin actions below to get a sense of what is possible.

If you want to unmap an action map it to ``no-op``. For example, to disable opening
of URLs with a plain click::

    mouse_map left click ungrabbed no-op

.. note::
    Once a selection is started, releasing the button that started it will
    automatically end it and no release event will be dispatched.
''')

opt('clear_all_mouse_actions', 'no',
    option_type='clear_all_mouse_actions',
    long_text='''
You can have kitty remove all mouse actions seen up to this point.
Useful, for instance, to remove the default mouse actions.
'''
    )

mma('Click the link under the mouse or move the cursor',
    'click_url_or_select left click ungrabbed mouse_handle_click selection link prompt',
    long_text='''
First check for a selection and if one exists do nothing. Then check for a link
under the mouse cursor and if one exists, click it. Finally check if the click happened at
the current shell prompt and if so, move the cursor to the click location. Note that this
requires :doc:`shell-integration` to work.
'''
    )

mma('Click the link under the mouse or move the cursor even when grabbed',
    'click_url_or_select_grabbed shift+left click grabbed,ungrabbed mouse_handle_click selection link prompt',
    long_text='''
Same as above, except that the action is performed even when the mouse is grabbed
by the program running in the terminal.
'''
    )

mma('Click the link under the mouse cursor',
    'click_url ctrl+shift+left release grabbed,ungrabbed mouse_handle_click link',
    long_text='Variant with :kbd:`ctrl+shift` is present because the simple'
    ' click based version has an unavoidable delay of :opt:`click_interval`, to disambiguate clicks from double clicks.'
    )

mma('Discard press event for link click',
    'click_url_discard ctrl+shift+left press grabbed discard_event',
    long_text='Prevent this press event from being sent to the program that has'
    ' grabbed the mouse, as the corresponding release event is used to open a URL.'
    )


mma('Paste from the primary selection',
    'paste_selection middle release ungrabbed paste_from_selection',
    )

mma('Start selecting text',
    'start_simple_selection left press ungrabbed mouse_selection normal',
    )

mma('Start selecting text in a rectangle',
    'start_rectangle_selection ctrl+alt+left press ungrabbed mouse_selection rectangle',
    )

mma('Select a word',
    'select_word left doublepress ungrabbed mouse_selection word',
    )

mma('Select a line',
    'select_line left triplepress ungrabbed mouse_selection line',
    long_text='Select the entire line'
    )

mma('Select line from point',
    'select_line_from_point ctrl+alt+left triplepress ungrabbed mouse_selection line_from_point',
    long_text='Select from the clicked point to the end of the line'
    )

mma('Extend the current selection',
    'extend_selection right press ungrabbed mouse_selection extend',
    long_text='If you want only the end of the selection to be moved instead of the nearest boundary, use move-end instead of extend.'
    )

mma('Paste from the primary selection even when grabbed',
    'paste_selection_grabbed shift+middle release ungrabbed,grabbed paste_selection',
    )

mma('Discard press event for middle click paste',
    'paste_selection_grabbed shift+middle press grabbed discard_event',
    )

mma('Start selecting text even when grabbed',
    'start_simple_selection_grabbed shift+left press ungrabbed,grabbed mouse_selection normal',
    )

mma('Start selecting text in a rectangle even when grabbed',
    'start_rectangle_selection_grabbed ctrl+shift+alt+left press ungrabbed,grabbed mouse_selection rectangle',
    )

mma('Select a word even when grabbed',
    'select_word_grabbed shift+left doublepress ungrabbed,grabbed mouse_selection word',
    )

mma('Select a line even when grabbed',
    'select_line_grabbed shift+left triplepress ungrabbed,grabbed mouse_selection line',
    long_text='Select the entire line'
    )

mma('Select line from point even when grabbed',
    'select_line_from_point_grabbed ctrl+shift+alt+left triplepress ungrabbed,grabbed mouse_selection line_from_point',
    long_text='Select from the clicked point to the end of the line'
    )

mma('Extend the current selection even when grabbed',
    'extend_selection_grabbed shift+right press ungrabbed,grabbed mouse_selection extend',
    )

mma('Show clicked command output in pager',
    'show_clicked_cmd_output_ungrabbed ctrl+shift+right press ungrabbed mouse_show_command_output',
    long_text='Requires :ref:`shell_integration` to work'
    )
egr()  # }}}
egr()  # }}}

# performance {{{
agr('performance', 'Performance tuning')

opt('repaint_delay', '10',
    option_type='positive_int', ctype='time-ms',
    long_text='''
Delay (in milliseconds) between screen updates. Decreasing it, increases frames-per-second
(FPS) at the cost of more CPU usage. The default value yields ~100
FPS which is more than sufficient for most uses. Note that to actually achieve
100 FPS you have to either set :opt:`sync_to_monitor` to no or use a monitor
with a high refresh rate. Also, to minimize latency when there is pending input
to be processed, repaint_delay is ignored.
'''
    )

opt('input_delay', '3',
    option_type='positive_int', ctype='time-ms',
    long_text='''
Delay (in milliseconds) before input from the program running in the terminal is
processed. Note that decreasing it will increase responsiveness, but also
increase CPU usage and might cause flicker in full screen programs that redraw
the entire screen on each loop, because kitty is so fast that partial screen
updates will be drawn.
'''
    )

opt('sync_to_monitor', 'yes',
    option_type='to_bool', ctype='bool',
    long_text='''
Sync screen updates to the refresh rate of the monitor. This prevents tearing
(https://en.wikipedia.org/wiki/Screen_tearing) when scrolling. However, it
limits the rendering speed to the refresh rate of your monitor. With a very high
speed mouse/high keyboard repeat rate, you may notice some slight input latency.
If so, set this to no.
'''
    )
egr()  # }}}

# bell {{{
agr('bell', 'Terminal bell')

opt('enable_audio_bell', 'yes',
    option_type='to_bool', ctype='bool',
    long_text='Enable/disable the audio bell. Useful in environments that require silence.'
    )

opt('visual_bell_duration', '0.0',
    option_type='positive_float', ctype='time',
    long_text='''
Visual bell duration. Flash the screen when a bell occurs for the specified
number of seconds. Set to zero to disable.
'''
    )

opt('visual_bell_color', 'none',
    option_type='to_color_or_none',
    long_text='''
The color used by visual bell. Set to :code:`none` will fall back to selection
background color. If you feel that the visual bell is too bright, you can
set it to a darker color.
''')

opt('window_alert_on_bell', 'yes',
    option_type='to_bool', ctype='bool',
    long_text='''
Request window attention on bell. Makes the dock icon bounce on macOS or the
taskbar flash on linux.
'''
    )

opt('bell_on_tab', 'yes',
    option_type='to_bool',
    long_text='''
Show a bell symbol on the tab if a bell occurs in one of the windows in the tab
and the window is not the currently focused window
'''
    )

opt('command_on_bell', 'none',
    option_type='to_cmdline',
    long_text='Program to run when a bell occurs.'
    ' The environment variable :envvar:`KITTY_CHILD_CMDLINE` can be used to get the program running in'
    ' the window in which the bell occurred.'
    )

opt('bell_path', 'none',
    option_type='config_or_absolute_path', ctype='!bell_path',
    long_text='Path to a sound file to play as the bell sound. If set to :code:`none`, the system default bell sound is used.'
    ' Must be in a format supported by the operating systems sound API, such as WAV or OGA on Linux (libcanberra)'
    ' or AIFF, MP3 or WAV on macOS (NSSound)'
    )

egr()  # }}}

# window {{{
agr('window', 'Window layout')

opt('remember_window_size', 'yes',
    option_type='to_bool',
    long_text='''
If enabled, the window size will be remembered so that new instances of kitty
will have the same size as the previous instance. If disabled, the window will
initially have size configured by initial_window_width/height, in pixels. You
can use a suffix of "c" on the width/height values to have them interpreted as
number of cells instead of pixels.
'''
    )

opt('initial_window_width', '640',
    option_type='window_size',
    )

opt('initial_window_height', '400',
    option_type='window_size',
    )

opt('enabled_layouts', '*',
    option_type='to_layout_names',
    long_text='''
The enabled window layouts. A comma separated list of layout names. The special
value :code:`all` means all layouts. The first listed layout will be used as the
startup layout. Default configuration is all layouts in alphabetical order. For
a list of available layouts, see the :ref:`layouts`.
'''
    )

opt('window_resize_step_cells', '2',
    option_type='positive_int',
    long_text='''
The step size (in units of cell width/cell height) to use when resizing kitty windows
in a layout with the keyboard (:sc:`start_resizing_window`).
The cells value is used for horizontal resizing and the lines value for vertical
resizing.
'''
    )

opt('window_resize_step_lines', '2',
    option_type='positive_int',
    )

opt('window_border_width', '0.5pt',
    option_type='window_border_width',
    long_text='''
The width of window borders. Can be either in pixels (px) or pts (pt). Values in
pts will be rounded to the nearest number of pixels based on screen resolution.
If not specified the unit is assumed to be pts. Note that borders are displayed
only when more than one window is visible. They are meant to separate multiple
windows.
'''
    )

opt('draw_minimal_borders', 'yes',
    option_type='to_bool',
    long_text='''
Draw only the minimum borders needed. This means that only the minimum needed
borders for inactive windows are drawn. That is only the borders that separate
the inactive window from a neighbor. Note that setting a non-zero window margin
overrides this and causes all borders to be drawn.
'''
    )

opt('window_margin_width', '0',
    option_type='edge_width',
    long_text='''
The window margin (in pts) (blank area outside the border). A single value sets
all four sides. Two values set the vertical and horizontal sides. Three values
set top, horizontal and bottom. Four values set top, right, bottom and left.
'''
    )

opt('single_window_margin_width', '-1',
    option_type='optional_edge_width',
    long_text='''
The window margin (in pts) to use when only a single window is visible. Negative
values will cause the value of :opt:`window_margin_width` to be used instead. A
single value sets all four sides. Two values set the vertical and horizontal
sides. Three values set top, horizontal and bottom. Four values set top, right,
bottom and left.
'''
    )

opt('window_padding_width', '0',
    option_type='edge_width',
    long_text='''
The window padding (in pts) (blank area between the text and the window border).
A single value sets all four sides. Two values set the vertical and horizontal
sides. Three values set top, horizontal and bottom. Four values set top, right,
bottom and left.
'''
    )

opt('placement_strategy', 'center',
    choices=('center', 'top-left'),
    long_text='''
When the window size is not an exact multiple of the cell size, the cell area of
the terminal window will have some extra padding on the sides. You can control
how that padding is distributed with this option. Using a value of
:code:`center` means the cell area will be placed centrally. A value of
:code:`top-left` means the padding will be on only the bottom and right edges.
'''
    )

opt('active_border_color', '#00ff00',
    option_type='to_color_or_none', ctype='active_border_color',
    long_text='''
The color for the border of the active window. Set this to none to not draw
borders around the active window.
'''
    )

opt('inactive_border_color', '#cccccc',
    option_type='to_color', ctype='color_as_int',
    long_text='The color for the border of inactive windows'
    )

opt('bell_border_color', '#ff5a00',
    option_type='to_color', ctype='color_as_int',
    long_text='The color for the border of inactive windows in which a bell has occurred'
    )

opt('inactive_text_alpha', '1.0',
    option_type='unit_float', ctype='float',
    long_text='''
Fade the text in inactive windows by the specified amount (a number between zero
and one, with zero being fully faded).
'''
    )

opt('hide_window_decorations', 'no',
    option_type='hide_window_decorations', ctype='uint',
    long_text='''
Hide the window decorations (title-bar and window borders) with :code:`yes`. On
macOS, :code:`titlebar-only` can be used to only hide the titlebar. Whether this
works and exactly what effect it has depends on the window manager/operating
system. Note that the effects of changing this setting when reloading config
are undefined.
'''
    )

opt('window_logo_path', 'none',
    option_type='config_or_absolute_path', ctype='!window_logo_path',
    long_text='''
Path to a logo image. Must be in PNG format. Relative paths are interpreted
relative to the kitty config directory.  The logo is displayed in a corner of every
kitty window. The position is controlled by :opt:`window_logo_position`.
Individual windows can be configured to have different logos either using the
:doc:`launch` function or the :doc:`remote-control` facility.
''')

opt('window_logo_position', 'bottom-right',
    choices=('top-left', 'top', 'top-right', 'left', 'center', 'right', 'bottom-left', 'bottom', 'bottom-right'), ctype='bganchor',
    long_text='''
Where to position the window logo in the window. The value can be one of:
:code:`top-left`, :code:`top`, :code:`top-right`, :code:`left`, :code:`center`,
:code:`right`, :code:`bottom-left`, :code:`bottom`, :code:`bottom-right`.
'''
    )

opt('window_logo_alpha', 0.5, option_type='unit_float', ctype='float', long_text='''
The amount the logo should be faded into the background. With zero being fully faded
and one being fully opaque.''')


opt('resize_debounce_time', '0.1',
    option_type='positive_float', ctype='time',
    long_text='''
The time (in seconds) to wait before redrawing the screen when a resize event is
received. On platforms such as macOS, where the operating system sends events
corresponding to the start and end of a resize, this number is ignored.
'''
    )

opt('resize_draw_strategy', 'static',
    option_type='resize_draw_strategy', ctype='int',
    long_text='''
Choose how kitty draws a window while a resize is in progress. A value of
:code:`static` means draw the current window contents, mostly unchanged. A value
of :code:`scale` means draw the current window contents scaled. A value of
:code:`blank` means draw a blank window. A value of :code:`size` means show the
window size in cells.
'''
    )

opt('resize_in_steps', 'no',
    option_type='to_bool', ctype='bool',
    long_text='''
Resize the OS window in steps as large as the cells, instead of with the usual
pixel accuracy. Combined with an :opt:`initial_window_width` and
:opt:`initial_window_height` in number of cells, this option can be used to keep
the margins as small as possible when resizing the OS window. Note that this
does not currently work on Wayland.
'''
    )

opt('visual_window_select_characters', defval=string.digits[1:] + '0' + string.ascii_uppercase,
    option_type='visual_window_select_characters',
    long_text='''
The list of characters to use for visual window selection (for example for
selecting a window to focus with :sc:`focus_visible_window`). The value should
be a series of unique numbers or alphabets, case insensitive, from the set
:code:`[0-9A-Z]`. Specify your preference as a string of characters.
'''
    )

opt('confirm_os_window_close', '0',
    option_type='int',
    long_text='''
Ask for confirmation when closing an OS window or a Tab with at least this
number of kitty windows in it by window manager (e.g. clicking the window close
button or pressing the Operating system shortcut to close windows) or by the
:sc:`close_tab` action. A value of zero disables confirmation. This
confirmation also applies to requests to quit the entire application (all OS
windows, via the quit action). Negative values are converted to positive ones,
however, with :ref:`shell_integration` enabled, using negative values means
windows sitting at a shell prompt are not counted, only windows where some
command is currently running. Note that if you want confirmation when closing
individual windows, you can map the :ref:`action-close_window_with_confirmation` action.
'''
    )
egr()  # }}}

# tabbar {{{
agr('tabbar', 'Tab bar')

opt('tab_bar_edge', 'bottom',
    option_type='tab_bar_edge', ctype='int',
    long_text='Which edge to show the tab bar on, top or bottom'
    )

opt('tab_bar_margin_width', '0.0',
    option_type='positive_float',
    long_text='The margin to the left and right of the tab bar (in pts)'
    )

opt('tab_bar_margin_height', '0.0 0.0',
    option_type='tab_bar_margin_height', ctype='!tab_bar_margin_height',
    long_text='''
The margin above and below the tab bar (in pts). The first number is the
margin between the edge of the OS Window and the tab bar and the second
number is the margin between the tab bar and the contents of the current
tab.
'''
    )


opt('tab_bar_style', 'fade',
    choices=('fade', 'hidden', 'powerline', 'separator', 'slant', 'custom'), ctype='!tab_bar_style',
    long_text='''
The tab bar style, can be one of:

:code:`fade`
    Each tab's edges fade into the background color (see :opt:`tab_fade`)
:code:`slant`
    Tabs look like the tabs in a physical file
:code:`separator`
    Tabs are separated by a configurable separator (see :opt:`tab_separator`)
:code:`powerline`
    Tabs are shown as a continuous line with "fancy" separators
    (see :opt:`tab_powerline_style`)
:code:`custom`
    A user-supplied Python function called draw_tab is loaded from the file
    :file:`tab_bar.py` in the kitty config directory. For examples of how to
    write such a function, see the functions named :code:`draw_tab_with_*` in
    kitty's source code: :file:`kitty/tab_bar.py`. See also
    :disc:`this discussion <4447>` for examples from kitty users.
:code:`hidden`
    The tab bar is hidden. If you use this, you might want to create a
    mapping for the :ref:`action-select_tab`
    action which presents you with a list of tabs and allows for easy
    switching to a tab.
'''
    )

opt('tab_bar_align', 'left', choices=('left', 'center', 'right'),
    long_text='''
The horizontal alignment of the tab bar, can be one of: :code:`left`,
:code:`center`, or :code:`right`.
'''
    )

opt('tab_bar_min_tabs', '2',
    option_type='tab_bar_min_tabs', ctype='uint',
    long_text='The minimum number of tabs that must exist before the tab bar is shown'
    )

opt('tab_switch_strategy', 'previous',
    choices=('last', 'left', 'previous', 'right'),
    long_text='''
The algorithm to use when switching to a tab when the current tab is closed. The
default of :code:`previous` will switch to the last used tab. A value of
:code:`left` will switch to the tab to the left of the closed tab. A value of
:code:`right` will switch to the tab to the right of the closed tab. A value of
:code:`last` will switch to the right-most tab.
'''
    )

opt('tab_fade', '0.25 0.5 0.75 1',
    option_type='tab_fade',
    long_text='''
Control how each tab fades into the background when using :code:`fade` for the
:opt:`tab_bar_style`. Each number is an alpha (between zero and one) that
controls how much the corresponding cell fades into the background, with zero
being no fade and one being full fade. You can change the number of cells used
by adding/removing entries to this list.
'''
    )

opt('tab_separator', '" ┇"',
    option_type='tab_separator',
    long_text='''
The separator between tabs in the tab bar when using :code:`separator` as the
:opt:`tab_bar_style`.
'''
    )

opt('tab_powerline_style', 'angled',
    choices=('angled', 'round', 'slanted'),
    long_text='''
The powerline separator style between tabs in the tab bar when using
:code:`powerline` as the :opt:`tab_bar_style`, can be one of: :code:`angled`,
:code:`slanted`, or :code:`round`.
'''
    )

opt('tab_activity_symbol', 'none',
    option_type='tab_activity_symbol',
    long_text='''
Some text or a unicode symbol to show on the tab if a window in the tab that
does not have focus has some activity. If you want to use leading or trailing spaces
surround the text with quotes. You can also use text formatting via the same templating
system as for :opt:`tab_title_template`.
'''
    )

opt('tab_title_template', '"{title}"',
    option_type='tab_title_template',
    long_text='''
A template to render the tab title. The default just renders the title. If you
wish to include the tab-index as well, use something like: :code:`{index}:
{title}`. Useful if you have shortcuts mapped for :code:`goto_tab N`. If you
prefer to see the index as a superscript, use {sup.index}. In
addition you can use :code:`{layout_name}` for the current layout name,
:code:`{num_windows}` for the number of windows in the tab and
:code:`{num_window_groups}` for the number of window groups
(not counting overlay windows) in the tab. Note that formatting
is done by Python's string formatting machinery, so you can use, for instance,
:code:`{layout_name[:2].upper()}` to show only the first two letters of the
layout name, upper-cased. If you want to style the text, you can use styling
directives, for example:
:code:`{fmt.fg.red}red{fmt.fg.default}normal{fmt.bg._00FF00}green
bg{fmt.bg.tab}`. Similarly, for bold and italic:
:code:`{fmt.bold}bold{fmt.nobold}normal{fmt.italic}italic{fmt.noitalic}`.
'''
    )

opt('active_tab_title_template', 'none',
    option_type='active_tab_title_template',
    long_text='''
Template to use for active tabs, if not specified falls back to
:opt:`tab_title_template`.
'''
    )

opt('active_tab_foreground', '#000',
    option_type='to_color',
    long_text='Tab bar colors and styles'
    )

opt('active_tab_background', '#eee',
    option_type='to_color',
    )

opt('active_tab_font_style', 'bold-italic',
    option_type='tab_font_style',
    )

opt('inactive_tab_foreground', '#444',
    option_type='to_color',
    )

opt('inactive_tab_background', '#999',
    option_type='to_color',
    )

opt('inactive_tab_font_style', 'normal',
    option_type='tab_font_style',
    )

opt('tab_bar_background', 'none',
    option_type='to_color_or_none', ctype='color_or_none_as_int',
    long_text='''
Background color for the tab bar. Defaults to using the terminal background
color.
'''
    )

opt('tab_bar_margin_color', 'none',
    option_type='to_color_or_none', ctype='color_or_none_as_int',
    long_text='''
Color for the tab bar margin area. Defaults to using the terminal background
color.
'''
    )
egr()  # }}}

# colors {{{
agr('colors', 'Color scheme')

opt('foreground', '#dddddd',
    option_type='to_color', ctype='color_as_int',
    long_text='The foreground and background colors'
    )

opt('background', '#000000',
    option_type='to_color', ctype='color_as_int',
    )

opt('background_opacity', '1.0',
    option_type='unit_float', ctype='float',
    long_text='''
The opacity of the background. A number between 0 and 1, where 1 is opaque and 0
is fully transparent.  This will only work if supported by the OS (for instance,
when using a compositor under X11). Note that it only sets the background
color's opacity in cells that have the same background color as the default
terminal background. This is so that things like the status bar in vim,
powerline prompts, etc. still look good.  But it means that if you use a color
theme with a background color in your editor, it will not be rendered as
transparent.  Instead you should change the default background color in your
kitty config and not use a background color in the editor color scheme. Or use
the escape codes to set the terminals default colors in a shell script to launch
your editor.  Be aware that using a value less than 1.0 is a (possibly
significant) performance hit.  If you want to dynamically change transparency of
windows set :opt:`dynamic_background_opacity` to :code:`yes` (this is off by
default as it has a performance cost). Changing this setting when reloading
the config will only work if :opt:`dynamic_background_opacity` was enabled
in the original config.
'''
    )

opt('background_image', 'none',
    option_type='config_or_absolute_path', ctype='!background_image',
    long_text='Path to a background image. Must be in PNG format.'
    )

opt('background_image_layout', 'tiled',
    choices=('mirror-tiled', 'scaled', 'tiled', 'clamped'), ctype='bglayout',
    long_text='''
Whether to tile, scale or clamp the background image. The value can be one of
:code:`tiled`, :code:`mirror-tiled`, :code:`scaled`, :code:`clamped`.
'''
    )

opt('background_image_linear', 'no',
    option_type='to_bool', ctype='bool',
    long_text='When background image is scaled, whether linear interpolation should be used.'
    )

opt('dynamic_background_opacity', 'no',
    option_type='to_bool', ctype='bool',
    long_text='''
Allow changing of the :opt:`background_opacity` dynamically, using either
keyboard shortcuts (:sc:`increase_background_opacity` and
:sc:`decrease_background_opacity`) or the remote control facility. Changing
this setting by reloading the config is not supported.
'''
    )

opt('background_tint', '0.0',
    option_type='unit_float', ctype='float',
    long_text='''
How much to tint the background image by the background color. The tint is
applied only under the text area, not margin/borders. Makes it easier to read
the text. Tinting is done using the current background color for each window.
This setting applies only if :opt:`background_opacity` is set and transparent
windows are supported or :opt:`background_image` is set.
'''
    )

opt('dim_opacity', '0.75',
    option_type='unit_float', ctype='float',
    long_text='''
How much to dim text that has the DIM/FAINT attribute set. One means no dimming
and zero means fully dimmed (i.e. invisible).
'''
    )

opt('selection_foreground', '#000000',
    option_type='to_color_or_none',
    long_text='''
The foreground and background colors for text selected with the mouse. Setting both of
these to :code:`none` will cause a "reverse video" effect for selections, where the
selection will be the cell text color and the text will become the cell background color.
Setting only selection_foreground to :code:`none` will cause the foreground color to be
used unchanged. Note that these colors can be overridden by the program running in the terminal.
''')

opt('selection_background', '#fffacd', option_type='to_color_or_none',)


# colors.table {{{
agr('colors.table', 'The color table', '''
The 256 terminal colors. There are 8 basic colors, each color has a dull and
bright version, for the first 16 colors. You can set the remaining 240 colors as
color16 to color255.
''')

opt('color0', '#000000',
    option_type='to_color',
    long_text='black'
    )

opt('color8', '#767676',
    option_type='to_color',
    )

opt('color1', '#cc0403',
    option_type='to_color',
    long_text='red'
    )

opt('color9', '#f2201f',
    option_type='to_color',
    )

opt('color2', '#19cb00',
    option_type='to_color',
    long_text='green'
    )

opt('color10', '#23fd00',
    option_type='to_color',
    )

opt('color3', '#cecb00',
    option_type='to_color',
    long_text='yellow'
    )

opt('color11', '#fffd00',
    option_type='to_color',
    )

opt('color4', '#0d73cc',
    option_type='to_color',
    long_text='blue'
    )

opt('color12', '#1a8fff',
    option_type='to_color',
    )

opt('color5', '#cb1ed1',
    option_type='to_color',
    long_text='magenta'
    )

opt('color13', '#fd28ff',
    option_type='to_color',
    )

opt('color6', '#0dcdcd',
    option_type='to_color',
    long_text='cyan'
    )

opt('color14', '#14ffff',
    option_type='to_color',
    )

opt('color7', '#dddddd',
    option_type='to_color',
    long_text='white'
    )

opt('color15', '#ffffff',
    option_type='to_color',
    )

opt('mark1_foreground', 'black',
    option_type='to_color', ctype='color_as_int',
    long_text='Color for marks of type 1'
    )

opt('mark1_background', '#98d3cb',
    option_type='to_color', ctype='color_as_int',
    long_text='Color for marks of type 1 (light steel blue)'
    )

opt('mark2_foreground', 'black',
    option_type='to_color', ctype='color_as_int',
    long_text='Color for marks of type 2'
    )

opt('mark2_background', '#f2dcd3',
    option_type='to_color', ctype='color_as_int',
    long_text='Color for marks of type 1 (beige)'
    )

opt('mark3_foreground', 'black',
    option_type='to_color', ctype='color_as_int',
    long_text='Color for marks of type 3'
    )

opt('mark3_background', '#f274bc',
    option_type='to_color', ctype='color_as_int',
    long_text='Color for marks of type 3 (violet)'
    )

opt('color16', '#000000',
    option_type='to_color',
    documented=False,
    )

opt('color17', '#00005f',
    option_type='to_color',
    documented=False,
    )

opt('color18', '#000087',
    option_type='to_color',
    documented=False,
    )

opt('color19', '#0000af',
    option_type='to_color',
    documented=False,
    )

opt('color20', '#0000d7',
    option_type='to_color',
    documented=False,
    )

opt('color21', '#0000ff',
    option_type='to_color',
    documented=False,
    )

opt('color22', '#005f00',
    option_type='to_color',
    documented=False,
    )

opt('color23', '#005f5f',
    option_type='to_color',
    documented=False,
    )

opt('color24', '#005f87',
    option_type='to_color',
    documented=False,
    )

opt('color25', '#005faf',
    option_type='to_color',
    documented=False,
    )

opt('color26', '#005fd7',
    option_type='to_color',
    documented=False,
    )

opt('color27', '#005fff',
    option_type='to_color',
    documented=False,
    )

opt('color28', '#008700',
    option_type='to_color',
    documented=False,
    )

opt('color29', '#00875f',
    option_type='to_color',
    documented=False,
    )

opt('color30', '#008787',
    option_type='to_color',
    documented=False,
    )

opt('color31', '#0087af',
    option_type='to_color',
    documented=False,
    )

opt('color32', '#0087d7',
    option_type='to_color',
    documented=False,
    )

opt('color33', '#0087ff',
    option_type='to_color',
    documented=False,
    )

opt('color34', '#00af00',
    option_type='to_color',
    documented=False,
    )

opt('color35', '#00af5f',
    option_type='to_color',
    documented=False,
    )

opt('color36', '#00af87',
    option_type='to_color',
    documented=False,
    )

opt('color37', '#00afaf',
    option_type='to_color',
    documented=False,
    )

opt('color38', '#00afd7',
    option_type='to_color',
    documented=False,
    )

opt('color39', '#00afff',
    option_type='to_color',
    documented=False,
    )

opt('color40', '#00d700',
    option_type='to_color',
    documented=False,
    )

opt('color41', '#00d75f',
    option_type='to_color',
    documented=False,
    )

opt('color42', '#00d787',
    option_type='to_color',
    documented=False,
    )

opt('color43', '#00d7af',
    option_type='to_color',
    documented=False,
    )

opt('color44', '#00d7d7',
    option_type='to_color',
    documented=False,
    )

opt('color45', '#00d7ff',
    option_type='to_color',
    documented=False,
    )

opt('color46', '#00ff00',
    option_type='to_color',
    documented=False,
    )

opt('color47', '#00ff5f',
    option_type='to_color',
    documented=False,
    )

opt('color48', '#00ff87',
    option_type='to_color',
    documented=False,
    )

opt('color49', '#00ffaf',
    option_type='to_color',
    documented=False,
    )

opt('color50', '#00ffd7',
    option_type='to_color',
    documented=False,
    )

opt('color51', '#00ffff',
    option_type='to_color',
    documented=False,
    )

opt('color52', '#5f0000',
    option_type='to_color',
    documented=False,
    )

opt('color53', '#5f005f',
    option_type='to_color',
    documented=False,
    )

opt('color54', '#5f0087',
    option_type='to_color',
    documented=False,
    )

opt('color55', '#5f00af',
    option_type='to_color',
    documented=False,
    )

opt('color56', '#5f00d7',
    option_type='to_color',
    documented=False,
    )

opt('color57', '#5f00ff',
    option_type='to_color',
    documented=False,
    )

opt('color58', '#5f5f00',
    option_type='to_color',
    documented=False,
    )

opt('color59', '#5f5f5f',
    option_type='to_color',
    documented=False,
    )

opt('color60', '#5f5f87',
    option_type='to_color',
    documented=False,
    )

opt('color61', '#5f5faf',
    option_type='to_color',
    documented=False,
    )

opt('color62', '#5f5fd7',
    option_type='to_color',
    documented=False,
    )

opt('color63', '#5f5fff',
    option_type='to_color',
    documented=False,
    )

opt('color64', '#5f8700',
    option_type='to_color',
    documented=False,
    )

opt('color65', '#5f875f',
    option_type='to_color',
    documented=False,
    )

opt('color66', '#5f8787',
    option_type='to_color',
    documented=False,
    )

opt('color67', '#5f87af',
    option_type='to_color',
    documented=False,
    )

opt('color68', '#5f87d7',
    option_type='to_color',
    documented=False,
    )

opt('color69', '#5f87ff',
    option_type='to_color',
    documented=False,
    )

opt('color70', '#5faf00',
    option_type='to_color',
    documented=False,
    )

opt('color71', '#5faf5f',
    option_type='to_color',
    documented=False,
    )

opt('color72', '#5faf87',
    option_type='to_color',
    documented=False,
    )

opt('color73', '#5fafaf',
    option_type='to_color',
    documented=False,
    )

opt('color74', '#5fafd7',
    option_type='to_color',
    documented=False,
    )

opt('color75', '#5fafff',
    option_type='to_color',
    documented=False,
    )

opt('color76', '#5fd700',
    option_type='to_color',
    documented=False,
    )

opt('color77', '#5fd75f',
    option_type='to_color',
    documented=False,
    )

opt('color78', '#5fd787',
    option_type='to_color',
    documented=False,
    )

opt('color79', '#5fd7af',
    option_type='to_color',
    documented=False,
    )

opt('color80', '#5fd7d7',
    option_type='to_color',
    documented=False,
    )

opt('color81', '#5fd7ff',
    option_type='to_color',
    documented=False,
    )

opt('color82', '#5fff00',
    option_type='to_color',
    documented=False,
    )

opt('color83', '#5fff5f',
    option_type='to_color',
    documented=False,
    )

opt('color84', '#5fff87',
    option_type='to_color',
    documented=False,
    )

opt('color85', '#5fffaf',
    option_type='to_color',
    documented=False,
    )

opt('color86', '#5fffd7',
    option_type='to_color',
    documented=False,
    )

opt('color87', '#5fffff',
    option_type='to_color',
    documented=False,
    )

opt('color88', '#870000',
    option_type='to_color',
    documented=False,
    )

opt('color89', '#87005f',
    option_type='to_color',
    documented=False,
    )

opt('color90', '#870087',
    option_type='to_color',
    documented=False,
    )

opt('color91', '#8700af',
    option_type='to_color',
    documented=False,
    )

opt('color92', '#8700d7',
    option_type='to_color',
    documented=False,
    )

opt('color93', '#8700ff',
    option_type='to_color',
    documented=False,
    )

opt('color94', '#875f00',
    option_type='to_color',
    documented=False,
    )

opt('color95', '#875f5f',
    option_type='to_color',
    documented=False,
    )

opt('color96', '#875f87',
    option_type='to_color',
    documented=False,
    )

opt('color97', '#875faf',
    option_type='to_color',
    documented=False,
    )

opt('color98', '#875fd7',
    option_type='to_color',
    documented=False,
    )

opt('color99', '#875fff',
    option_type='to_color',
    documented=False,
    )

opt('color100', '#878700',
    option_type='to_color',
    documented=False,
    )

opt('color101', '#87875f',
    option_type='to_color',
    documented=False,
    )

opt('color102', '#878787',
    option_type='to_color',
    documented=False,
    )

opt('color103', '#8787af',
    option_type='to_color',
    documented=False,
    )

opt('color104', '#8787d7',
    option_type='to_color',
    documented=False,
    )

opt('color105', '#8787ff',
    option_type='to_color',
    documented=False,
    )

opt('color106', '#87af00',
    option_type='to_color',
    documented=False,
    )

opt('color107', '#87af5f',
    option_type='to_color',
    documented=False,
    )

opt('color108', '#87af87',
    option_type='to_color',
    documented=False,
    )

opt('color109', '#87afaf',
    option_type='to_color',
    documented=False,
    )

opt('color110', '#87afd7',
    option_type='to_color',
    documented=False,
    )

opt('color111', '#87afff',
    option_type='to_color',
    documented=False,
    )

opt('color112', '#87d700',
    option_type='to_color',
    documented=False,
    )

opt('color113', '#87d75f',
    option_type='to_color',
    documented=False,
    )

opt('color114', '#87d787',
    option_type='to_color',
    documented=False,
    )

opt('color115', '#87d7af',
    option_type='to_color',
    documented=False,
    )

opt('color116', '#87d7d7',
    option_type='to_color',
    documented=False,
    )

opt('color117', '#87d7ff',
    option_type='to_color',
    documented=False,
    )

opt('color118', '#87ff00',
    option_type='to_color',
    documented=False,
    )

opt('color119', '#87ff5f',
    option_type='to_color',
    documented=False,
    )

opt('color120', '#87ff87',
    option_type='to_color',
    documented=False,
    )

opt('color121', '#87ffaf',
    option_type='to_color',
    documented=False,
    )

opt('color122', '#87ffd7',
    option_type='to_color',
    documented=False,
    )

opt('color123', '#87ffff',
    option_type='to_color',
    documented=False,
    )

opt('color124', '#af0000',
    option_type='to_color',
    documented=False,
    )

opt('color125', '#af005f',
    option_type='to_color',
    documented=False,
    )

opt('color126', '#af0087',
    option_type='to_color',
    documented=False,
    )

opt('color127', '#af00af',
    option_type='to_color',
    documented=False,
    )

opt('color128', '#af00d7',
    option_type='to_color',
    documented=False,
    )

opt('color129', '#af00ff',
    option_type='to_color',
    documented=False,
    )

opt('color130', '#af5f00',
    option_type='to_color',
    documented=False,
    )

opt('color131', '#af5f5f',
    option_type='to_color',
    documented=False,
    )

opt('color132', '#af5f87',
    option_type='to_color',
    documented=False,
    )

opt('color133', '#af5faf',
    option_type='to_color',
    documented=False,
    )

opt('color134', '#af5fd7',
    option_type='to_color',
    documented=False,
    )

opt('color135', '#af5fff',
    option_type='to_color',
    documented=False,
    )

opt('color136', '#af8700',
    option_type='to_color',
    documented=False,
    )

opt('color137', '#af875f',
    option_type='to_color',
    documented=False,
    )

opt('color138', '#af8787',
    option_type='to_color',
    documented=False,
    )

opt('color139', '#af87af',
    option_type='to_color',
    documented=False,
    )

opt('color140', '#af87d7',
    option_type='to_color',
    documented=False,
    )

opt('color141', '#af87ff',
    option_type='to_color',
    documented=False,
    )

opt('color142', '#afaf00',
    option_type='to_color',
    documented=False,
    )

opt('color143', '#afaf5f',
    option_type='to_color',
    documented=False,
    )

opt('color144', '#afaf87',
    option_type='to_color',
    documented=False,
    )

opt('color145', '#afafaf',
    option_type='to_color',
    documented=False,
    )

opt('color146', '#afafd7',
    option_type='to_color',
    documented=False,
    )

opt('color147', '#afafff',
    option_type='to_color',
    documented=False,
    )

opt('color148', '#afd700',
    option_type='to_color',
    documented=False,
    )

opt('color149', '#afd75f',
    option_type='to_color',
    documented=False,
    )

opt('color150', '#afd787',
    option_type='to_color',
    documented=False,
    )

opt('color151', '#afd7af',
    option_type='to_color',
    documented=False,
    )

opt('color152', '#afd7d7',
    option_type='to_color',
    documented=False,
    )

opt('color153', '#afd7ff',
    option_type='to_color',
    documented=False,
    )

opt('color154', '#afff00',
    option_type='to_color',
    documented=False,
    )

opt('color155', '#afff5f',
    option_type='to_color',
    documented=False,
    )

opt('color156', '#afff87',
    option_type='to_color',
    documented=False,
    )

opt('color157', '#afffaf',
    option_type='to_color',
    documented=False,
    )

opt('color158', '#afffd7',
    option_type='to_color',
    documented=False,
    )

opt('color159', '#afffff',
    option_type='to_color',
    documented=False,
    )

opt('color160', '#d70000',
    option_type='to_color',
    documented=False,
    )

opt('color161', '#d7005f',
    option_type='to_color',
    documented=False,
    )

opt('color162', '#d70087',
    option_type='to_color',
    documented=False,
    )

opt('color163', '#d700af',
    option_type='to_color',
    documented=False,
    )

opt('color164', '#d700d7',
    option_type='to_color',
    documented=False,
    )

opt('color165', '#d700ff',
    option_type='to_color',
    documented=False,
    )

opt('color166', '#d75f00',
    option_type='to_color',
    documented=False,
    )

opt('color167', '#d75f5f',
    option_type='to_color',
    documented=False,
    )

opt('color168', '#d75f87',
    option_type='to_color',
    documented=False,
    )

opt('color169', '#d75faf',
    option_type='to_color',
    documented=False,
    )

opt('color170', '#d75fd7',
    option_type='to_color',
    documented=False,
    )

opt('color171', '#d75fff',
    option_type='to_color',
    documented=False,
    )

opt('color172', '#d78700',
    option_type='to_color',
    documented=False,
    )

opt('color173', '#d7875f',
    option_type='to_color',
    documented=False,
    )

opt('color174', '#d78787',
    option_type='to_color',
    documented=False,
    )

opt('color175', '#d787af',
    option_type='to_color',
    documented=False,
    )

opt('color176', '#d787d7',
    option_type='to_color',
    documented=False,
    )

opt('color177', '#d787ff',
    option_type='to_color',
    documented=False,
    )

opt('color178', '#d7af00',
    option_type='to_color',
    documented=False,
    )

opt('color179', '#d7af5f',
    option_type='to_color',
    documented=False,
    )

opt('color180', '#d7af87',
    option_type='to_color',
    documented=False,
    )

opt('color181', '#d7afaf',
    option_type='to_color',
    documented=False,
    )

opt('color182', '#d7afd7',
    option_type='to_color',
    documented=False,
    )

opt('color183', '#d7afff',
    option_type='to_color',
    documented=False,
    )

opt('color184', '#d7d700',
    option_type='to_color',
    documented=False,
    )

opt('color185', '#d7d75f',
    option_type='to_color',
    documented=False,
    )

opt('color186', '#d7d787',
    option_type='to_color',
    documented=False,
    )

opt('color187', '#d7d7af',
    option_type='to_color',
    documented=False,
    )

opt('color188', '#d7d7d7',
    option_type='to_color',
    documented=False,
    )

opt('color189', '#d7d7ff',
    option_type='to_color',
    documented=False,
    )

opt('color190', '#d7ff00',
    option_type='to_color',
    documented=False,
    )

opt('color191', '#d7ff5f',
    option_type='to_color',
    documented=False,
    )

opt('color192', '#d7ff87',
    option_type='to_color',
    documented=False,
    )

opt('color193', '#d7ffaf',
    option_type='to_color',
    documented=False,
    )

opt('color194', '#d7ffd7',
    option_type='to_color',
    documented=False,
    )

opt('color195', '#d7ffff',
    option_type='to_color',
    documented=False,
    )

opt('color196', '#ff0000',
    option_type='to_color',
    documented=False,
    )

opt('color197', '#ff005f',
    option_type='to_color',
    documented=False,
    )

opt('color198', '#ff0087',
    option_type='to_color',
    documented=False,
    )

opt('color199', '#ff00af',
    option_type='to_color',
    documented=False,
    )

opt('color200', '#ff00d7',
    option_type='to_color',
    documented=False,
    )

opt('color201', '#ff00ff',
    option_type='to_color',
    documented=False,
    )

opt('color202', '#ff5f00',
    option_type='to_color',
    documented=False,
    )

opt('color203', '#ff5f5f',
    option_type='to_color',
    documented=False,
    )

opt('color204', '#ff5f87',
    option_type='to_color',
    documented=False,
    )

opt('color205', '#ff5faf',
    option_type='to_color',
    documented=False,
    )

opt('color206', '#ff5fd7',
    option_type='to_color',
    documented=False,
    )

opt('color207', '#ff5fff',
    option_type='to_color',
    documented=False,
    )

opt('color208', '#ff8700',
    option_type='to_color',
    documented=False,
    )

opt('color209', '#ff875f',
    option_type='to_color',
    documented=False,
    )

opt('color210', '#ff8787',
    option_type='to_color',
    documented=False,
    )

opt('color211', '#ff87af',
    option_type='to_color',
    documented=False,
    )

opt('color212', '#ff87d7',
    option_type='to_color',
    documented=False,
    )

opt('color213', '#ff87ff',
    option_type='to_color',
    documented=False,
    )

opt('color214', '#ffaf00',
    option_type='to_color',
    documented=False,
    )

opt('color215', '#ffaf5f',
    option_type='to_color',
    documented=False,
    )

opt('color216', '#ffaf87',
    option_type='to_color',
    documented=False,
    )

opt('color217', '#ffafaf',
    option_type='to_color',
    documented=False,
    )

opt('color218', '#ffafd7',
    option_type='to_color',
    documented=False,
    )

opt('color219', '#ffafff',
    option_type='to_color',
    documented=False,
    )

opt('color220', '#ffd700',
    option_type='to_color',
    documented=False,
    )

opt('color221', '#ffd75f',
    option_type='to_color',
    documented=False,
    )

opt('color222', '#ffd787',
    option_type='to_color',
    documented=False,
    )

opt('color223', '#ffd7af',
    option_type='to_color',
    documented=False,
    )

opt('color224', '#ffd7d7',
    option_type='to_color',
    documented=False,
    )

opt('color225', '#ffd7ff',
    option_type='to_color',
    documented=False,
    )

opt('color226', '#ffff00',
    option_type='to_color',
    documented=False,
    )

opt('color227', '#ffff5f',
    option_type='to_color',
    documented=False,
    )

opt('color228', '#ffff87',
    option_type='to_color',
    documented=False,
    )

opt('color229', '#ffffaf',
    option_type='to_color',
    documented=False,
    )

opt('color230', '#ffffd7',
    option_type='to_color',
    documented=False,
    )

opt('color231', '#ffffff',
    option_type='to_color',
    documented=False,
    )

opt('color232', '#080808',
    option_type='to_color',
    documented=False,
    )

opt('color233', '#121212',
    option_type='to_color',
    documented=False,
    )

opt('color234', '#1c1c1c',
    option_type='to_color',
    documented=False,
    )

opt('color235', '#262626',
    option_type='to_color',
    documented=False,
    )

opt('color236', '#303030',
    option_type='to_color',
    documented=False,
    )

opt('color237', '#3a3a3a',
    option_type='to_color',
    documented=False,
    )

opt('color238', '#444444',
    option_type='to_color',
    documented=False,
    )

opt('color239', '#4e4e4e',
    option_type='to_color',
    documented=False,
    )

opt('color240', '#585858',
    option_type='to_color',
    documented=False,
    )

opt('color241', '#626262',
    option_type='to_color',
    documented=False,
    )

opt('color242', '#6c6c6c',
    option_type='to_color',
    documented=False,
    )

opt('color243', '#767676',
    option_type='to_color',
    documented=False,
    )

opt('color244', '#808080',
    option_type='to_color',
    documented=False,
    )

opt('color245', '#8a8a8a',
    option_type='to_color',
    documented=False,
    )

opt('color246', '#949494',
    option_type='to_color',
    documented=False,
    )

opt('color247', '#9e9e9e',
    option_type='to_color',
    documented=False,
    )

opt('color248', '#a8a8a8',
    option_type='to_color',
    documented=False,
    )

opt('color249', '#b2b2b2',
    option_type='to_color',
    documented=False,
    )

opt('color250', '#bcbcbc',
    option_type='to_color',
    documented=False,
    )

opt('color251', '#c6c6c6',
    option_type='to_color',
    documented=False,
    )

opt('color252', '#d0d0d0',
    option_type='to_color',
    documented=False,
    )

opt('color253', '#dadada',
    option_type='to_color',
    documented=False,
    )

opt('color254', '#e4e4e4',
    option_type='to_color',
    documented=False,
    )

opt('color255', '#eeeeee',
    option_type='to_color',
    documented=False,
    )
egr()  # }}}
egr()  # }}}

# advanced {{{
agr('advanced', 'Advanced')

opt('shell', '.',
    long_text='''
The shell program to execute. The default value of . means to use whatever shell
is set as the default shell for the current user. Note that on macOS if you
change this, you might need to add :code:`--login` and :code:`--interactive`
to ensure that the shell starts in interactive mode and reads its startup rc files.
'''
    )

opt('editor', '.',
    long_text='''
The terminal editor (such as ``vim`` or ``nano``) to use when editing the kitty
config file or similar tasks.

The default value of :code:`.` means to use the environment variables :envvar:`VISUAL`
and :envvar:`EDITOR` in that order. If these variables aren't set, kitty will
run your :opt:`shell` (``$SHELL -l -i -c env``) to see if your shell config
files set :envvar:`VISUAL` or :envvar:`EDITOR`. If that doesn't work, kitty
will cycle through various known editors (``vim``, ``emacs``, etc) and take the
first one that exists on your system.
''')

opt('close_on_child_death', 'no',
    option_type='to_bool', ctype='bool',
    long_text='''
Close the window when the child process (shell) exits. If no (the default), the
terminal will remain open when the child exits as long as there are still
processes outputting to the terminal (for example disowned or backgrounded
processes). If yes, the window will close as soon as the child process exits.
Note that setting it to yes means that any background processes still using the
terminal can fail silently because their stdout/stderr/stdin no longer work.
'''
    )

opt('allow_remote_control', 'no',
    option_type='allow_remote_control',
    long_text='''
Allow other programs to control kitty. If you turn this on other programs can
control all aspects of kitty, including sending text to kitty windows, opening
new windows, closing windows, reading the content of windows, etc.  Note that
this even works over ssh connections. You can chose to either allow any program
running within kitty to control it, with :code:`yes` or only programs that
connect to the socket specified with the :option:`kitty --listen-on` command
line option, if you use the value :code:`socket-only`. The latter is useful if
you want to prevent programs running on a remote computer over ssh from
controlling kitty. Reloading the config will not affect this setting.
'''
    )

opt('listen_on', 'none',
    long_text='''
Tell kitty to listen to the specified unix/tcp socket for remote control
connections. Note that this will apply to all kitty instances. It can be
overridden by the :option:`kitty --listen-on` command line flag. This option
accepts only UNIX sockets, such as unix:${TEMP}/mykitty or (on Linux)
unix:@mykitty. Environment variables are expanded. If {kitty_pid} is present
then it is replaced by the PID of the kitty process, otherwise the PID of the
kitty process is appended to the value, with a hyphen. This option is ignored
unless you also set :opt:`allow_remote_control` to enable remote control. See
the help for :option:`kitty --listen-on` for more details. Changing this option
by reloading the config is not supported.
'''
    )

opt('+env', '',
    option_type='env',
    add_to_default=False,
    long_text='''
Specify environment variables to set in all child processes. Note that
environment variables are expanded recursively, so if you use::

    env MYVAR1=a
    env MYVAR2=${MYVAR1}/${HOME}/b

The value of MYVAR2 will be :code:`a/<path to home directory>/b`. Using
:code:`VAR=` will set it to the empty string and using just :code:`VAR`
will delete the variable from the child process' environment.
'''
    )

opt('+watcher', '',
    option_type='store_multiple',
    add_to_default=False,
    long_text='''
Path to python file which will be loaded for :ref:`watchers`.
Can be specified more than once to load multiple watchers.
The watchers will be added to every kitty window. Relative
paths are resolved relative to the kitty config directory.
Note that reloading the config will only affect windows
created after the reload.
''')

opt('+exe_search_path', '',
    option_type='store_multiple',
    add_to_default=False,
    long_text='''
Control where kitty looks to find programs to run. The default search order is:
First search the system wide :code:`PATH`, then :file:`~/.local/bin` and :file:`~/bin`.
If not still not found, the :code:`PATH` defined in the login shell after sourcing
all its startup files is tried. Finally, if present, the :code:`PATH` in the :opt:`env`
option is tried.

This option allows you to prepend, append, or remove paths from this search order.
It can be specified multiple times for multiple paths. A simple path will be prepended
to the search order. A path that starts with the :code:`+` sign will be append to the search
order, after :file:`~/bin` above. A path that starts with the :code:`-` sign will be removed
from the entire search order. For example::

    exe_search_path /some/prepended/path
    exe_search_path +/some/appended/path
    exe_search_path -/some/excluded/path

''')

opt('update_check_interval', '24',
    option_type='float',
    long_text='''
Periodically check if an update to kitty is available. If an update is found a
system notification is displayed informing you of the available update. The
default is to check every 24 hrs, set to zero to disable. Changing this option
by reloading the config is not supported.
'''
    )

opt('startup_session', 'none',
    option_type='config_or_absolute_path',
    long_text='''
Path to a session file to use for all kitty instances. Can be overridden by
using the :option:`kitty --session` command line option for individual
instances. See :ref:`sessions` in the kitty documentation for details. Note that
relative paths are interpreted with respect to the kitty config directory.
Environment variables in the path are expanded. Changing this option by reloading
the config is not supported.
'''
    )

opt('clipboard_control', 'write-clipboard write-primary read-clipboard-ask read-primary-ask',
    option_type='clipboard_control',
    long_text='''
Allow programs running in kitty to read and write from the clipboard. You can
control exactly which actions are allowed. The set of possible actions is:
:code:`write-clipboard read-clipboard write-primary read-primary read-clipboard-ask read-primary-ask`.
The default is to allow writing to the clipboard and primary selection and to
ask for permission when a program tries to read from the clipboard. Note that
disabling the read confirmation is a security risk as it means that any
program, even one running on a remote server via SSH can read your clipboard.
See also :opt:`clipboard_max_size`.
'''
    )

opt('clipboard_max_size', 64, option_type='positive_float', long_text='''
The maximum size (in MB) of data from programs running in kitty that will be
stored for writing to the system clipboard. See also :opt:`clipboard_control`.
A value of zero means no size limit is applied.
''')

opt('file_transfer_confirmation_bypass', '', long_text='''
A password, that can be supplied to the file transfer kitten to skip the
transfer confirmation prompt. This should only be used when initiating
transfers from trusted computers, over trusted networks or encrypted
transports, as it allows programs running on the remote machine to read/write
to the local filesystem, without permission.
''')

opt('allow_hyperlinks', 'yes',
    option_type='allow_hyperlinks', ctype='bool',
    long_text='''
Process hyperlink (OSC 8) escape sequences. If disabled OSC 8 escape sequences
are ignored. Otherwise they become clickable links, that you can click by
with the mouse or the :doc:`hints kitten </kittens/hints>`. The special value of
``ask`` means that kitty will ask before opening the link when clicked.
'''
    )

opt('shell_integration', 'enabled', option_type='shell_integration',
    long_text='''
Enable shell integration on supported shells. This enables features such as
jumping to previous prompts, browsing the output of the previous command in a
pager, etc. on supported shells.  Set to ``disabled`` to turn off shell
integration, completely. See :ref:`shell_integration` for details.
''')

opt('term', 'xterm-kitty',
    long_text='''
The value of the TERM environment variable to set. Changing this can break many
terminal programs, only change it if you know what you are doing, not because
you read some advice on Stack Overflow to change it. The TERM variable is used
by various programs to get information about the capabilities and behavior of
the terminal. If you change it, depending on what programs you run, and how
different the terminal you are changing it to is, various things from key-presses,
to colors, to various advanced features may not work. Changing this option by reloading
the config will only affect newly created windows.
'''
    )
egr()  # }}}

# os {{{
agr('os', 'OS specific tweaks')

opt('wayland_titlebar_color', 'system',
    option_type='titlebar_color',
    long_text='''
Change the color of the kitty window's titlebar on Wayland systems with client
side window decorations such as GNOME. A value of :code:`system` means to use
the default system color, a value of :code:`background` means to use the
background color of the currently active window and finally you can use an
arbitrary color, such as :code:`#12af59` or :code:`red`.
'''
    )

opt('macos_titlebar_color', 'system',
    option_type='macos_titlebar_color',
    long_text='''
Change the color of the kitty window's titlebar on macOS. A value of
:code:`system` means to use the default system color, :code:`light` or
:code:`dark` can also be used to set it explicitly. A value of
:code:`background` means to use the background color of the currently active
window and finally you can use an arbitrary color, such as :code:`#12af59` or
:code:`red`. WARNING: This option works by using a hack, as there is no proper
Cocoa API for it. It sets the background color of the entire window and makes
the titlebar transparent. As such it is incompatible with
:opt:`background_opacity`. If you want to use both, you are probably better off
just hiding the titlebar with :opt:`hide_window_decorations`.
'''
    )

opt('macos_option_as_alt', 'no',
    option_type='macos_option_as_alt', ctype='uint',
    long_text='''
Use the option key as an alt key. With this set to :code:`no`, kitty will use
the macOS native :kbd:`Option+Key` = unicode character behavior. This will break
any :kbd:`Alt+key` keyboard shortcuts in your terminal programs, but you can use
the macOS unicode input technique. You can use the values: :code:`left`,
:code:`right`, or :code:`both` to use only the left, right or both Option keys
as Alt, instead. Changing this setting by reloading the config is not supported.
'''
    )

opt('macos_hide_from_tasks', 'no',
    option_type='to_bool', ctype='bool',
    long_text='Hide the kitty window from running tasks (:kbd:`⌘+Tab`) on macOS.'
    ' Changing this setting by reloading the config is not supported.'
    )

opt('macos_quit_when_last_window_closed', 'no',
    option_type='to_bool', ctype='bool',
    long_text='''
Have kitty quit when all the top-level windows are closed. By default, kitty
will stay running, even with no open windows, as is the expected behavior on
macOS.
'''
    )

opt('macos_window_resizable', 'yes',
    option_type='to_bool', ctype='bool',
    long_text='''
Disable this if you want kitty top-level (OS) windows to not be resizable on
macOS. Changing this setting by reloading the config will only affect newly
created windows.
'''
    )

opt('macos_thicken_font', '0',
    option_type='positive_float', ctype='float',
    long_text='''
Draw an extra border around the font with the given width, to increase
legibility at small font sizes. For example, a value of 0.75 will result in
rendering that looks similar to sub-pixel antialiasing at common font sizes.
'''
    )

opt('macos_traditional_fullscreen', 'no',
    option_type='to_bool', ctype='bool',
    long_text='Use the traditional full-screen transition, that is faster, but less pretty.'
    )

opt('macos_show_window_title_in', 'all',
    choices=('all', 'menubar', 'none', 'window'), ctype='window_title_in',
    long_text='''
Show or hide the window title in the macOS window or menu-bar. A value of
:code:`window` will show the title of the currently active window at the top of
the macOS window. A value of :code:`menubar` will show the title of the
currently active window in the macOS menu-bar, making use of otherwise wasted
space. :code:`all` will show the title everywhere and :code:`none` hides the
title in the window and the menu-bar.
'''
    )

opt('macos_custom_beam_cursor', 'no',
    option_type='to_bool',
    long_text='''
Enable/disable custom mouse cursor for macOS that is easier to see on both light
and dark backgrounds. WARNING: this might make your mouse cursor invisible on
dual GPU machines. Changing this setting by reloading the config is not supported.
'''
    )

opt('linux_display_server', 'auto',
    choices=('auto', 'wayland', 'x11'),
    long_text='''
Choose between Wayland and X11 backends. By default, an appropriate backend
based on the system state is chosen automatically. Set it to :code:`x11` or
:code:`wayland` to force the choice. Changing this setting by reloading the
config is not supported.
'''
    )
egr()  # }}}

# shortcuts {{{
agr('shortcuts', 'Keyboard shortcuts', '''
Keys are identified simply by their lowercase unicode characters. For example:
``a`` for the A key, ``[`` for the left square bracket key, etc. For functional
keys, such as ``Enter or Escape`` the names are present at :ref:`functional`.
For a list of modifier names, see:
:link:`GLFW mods <https://www.glfw.org/docs/latest/group__mods.html>`

On Linux you can also use XKB key names to bind keys that are not supported by
GLFW. See :link:`XKB keys
<https://github.com/xkbcommon/libxkbcommon/blob/master/include/xkbcommon/xkbcommon-keysyms.h>`
for a list of key names. The name to use is the part after the :code:`XKB_KEY_`
prefix. Note that you can only use an XKB key name for keys that are not known
as GLFW keys.

Finally, you can use raw system key codes to map keys, again only for keys that are not
known as GLFW keys. To see the system key code
for a key, start kitty with the :option:`kitty --debug-input` option. Then kitty will
output some debug text for every key event. In that text look for ``native_code``
the value of that becomes the key name in the shortcut. For example:

.. code-block:: none

    on_key_input: glfw key: 65 native_code: 0x61 action: PRESS mods: 0x0 text: 'a'

Here, the key name for the :kbd:`A` key is :kbd:`0x61` and you can use it with::

    map ctrl+0x61 something

to map :kbd:`ctrl+a` to something.

You can use the special action :code:`no_op` to unmap a keyboard shortcut that is
assigned in the default configuration::

    map kitty_mod+space no_op

If you would like kitty to completely ignore a key event, not even sending it to
the program running in the terminal, map it to :code:`discard_event`::

    map kitty_mod+f1 discard_event

You can combine multiple actions to be triggered by a single shortcut, using the
syntax below::

    map key combine <separator> action1 <separator> action2 <separator> action3 ...

For example::

    map kitty_mod+e combine : new_window : next_layout

this will create a new window and switch to the next available layout

You can use multi-key shortcuts using the syntax shown below::

    map key1>key2>key3 action

For example::

    map ctrl+f>2 set_font_size 20

The full list of actions that can be mapped to key presses is available
:doc:`here </actions>`.
''')

opt('kitty_mod', 'ctrl+shift',
    option_type='to_modifiers',
    long_text='''
The value of :code:`kitty_mod` is used as the modifier for all default
shortcuts, you can change it in your kitty.conf to change the modifiers for all
the default shortcuts.
'''
    )

opt('clear_all_shortcuts', 'no',
    option_type='clear_all_shortcuts',
    long_text='''
You can have kitty remove all shortcut definition seen up to this point. Useful,
for instance, to remove the default shortcuts.
'''
    )

opt('+action_alias', 'launch_tab launch --type=tab --cwd=current',
    option_type='action_alias',
    add_to_default=False,
    long_text='''
Define aliases to avoid repeating the same options in multiple mappings. Aliases
can be defined for any action. Aliases are expanded recursively.
For example, the above alias allows you to create mappings to launch a new tab
in the current working directory without duplication::

    map f1 launch_tab vim
    map f2 launch_tab emacs

Similarly, to alias kitten invocation::

    action_alias hints kitten hints --hints-offset=0
''')

opt('+kitten_alias', 'hints hints --hints-offset=0',
    option_type='kitten_alias',
    add_to_default=False,
    long_text='''
Like :opt:`action_alias` above but, specifically for kittens. Generally,
prefer to use :opt:`action_alias`. This option is a legacy
version, present for backwards compatibility. It causes all invocations
of the aliased kitten to be substituted. So the example above will cause
all invocations of the hints kitten to have the :code:`--hints-offset=0`
option applied.
'''
    )


# shortcuts.clipboard {{{
agr('shortcuts.clipboard', 'Clipboard')

map('Copy to clipboard',
    'copy_to_clipboard kitty_mod+c copy_to_clipboard',
    long_text='''
There is also a :code:`copy_or_interrupt` action that can be optionally mapped
to :kbd:`Ctrl+c`. It will copy only if there is a selection and send an
interrupt otherwise. Similarly, :code:`copy_and_clear_or_interrupt` will copy
and clear the selection or send an interrupt if there is no selection.
'''
    )
map('Copy to clipboard',
    'copy_to_clipboard cmd+c copy_to_clipboard',
    only='macos',
    documented=False,
    )

map('Paste from clipboard',
    'paste_from_clipboard kitty_mod+v paste_from_clipboard',
    )
map('Paste from clipboard',
    'paste_from_clipboard cmd+v paste_from_clipboard',
    only='macos',
    documented=False,
    )

map('Paste from selection',
    'paste_from_selection kitty_mod+s paste_from_selection',
    )
map('Paste from selection',
    'paste_from_selection shift+insert paste_from_selection',
    )

map('Pass selection to program',
    'pass_selection_to_program kitty_mod+o pass_selection_to_program',
    long_text='''
You can also pass the contents of the current selection to any program using
:code:`pass_selection_to_program`. By default, the system's open program is used, but
you can specify your own, the selection will be passed as a command line argument to the program,
for example::

    map kitty_mod+o pass_selection_to_program firefox

You can pass the current selection to a terminal program running in a new kitty
window, by using the @selection placeholder::

    map kitty_mod+y new_window less @selection
'''
    )
egr()  # }}}


# shortcuts.scrolling {{{
agr('shortcuts.scrolling', 'Scrolling')

map('Scroll line up',
    'scroll_line_up kitty_mod+up scroll_line_up',
    )
map('Scroll line up',
    'scroll_line_up kitty_mod+k scroll_line_up',
    )
map('Scroll line up',
    'scroll_line_up opt+cmd+page_up scroll_line_up',
    only='macos',
    )
map('Scroll line up',
    'scroll_line_up cmd+up scroll_line_up',
    only='macos',
    )

map('Scroll line down',
    'scroll_line_down kitty_mod+down scroll_line_down',
    )
map('Scroll line down',
    'scroll_line_down kitty_mod+j scroll_line_down',
    )
map('Scroll line down',
    'scroll_line_down opt+cmd+page_down scroll_line_down',
    only='macos',
    )
map('Scroll line down',
    'scroll_line_down cmd+down scroll_line_down',
    only='macos',
    )

map('Scroll page up',
    'scroll_page_up kitty_mod+page_up scroll_page_up',
    )
map('Scroll page up',
    'scroll_page_up cmd+page_up scroll_page_up',
    only='macos',
    )

map('Scroll page down',
    'scroll_page_down kitty_mod+page_down scroll_page_down',
    )
map('Scroll page down',
    'scroll_page_down cmd+page_down scroll_page_down',
    only='macos',
    )

map('Scroll to top',
    'scroll_home kitty_mod+home scroll_home',
    )
map('Scroll to top',
    'scroll_home cmd+home scroll_home',
    only='macos',
    )

map('Scroll to bottom',
    'scroll_end kitty_mod+end scroll_end',
    )
map('Scroll to bottom',
    'scroll_end cmd+end scroll_end',
    only='macos',
    )

map('Scroll to previous shell prompt',
    'scroll_to_previous_prompt kitty_mod+z scroll_to_prompt -1',
    long_text='''
Use a parameter of zero for :code:`scroll_to_prompt` to scroll to the last jumped
to or the last clicked position. Requires :ref:`shell_integration` to work.
'''
    )

map('Scroll to next shell prompt', 'scroll_to_next_prompt kitty_mod+x scroll_to_prompt 1')

map('Browse scrollback buffer in pager',
    'show_scrollback kitty_mod+h show_scrollback',
    long_text='''
You can pipe the contents of the current screen + history buffer as
:file:`STDIN` to an arbitrary program using the ``launch`` function. For example,
the following opens the scrollback buffer in less in an overlay window::

    map f1 launch --stdin-source=@screen_scrollback --stdin-add-formatting --type=overlay less +G -R

For more details on piping screen and buffer contents to external programs,
see :doc:`launch`.
'''
    )

map('Browse output of the last shell command in pager',
    'show_last_command_output kitty_mod+g show_last_command_output',
    long_text='''
You can also define additional shortcuts to get the command output.
For example, to get the first command output on screen::

    map f1 show_first_command_output_on_screen

To get the command output that was last accessed by a keyboard action or mouse action::

    map f1 show_last_visited_command_output

You can pipe the output of the last command run in the shell using the :doc:`launch` function.
For example, the following opens the output in less in an overlay window::

    map f1 launch --stdin-source=@last_cmd_output --stdin-add-formatting --type=overlay less +G -R

To get the output of the first command on the screen, use :code:`@first_cmd_output_on_screen`.
To get the output of the last jumped to command, use :code:`@last_visited_cmd_output`.

Requires :ref:`shell_integration` to work.
''')
egr()  # }}}


# shortcuts.window {{{
agr('shortcuts.window', 'Window management')

map('New window',
    'new_window kitty_mod+enter new_window',
    long_text='''
You can open a new window running an arbitrary program, for example::

    map kitty_mod+y      launch mutt

You can open a new window with the current working directory set to the
working directory of the current window using::

    map ctrl+alt+enter    launch --cwd=current

You can open a new window that is allowed to control kitty via
the kitty remote control facility by prefixing the command line with @.
Any programs running in that window will be allowed to control kitty.
For example::

    map ctrl+enter launch --allow-remote-control some_program

You can open a new window next to the currently active window or as the first window,
with::

    map ctrl+n launch --location=neighbor some_program
    map ctrl+f launch --location=first some_program

For more details, see :doc:`launch`.
'''
    )
map('New window',
    'new_window cmd+enter new_window',
    only='macos',
    )

map('New OS window',
    'new_os_window kitty_mod+n new_os_window',
    long_text='''
Works like new_window above, except that it opens a top level OS kitty window.
In particular you can use new_os_window_with_cwd to open a window with the
current working directory.
'''
    )
map('New OS window',
    'new_os_window cmd+n new_os_window',
    only='macos',
    )

map('Close window',
    'close_window kitty_mod+w close_window',
    )
map('Close window',
    'close_window shift+cmd+d close_window',
    only='macos',
    )

map('Next window',
    'next_window kitty_mod+] next_window',
    )

map('Previous window',
    'previous_window kitty_mod+[ previous_window',
    )

map('Move window forward',
    'move_window_forward kitty_mod+f move_window_forward',
    )

map('Move window backward',
    'move_window_backward kitty_mod+b move_window_backward',
    )

map('Move window to top',
    'move_window_to_top kitty_mod+` move_window_to_top',
    )

map('Start resizing window',
    'start_resizing_window kitty_mod+r start_resizing_window',
    )
map('Start resizing window',
    'start_resizing_window cmd+r start_resizing_window',
    only='macos',
    )

map('First window',
    'first_window kitty_mod+1 first_window',
    )
map('First window',
    'first_window cmd+1 first_window',
    only='macos',
    )

map('Second window',
    'second_window kitty_mod+2 second_window',
    )
map('Second window',
    'second_window cmd+2 second_window',
    only='macos',
    )

map('Third window',
    'third_window kitty_mod+3 third_window',
    )
map('Third window',
    'third_window cmd+3 third_window',
    only='macos',
    )

map('Fourth window',
    'fourth_window kitty_mod+4 fourth_window',
    )
map('Fourth window',
    'fourth_window cmd+4 fourth_window',
    only='macos',
    )

map('Fifth window',
    'fifth_window kitty_mod+5 fifth_window',
    )
map('Fifth window',
    'fifth_window cmd+5 fifth_window',
    only='macos',
    )

map('Sixth window',
    'sixth_window kitty_mod+6 sixth_window',
    )
map('Sixth window',
    'sixth_window cmd+6 sixth_window',
    only='macos',
    )

map('Seventh window',
    'seventh_window kitty_mod+7 seventh_window',
    )
map('Seventh window',
    'seventh_window cmd+7 seventh_window',
    only='macos',
    )

map('Eight window',
    'eighth_window kitty_mod+8 eighth_window',
    )
map('Eight window',
    'eighth_window cmd+8 eighth_window',
    only='macos',
    )

map('Ninth window',
    'ninth_window kitty_mod+9 ninth_window',
    )
map('Ninth window',
    'ninth_window cmd+9 ninth_window',
    only='macos',
    )

map('Tenth window',
    'tenth_window kitty_mod+0 tenth_window',
    )

map('Visually select focus window', 'focus_visible_window kitty_mod+f7 focus_visible_window')
map('Visually swap window with another', 'swap_with_window kitty_mod+f8 swap_with_window')
egr()  # }}}


# shortcuts.tab {{{
agr('shortcuts.tab', 'Tab management')

map('Next tab',
    'next_tab kitty_mod+right next_tab',
    )
map('Next tab',
    'next_tab shift+cmd+] next_tab',
    only='macos',
    )
map('Next tab',
    'next_tab ctrl+tab next_tab',
    )

map('Previous tab',
    'previous_tab kitty_mod+left previous_tab',
    )
map('Previous tab',
    'previous_tab shift+cmd+[ previous_tab',
    only='macos',
    )
map('Previous tab',
    'previous_tab ctrl+shift+tab previous_tab',
    )

map('New tab',
    'new_tab kitty_mod+t new_tab',
    )
map('New tab',
    'new_tab cmd+t new_tab',
    only='macos',
    )

map('Close tab',
    'close_tab kitty_mod+q close_tab',
    )
map('Close tab',
    'close_tab cmd+w close_tab',
    only='macos',
    )

map('Close OS window',
    'close_os_window shift+cmd+w close_os_window',
    only='macos',
    )

map('Move tab forward',
    'move_tab_forward kitty_mod+. move_tab_forward',
    )

map('Move tab backward',
    'move_tab_backward kitty_mod+, move_tab_backward',
    )

map('Set tab title',
    'set_tab_title kitty_mod+alt+t set_tab_title',
    )
map('Set tab title',
    'set_tab_title shift+cmd+i set_tab_title',
    only='macos',
    )
egr('''
You can also create shortcuts to go to specific tabs, with 1 being the first
tab, 2 the second tab and -1 being the previously active tab, and any number
larger than the last tab being the last tab::

    map ctrl+alt+1 goto_tab 1
    map ctrl+alt+2 goto_tab 2

Just as with :code:`new_window` above, you can also pass the name of arbitrary
commands to run when using new_tab and use :code:`new_tab_with_cwd`. Finally,
if you want the new tab to open next to the current tab rather than at the
end of the tabs list, use::

    map ctrl+t new_tab !neighbor [optional cmd to run]
''')  # }}}


# shortcuts.layout {{{
agr('shortcuts.layout', 'Layout management')

map('Next layout',
    'next_layout kitty_mod+l next_layout',
    )
egr('''
You can also create shortcuts to switch to specific layouts::

    map ctrl+alt+t goto_layout tall
    map ctrl+alt+s goto_layout stack

Similarly, to switch back to the previous layout::

   map ctrl+alt+p last_used_layout

There is also a toggle layout function that switches
to the named layout or back to the previous layout if
in the named layout. Useful to temporarily "zoom" the
active window by switching to the stack layout::

    map ctrl+alt+z toggle_layout stack
''')  # }}}


# shortcuts.fonts {{{
agr('shortcuts.fonts', 'Font sizes', '''
You can change the font size for all top-level kitty OS windows at a time or
only the current one.
''')

map('Increase font size',
    'increase_font_size kitty_mod+equal change_font_size all +2.0',
    )
map('Increase font size',
    'increase_font_size kitty_mod+plus change_font_size all +2.0',
    )
map('Increase font size',
    'increase_font_size kitty_mod+kp_add change_font_size all +2.0',
    )
map('Increase font size',
    'increase_font_size cmd+plus change_font_size all +2.0',
    only='macos',
    )
map('Increase font size',
    'increase_font_size cmd+equal change_font_size all +2.0',
    only='macos',
    )
map('Increase font size',
    'increase_font_size shift+cmd+equal change_font_size all +2.0',
    only='macos',
    )

map('Decrease font size',
    'decrease_font_size kitty_mod+minus change_font_size all -2.0',
    )
map('Decrease font size',
    'decrease_font_size kitty_mod+kp_subtract change_font_size all -2.0',
    )
map('Decrease font size',
    'decrease_font_size cmd+minus change_font_size all -2.0',
    only='macos',
    )
map('Decrease font size',
    'decrease_font_size shift+cmd+minus change_font_size all -2.0',
    only='macos',
    )

map('Reset font size',
    'reset_font_size kitty_mod+backspace change_font_size all 0',
    )
map('Reset font size',
    'reset_font_size cmd+0 change_font_size all 0',
    only='macos',
    )
egr('''
To setup shortcuts for specific font sizes::

    map kitty_mod+f6 change_font_size all 10.0

To setup shortcuts to change only the current OS window's font size::

    map kitty_mod+f6 change_font_size current 10.0
''')  # }}}


# shortcuts.selection {{{
agr('shortcuts.selection', 'Select and act on visible text', '''
Use the hints kitten to select text and either pass it to an external program or
insert it into the terminal or copy it to the clipboard.
''')

map('Open URL',
    'open_url kitty_mod+e open_url_with_hints',
    long_text='''
Open a currently visible URL using the keyboard. The program used to open the
URL is specified in :opt:`open_url_with`.
'''
    )

map('Insert selected path',
    'insert_selected_path kitty_mod+p>f kitten hints --type path --program -',
    long_text='''
Select a path/filename and insert it into the terminal. Useful, for instance to
run git commands on a filename output from a previous git command.
'''
    )

map('Open selected path',
    'open_selected_path kitty_mod+p>shift+f kitten hints --type path',
    long_text='Select a path/filename and open it with the default open program.'
    )

map('Insert selected line',
    'insert_selected_line kitty_mod+p>l kitten hints --type line --program -',
    long_text='''
Select a line of text and insert it into the terminal. Use for the output of
things like: ls -1
'''
    )

map('Insert selected word',
    'insert_selected_word kitty_mod+p>w kitten hints --type word --program -',
    long_text='Select words and insert into terminal.'
    )

map('Insert selected hash',
    'insert_selected_hash kitty_mod+p>h kitten hints --type hash --program -',
    long_text='''
Select something that looks like a hash and insert it into the terminal. Useful
with git, which uses sha1 hashes to identify commits
'''
    )

map('Open the selected file at the selected line',
    'goto_file_line kitty_mod+p>n kitten hints --type linenum',
    long_text='''
Select something that looks like :code:`filename:linenum` and open it in vim at
the specified line number.
'''
    )

map('Open the selected hyperlink',
    'open_selected_hyperlink kitty_mod+p>y kitten hints --type hyperlink',
    long_text='''
Select a hyperlink (i.e. a URL that has been marked as such by the terminal
program, for example, by :code:`ls --hyperlink=auto`).
'''
    )
egr('''
The hints kitten has many more modes of operation that you can map to different
shortcuts. For a full description see :doc:`kittens/hints`.
''')  # }}}


# shortcuts.misc {{{
agr('shortcuts.misc', 'Miscellaneous')

map('Toggle fullscreen',
    'toggle_fullscreen kitty_mod+f11 toggle_fullscreen',
    )

map('Toggle maximized',
    'toggle_maximized kitty_mod+f10 toggle_maximized',
    )

map('Toggle macOS secure keyboard entry',
    'toggle_macos_secure_keyboard_entry opt+cmd+s toggle_macos_secure_keyboard_entry',
    only='macos',
    )

map('Unicode input',
    'input_unicode_character kitty_mod+u kitten unicode_input',
    )
map('Unicode input',
    'input_unicode_character ctrl+cmd+space kitten unicode_input',
    only='macos',
    )

map('Edit config file',
    'edit_config_file kitty_mod+f2 edit_config_file',
    )
map('Edit config file',
    'edit_config_file cmd+, edit_config_file',
    only='macos',
    )

map('Open the kitty command shell',
    'kitty_shell kitty_mod+escape kitty_shell window',
    long_text='''
Open the kitty shell in a new window/tab/overlay/os_window to control kitty
using commands.
'''
    )

map('Increase background opacity',
    'increase_background_opacity kitty_mod+a>m set_background_opacity +0.1',
    )

map('Decrease background opacity',
    'decrease_background_opacity kitty_mod+a>l set_background_opacity -0.1',
    )

map('Make background fully opaque',
    'full_background_opacity kitty_mod+a>1 set_background_opacity 1',
    )

map('Reset background opacity',
    'reset_background_opacity kitty_mod+a>d set_background_opacity default',
    )

map('Reset the terminal',
    'reset_terminal kitty_mod+delete clear_terminal reset active',
    long_text='''
You can create shortcuts to clear/reset the terminal. For example::

    # Reset the terminal
    map kitty_mod+f9 clear_terminal reset active
    # Clear the terminal screen by erasing all contents
    map kitty_mod+f10 clear_terminal clear active
    # Clear the terminal scrollback by erasing it
    map kitty_mod+f11 clear_terminal scrollback active
    # Scroll the contents of the screen into the scrollback
    map kitty_mod+f12 clear_terminal scroll active

If you want to operate on all windows instead of just the current one, use
:italic:`all` instead of :italic:`active`.

It is also possible to remap Ctrl+L to both scroll the current screen contents
into the scrollback buffer and clear the screen, instead of just clearing the
screen, for example, for ZSH add the following to :file:`~/.zshrc`:

.. code-block:: sh

    scroll-and-clear-screen() {
        printf '\\n%.0s' {1..$LINES}
        zle clear-screen
    }
    zle -N scroll-and-clear-screen
    bindkey '^l' scroll-and-clear-screen

'''
    )

map('Reset the terminal',
    'reset_terminal opt+cmd+r clear_terminal reset active',
    only='macos',
    )

map('Reload kitty.conf',
    'reload_config_file kitty_mod+f5 load_config_file',
    long_text='''
Reload kitty.conf, applying any changes since the last time it was loaded.
Note that a handful of settings cannot be dynamically changed and require a
full restart of kitty.  You can also map a keybinding to load a different
config file, for example::

    map f5 load_config /path/to/alternative/kitty.conf

Note that all setting from the original kitty.conf are discarded, in other words
the new conf settings *replace* the old ones.
'''
    )

map('Reload kitty.conf',
    'reload_config_file ctrl+cmd+, load_config_file',
    only='macos'
    )

map('Debug kitty configuration',
    'debug_config kitty_mod+f6 debug_config',
    long_text='''
Show details about exactly what configuration kitty is running with and
its host environment. Useful for debugging issues.
'''
    )

map('Debug kitty configuration',
    'debug_config opt+cmd+, debug_config',
    only='macos'
    )


map('Send arbitrary text on key presses',
    'send_text ctrl+shift+alt+h send_text all Hello World',
    add_to_default=False,
    long_text='''
You can tell kitty to send arbitrary (UTF-8) encoded text to
the client program when pressing specified shortcut keys. For example::

    map ctrl+alt+a send_text all Special text

This will send "Special text" when you press the :kbd:`ctrl+alt+a` key
combination.  The text to be sent is a python string literal so you can use
escapes like :code:`\\x1b` to send control codes or :code:`\\u21fb` to send
unicode characters (or you can just input the unicode characters directly as
UTF-8 text). The first argument to :code:`send_text` is the keyboard modes in which to
activate the shortcut. The possible values are :code:`normal` or :code:`application` or :code:`kitty`
or a comma separated combination of them.  The special keyword :code:`all` means all
modes. The modes :code:`normal` and :code:`application` refer to the DECCKM cursor key mode for
terminals, and :code:`kitty` refers to the special kitty extended keyboard protocol.

Another example, that outputs a word and then moves the cursor to the start of
the line (same as pressing the Home key)::

    map ctrl+alt+a send_text normal Word\\x1b[H
    map ctrl+alt+a send_text application Word\\x1bOH
'''
    )
egr()  # }}}
egr()  # }}}
