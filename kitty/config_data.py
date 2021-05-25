#!/usr/bin/env python3
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2018, Kovid Goyal <kovid at kovidgoyal.net>

# Utils  {{{
from gettext import gettext as _
from typing import Dict

from . import fast_data_types as defines
from .conf.definition import OptionOrAction, option_func
from .conf.utils import (
    choices, positive_float, positive_int, to_cmdline, to_color,
    to_color_or_none, unit_float
)
from .constants import is_macos
from .options_types import (
    active_tab_title_template, adjust_line_height, allow_hyperlinks,
    allow_remote_control, box_drawing_scale, clipboard_control,
    config_or_absolute_path, copy_on_select, cursor_text_color,
    default_tab_separator, disable_ligatures, edge_width, env, font_features,
    hide_window_decorations, macos_option_as_alt, macos_titlebar_color,
    optional_edge_width, resize_draw_strategy, scrollback_lines,
    scrollback_pager_history_size, symbol_map, tab_activity_symbol,
    tab_bar_edge, tab_bar_min_tabs, tab_fade, tab_font_style, tab_separator,
    tab_title_template, to_cursor_shape, to_font_size, to_layout_names,
    to_modifiers, url_prefixes, url_style, window_border_width, window_size
)
from .rgb import color_as_sharp, color_from_int

# }}}

# Groups {{{


all_options: Dict[str, OptionOrAction] = {}


o, k, m, g, all_groups = option_func(all_options, {
    'fonts': [
        _('Fonts'),
        _('kitty has very powerful font management. You can configure individual\n'
          'font faces and even specify special fonts for particular characters.')
    ],

    'cursor': [_('Cursor customization'), ],
    'scrollback': [_('Scrollback'), ],
    'mouse': [_('Mouse'), ],
    'performance': [_('Performance tuning')],
    'bell': [_('Terminal bell')],
    'window': [_('Window layout')],
    'tabbar': [_('Tab bar')],
    'colors': [_('Color scheme')],
    'colors.table': [
        _('The color table'),
        _('''\
The 256 terminal colors. There are 8 basic colors, each color has a dull and
bright version, for the first 16 colors. You can set the remaining 240 colors
as color16 to color255.''')
    ],
    'advanced': [_('Advanced')],
    'os': [_('OS specific tweaks')],
    'mouse.mousemap': [
        _('Mouse actions'),
        _('''\
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
performed when the mouse is grabbed by the terminal application or not. It can
have one or more or the values, ``grabbed,ungrabbed``. Note that the click
and double click events have a delay of :opt:`click_interval` to disambiguate
from double and triple presses.

You can run kitty with the :option:`kitty --debug-input` command line option
to see mouse events. See the builtin actions below to get a sense of what is possible.

If you want to unmap an action map it to ``no-op``.

.. note::
    Once a selection is started, releasing the button that started it will
    automatically end it and no release event will be dispatched.

'''),
    ],
    'shortcuts': [
        _('Keyboard shortcuts'),
        _('''\
Keys are identified simply by their lowercase unicode characters. For example:
``a`` for the A key, ``[`` for the left square bracket key, etc. For functional
keys, such as ``Enter or Escape`` the names are present at :ref:`functional`.
For a list of modifier names, see:
:link:`GLFW mods <https://www.glfw.org/docs/latest/group__mods.html>`

On Linux you can also use XKB key names to bind keys that are not supported by
GLFW. See :link:`XKB keys
<https://github.com/xkbcommon/libxkbcommon/blob/master/xkbcommon/xkbcommon-keysyms.h>`
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
''')
    ],
    'shortcuts.clipboard': [_('Clipboard')],
    'shortcuts.scrolling': [_('Scrolling')],
    'shortcuts.misc': [_('Miscellaneous')],
    'shortcuts.window': [_('Window management')],
    'shortcuts.tab': [
            _('Tab management'), '',
            _('''\
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

''')],
    'shortcuts.layout': [
            _('Layout management'), '',
            _('''\
You can also create shortcuts to switch to specific layouts::

    map ctrl+alt+t goto_layout tall
    map ctrl+alt+s goto_layout stack

Similarly, to switch back to the previous layout::

   map ctrl+alt+p last_used_layout

''')],
    'shortcuts.fonts': [
        _('Font sizes'), _('''\
You can change the font size for all top-level kitty OS windows at a time
or only the current one.
'''), _('''\
To setup shortcuts for specific font sizes::

    map kitty_mod+f6 change_font_size all 10.0

To setup shortcuts to change only the current OS window's font size::

    map kitty_mod+f6 change_font_size current 10.0
''')],
    'shortcuts.selection': [
            _('Select and act on visible text'), _('''\
Use the hints kitten to select text and either pass it to an external program or
insert it into the terminal or copy it to the clipboard.
'''), _('''
The hints kitten has many more modes of operation that you can map to different
shortcuts. For a full description see :doc:`kittens/hints`.''')],

})
# }}}

g('fonts')  # {{{

o(
    'font_family',
    'monospace',
    long_text=_('''
You can specify different fonts for the bold/italic/bold-italic variants.
To get a full list of supported fonts use the `kitty list-fonts` command.
By default they are derived automatically, by the OSes font system. Setting
them manually is useful for font families that have many weight variants like
Book, Medium, Thick, etc. For example::

    font_family      Operator Mono Book
    bold_font        Operator Mono Medium
    italic_font      Operator Mono Book Italic
    bold_italic_font Operator Mono Medium Italic
''')
)
o('bold_font', 'auto')
o('italic_font', 'auto')
o('bold_italic_font', 'auto')

o('font_size', 11.0, long_text=_('Font size (in pts)'), option_type=to_font_size)

o('force_ltr', False, long_text=_("""
kitty does not support BIDI (bidirectional text), however, for RTL scripts,
words are automatically displayed in RTL. That is
to say, in an RTL script, the words "HELLO WORLD" display in kitty as "WORLD
HELLO", and if you try to select a substring of an RTL-shaped string, you will
get the character that would be there had the the string been LTR. For example,
assuming the Hebrew word ירושלים, selecting the character that on the screen
appears to be ם actually writes into the selection buffer the character י.

kitty's default behavior is useful in conjunction with a filter to reverse the
word order, however, if you wish to manipulate RTL glyphs, it can be very
challenging to work with, so this option is provided to turn it off.
Furthermore, this option can be used with the command line program
:link:`GNU FriBidi <https://github.com/fribidi/fribidi#executable>` to get BIDI
support, because it will force kitty to always treat the text as LTR, which
FriBidi expects for terminals."""))


o('adjust_line_height', 0, option_type=adjust_line_height, long_text=_('''
Change the size of each character cell kitty renders. You can use either numbers,
which are interpreted as pixels or percentages (number followed by %), which
are interpreted as percentages of the unmodified values. You can use negative
pixels or percentages less than 100% to reduce sizes (but this might cause
rendering artifacts).'''))
o('adjust_column_width', 0, option_type=adjust_line_height)


