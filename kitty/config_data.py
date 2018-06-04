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
from .rgb import color_as_int, color_as_sharp, color_from_int
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
For a list of key names, see: :link:`GLFW keys <http://www.glfw.org/docs/latest/group__keys.html>`
For a list of modifier names, see: :link:`GLFW mods <http://www.glfw.org/docs/latest/group__mods.html>`

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

o('selection_foreground', '#000000', option_type=to_color, long_text=_('''
The foreground and background for text selected with the mouse'''))
o('selection_background', '#FFFACD', option_type=to_color)

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
    k = 'color{}'.format(i)
    o(k, color_as_sharp(color_from_int(dfctl[i])), option_type=to_color, add_to_docs=False)

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

o('clipboard_control', 'write-clipboard write-primary', option_type=lambda x: frozenset(x.lower().split()), long_text=_('''
Allow programs running in kitty to read and write from the clipboard. You can
control exactly which actions are allowed. The set of possible actions is:
write-clipboard read-clipboard write-primary read-primary
The default is to allow writing to the clipboard and primary selection. Note
that enabling the read functionality is a security risk as it means that any
program, even one running on a remote server via SSH can read your clipboard.
'''))

o('term', 'xterm-kitty', long_text=_('''
The value of the TERM environment variable to set. Changing this can break
many terminal programs, only change it if you know what you are doing, not
because you read some advice on Stack Overflow to change it.
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
probably better off just hiding the titlebar with :opt:`macos_hide_titlebar`.
'''))

o('macos_hide_titlebar', False, long_text=_('''
# Hide the kitty window's title bar on macOS.'''))

o('macos_option_as_alt', True, long_text=_('''
Use the option key as an alt key. With this set to no, kitty will use
the macOS native :kbd:`Option+Key` = unicode character behavior. This will
break any :kbd:`Alt+key` keyboard shortcuts in your terminal programs, but you
can use the macOS unicode input technique.
'''))

o('macos_hide_from_tasks', False, long_text=_('''
Hide the kitty window from running tasks (:kbd:`Option+Tab`) on macOS.
'''))


# }}}

g('shortcuts')  # {{{

o('kitty_mod', 'ctrl+shift', option_type=to_modifiers, long_text=_('''
The value of :code:`kitty_mod` is used as the modifier for all default shortcuts, you
can change it in your kitty.conf to change the modifiers for all the default
shortcuts.'''))

o('clear_all_shortcuts', False, long_text=_('''
You can have kitty remove all shortcut definition seen up to this point. Useful, for
instance, to remove the default shortcuts.'''))
# }}}

type_map = {o.name: o.option_type for o in all_options.values()}
