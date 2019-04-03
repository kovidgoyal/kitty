#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2018, Kovid Goyal <kovid at kovidgoyal.net>

# Utils  {{{
import os
from gettext import gettext as _

from . import fast_data_types as defines
from .conf.definition import option_func
from .conf.utils import (
    choices, positive_float, positive_int, to_bool, to_cmdline, to_color,
    to_color_or_none, unit_float
)
from .constants import config_dir, is_macos
from .fast_data_types import CURSOR_BEAM, CURSOR_BLOCK, CURSOR_UNDERLINE
from .layout import all_layouts
from .rgb import color_as_int, color_as_sharp, color_from_int
from .utils import log_error

MINIMUM_FONT_SIZE = 4


mod_map = {'CTRL': 'CONTROL', 'CMD': 'SUPER', '⌘': 'SUPER',
           '⌥': 'ALT', 'OPTION': 'ALT', 'KITTY_MOD': 'KITTY'}


def parse_mods(parts, sc):

    def map_mod(m):
        return mod_map.get(m, m)

    mods = 0
    for m in parts:
        try:
            mods |= getattr(defines, 'GLFW_MOD_' + map_mod(m.upper()))
        except AttributeError:
            log_error('Shortcut: {} has unknown modifier, ignoring'.format(sc))
            return

    return mods


def to_modifiers(val):
    return parse_mods(val.split('+'), val) or 0


def uniq(vals, result_type=list):
    seen = set()
    seen_add = seen.add
    return result_type(x for x in vals if x not in seen and not seen_add(x))
# }}}

# Groups {{{


all_options = {}