o(
    '+symbol_map',
    'U+E0A0-U+E0A3,U+E0C0-U+E0C7 PowerlineSymbols',
    add_to_default=False, option_type=symbol_map,
    long_text=_('''
Map the specified unicode codepoints to a particular font. Useful if you need
special rendering for some symbols, such as for Powerline. Avoids the need for
patched fonts. Each unicode code point is specified in the form :code:`U+<code point
in hexadecimal>`. You can specify multiple code points, separated by commas and
ranges separated by hyphens. :code:`symbol_map` itself can be specified multiple times.
Syntax is::

    symbol_map codepoints Font Family Name

'''))


o('disable_ligatures', 'never', option_type=disable_ligatures, long_text=_('''
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
'''))

o('+font_features', 'none', add_to_default=False, option_type=font_features, long_text=_('''
Choose exactly which OpenType features to enable or disable. This is useful as
some fonts might have features worthwhile in a terminal. For example, Fira
Code Retina includes a discretionary feature, :code:`zero`, which in that font
changes the appearance of the zero (0), to make it more easily distinguishable
from Ø. Fira Code Retina also includes other discretionary features known as
Stylistic Sets which have the tags :code:`ss01` through :code:`ss20`.

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
'''))


o(
    'box_drawing_scale',
    '0.001, 1, 1.5, 2',
    option_type=box_drawing_scale,
    long_text=_('''
Change the sizes of the lines used for the box drawing unicode characters
These values are in pts. They will be scaled by the monitor DPI to arrive at
a pixel value. There must be four values corresponding to thin, normal, thick,
and very thick lines.
'''))

# }}}

g('cursor')  # {{{

o('cursor', '#cccccc', _('Default cursor color'), option_type=to_color)
o('cursor_text_color', '#111111', option_type=cursor_text_color, long_text=_('''
Choose the color of text under the cursor. If you want it rendered with the
background color of the cell underneath instead, use the special keyword: background'''))
o('cursor_shape', 'block', option_type=to_cursor_shape, long_text=_(
    'The cursor shape can be one of (block, beam, underline)'))
o('cursor_beam_thickness', 1.5, option_type=positive_float, long_text=_(
    'Defines the thickness of the beam cursor (in pts)'))
o('cursor_underline_thickness', 2.0, option_type=positive_float, long_text=_(
    'Defines the thickness of the underline cursor (in pts)'))
o('cursor_blink_interval', -1, option_type=float, long_text=_('''
The interval (in seconds) at which to blink the cursor. Set to zero to disable
blinking. Negative values mean use system default. Note that numbers smaller
than :opt:`repaint_delay` will be limited to :opt:`repaint_delay`.
'''))
o('cursor_stop_blinking_after', 15.0, option_type=positive_float, long_text=_('''
Stop blinking cursor after the specified number of seconds of keyboard
inactivity.  Set to zero to never stop blinking.
'''))

# }}}

g('scrollback')  # {{{


o('scrollback_lines', 2000, option_type=scrollback_lines, long_text=_('''
Number of lines of history to keep in memory for scrolling back. Memory is allocated
on demand. Negative numbers are (effectively) infinite scrollback. Note that using
very large scrollback is not recommended as it can slow down performance of the terminal
and also use large amounts of RAM. Instead, consider using :opt:`scrollback_pager_history_size`.'''))

o('scrollback_pager', 'less --chop-long-lines --RAW-CONTROL-CHARS +INPUT_LINE_NUMBER', option_type=to_cmdline, long_text=_('''
Program with which to view scrollback in a new window. The scrollback buffer is
passed as STDIN to this program. If you change it, make sure the program you
use can handle ANSI escape sequences for colors and text formatting.
INPUT_LINE_NUMBER in the command line above will be replaced by an integer
representing which line should be at the top of the screen. Similarly CURSOR_LINE and CURSOR_COLUMN
will be replaced by the current cursor position.'''))

o('scrollback_pager_history_size', 0, option_type=scrollback_pager_history_size, long_text=_('''
Separate scrollback history size, used only for browsing the scrollback buffer (in MB).
This separate buffer is not available for interactive scrolling but will be
piped to the pager program when viewing scrollback buffer in a separate window.
The current implementation stores the data in UTF-8, so approximatively
10000 lines per megabyte at 100 chars per line, for pure ASCII text, unformatted text.
A value of zero or less disables this feature. The maximum allowed size is 4GB.'''))

o('scrollback_fill_enlarged_window', False, long_text=_('''
Fill new space with lines from the scrollback buffer after enlarging a window.
'''))

o('wheel_scroll_multiplier', 5.0, long_text=_('''
Modify the amount scrolled by the mouse wheel. Note this is only used for low
precision scrolling devices, not for high precision scrolling on platforms such
as macOS and Wayland. Use negative numbers to change scroll direction.'''))

o('touch_scroll_multiplier', 1.0, long_text=_('''
Modify the amount scrolled by a touchpad. Note this is only used for high
precision scrolling devices on platforms such as macOS and Wayland.
Use negative numbers to change scroll direction.'''))

# }}}

g('mouse')  # {{{

o('mouse_hide_wait', 0.0 if is_macos else 3.0, option_type=float, long_text=_('''
Hide mouse cursor after the specified number of seconds
of the mouse not being used. Set to zero to disable mouse cursor hiding.
Set to a negative value to hide the mouse cursor immediately when typing text.
Disabled by default on macOS as getting it to work robustly with
the ever-changing sea of bugs that is Cocoa is too much effort.
'''))

o('url_color', '#0087bd', option_type=to_color, long_text=_('''
The color and style for highlighting URLs on mouse-over.
:code:`url_style` can be one of: none, single, double, curly'''))

o('url_style', 'curly', option_type=url_style)

o('open_url_with', 'default', option_type=to_cmdline, long_text=_('''
The program with which to open URLs that are clicked on.
The special value :code:`default` means to use the
operating system's default URL handler.'''))


o('url_prefixes', 'http https file ftp gemini irc gopher mailto news git', option_type=url_prefixes, long_text=_('''
The set of URL prefixes to look for when detecting a URL under the mouse cursor.'''))

o('detect_urls', True, long_text=_('''
Detect URLs under the mouse. Detected URLs are highlighted
with an underline and the mouse cursor becomes a hand over them.
Even if this option is disabled, URLs are still clickable.'''))


o('copy_on_select', 'no', option_type=copy_on_select, long_text=_('''
Copy to clipboard or a private buffer on select. With this set to
:code:`clipboard`, simply selecting text with the mouse will cause the text to
be copied to clipboard. Useful on platforms such as macOS that do not have the
concept of primary selections. You can instead specify a name such as :code:`a1` to
copy to a private kitty buffer instead. Map a shortcut with the
:code:`paste_from_buffer` action to paste from this private buffer.
For example::

    map cmd+shift+v paste_from_buffer a1

Note that copying to the clipboard is a security risk, as all programs,
including websites open in your browser can read the contents of the
system clipboard.'''))

o('strip_trailing_spaces', 'never', option_type=choices('never', 'smart', 'always'), long_text=_('''
Remove spaces at the end of lines when copying to clipboard.
A value of :code:`smart` will do it when using normal selections, but not rectangle
selections. :code:`always` will always do it.'''))

o('select_by_word_characters', '@-./_~?&=%+#', long_text=_('''
Characters considered part of a word when double clicking. In addition to these characters
any character that is marked as an alphanumeric character in the unicode
database will be matched.'''))

