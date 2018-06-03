#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2018, Kovid Goyal <kovid at kovidgoyal.net>


from gettext import gettext as _

from .conf.definition import option_func
from .conf.utils import positive_float, to_color
from .fast_data_types import CURSOR_BEAM, CURSOR_BLOCK, CURSOR_UNDERLINE

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


all_options = {}


o, g, all_groups = option_func(all_options, {
    'fonts': [
        _('Fonts'),
        _('kitty has very powerful font management. You can configure individual\n'
          'font faces and even specify special fonts for particular characters.')
    ],

    'cursor': [
        _('Cursor customization'),
    ],
})
type_map = {o.name: o.option_type for o in all_options.values()}


g('fonts')  # {{{

o(
    'font_family',
    'monospace',
    _('Font family'),
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

o('font_size', 11.0, _('Font size (in pts)'), option_type=to_font_size)

o('adjust_line_height', 0, _('Adjust cell dimensions'), option_type=adjust_line_height, long_text=_('''
Change the size of each character cell kitty renders. You can use either numbers,
which are interpreted as pixels or percentages (number followed by %), which
are interpreted as percentages of the unmodified values. You can use negative
pixels or percentages less than 100% to reduce sizes (but this might cause
rendering artifacts).'''))
o('adjust_column_width', 0, option_type=adjust_line_height)


o(
    '+symbol_map',
    'U+E0A0-U+E0A2,U+E0B0-U+E0B3 PowerlineSymbols',
    _('Font character mapping'),
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
    _('Box drawing line thickness'),
    option_type=box_drawing_scale,
    long_text=_('''
Change the sizes of the lines used for the box drawing unicode characters
These values are in pts. They will be scaled by the monitor DPI to arrive at
a pixel value. There must be four values corresponding to thin, normal, thick,
and very thick lines.
'''))

# }}}

g('cursor')  # {{{

o('cursor', '#cccccc', _('Cursor color'), option_type=to_color)
o('cursor_shape', 'block', _('Cursor shape'), option_type=to_cursor_shape, long_text=_(
    'The cursor shape can be one of (block, beam, underline)'))
o('cursor_blink_interval', 0.5, _('Cursor blink'), option_type=positive_float, long_text=_('''
The interval (in seconds) at which to blink the cursor. Set to zero to disable
blinking. Note that numbers smaller than :conf:`repaint_delay` will be limited
to :conf:`repaint_delay`. Stop blinking cursor after the specified number of
seconds of keyboard inactivity. Set to zero to never stop blinking.
'''))
o('cursor_stop_blinking_after', 15.0, option_type=positive_float)

# }}}