o, k, g, all_groups = option_func(all_options, {
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
The 16 terminal colors. There are 8 basic colors, each color has a dull and
bright version. You can also set the remaining colors from the 256 color table
as color16 to color255.''')
    ],
    'advanced': [_('Advanced')],
    'os': [_('OS specific tweaks')],
    'shortcuts': [
        _('Keyboard shortcuts'),
        _('''\
For a list of key names, see: :link:`GLFW keys
<http://www.glfw.org/docs/latest/group__keys.html>`. The name to use is the part
after the :code:`GLFW_KEY_` prefix. For a list of modifier names, see:
:link:`GLFW mods <http://www.glfw.org/docs/latest/group__mods.html>`

On Linux you can also use XKB key names to bind keys that are not supported by
GLFW. See :link:`XKB keys
<https://github.com/xkbcommon/libxkbcommon/blob/master/xkbcommon/xkbcommon-keysyms.h>`
for a list of key names. The name to use is the part after the :code:`XKB_KEY_`
prefix. Note that you should only use an XKB key name for keys that are not present
in the list of GLFW keys.

Finally, you can use raw system key codes to map keys. To see the system key code
for a key, start kitty with the :option:`kitty --debug-keyboard` option. Then kitty will
output some debug text for every key event. In that text look for ``native_code``
the value of that becomes the key name in the shortcut. For example:

.. code-block:: none

    on_key_input: glfw key: 65 native_code: 0x61 action: PRESS mods: 0x0 text: 'a'

Here, the key name for the :kbd:`A` key is :kbd:`0x61` and you can use it with::

    map ctrl+0x61 something

to map :kbd:`ctrl+a` to something.

You can use the special action :code:`no_op` to unmap a keyboard shortcut that is
assigned in the default configuration.

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
tab, 2 the second tab and -1 being the previously active tab::

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


def to_font_size(x):
    return max(MINIMUM_FONT_SIZE, float(x))


o('font_size', 11.0, long_text=_('Font size (in pts)'), option_type=to_font_size)


def adjust_line_height(x):
    if x.endswith('%'):
        ans = float(x[:-1].strip()) / 100.0
        if ans < 0:
            log_error('Percentage adjustments of cell sizes must be positive numbers')
            return 0
        return ans
    return int(x)


o('adjust_line_height', 0, option_type=adjust_line_height, long_text=_('''
Change the size of each character cell kitty renders. You can use either numbers,
which are interpreted as pixels or percentages (number followed by %), which
are interpreted as percentages of the unmodified values. You can use negative
pixels or percentages less than 100% to reduce sizes (but this might cause
rendering artifacts).'''))
o('adjust_column_width', 0, option_type=adjust_line_height)


o(
    '+symbol_map',
    'U+E0A0-U+E0A2,U+E0B0-U+E0B3 PowerlineSymbols',
    add_to_default=False,
    long_text=_('''
Map the specified unicode codepoints to a particular font. Useful if you need
special rendering for some symbols, such as for Powerline. Avoids the need for
patched fonts. Each unicode code point is specified in the form :code:`U+<code point
in hexadecimal>`. You can specify multiple code points, separated by commas and
ranges separated by hyphens. :code:`symbol_map` itself can be specified multiple times.
Syntax is::

    symbol_map codepoints Font Family Name

'''))

o('disable_ligatures_under_cursor', False, long_text=_('''
Render the characters of a multi-character ligature under the cursor
individually to make editing more intuitive.
'''))


def box_drawing_scale(x):
    ans = tuple(float(x.strip()) for x in x.split(','))
    if len(ans) != 4:
        raise ValueError('Invalid box_drawing scale, must have four entries')
    return ans


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

cshapes = {
    'block': CURSOR_BLOCK,
    'beam': CURSOR_BEAM,
    'underline': CURSOR_UNDERLINE
}


def to_cursor_shape(x):
    try:
        return cshapes[x.lower()]
    except KeyError:
        raise ValueError(
            'Invalid cursor shape: {} allowed values are {}'.format(
                x, ', '.join(cshapes)
            )
        )


def cursor_text_color(x):
    if x.lower() == 'background':
        return
    return to_color(x)


o('cursor', '#cccccc', _('Default cursor color'), option_type=to_color)
o('cursor_text_color', '#111111', option_type=cursor_text_color, long_text=_('''
Choose the color of text under the cursor. If you want it rendered with the
background color of the cell underneath instead, use the special keyword: background'''))
o('cursor_shape', 'block', option_type=to_cursor_shape, long_text=_(
    'The cursor shape can be one of (block, beam, underline)'))
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


def scrollback_lines(x):
    x = int(x)
    if x < 0:
        x = 2 ** 32 - 1
    return x


def scrollback_pager_history_size(x):
    ans = int(max(0, float(x)) * 1024 * 1024)
    return min(ans, 4096 * 1024 * 1024 - 1)


o('scrollback_lines', 2000, option_type=scrollback_lines, long_text=_('''
Number of lines of history to keep in memory for scrolling back. Memory is allocated
on demand. Negative numbers are (effectively) infinite scrollback. Note that using
very large scrollback is not recommended as it can slow down resizing of the terminal
and also use large amounts of RAM.'''))

o('scrollback_pager', 'less --chop-long-lines --RAW-CONTROL-CHARS +INPUT_LINE_NUMBER', option_type=to_cmdline, long_text=_('''
Program with which to view scrollback in a new window. The scrollback buffer is
passed as STDIN to this program. If you change it, make sure the program you
use can handle ANSI escape sequences for colors and text formatting.
INPUT_LINE_NUMBER in the command line above will be replaced by an integer
representing which line should be at the top of the screen.'''))

o('scrollback_pager_history_size', 0, option_type=scrollback_pager_history_size, long_text=_('''
Separate scrollback history size, used only for browsing the scrollback buffer (in MB).
This separate buffer is not available for interactive scrolling but will be
piped to the pager program when viewing scrollback buffer in a separate window.
The current implementation stores one character in 4 bytes, so approximatively
2500 lines per megabyte at 100 chars per line. A value of zero or less disables
this feature. The maximum allowed size is 4GB.'''))

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

o('url_color', '#0087bd', option_type=to_color, long_text=_('''
The color and style for highlighting URLs on mouse-over.
:code:`url_style` can be one of: none, single, double, curly'''))


def url_style(x):
    return url_style.map.get(x, url_style.map['curly'])


url_style.map = dict(
    ((v, i) for i, v in enumerate('none single double curly'.split()))
)


o('url_style', 'curly', option_type=url_style)

o('open_url_modifiers', 'kitty_mod', option_type=to_modifiers, long_text=_('''
The modifier keys to press when clicking with the
mouse on URLs to open the URL'''))

o('open_url_with', 'default', option_type=to_cmdline, long_text=_('''
The program with which to open URLs that are clicked on.
The special value :code:`default` means to use the
operating system's default URL handler.'''))


def copy_on_select(raw):
    q = raw.lower()
    # boolean values special cased for backwards compat
    if q in ('y', 'yes', 'true', 'clipboard'):
        return 'clipboard'
    if q in ('n', 'no', 'false', ''):
        return ''
    return raw


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

o('rectangle_select_modifiers', 'ctrl+alt', option_type=to_modifiers, long_text=_('''
The modifiers to use rectangular selection (i.e. to select text in a
rectangular block with the mouse)'''))

o('select_by_word_characters', ':@-./_~?&=%+#', long_text=_('''
Characters considered part of a word when double clicking. In addition to these characters
any character that is marked as an alpha-numeric character in the unicode
database will be matched.'''))

o('click_interval', -1.0, option_type=float, long_text=_('''
The interval between successive clicks to detect double/triple clicks (in seconds).
Negative numbers will use the system default instead, if available, or fallback to 0.5.'''))

o('mouse_hide_wait', 3.0, option_type=positive_float, long_text=_('''
Hide mouse cursor after the specified number of seconds
of the mouse not being used. Set to zero to disable mouse cursor hiding.'''))

o('focus_follows_mouse', False, long_text=_('''
Set the active window to the window under the mouse when
moving the mouse around'''))

# }}}

g('performance')  # {{{

o('repaint_delay', 10, option_type=positive_int, long_text=_('''
Delay (in milliseconds) between screen updates. Decreasing it, increases
frames-per-second (FPS) at the cost of more CPU usage. The default value
yields ~100 FPS which is more than sufficient for most uses. Note that to
actually achieve 100 FPS you have to either set :opt:`sync_to_monitor` to no
or use a monitor with a high refresh rate.'''))

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

# }}}

g('window')  # {{{
o('remember_window_size', True, long_text=_('''
If enabled, the window size will be remembered so that new instances of kitty
will have the same size as the previous instance. If disabled, the window will
initially have size configured by initial_window_width/height, in pixels. You
can use a suffix of "c" on the width/height values to have them interpreted as
number of cells instead of pixels.
'''))


def window_size(val):
    val = val.lower()
    unit = 'cells' if val.endswith('c') else 'px'
    return positive_int(val.rstrip('c')), unit


o('initial_window_width', '640', option_type=window_size)
o('initial_window_height', '400', option_type=window_size)


def to_layout_names(raw):
    parts = [x.strip().lower() for x in raw.split(',')]
    ans = []
    for p in parts:
        if p in ('*', 'all'):
            ans.extend(sorted(all_layouts))
            continue
        name = p.partition(':')[0]
        if name not in all_layouts:
            raise ValueError('The window layout {} is unknown'.format(p))
        ans.append(p)
    return uniq(ans)


o('enabled_layouts', '*', option_type=to_layout_names, long_text=_('''
The enabled window layouts. A comma separated list of layout names. The special
value :code:`all` means all layouts. The first listed layout will be used as the
startup layout. For a list of available layouts, see the :ref:`layouts`.
'''))

o('window_resize_step_cells', 2, option_type=positive_int, long_text=_('''
The step size (in units of cell width/cell height) to use when resizing
windows. The cells value is used for horizontal resizing and the lines value
for vertical resizing.
'''))
o('window_resize_step_lines', 2, option_type=positive_int)

o('window_border_width', 1.0, option_type=positive_float, long_text=_('''
The width (in pts) of window borders. Will be rounded to the nearest number of pixels based on screen resolution.
Note that borders are displayed only when more than one window is visible. They are meant to separate multiple windows.'''))

o('draw_minimal_borders', True, long_text=_('''
Draw only the minimum borders needed. This means that only the minimum
needed borders for inactive windows are drawn. That is only the borders
that separate the inactive window from a neighbor. Note that setting
a non-zero window margin overrides this and causes all borders to be drawn.
'''))

o('window_margin_width', 0.0, option_type=positive_float, long_text=_('''
The window margin (in pts) (blank area outside the border)'''))

o('single_window_margin_width', -1000.0, option_type=float, long_text=_('''
The window margin (in pts) to use when only a single window is visible.
Negative values will cause the value of :opt:`window_margin_width` to be used instead.'''))

o('window_padding_width', 0.0, option_type=positive_float, long_text=_('''
The window padding (in pts) (blank area between the text and the window border)'''))

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

o('hide_window_decorations', False, long_text=_('''
Hide the window decorations (title-bar and window borders).
Whether this works and exactly what effect it has depends on the
window manager/operating system.
'''))
# }}}

g('tabbar')   # {{{
default_tab_separator = ' ┇'


def tab_separator(x):
    for q in '\'"':
        if x.startswith(q) and x.endswith(q):
            x = x[1:-1]
            break
    if not x.strip():
        x = ('\xa0' * len(x)) if x else default_tab_separator
    return x


def tab_bar_edge(x):
    return {'top': 1, 'bottom': 3}.get(x.lower(), 3)


def tab_font_style(x):
    return {
        'bold-italic': (True, True),
        'bold': (True, False),
        'italic': (False, True)
    }.get(x.lower().replace('_', '-'), (False, False))


o('tab_bar_edge', 'bottom', option_type=tab_bar_edge, long_text=_('''
Which edge to show the tab bar on, top or bottom'''))

o('tab_bar_margin_width', 0.0, option_type=positive_float, long_text=_('''
The margin to the left and right of the tab bar (in pts)'''))

o('tab_bar_style', 'fade', option_type=choices('fade', 'separator', 'hidden'), long_text=_('''
The tab bar style, can be one of: :code:`fade`, :code:`separator` or :code:`hidden`. In the fade style,
each tab's edges fade into the background color, in the separator style, tabs are
separated by a configurable separator.
'''))

o('tab_bar_min_tabs', 2, option_type=lambda x: max(1, positive_int(x)), long_text=_('''
The minimum number of tabs that must exist before the tab bar is shown
'''))

o('tab_switch_strategy', 'previous', option_type=choices('previous', 'left', 'last'), long_text=_('''
The algorithm to use when switching to a tab when the current tab is closed.
The default of :code:`previous` will switch to the last used tab. A value of
:code:`left` will switch to the tab to the left of the closed tab. A value
of :code:`last` will switch to the right-most tab.
'''))


def tab_fade(x):
    return tuple(map(unit_float, x.split()))


o('tab_fade', '0.25 0.5 0.75 1', option_type=tab_fade, long_text=_('''
Control how each tab fades into the background when using :code:`fade` for the
:opt:`tab_bar_style`. Each number is an alpha (between zero and one) that controls
how much the corresponding cell fades into the background, with zero being no fade
and one being full fade. You can change the number of cells used by adding/removing
entries to this list.
'''))

o('tab_separator', '"{}"'.format(default_tab_separator), option_type=tab_separator, long_text=_('''
The separator between tabs in the tab bar when using :code:`separator` as the :opt:`tab_bar_style`.'''))

o('tab_title_template', '{title}', long_text=_('''
A template to render the tab title. The default just renders
the title. If you wish to include the tab-index as well,
use something like: :code:`{index}: {title}`. Useful
if you have shortcuts mapped for :code:`goto_tab N`.
'''))

o('active_tab_foreground', '#000', option_type=to_color, long_text=_('''
Tab bar colors and styles'''))
o('active_tab_background', '#eee', option_type=to_color)
o('active_tab_font_style', 'bold-italic', option_type=tab_font_style)
o('inactive_tab_foreground', '#444', option_type=to_color)
o('inactive_tab_background', '#999', option_type=to_color)
o('inactive_tab_font_style', 'normal', option_type=tab_font_style)

# }}}

g('colors')  # {{{

o('foreground',       '#dddddd', option_type=to_color, long_text=_('''
The foreground and background colors'''))
o('background',       '#000000', option_type=to_color)

o('background_opacity', 1.0, option_type=unit_float, long_text=_('''
The opacity of the background. A number between 0 and 1, where 1 is opaque and
0 is fully transparent.  This will only work if supported by the OS (for
instance, when using a compositor under X11). Note that it only sets the
default background color's opacity. This is so that things like the status bar
in vim, powerline prompts, etc. still look good.  But it means that if you use
a color theme with a background color in your editor, it will not be rendered
as transparent.  Instead you should change the default background color in your
kitty config and not use a background color in the editor color scheme. Or use
the escape codes to set the terminals default colors in a shell script to
launch your editor.  Be aware that using a value less than 1.0 is a (possibly
significant) performance hit.  If you want to dynamically change transparency
of windows set dynamic_background_opacity to yes (this is off by default as it
has a performance cost)
'''))
o('dynamic_background_opacity', False)

o('dim_opacity', 0.75, option_type=unit_float, long_text=_('''
How much to dim text that has the DIM/FAINT attribute set. One means no dimming and
zero means fully dimmed (i.e. invisible).'''))


def selection_foreground(x):
    if x.lower() != 'none':
        return to_color(x)


o('selection_foreground', '#000000', option_type=selection_foreground, long_text=_('''
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
A value of . means to use the environment variable EDITOR. Note that this
environment variable has to be set not just in your shell startup scripts but
system-wide, otherwise kitty will not see it.
'''))

o('close_on_child_death', False, long_text=_('''
Close the window when the child process (shell) exits. If no (the default), the
terminal will remain open when the child exits as long as there are still
processes outputting to the terminal (for example disowned or backgrounded
processes). If yes, the window will close as soon as the child process exits.
Note that setting it to yes means that any background processes still using the
terminal can fail silently because their stdout/stderr/stdin no longer work.
'''))

o('allow_remote_control', False, long_text=_('''
Allow other programs to control kitty. If you turn this on other programs can
control all aspects of kitty, including sending text to kitty windows,
opening new windows, closing windows, reading the content of windows, etc.
Note that this even works over ssh connections.
'''))

o(
    '+env', '',
    add_to_default=False,
    long_text=_('''
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


def startup_session(x):
    if x.lower() == 'none':
        return
    x = os.path.expanduser(x)
    x = os.path.expandvars(x)
    if not os.path.isabs(x):
        x = os.path.join(config_dir, x)
    return x


o('startup_session', 'none', option_type=startup_session, long_text=_('''
Path to a session file to use for all kitty instances. Can be overridden
by using the :option:`kitty --session` command line option for individual
instances. See :ref:`sessions` in the kitty documentation for details. Note
that relative paths are interpreted with respect to the kitty config directory.
Environment variables in the path are expanded.
'''))

o('clipboard_control', 'write-clipboard write-primary', option_type=lambda x: frozenset(x.lower().split()), long_text=_('''
Allow programs running in kitty to read and write from the clipboard. You can
control exactly which actions are allowed. The set of possible actions is:
write-clipboard read-clipboard write-primary read-primary. You can
additionally specify no-append to disable kitty's protocol extension
for clipboard concatenation. The default is to allow writing to the
clipboard and primary selection with concatenation enabled. Note
that enabling the read functionality is a security risk as it means that any
program, even one running on a remote server via SSH can read your clipboard.
'''))

o('term', 'xterm-kitty', long_text=_('''
The value of the TERM environment variable to set. Changing this can break many
terminal programs, only change it if you know what you are doing, not because
you read some advice on Stack Overflow to change it. The TERM variable if used
by various programs to get information about the capabilities and behavior of
the terminal. If you change it, depending on what programs you run, and how
different the terminal you are changing it to is, various things from
key-presses, to colors, to various advanced features may not work.
'''))

# }}}

g('os')  # {{{


def macos_titlebar_color(x):
    x = x.strip('"')
    if x == 'system':
        return 0
    if x == 'background':
        return 1
    return (color_as_int(to_color(x)) << 8) | 2


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


def macos_option_as_alt(x):
    x = x.lower()
    if x == 'both':
        return 0b11
    if x == 'left':
        return 0b10
    if x == 'right':
        return 0b01
    if to_bool(x):
        return 0b11
    return 0


o('macos_option_as_alt', 'no', option_type=macos_option_as_alt, long_text=_('''
Use the option key as an alt key. With this set to :code:`no`, kitty will use
the macOS native :kbd:`Option+Key` = unicode character behavior. This will
break any :kbd:`Alt+key` keyboard shortcuts in your terminal programs, but you
can use the macOS unicode input technique. You can use the values:
:code:`left`, :code:`right`, or :code:`both` to use only the left, right or
both Option keys as Alt, instead.
'''))

o('macos_hide_from_tasks', False, long_text=_('''
Hide the kitty window from running tasks (:kbd:`Option+Tab`) on macOS.
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

o('macos_show_window_title_in_menubar', True, long_text=_('''
Show the title of the currently active window in the macOS
menu-bar, making use of otherwise wasted space.'''))

# Disabled by default because of https://github.com/kovidgoyal/kitty/issues/794
o('macos_custom_beam_cursor', False, long_text=_('''
Enable/disable custom mouse cursor for macOS that is easier to see on both
light and dark backgrounds. WARNING: this might make your mouse cursor
invisible on dual GPU machines.'''))
# }}}

g('shortcuts')  # {{{

o('kitty_mod', 'ctrl+shift', option_type=to_modifiers, long_text=_('''
The value of :code:`kitty_mod` is used as the modifier for all default shortcuts, you
can change it in your kitty.conf to change the modifiers for all the default
shortcuts.'''))

o('clear_all_shortcuts', False, long_text=_('''
You can have kitty remove all shortcut definition seen up to this point. Useful, for
instance, to remove the default shortcuts.'''))

g('shortcuts.clipboard')  # {{{
k('copy_to_clipboard', 'kitty_mod+c', 'copy_to_clipboard', _('Copy to clipboard'), long_text=_('''
There is also a :code:`copy_or_interrupt` action that can be optionally mapped to :kbd:`Ctrl+c`.
It will copy only if there is a selection and send an interrupt otherwise.'''))
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
you can specify your own, for example::

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
:file:`STDIN` to an arbitrary program using the ``pipe`` function. For example,
the following opens the scrollback buffer in less in an overlay window::

    map f1 pipe @ansi overlay less +G -R

For more details on piping screen and buffer contents to external programs,
see :doc:`pipe`.
'''))


# }}}

g('shortcuts.window')  # {{{
k('new_window', 'kitty_mod+enter', 'new_window', _(''), long_text=_('''
You can open a new window running an arbitrary program, for example::

    map kitty_mod+y      new_window mutt

You can open a new window with the current working directory set to the
working directory of the current window using::

    map ctrl+alt+enter    new_window_with_cwd

You can open a new window that is allowed to control kitty via
the kitty remote control facility by prefixing the command line with @.
Any programs running in that window will be allowed to control kitty.
For example::

    map ctrl+enter new_window @ some_program
'''))
if is_macos:
    k('new_window', 'cmd+enter', 'new_window', _('New window'), add_to_docs=False)
k('new_os_window', 'kitty_mod+n', 'new_os_window', _('New OS window'))
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
    k('next_tab', 'ctrl+tab', 'next_tab', _('Next tab'), add_to_docs=False)
    k('next_tab', 'shift+cmd+]', 'next_tab', _('Next tab'), add_to_docs=False)
k('previous_tab', 'kitty_mod+left', 'previous_tab', _('Previous tab'))
if is_macos:
    k('previous_tab', 'shift+ctrl+tab', 'previous_tab', _('Previous tab'), add_to_docs=False)
    k('previous_tab', 'shift+cmd+[', 'previous_tab', _('Previous tab'), add_to_docs=False)
k('new_tab', 'kitty_mod+t', 'new_tab', _('New tab'))
if is_macos:
    k('new_tab', 'cmd+t', 'new_tab', _('New tab'), add_to_docs=False)
k('close_tab', 'kitty_mod+q', 'close_tab', _('Close tab'))
if is_macos:
    k('close_tab', 'cmd+w', 'close_tab', _('Close tab'), add_to_docs=False)
    #  Not yet implemented
    #  k('close_os_window', 'shift+cmd+w', 'close_os_window', _('Close os window'), add_to_docs=False)
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
if is_macos:
    k('increase_font_size', 'cmd+plus', 'change_font_size all +2.0', _('Increase font size'), add_to_docs=False)
k('decrease_font_size', 'kitty_mod+minus', 'change_font_size all -2.0', _('Decrease font size'))
if is_macos:
    k('decrease_font_size', 'cmd+minus', 'change_font_size all -2.0', _('Decrease font size'), add_to_docs=False)
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

# }}}

g('shortcuts.misc')  # {{{
k('toggle_fullscreen', 'kitty_mod+f11', 'toggle_fullscreen', _('Toggle fullscreen'))
k('input_unicode_character', 'kitty_mod+u', 'kitten unicode_input', _('Unicode input'))
k('edit_config_file', 'kitty_mod+f2', 'edit_config_file', _('Edit config file'))
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

If you want to operate on all windows instead of just the current one, use :italic:`all` instead of :italic`active`.

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

type_map = {o.name: o.option_type for o in all_options.values() if hasattr(o, 'option_type')}