o('click_interval', -1.0, option_type=float, long_text=_('''
The interval between successive clicks to detect double/triple clicks (in seconds).
Negative numbers will use the system default instead, if available, or fallback to 0.5.'''))

o('focus_follows_mouse', False, long_text=_('''
Set the active window to the window under the mouse when
moving the mouse around'''))

o('pointer_shape_when_grabbed', 'arrow', option_type=choices('arrow', 'beam', 'hand'), long_text=('''
The shape of the mouse pointer when the program running in the terminal grabs the mouse.
Valid values are: :code:`arrow`, :code:`beam` and :code:`hand`
'''))

o('default_pointer_shape', 'beam', option_type=choices('arrow', 'beam', 'hand'), long_text=('''
The default shape of the mouse pointer.
Valid values are: :code:`arrow`, :code:`beam` and :code:`hand`
'''))

o('pointer_shape_when_dragging', 'beam', option_type=choices('arrow', 'beam', 'hand'), long_text=('''
The default shape of the mouse pointer when dragging across text.
Valid values are: :code:`arrow`, :code:`beam` and :code:`hand`
'''))

g('mouse.mousemap')  # {{{

m('click_url_or_select', 'left', 'click', 'ungrabbed', 'mouse_click_url_or_select', _('Click the link under the mouse cursor when no selection is created'))
m('click_url_or_select_grabbed', 'shift+left', 'click', 'grabbed,ungrabbed', 'mouse_click_url_or_select', _(
    'Click the link under the mouse cursor when no selection is created even if grabbed'))
m('click_url', 'ctrl+shift+left', 'release', 'grabbed,ungrabbed', 'mouse_click_url',
  _('Click the link under the mouse cursor'), _('Variant with :kbd:`ctrl+shift` is present only for legacy compatibility.'))

for grabbed in (False, True):
    modes = 'ungrabbed' + (',grabbed' if grabbed else '')
    name_s = '_grabbed' if grabbed else ''
    mods_p = 'shift+' if grabbed else ''
    ts = _(' even when grabbed') if grabbed else ''
    m('paste_selection' + name_s, mods_p + 'middle', 'release', modes, 'paste_selection', _('Paste from the primary selection') + ts)
    m('start_simple_selection' + name_s, mods_p + 'left', 'press', modes, 'mouse_selection normal', _('Start selecting text') + ts)
    m('start_rectangle_selection' + name_s, mods_p + 'ctrl+alt+left', 'press', modes, 'mouse_selection rectangle',
      _('Start selecting text in a rectangle') + ts)
    m('select_word' + name_s, mods_p + 'left', 'doublepress', modes, 'mouse_selection word', _('Select a word') + ts)
    m('select_line' + name_s, mods_p + 'left', 'triplepress', modes, 'mouse_selection line', _('Select a line') + ts, _('Select the entire line'))
    m('select_line_from_point' + name_s, mods_p + 'ctrl+alt+left', 'triplepress', modes,
      'mouse_selection line_from_point', _('Select line from point') + ts, _('Select from the clicked point to the end of the line'))
    m('extend_selection' + name_s, mods_p + 'right', 'press', modes, 'mouse_selection extend', _('Extend the current selection') + ts)
# }}}

# }}}

g('performance')  # {{{

o('repaint_delay', 10, option_type=positive_int, long_text=_('''
Delay (in milliseconds) between screen updates. Decreasing it, increases
frames-per-second (FPS) at the cost of more CPU usage. The default value
yields ~100 FPS which is more than sufficient for most uses. Note that to
actually achieve 100 FPS you have to either set :opt:`sync_to_monitor` to no
or use a monitor with a high refresh rate. Also, to minimize latency
when there is pending input to be processed, repaint_delay is ignored.'''))

o('input_delay', 3, option_type=positive_int, long_text=_('''
Delay (in milliseconds) before input from the program running in the terminal
is processed. Note that decreasing it will increase responsiveness, but also
increase CPU usage and might cause flicker in full screen programs that
redraw the entire screen on each loop, because kitty is so fast that partial
screen updates will be drawn.'''))

o('sync_to_monitor', True, long_text=_('''
Sync screen updates to the refresh rate of the monitor. This prevents
tearing (https://en.wikipedia.org/wiki/Screen_tearing) when scrolling. However,
it limits the rendering speed to the refresh rate of your monitor. With a
very high speed mouse/high keyboard repeat rate, you may notice some slight input latency.
If so, set this to no.'''))

# }}}

g('bell')  # {{{

o('enable_audio_bell', True, long_text=_('''
Enable/disable the audio bell. Useful in environments that require silence.'''))

o('visual_bell_duration', 0.0, option_type=positive_float, long_text=_('''
Visual bell duration. Flash the screen when a bell occurs for the specified number of
seconds. Set to zero to disable.'''))

o('window_alert_on_bell', True, long_text=_('''
Request window attention on bell.
Makes the dock icon bounce on macOS or the taskbar flash on linux.'''))

o('bell_on_tab', True, long_text=_('''
Show a bell symbol on the tab if a bell occurs in one of the windows in the
tab and the window is not the currently focused window'''))

o('command_on_bell', 'none', option_type=to_cmdline, long_text=_('''
Program to run when a bell occurs.
'''))
# }}}

g('window')  # {{{
o('remember_window_size', True, long_text=_('''
If enabled, the window size will be remembered so that new instances of kitty
will have the same size as the previous instance. If disabled, the window will
initially have size configured by initial_window_width/height, in pixels. You
can use a suffix of "c" on the width/height values to have them interpreted as
number of cells instead of pixels.
'''))


o('initial_window_width', '640', option_type=window_size)
o('initial_window_height', '400', option_type=window_size)


o('enabled_layouts', '*', option_type=to_layout_names, long_text=_('''
The enabled window layouts. A comma separated list of layout names. The special
value :code:`all` means all layouts. The first listed layout will be used as the
startup layout. Default configuration is all layouts in alphabetical order.
For a list of available layouts, see the :ref:`layouts`.
'''))

o('window_resize_step_cells', 2, option_type=positive_int, long_text=_('''
The step size (in units of cell width/cell height) to use when resizing
windows. The cells value is used for horizontal resizing and the lines value
for vertical resizing.
'''))
o('window_resize_step_lines', 2, option_type=positive_int)


o('window_border_width', '0.5pt', option_type=window_border_width, long_text=_('''
The width of window borders. Can be either in pixels (px) or pts (pt). Values
in pts will be rounded to the nearest number of pixels based on screen
resolution. If not specified the unit is assumed to be pts.
Note that borders are displayed only when more than one window
is visible. They are meant to separate multiple windows.'''))

o('draw_minimal_borders', True, long_text=_('''
Draw only the minimum borders needed. This means that only the minimum
needed borders for inactive windows are drawn. That is only the borders
that separate the inactive window from a neighbor. Note that setting
a non-zero window margin overrides this and causes all borders to be drawn.
'''))


edge_desc = _(
    'A single value sets all four sides. Two values set the vertical and horizontal sides.'
    ' Three values set top, horizontal and bottom. Four values set top, right, bottom and left.')


o('window_margin_width', '0', option_type=edge_width, long_text=_('''
The window margin (in pts) (blank area outside the border). ''' + edge_desc))

