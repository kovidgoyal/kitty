#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2018, Kovid Goyal <kovid at kovidgoyal.net>


from gettext import gettext as _

from . import fast_data_types as defines
from .conf.definition import option_func
from .conf.utils import (
    positive_float, positive_int, to_cmdline, to_color, unit_float
)
from .fast_data_types import CURSOR_BEAM, CURSOR_BLOCK, CURSOR_UNDERLINE
from .layout import all_layouts
from .utils import log_error

# Utils  {{{
MINIMUM_FONT_SIZE = 4


def to_font_size(x):
    return max(MINIMUM_FONT_SIZE, float(x))


def adjust_line_height(x):
    if x.endswith('%'):
        return float(x[:-1].strip()) / 100.0
    return int(x)


def box_drawing_scale(x):
    ans = tuple(float(x.strip()) for x in x.split(','))
    if len(ans) != 4:
        raise ValueError('Invalid box_drawing scale, must have four entries')
    return ans


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


def url_style(x):
    return url_style.map.get(x, url_style.map['curly'])


url_style.map = dict(
    ((v, i) for i, v in enumerate('none single double curly'.split()))
)

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


def window_size(val):
    val = val.lower()
    unit = 'cells' if val.endswith('c') else 'px'
    return positive_int(val.rstrip('c')), unit


def uniq(vals, result_type=list):
    seen = set()
    seen_add = seen.add
    return result_type(x for x in vals if x not in seen and not seen_add(x))


def to_layout_names(raw):
    parts = [x.strip().lower() for x in raw.split(',')]
    ans = []
    for p in parts:
        if p == '*':
            ans.extend(sorted(all_layouts))
            continue
        name = p.partition(':')[0]
        if name not in all_layouts:
            raise ValueError('The window layout {} is unknown'.format(p))
        ans.append(p)
    return uniq(ans)


all_options = {}


o, g, all_groups = option_func(all_options, {
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
})
type_map = {o.name: o.option_type for o in all_options.values()}
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

o('font_size', 11.0, long_text=_('Font size (in pts)'), option_type=to_font_size)

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
o('cursor_shape', 'block', option_type=to_cursor_shape, long_text=_(
    'The cursor shape can be one of (block, beam, underline)'))
o('cursor_blink_interval', 0.5, option_type=positive_float, long_text=_('''
The interval (in seconds) at which to blink the cursor. Set to zero to disable
blinking. Note that numbers smaller than :opt:`repaint_delay` will be limited
to :opt:`repaint_delay`. Stop blinking cursor after the specified number of
seconds of keyboard inactivity. Set to zero to never stop blinking.
'''))
o('cursor_stop_blinking_after', 15.0, option_type=positive_float)

# }}}

g('scrollback')  # {{{

o('scrollback_lines', 2000, option_type=positive_int, long_text=_('''
Number of lines of history to keep in memory for scrolling back. Memory is allocated
on demand.'''))

o('scrollback_pager', 'less +G -R', option_type=to_cmdline, long_text=_('''
Program with which to view scrollback in a new window. The scrollback buffer is
passed as STDIN to this program. If you change it, make sure the program you
use can handle ANSI escape sequences for colors and text formatting.'''))

o('wheel_scroll_multiplier', 5.0, long_text=_('''
Modify the amount scrolled by the mouse wheel or touchpad. Use
negative numbers to change scroll direction.'''))
# }}}

g('mouse')  # {{{

o('url_color', '#0087BD', option_type=to_color, long_text=_('''
The color and style for highlighting URLs on mouse-over.
:code:`url_style` can be one of: none, single, double, curly'''))

o('url_style', 'curly', option_type=url_style)

o('open_url_modifiers', 'kitty_mod', option_type=to_modifiers, long_text=_('''
The modifier keys to press when clicking with the
mouse on URLs to open the URL'''))

o('open_url_with', 'default', option_type=to_cmdline, long_text=_('''
The program with which to open URLs that are clicked on.
The special value :code:`default` means to use the
operating system's default URL handler.'''))

o('copy_on_select', False, long_text=_('''
Copy to clipboard on select. With this enabled, simply selecting text with
the mouse will cause the text to be copied to clipboard. Useful on platforms
such as macOS/Wayland that do not have the concept of primary selections. Note
that this is a security risk, as all programs, including websites open in your
browser can read the contents of the clipboard.'''))

o('rectangle_select_modifiers', 'ctrl+alt', option_type=to_modifiers, long_text=_('''
The modifiers to use rectangular selection (i.e. to select text in a
rectangular block with the mouse)'''))

o('select_by_word_characters', ':@-./_~?&=%+#', long_text=_('''
Characters considered part of a word when double clicking. In addition to these characters
any character that is marked as an alpha-numeric character in the unicode
database will be matched.'''))

o('click_interval', 0.5, option_type=positive_float, long_text=_('''
The interval between successive clicks to detect
double/triple clicks (in seconds)'''))

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
o('initial_window_width', '640', option_type=window_size)
o('initial_window_height', '400', option_type=window_size)

o('enabled_layouts', '*', option_type=to_layout_names, long_text=_('''
The enabled window layouts. A comma separated list of layout names. The special
value :code:`*` means all layouts. The first listed layout will be used as the
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

o('window_margin_width', 0.0, option_type=positive_float, long_text=_('''
The window margin (in pts) (blank area outside the border)'''))

o('window_padding_width', 0.0, option_type=positive_float, long_text=_('''
The window padding (in pts) (blank area between the text and the window border)'''))

o('active_border_color', '#00ff00', option_type=to_color, long_text=_('''
The color for the border of the active window'''))

o('inactive_border_color', '#cccccc', option_type=to_color, long_text=_('''
The color for the border of inactive windows'''))

o('bell_border_color', '#ff5a00', option_type=to_color, long_text=_('''
The color for the border of inactive windows in which a bell has occurred'''))

o('inactive_text_alpha', 1.0, option_type=unit_float, long_text=_('''
Fade the text in inactive windows by the specified amount (a number between
zero and one, with zero being fully faded).
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

o('tab_separator', '"{}"'.format(default_tab_separator), option_type=tab_separator, long_text=_('''
The separator between tabs in the tab bar'''))

o('active_tab_foreground', '#000', option_type=to_color, long_text=_('''
Tab bar colors and styles'''))
o('active_tab_background', '#eee', option_type=to_color)
o('active_tab_font_style', 'bold-italic', option_type=tab_font_style)
o('inactive_tab_foreground', '#444', option_type=to_color)
o('inactive_tab_background', '#999', option_type=to_color)
o('inactive_tab_font_style', 'normal', option_type=tab_font_style)

# }}}