o('single_window_margin_width', '-1', option_type=optional_edge_width, long_text=_('''
The window margin (in pts) to use when only a single window is visible.
Negative values will cause the value of :opt:`window_margin_width` to be used instead. ''' + edge_desc))

o('window_padding_width', '0', option_type=edge_width, long_text=_('''
The window padding (in pts) (blank area between the text and the window border). ''' + edge_desc))

o('placement_strategy', 'center', option_type=choices('center', 'top-left'), long_text=_('''
When the window size is not an exact multiple of the cell size, the cell area of the terminal
window will have some extra padding on the sides. You can control how that padding is
distributed with this option. Using a value of :code:`center` means the cell area will
be placed centrally. A value of :code:`top-left` means the padding will be on only
the bottom and right edges.
'''))

o('active_border_color', '#00ff00', option_type=to_color_or_none, long_text=_('''
The color for the border of the active window. Set this to none to not draw borders
around the active window.'''))

o('inactive_border_color', '#cccccc', option_type=to_color, long_text=_('''
The color for the border of inactive windows'''))

o('bell_border_color', '#ff5a00', option_type=to_color, long_text=_('''
The color for the border of inactive windows in which a bell has occurred'''))

o('inactive_text_alpha', 1.0, option_type=unit_float, long_text=_('''
Fade the text in inactive windows by the specified amount (a number between
zero and one, with zero being fully faded).
'''))


o('hide_window_decorations', 'no', option_type=hide_window_decorations, long_text=_('''
Hide the window decorations (title-bar and window borders) with :code:`yes`.
On macOS, :code:`titlebar-only` can be used to only hide the titlebar.
Whether this works and exactly what effect it has depends on the
window manager/operating system.
'''))

o('resize_debounce_time', 0.1, option_type=positive_float, long_text=_('''
The time (in seconds) to wait before redrawing the screen when a
resize event is received. On platforms such as macOS, where the
operating system sends events corresponding to the start and end
of a resize, this number is ignored.'''))


o('resize_draw_strategy', 'static', option_type=resize_draw_strategy, long_text=_('''
Choose how kitty draws a window while a resize is in progress.
A value of :code:`static` means draw the current window contents, mostly unchanged.
A value of :code:`scale` means draw the current window contents scaled.
A value of :code:`blank` means draw a blank window.
A value of :code:`size` means show the window size in cells.
'''))

o('resize_in_steps', False, long_text=_('''
Resize the OS window in steps as large as the cells, instead of with the usual pixel accuracy.
Combined with an :opt:`initial_window_width` and :opt:`initial_window_height` in number of cells,
this option can be used to keep the margins as small as possible when resizing the OS window.
Note that this does not currently work on Wayland.
'''))

o('confirm_os_window_close', 0, option_type=positive_int, long_text=_('''
Ask for confirmation when closing an OS window or a tab that has at least this
number of kitty windows in it. A value of zero disables confirmation.
This confirmation also applies to requests to quit the entire application (all
OS windows, via the quit action).
'''))
# }}}

g('tabbar')   # {{{


o('tab_bar_edge', 'bottom', option_type=tab_bar_edge, long_text=_('''
Which edge to show the tab bar on, top or bottom'''))

o('tab_bar_margin_width', 0.0, option_type=positive_float, long_text=_('''
The margin to the left and right of the tab bar (in pts)'''))

o('tab_bar_style', 'fade', option_type=choices('fade', 'separator', 'powerline', 'hidden'), long_text=_('''
The tab bar style, can be one of: :code:`fade`, :code:`separator`, :code:`powerline`, or :code:`hidden`.
In the fade style, each tab's edges fade into the background color, in the separator style, tabs are
separated by a configurable separator, and the powerline shows the tabs as a continuous line.
If you use the hidden style, you might want to create a mapping for the :code:`select_tab` action which
presents you with a list of tabs and allows for easy switching to a tab.
'''))


o('tab_bar_min_tabs', 2, option_type=tab_bar_min_tabs, long_text=_('''
The minimum number of tabs that must exist before the tab bar is shown
'''))

o('tab_switch_strategy', 'previous', option_type=choices('previous', 'left', 'right', 'last'), long_text=_('''
The algorithm to use when switching to a tab when the current tab is closed.
The default of :code:`previous` will switch to the last used tab. A value of
:code:`left` will switch to the tab to the left of the closed tab. A value
of :code:`right` will switch to the tab to the right of the closed tab.
A value of :code:`last` will switch to the right-most tab.
'''))


o('tab_fade', '0.25 0.5 0.75 1', option_type=tab_fade, long_text=_('''
Control how each tab fades into the background when using :code:`fade` for the
:opt:`tab_bar_style`. Each number is an alpha (between zero and one) that controls
how much the corresponding cell fades into the background, with zero being no fade
and one being full fade. You can change the number of cells used by adding/removing
entries to this list.
'''))

o('tab_separator', '"{}"'.format(default_tab_separator), option_type=tab_separator, long_text=_('''
The separator between tabs in the tab bar when using :code:`separator` as the :opt:`tab_bar_style`.'''))

o('tab_powerline_style', 'angled', option_type=choices('angled', 'slanted', 'round'), long_text=_('''
The powerline separator style between tabs in the tab bar when using :code:`powerline`
as the :opt:`tab_bar_style`, can be one of: :code:`angled`, :code:`slanted`, or :code:`round`.
'''))


o('tab_activity_symbol', 'none', option_type=tab_activity_symbol, long_text=_('''
Some text or a unicode symbol to show on the tab if a window in the tab that does
not have focus has some activity.'''))

o('tab_title_template', '"{title}"', option_type=tab_title_template, long_text=_('''
A template to render the tab title. The default just renders
the title. If you wish to include the tab-index as well,
use something like: :code:`{index}: {title}`. Useful
if you have shortcuts mapped for :code:`goto_tab N`.
In addition you can use :code:`{layout_name}` for the current
layout name and :code:`{num_windows}` for the number of windows
in the tab. Note that formatting is done by Python's string formatting
machinery, so you can use, for instance, :code:`{layout_name[:2].upper()}` to
show only the first two letters of the layout name, upper-cased.
If you want to style the text, you can use styling directives, for example:
:code:`{fmt.fg.red}red{fmt.fg.default}normal{fmt.bg._00FF00}green bg{fmt.bg.normal}`.
Similarly, for bold and italic:
:code:`{fmt.bold}bold{fmt.nobold}normal{fmt.italic}italic{fmt.noitalic}`.
'''))
o('active_tab_title_template', 'none', option_type=active_tab_title_template, long_text=_('''
Template to use for active tabs, if not specified falls back
to :opt:`tab_title_template`.'''))

o('active_tab_foreground', '#000', option_type=to_color, long_text=_('''
Tab bar colors and styles'''))
o('active_tab_background', '#eee', option_type=to_color)
o('active_tab_font_style', 'bold-italic', option_type=tab_font_style)
o('inactive_tab_foreground', '#444', option_type=to_color)
o('inactive_tab_background', '#999', option_type=to_color)
o('inactive_tab_font_style', 'normal', option_type=tab_font_style)
o('tab_bar_background', 'none', option_type=to_color_or_none, long_text=_('''
Background color for the tab bar. Defaults to using the terminal background color.'''))

# }}}

g('colors')  # {{{

o('foreground',       '#dddddd', option_type=to_color, long_text=_('''
The foreground and background colors'''))
o('background',       '#000000', option_type=to_color)

o('background_opacity', 1.0, option_type=unit_float, long_text=_('''
The opacity of the background. A number between 0 and 1, where 1 is opaque and
0 is fully transparent.  This will only work if supported by the OS (for
instance, when using a compositor under X11). Note that it only sets the
background color's opacity in cells that have the same background color as
the default terminal background. This is so that things like the status bar
in vim, powerline prompts, etc. still look good.  But it means that if you use
a color theme with a background color in your editor, it will not be rendered
as transparent.  Instead you should change the default background color in your
kitty config and not use a background color in the editor color scheme. Or use
the escape codes to set the terminals default colors in a shell script to
launch your editor.  Be aware that using a value less than 1.0 is a (possibly
significant) performance hit.  If you want to dynamically change transparency
of windows set :opt:`dynamic_background_opacity` to :code:`yes` (this is off by
default as it has a performance cost)
'''))


o('background_image', 'none', option_type=config_or_absolute_path, long_text=_('''
Path to a background image. Must be in PNG format.'''))

o('background_image_layout', 'tiled', option_type=choices('tiled', 'scaled', 'mirror-tiled'), long_text=_('''
Whether to tile or scale the background image.'''))

o('background_image_linear', False, long_text=_('''
When background image is scaled, whether linear interpolation should be used.'''))

o('dynamic_background_opacity', False, long_text=_('''
Allow changing of the :opt:`background_opacity` dynamically, using either keyboard
shortcuts (:sc:`increase_background_opacity` and :sc:`decrease_background_opacity`)
or the remote control facility.
'''))

o('background_tint', 0.0, option_type=unit_float, long_text=_('''
How much to tint the background image by the background color. The tint is applied
only under the text area, not margin/borders. Makes it easier to read the text.
Tinting is done using the current background color for each window. This setting
applies only if :opt:`background_opacity` is set and transparent windows are supported
or :opt:`background_image` is set.
'''))

o('dim_opacity', 0.75, option_type=unit_float, long_text=_('''
How much to dim text that has the DIM/FAINT attribute set. One means no dimming and
zero means fully dimmed (i.e. invisible).'''))

o('selection_foreground', '#000000', option_type=to_color_or_none, long_text=_('''
The foreground for text selected with the mouse. A value of none means to leave the color unchanged.'''))
o('selection_background', '#fffacd', option_type=to_color, long_text=_('''
The background for text selected with the mouse.'''))

g('colors.table')
o('color0', '#000000', long_text=_('black'), option_type=to_color)
o('color8', '#767676', option_type=to_color)

o('color1', '#cc0403', long_text=_('red'), option_type=to_color)
o('color9', '#f2201f', option_type=to_color)

o('color2', '#19cb00', long_text=_('green'), option_type=to_color)
o('color10', '#23fd00', option_type=to_color)

o('color3', '#cecb00', long_text=_('yellow'), option_type=to_color)
o('color11', '#fffd00', option_type=to_color)

o('color4', '#0d73cc', long_text=_('blue'), option_type=to_color)
o('color12', '#1a8fff', option_type=to_color)

o('color5', '#cb1ed1', long_text=_('magenta'), option_type=to_color)
o('color13', '#fd28ff', option_type=to_color)

o('color6', '#0dcdcd', long_text=_('cyan'), option_type=to_color)
o('color14', '#14ffff', option_type=to_color)

o('color7', '#dddddd', long_text=_('white'), option_type=to_color)
o('color15', '#ffffff', option_type=to_color)

o('mark1_foreground', 'black', long_text=_('Color for marks of type 1'), option_type=to_color)
o('mark1_background', '#98d3cb', long_text=_('Color for marks of type 1 (light steel blue)'), option_type=to_color)
o('mark2_foreground', 'black', long_text=_('Color for marks of type 2'), option_type=to_color)
o('mark2_background', '#f2dcd3', long_text=_('Color for marks of type 1 (beige)'), option_type=to_color)
o('mark3_foreground', 'black', long_text=_('Color for marks of type 3'), option_type=to_color)
o('mark3_background', '#f274bc', long_text=_('Color for marks of type 1 (violet)'), option_type=to_color)
dfctl = defines.default_color_table()
for i in range(16, 256):
    o('color{}'.format(i), color_as_sharp(color_from_int(dfctl[i])), option_type=to_color, add_to_docs=False)

# }}}

g('advanced')  # {{{
o('shell', '.', long_text=_('''
The shell program to execute. The default value of . means
to use whatever shell is set as the default shell for the current user.
Note that on macOS if you change this, you might need to add :code:`--login` to
ensure that the shell starts in interactive mode and reads its startup rc files.'''))

o('editor', '.', long_text=_('''
The console editor to use when editing the kitty config file or similar tasks.
A value of . means to use the environment variables VISUAL and EDITOR in that
order. Note that this environment variable has to be set not just in your shell
startup scripts but system-wide, otherwise kitty will not see it.
'''))

o('close_on_child_death', False, long_text=_('''
Close the window when the child process (shell) exits. If no (the default), the
terminal will remain open when the child exits as long as there are still
processes outputting to the terminal (for example disowned or backgrounded
processes). If yes, the window will close as soon as the child process exits.
Note that setting it to yes means that any background processes still using the
terminal can fail silently because their stdout/stderr/stdin no longer work.
'''))


o('allow_remote_control', 'no', option_type=allow_remote_control, long_text=_('''
Allow other programs to control kitty. If you turn this on other programs can
control all aspects of kitty, including sending text to kitty windows, opening
new windows, closing windows, reading the content of windows, etc.  Note that
this even works over ssh connections. You can chose to either allow any program
running within kitty to control it, with :code:`yes` or only programs that
connect to the socket specified with the :option:`kitty --listen-on` command
line option, if you use the value :code:`socket-only`. The latter is useful if
you want to prevent programs running on a remote computer over ssh from
controlling kitty.
'''))


o('listen_on', 'none', long_text=_('''
Tell kitty to listen to the specified unix/tcp socket for remote control
connections. Note that this will apply to all kitty instances. It can be
overridden by the :option:`kitty --listen-on` command line flag. This
option accepts only UNIX sockets, such as unix:${TEMP}/mykitty or (on Linux)
unix:@mykitty. Environment variables are expanded. If {kitty_pid} is present
then it is replaced by the PID of the kitty process, otherwise the PID of the kitty
process is appended to the value, with a hyphen. This option is ignored unless
you also set :opt:`allow_remote_control` to enable remote control. See the
help for :option:`kitty --listen-on` for more details.
'''))

o('+env', '', add_to_default=False, option_type=env, long_text=_('''
Specify environment variables to set in all child processes. Note that
environment variables are expanded recursively, so if you use::

    env MYVAR1=a
    env MYVAR2=${MYVAR1}/${HOME}/b

The value of MYVAR2 will be :code:`a/<path to home directory>/b`.
'''))

o('update_check_interval', 24, option_type=float, long_text=_('''
Periodically check if an update to kitty is available. If an update is found
a system notification is displayed informing you of the available update.
The default is to check every 24 hrs, set to zero to disable.
'''))


o('startup_session', 'none', option_type=config_or_absolute_path, long_text=_('''
Path to a session file to use for all kitty instances. Can be overridden
by using the :option:`kitty --session` command line option for individual
instances. See :ref:`sessions` in the kitty documentation for details. Note
that relative paths are interpreted with respect to the kitty config directory.
Environment variables in the path are expanded.
'''))


o('clipboard_control', 'write-clipboard write-primary', option_type=clipboard_control, long_text=_('''
Allow programs running in kitty to read and write from the clipboard. You can
control exactly which actions are allowed. The set of possible actions is:
write-clipboard read-clipboard write-primary read-primary. You can
additionally specify no-append to disable kitty's protocol extension
for clipboard concatenation. The default is to allow writing to the
clipboard and primary selection with concatenation enabled. Note
that enabling the read functionality is a security risk as it means that any
program, even one running on a remote server via SSH can read your clipboard.
'''))


o('allow_hyperlinks', 'yes', option_type=allow_hyperlinks, long_text=_('''
Process hyperlink (OSC 8) escape sequences. If disabled OSC 8 escape
sequences are ignored. Otherwise they become clickable links, that you
can click by holding down ctrl+shift and clicking with the mouse. The special
value of ``ask`` means that kitty will ask before opening the link.'''))


o('term', 'xterm-kitty', long_text=_('''
The value of the TERM environment variable to set. Changing this can break many
terminal programs, only change it if you know what you are doing, not because
you read some advice on Stack Overflow to change it. The TERM variable is used
by various programs to get information about the capabilities and behavior of
the terminal. If you change it, depending on what programs you run, and how
different the terminal you are changing it to is, various things from
key-presses, to colors, to various advanced features may not work.
'''))

# }}}

g('os')  # {{{


o('wayland_titlebar_color', 'system', option_type=macos_titlebar_color, long_text=_('''
Change the color of the kitty window's titlebar on Wayland systems with client side window decorations such as GNOME.
A value of :code:`system` means to use the default system color,
a value of :code:`background` means to use the background color
of the currently active window and finally you can use
an arbitrary color, such as :code:`#12af59` or :code:`red`.
'''))

o('macos_titlebar_color', 'system', option_type=macos_titlebar_color, long_text=_('''
Change the color of the kitty window's titlebar on macOS. A value of :code:`system`
means to use the default system color, a value of :code:`background` means to use
the background color of the currently active window and finally you can use
an arbitrary color, such as :code:`#12af59` or :code:`red`. WARNING: This option works by
using a hack, as there is no proper Cocoa API for it. It sets the background
color of the entire window and makes the titlebar transparent. As such it is
incompatible with :opt:`background_opacity`. If you want to use both, you are
probably better off just hiding the titlebar with :opt:`hide_window_decorations`.
'''))


o('macos_option_as_alt', 'no', option_type=macos_option_as_alt, long_text=_('''
Use the option key as an alt key. With this set to :code:`no`, kitty will use
the macOS native :kbd:`Option+Key` = unicode character behavior. This will
break any :kbd:`Alt+key` keyboard shortcuts in your terminal programs, but you
can use the macOS unicode input technique. You can use the values:
:code:`left`, :code:`right`, or :code:`both` to use only the left, right or
both Option keys as Alt, instead.
'''))

o('macos_hide_from_tasks', False, long_text=_('''
Hide the kitty window from running tasks (:kbd:`⌘+Tab`) on macOS.
'''))

o('macos_quit_when_last_window_closed', False, long_text=_('''
Have kitty quit when all the top-level windows are closed. By default,
kitty will stay running, even with no open windows, as is the expected
behavior on macOS.
'''))

o('macos_window_resizable', True, long_text=_('''
Disable this if you want kitty top-level (OS) windows to not be resizable
on macOS.
'''))

o('macos_thicken_font', 0, option_type=positive_float, long_text=_('''
Draw an extra border around the font with the given width, to increase
legibility at small font sizes. For example, a value of 0.75 will
result in rendering that looks similar to sub-pixel antialiasing at
common font sizes.
'''))

o('macos_traditional_fullscreen', False, long_text=_('''
Use the traditional full-screen transition, that is faster, but less pretty.
'''))

o('macos_show_window_title_in', 'all', option_type=choices('all', 'window', 'menubar', 'none'), long_text=_('''
Show or hide the window title in the macOS window or menu-bar.
A value of :code:`window` will show the title of the currently
active window at the top of the macOS window. A value of
:code:`menubar` will show the title of the currently active window
in the macOS menu-bar, making use of otherwise wasted space.
:code:`all` will show the title everywhere and :code:`none`
hides the title in the window and the menu-bar.
'''))

# Disabled by default because of https://github.com/kovidgoyal/kitty/issues/794
o('macos_custom_beam_cursor', False, long_text=_('''
Enable/disable custom mouse cursor for macOS that is easier to see on both
light and dark backgrounds. WARNING: this might make your mouse cursor
invisible on dual GPU machines.'''))

o('linux_display_server', 'auto', option_type=choices('auto', 'x11', 'wayland'), long_text=_('''
Choose between Wayland and X11 backends. By default, an
appropriate backend based on the system state is chosen
automatically. Set it to :code:`x11` or :code:`wayland`
to force the choice.'''))
# }}}

g('shortcuts')  # {{{

o('kitty_mod', 'ctrl+shift', option_type=to_modifiers, long_text=_('''
The value of :code:`kitty_mod` is used as the modifier for all default shortcuts, you
can change it in your kitty.conf to change the modifiers for all the default
shortcuts.'''))

o('clear_all_shortcuts', False, long_text=_('''
You can have kitty remove all shortcut definition seen up to this point. Useful, for
instance, to remove the default shortcuts.'''))

o('kitten_alias', 'hints hints --hints-offset=0', add_to_default=False, long_text=_('''
You can create aliases for kitten names, this allows overriding the defaults
for kitten options and can also be used to shorten repeated mappings of the same
kitten with a specific group of options. For example, the above alias
changes the default value of :option:`kitty +kitten hints --hints-offset`
to zero for all mappings, including the builtin ones.
'''))

g('shortcuts.clipboard')  # {{{
k('copy_to_clipboard', 'kitty_mod+c', 'copy_to_clipboard', _('Copy to clipboard'), long_text=_('''
There is also a :code:`copy_or_interrupt` action that can be optionally mapped to :kbd:`Ctrl+c`.
It will copy only if there is a selection and send an interrupt otherwise. Similarly, :code:`copy_and_clear_or_interrupt`
will copy and clear the selection or send an interrupt if there is no selection.'''))
if is_macos:
    k('copy_to_clipboard', 'cmd+c', 'copy_to_clipboard', _('Copy to clipboard'), add_to_docs=False)
k('paste_from_clipboard', 'kitty_mod+v', 'paste_from_clipboard', _('Paste from clipboard'))
if is_macos:
    k('paste_from_clipboard', 'cmd+v', 'paste_from_clipboard', _('Paste from clipboard'), add_to_docs=False)
k('paste_from_selection', 'kitty_mod+s', 'paste_from_selection', _('Paste from selection'))
k('paste_from_selection', 'shift+insert', 'paste_from_selection', _('Paste from selection'))
k('pass_selection_to_program', 'kitty_mod+o', 'pass_selection_to_program', _('Pass selection to program'), long_text=_('''
You can also pass the contents of the current selection to any program using
:code:`pass_selection_to_program`. By default, the system's open program is used, but
you can specify your own, the selection will be passed as a command line argument to the program,
for example::

    map kitty_mod+o pass_selection_to_program firefox

You can pass the current selection to a terminal program running in a new kitty
window, by using the @selection placeholder::

    map kitty_mod+y new_window less @selection
'''))

# }}}

g('shortcuts.scrolling')  # {{{
k('scroll_line_up', 'kitty_mod+up', 'scroll_line_up', _('Scroll line up'))
if is_macos:
    k('scroll_line_up', 'alt+cmd+page_up', 'scroll_line_up', _('Scroll line up'), add_to_docs=False)
    k('scroll_line_up', 'cmd+up', 'scroll_line_up', _('Scroll line up'), add_to_docs=False)
k('scroll_line_up', 'kitty_mod+k', 'scroll_line_up')
k('scroll_line_down', 'kitty_mod+down', 'scroll_line_down', _('Scroll line down'))
k('scroll_line_down', 'kitty_mod+j', 'scroll_line_down')
if is_macos:
    k('scroll_line_down', 'alt+cmd+page_down', 'scroll_line_down', _('Scroll line down'), add_to_docs=False)
    k('scroll_line_down', 'cmd+down', 'scroll_line_down', _('Scroll line down'), add_to_docs=False)
k('scroll_page_up', 'kitty_mod+page_up', 'scroll_page_up', _('Scroll page up'))
if is_macos:
    k('scroll_page_up', 'cmd+page_up', 'scroll_page_up', _('Scroll page up'), add_to_docs=False)
k('scroll_page_down', 'kitty_mod+page_down', 'scroll_page_down', _('Scroll page down'))
if is_macos:
    k('scroll_page_down', 'cmd+page_down', 'scroll_page_down', _('Scroll page down'), add_to_docs=False)
k('scroll_home', 'kitty_mod+home', 'scroll_home', _('Scroll to top'))
if is_macos:
    k('scroll_home', 'cmd+home', 'scroll_home', _('Scroll to top'), add_to_docs=False)
k('scroll_end', 'kitty_mod+end', 'scroll_end', _('Scroll to bottom'))
if is_macos:
    k('scroll_end', 'cmd+end', 'scroll_end', _('Scroll to bottom'), add_to_docs=False)
k('show_scrollback', 'kitty_mod+h', 'show_scrollback', _('Browse scrollback buffer in less'), long_text=_('''

You can pipe the contents of the current screen + history buffer as
:file:`STDIN` to an arbitrary program using the ``launch`` function. For example,
the following opens the scrollback buffer in less in an overlay window::

    map f1 launch --stdin-source=@screen_scrollback --stdin-add-formatting --type=overlay less +G -R

For more details on piping screen and buffer contents to external programs,
see :doc:`launch`.
'''))


# }}}

g('shortcuts.window')  # {{{
k('new_window', 'kitty_mod+enter', 'new_window', _(''), long_text=_('''
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
'''))
if is_macos:
    k('new_window', 'cmd+enter', 'new_window', _('New window'), add_to_docs=False)
k('new_os_window', 'kitty_mod+n', 'new_os_window', _('New OS window'), _(
    'Works like new_window above, except that it opens a top level OS kitty window.'
    ' In particular you can use new_os_window_with_cwd to open a window with the current working directory.'))
if is_macos:
    k('new_os_window', 'cmd+n', 'new_os_window', _('New OS window'), add_to_docs=False)
k('close_window', 'kitty_mod+w', 'close_window', _('Close window'))
if is_macos:
    k('close_window', 'shift+cmd+d', 'close_window', _('Close window'), add_to_docs=False)
k('next_window', 'kitty_mod+]', 'next_window', _('Next window'))
k('previous_window', 'kitty_mod+[', 'previous_window', _('Previous window'))
k('move_window_forward', 'kitty_mod+f', 'move_window_forward', _('Move window forward'))
k('move_window_backward', 'kitty_mod+b', 'move_window_backward', _('Move window backward'))
k('move_window_to_top', 'kitty_mod+`', 'move_window_to_top', _('Move window to top'))
k('start_resizing_window', 'kitty_mod+r', 'start_resizing_window', _('Start resizing window'))
if is_macos:
    k('start_resizing_window', 'cmd+r', 'start_resizing_window', _('Start resizing window'), add_to_docs=False)
k('first_window', 'kitty_mod+1', 'first_window', _('First window'))
k('second_window', 'kitty_mod+2', 'second_window', _('Second window'))
k('third_window', 'kitty_mod+3', 'third_window', _('Third window'))
k('fourth_window', 'kitty_mod+4', 'fourth_window', _('Fourth window'))
k('fifth_window', 'kitty_mod+5', 'fifth_window', _('Fifth window'))
k('sixth_window', 'kitty_mod+6', 'sixth_window', _('Sixth window'))
k('seventh_window', 'kitty_mod+7', 'seventh_window', _('Seventh window'))
k('eighth_window', 'kitty_mod+8', 'eighth_window', _('Eight window'))
k('ninth_window', 'kitty_mod+9', 'ninth_window', _('Ninth window'))
k('tenth_window', 'kitty_mod+0', 'tenth_window', _('Tenth window'))
if is_macos:
    k('first_window', 'cmd+1', 'first_window', _('First window'), add_to_docs=False)
    k('second_window', 'cmd+2', 'second_window', _('Second window'), add_to_docs=False)
    k('third_window', 'cmd+3', 'third_window', _('Third window'), add_to_docs=False)
    k('fourth_window', 'cmd+4', 'fourth_window', _('Fourth window'), add_to_docs=False)
    k('fifth_window', 'cmd+5', 'fifth_window', _('Fifth window'), add_to_docs=False)
    k('sixth_window', 'cmd+6', 'sixth_window', _('Sixth window'), add_to_docs=False)
    k('seventh_window', 'cmd+7', 'seventh_window', _('Seventh window'), add_to_docs=False)
    k('eighth_window', 'cmd+8', 'eighth_window', _('Eight window'), add_to_docs=False)
    k('ninth_window', 'cmd+9', 'ninth_window', _('Ninth window'), add_to_docs=False)
# }}}

g('shortcuts.tab')  # {{{
k('next_tab', 'kitty_mod+right', 'next_tab', _('Next tab'))
if is_macos:
    k('next_tab', 'shift+cmd+]', 'next_tab', _('Next tab'), add_to_docs=False)
    k('next_tab', 'ctrl+tab', 'next_tab', _('Next tab'), add_to_docs=False)
k('previous_tab', 'kitty_mod+left', 'previous_tab', _('Previous tab'))
if is_macos:
    k('previous_tab', 'shift+cmd+[', 'previous_tab', _('Previous tab'), add_to_docs=False)
    k('previous_tab', 'shift+ctrl+tab', 'previous_tab', _('Previous tab'), add_to_docs=False)
k('new_tab', 'kitty_mod+t', 'new_tab', _('New tab'))
if is_macos:
    k('new_tab', 'cmd+t', 'new_tab', _('New tab'), add_to_docs=False)
k('close_tab', 'kitty_mod+q', 'close_tab', _('Close tab'))
if is_macos:
    k('close_tab', 'cmd+w', 'close_tab', _('Close tab'), add_to_docs=False)
    k('close_os_window', 'shift+cmd+w', 'close_os_window', _('Close OS window'), add_to_docs=False)
k('move_tab_forward', 'kitty_mod+.', 'move_tab_forward', _('Move tab forward'))
k('move_tab_backward', 'kitty_mod+,', 'move_tab_backward', _('Move tab backward'))
k('set_tab_title', 'kitty_mod+alt+t', 'set_tab_title', _('Set tab title'))
if is_macos:
    k('set_tab_title', 'shift+cmd+i', 'set_tab_title', _('Set tab title'), add_to_docs=False)
# }}}

g('shortcuts.layout')  # {{{
k('next_layout', 'kitty_mod+l', 'next_layout', _('Next layout'))
# }}}

g('shortcuts.fonts')  # {{{
k('increase_font_size', 'kitty_mod+equal', 'change_font_size all +2.0', _('Increase font size'))
k('increase_font_size', 'kitty_mod+plus', 'change_font_size all +2.0', _('Increase font size'), add_to_docs=False)
k('increase_font_size', 'kitty_mod+kp_add', 'change_font_size all +2.0', _('Increase font size'), add_to_docs=False)
if is_macos:
    k('increase_font_size', 'cmd+plus', 'change_font_size all +2.0', _('Increase font size'), add_to_docs=False)
    k('increase_font_size', 'cmd+equal', 'change_font_size all +2.0', _('Increase font size'), add_to_docs=False)
    k('increase_font_size', 'cmd+shift+equal', 'change_font_size all +2.0', _('Increase font size'), add_to_docs=False)
k('decrease_font_size', 'kitty_mod+minus', 'change_font_size all -2.0', _('Decrease font size'))
k('decrease_font_size', 'kitty_mod+kp_subtract', 'change_font_size all -2.0', _('Decrease font size'))
if is_macos:
    k('decrease_font_size', 'cmd+minus', 'change_font_size all -2.0', _('Decrease font size'), add_to_docs=False)
    k('decrease_font_size', 'cmd+shift+minus', 'change_font_size all -2.0', _('Decrease font size'), add_to_docs=False)
k('reset_font_size', 'kitty_mod+backspace', 'change_font_size all 0', _('Reset font size'))
if is_macos:
    k('reset_font_size', 'cmd+0', 'change_font_size all 0', _('Reset font size'), add_to_docs=False)
# }}}

g('shortcuts.selection')   # {{{
k('open_url', 'kitty_mod+e', 'kitten hints', _('Open URL'), _('''
Open a currently visible URL using the keyboard. The program used to open the
URL is specified in :opt:`open_url_with`.'''))

k('insert_selected_path', 'kitty_mod+p>f', 'kitten hints --type path --program -', _('Insert selected path'), long_text=_('''
Select a path/filename and insert it into the terminal. Useful, for instance to
run git commands on a filename output from a previous git command.'''))

k('open_selected_path', 'kitty_mod+p>shift+f', 'kitten hints --type path', _('Open selected path'), long_text=_('''
Select a path/filename and open it with the default open program.'''))

k('insert_selected_line', 'kitty_mod+p>l', 'kitten hints --type line --program -', _('Insert selected line'), long_text=_('''
Select a line of text and insert it into the terminal. Use for the
output of things like: ls -1'''))

k('insert_selected_word', 'kitty_mod+p>w', 'kitten hints --type word --program -', _('Insert selected word'), long_text=_('''
Select words and insert into terminal.'''))

k('insert_selected_hash', 'kitty_mod+p>h', 'kitten hints --type hash --program -', _('Insert selected hash'), long_text=_('''
Select something that looks like a hash and insert it into the terminal.
Useful with git, which uses sha1 hashes to identify commits'''))

k('goto_file_line', 'kitty_mod+p>n', 'kitten hints --type linenum', _('Open the selected file at the selected line'), long_text=_('''
Select something that looks like :code:`filename:linenum` and open it in vim at
the specified line number.'''))

k('open_selected_hyperlink', 'kitty_mod+p>y', 'kitten hints --type hyperlink', _('Open the selected hyperlink'), long_text=_('''
Select a hyperlink (i.e. a URL that has been marked as such by the terminal program, for example, by ls --hyperlink=auto).
'''))

# }}}

g('shortcuts.misc')  # {{{
k('toggle_fullscreen', 'kitty_mod+f11', 'toggle_fullscreen', _('Toggle fullscreen'))
k('toggle_maximized', 'kitty_mod+f10', 'toggle_maximized', _('Toggle maximized'))
k('input_unicode_character', 'kitty_mod+u', 'kitten unicode_input', _('Unicode input'))
if is_macos:
    k('input_unicode_character', 'cmd+ctrl+space', 'kitten unicode_input', _('Unicode input'), add_to_docs=False)
k('edit_config_file', 'kitty_mod+f2', 'edit_config_file', _('Edit config file'))
if is_macos:
    k('edit_config_file', 'cmd+,', 'edit_config_file', _('Edit config file'), add_to_docs=False)
k('kitty_shell', 'kitty_mod+escape', 'kitty_shell window', _('Open the kitty command shell'), long_text=_('''
Open the kitty shell in a new window/tab/overlay/os_window to control kitty using commands.'''))
k('increase_background_opacity', 'kitty_mod+a>m', 'set_background_opacity +0.1', _('Increase background opacity'))
k('decrease_background_opacity', 'kitty_mod+a>l', 'set_background_opacity -0.1', _('Decrease background opacity'))
k('full_background_opacity', 'kitty_mod+a>1', 'set_background_opacity 1', _('Make background fully opaque'))
k('reset_background_opacity', 'kitty_mod+a>d', 'set_background_opacity default', _('Reset background opacity'))
k('reset_terminal', 'kitty_mod+delete', 'clear_terminal reset active', _('Reset the terminal'),
    long_text=_('''
You can create shortcuts to clear/reset the terminal. For example::

    # Reset the terminal
    map kitty_mod+f9 clear_terminal reset active
    # Clear the terminal screen by erasing all contents
    map kitty_mod+f10 clear_terminal clear active
    # Clear the terminal scrollback by erasing it
    map kitty_mod+f11 clear_terminal scrollback active
    # Scroll the contents of the screen into the scrollback
    map kitty_mod+f12 clear_terminal scroll active

If you want to operate on all windows instead of just the current one, use :italic:`all` instead of :italic:`active`.

It is also possible to remap Ctrl+L to both scroll the current screen contents into the scrollback buffer
and clear the screen, instead of just clearing the screen::

    map ctrl+l combine : clear_terminal scroll active : send_text normal,application \\x0c
'''))
k('send_text', 'ctrl+shift+alt+h', 'send_text all Hello World', _('Send arbitrary text on key presses'),
  add_to_default=False, long_text=_('''
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
'''))
# }}}
# }}}
