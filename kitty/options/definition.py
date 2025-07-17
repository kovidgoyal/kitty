#!/usr/bin/env python
# License: GPLv3 Copyright: 2021, Kovid Goyal <kovid at kovidgoyal.net>

# After editing this file run ./gen-config.py to apply the changes

import string

from kitty.conf.types import Action, Definition
from kitty.constants import website_url
from kitty.options.utils import pointer_shape_names

definition = Definition(
    'kitty',
    Action('map', 'parse_map', {'keyboard_modes': 'KeyboardModeMap', 'alias_map': 'AliasMap'},
           ['KeyDefinition', 'kitty.fast_data_types.SingleKey']),
    Action('mouse_map', 'parse_mouse_map', {'mousemap': 'MouseMap'}, ['MouseMapping']),
    has_color_table=True,
)
definition.add_deprecation('deprecated_hide_window_decorations_aliases', 'x11_hide_window_decorations', 'macos_hide_titlebar')
definition.add_deprecation('deprecated_macos_show_window_title_in_menubar_alias', 'macos_show_window_title_in_menubar')
definition.add_deprecation('deprecated_send_text', 'send_text')
definition.add_deprecation('deprecated_adjust_line_height', 'adjust_line_height', 'adjust_column_width', 'adjust_baseline')

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

opt('font_family', 'monospace', option_type='parse_font_spec',
    long_text='''
You can specify different fonts for the bold/italic/bold-italic variants.
The easiest way to select fonts is to run the ``kitten choose-fonts`` command
which will present a nice UI for you to select the fonts you want with previews
and support for selecting variable fonts and font features. If you want to learn
to select fonts manually, read the :ref:`font specification syntax <font_spec_syntax>`.
'''
    )

opt('bold_font', 'auto', option_type='parse_font_spec')

opt('italic_font', 'auto', option_type='parse_font_spec')

opt('bold_italic_font', 'auto', option_type='parse_font_spec')

opt('font_size', '11.0',
    option_type='to_font_size', ctype='double',
    long_text='Font size (in pts).'
    )

opt('force_ltr', 'no',
    option_type='to_bool', ctype='bool',
    long_text='''
kitty does not support BIDI (bidirectional text), however, for RTL scripts,
words are automatically displayed in RTL. That is to say, in an RTL script, the
words "HELLO WORLD" display in kitty as "WORLD HELLO", and if you try to select
a substring of an RTL-shaped string, you will get the character that would be
there had the string been LTR. For example, assuming the Hebrew word
ירושלים, selecting the character that on the screen appears to be ם actually
writes into the selection buffer the character י. kitty's default behavior is
useful in conjunction with a filter to reverse the word order, however, if you
wish to manipulate RTL glyphs, it can be very challenging to work with, so this
option is provided to turn it off. Furthermore, this option can be used with the
command line program :link:`GNU FriBidi
<https://github.com/fribidi/fribidi#executable>` to get BIDI support, because it
will force kitty to always treat the text as LTR, which FriBidi expects for
terminals.
'''
    )

opt('+symbol_map', 'U+E0A0-U+E0A3,U+E0C0-U+E0C7 PowerlineSymbols',
    option_type='symbol_map',
    add_to_default=False,
    long_text='''
Map the specified Unicode codepoints to a particular font. Useful if you need
special rendering for some symbols, such as for Powerline. Avoids the need for
patched fonts. Each Unicode code point is specified in the form ``U+<code
point in hexadecimal>``. You can specify multiple code points, separated by
commas and ranges separated by hyphens. This option can be specified multiple
times. The syntax is::

    symbol_map codepoints Font Family Name
'''
    )

opt('+narrow_symbols', 'U+E0A0-U+E0A3,U+E0C0-U+E0C7 1',
    option_type='narrow_symbols',
    add_to_default=False,
    long_text='''
Usually, for Private Use Unicode characters and some symbol/dingbat characters,
if the character is followed by one or more spaces, kitty will use those extra
cells to render the character larger, if the character in the font has a wide
aspect ratio. Using this option you can force kitty to restrict the specified
code points to render in the specified number of cells (defaulting to one cell).
This option can be specified multiple times. The syntax is::

    narrow_symbols codepoints [optionally the number of cells]
'''
    )


opt('disable_ligatures', 'never',
    option_type='disable_ligatures', ctype='int',
    long_text='''
Choose how you want to handle multi-character ligatures. The default is to
always render them. You can tell kitty to not render them when the cursor is
over them by using :code:`cursor` to make editing easier, or have kitty never
render them at all by using :code:`always`, if you don't like them. The ligature
strategy can be set per-window either using the kitty remote control facility
or by defining shortcuts for it in :file:`kitty.conf`, for example::

    map alt+1 disable_ligatures_in active always
    map alt+2 disable_ligatures_in all never
    map alt+3 disable_ligatures_in tab cursor

Note that this refers to programming ligatures, typically implemented using the
:code:`calt` OpenType feature. For disabling general ligatures, use the
:opt:`font_features` option.
'''
    )

opt('+font_features', 'none', option_type='font_features', ctype='!font_features',
    add_to_default=False, long_text='''
Choose exactly which OpenType features to enable or disable. Note that for the
main fonts, features can be specified when selecting the font using the choose-fonts kitten.
This setting is useful for fallback fonts.

Some fonts might have features worthwhile in a terminal. For example, Fira Code
includes a discretionary feature, :code:`zero`, which in that font changes the
appearance of the zero (0), to make it more easily distinguishable from Ø. Fira
Code also includes other discretionary features known as Stylistic Sets which
have the tags :code:`ss01` through :code:`ss20`.

For the exact syntax to use for individual features, see the
:link:`HarfBuzz documentation
<https://harfbuzz.github.io/harfbuzz-hb-common.html#hb-feature-from-string>`.

Note that this code is indexed by PostScript name, and not the font family. This
allows you to define very precise feature settings; e.g. you can disable a
feature in the italic font but not in the regular font.

On Linux, font features are first read from the FontConfig database and then
this option is applied, so they can be configured in a single, central place.

To get the PostScript name for a font, use the ``fc-scan file.ttf`` command on Linux
or the `Font Book tool on macOS <https://apple.stackexchange.com/questions/79875/how-can-i-get-the-postscript-name-of-a-ttf-font-installed-in-os-x>`__.

Enable alternate zero and oldstyle numerals::

    font_features FiraCode-Retina +zero +onum

Enable only alternate zero in the bold font::

    font_features FiraCode-Bold +zero

Disable the normal ligatures, but keep the :code:`calt` feature which (in this
font) breaks up monotony::

    font_features TT2020StyleB-Regular -liga +calt

In conjunction with :opt:`force_ltr`, you may want to disable Arabic shaping
entirely, and only look at their isolated forms if they show up in a document.
You can do this with e.g.::

    font_features UnifontMedium +isol -medi -fina -init
'''
    )

opt('+modify_font', '',
    option_type='modify_font', ctype='!modify_font',
    add_to_default=False,
    long_text='''
Modify font characteristics such as the position or thickness of the underline
and strikethrough. The modifications can have the suffix :code:`px` for pixels
or :code:`%` for percentage of original value. No suffix means use pts.
For example::

    modify_font underline_position -2
    modify_font underline_thickness 150%
    modify_font strikethrough_position 2px

Additionally, you can modify the size of the cell in which each font glyph is
rendered and the baseline at which the glyph is placed in the cell.
For example::

    modify_font cell_width 80%
    modify_font cell_height -2px
    modify_font baseline 3

Note that modifying the baseline will automatically adjust the underline and
strikethrough positions by the same amount. Increasing the baseline raises
glyphs inside the cell and decreasing it lowers them. Decreasing the cell size
might cause rendering artifacts, so use with care.
''')

opt('box_drawing_scale', '0.001, 1, 1.5, 2',
    option_type='box_drawing_scale', ctype='!box_drawing_scale',
    long_text='''
The sizes of the lines used for the box drawing Unicode characters. These values
are in pts. They will be scaled by the monitor DPI to arrive at a pixel value.
There must be four values corresponding to thin, normal, thick, and very thick
lines.
'''
    )

opt('undercurl_style', 'thin-sparse', ctype='undercurl_style',
    choices=('thin-sparse', 'thin-dense', 'thick-sparse', 'thick-dense'),
    long_text='''
The style with which undercurls are rendered. This option takes the form
:code:`(thin|thick)-(sparse|dense)`. Thin and thick control the thickness of the
undercurl. Sparse and dense control how often the curl oscillates. With sparse
the curl will peak once per character, with dense twice. Changing this
option dynamically via reloading the config or remote control is undefined.
'''
    )


opt('underline_exclusion', '1', option_type='underline_exclusion', ctype='!underline_exclusion', long_text='''
By default kitty renders gaps in underlines when they overlap with descenders
(the parts of letters below the baseline, such as for y, q, p etc.). This option
controls the thickness of the gaps. It can be either a unitless number in which
case it is a fraction of the underline thickness as specified in the font or
it can have a suffix of :code:`px` for pixels or :code:`pt` for points. Set to zero
to disable the gaps. Changing this option dynamically via reloading the config or remote
control is undefined.
''')


opt('text_composition_strategy', 'platform',
    ctype='!text_composition_strategy',
    long_text='''
Control how kitty composites text glyphs onto the background color. The default
value of :code:`platform` tries for text rendering as close to "native" for
the platform kitty is running on as possible.

A value of :code:`legacy` uses the old (pre kitty 0.28) strategy for how glyphs
are composited. This will make dark text on light backgrounds look thicker and
light text on dark backgrounds thinner. It might also make some text appear like
the strokes are uneven.

You can fine tune the actual contrast curve used for glyph composition by
specifying up to two space-separated numbers for this setting.

The first number is the gamma adjustment, which controls the thickness of dark
text on light backgrounds. Increasing the value will make text appear thicker.
The default value for this is :code:`1.0` on Linux and :code:`1.7` on macOS.
Valid values are :code:`0.01` and above. The result is scaled based on the
luminance difference between the background and the foreground. Dark text on
light backgrounds receives the full impact of the curve while light text on dark
backgrounds is affected very little.

The second number is an additional multiplicative contrast. It is percentage
ranging from :code:`0` to :code:`100`. The default value is :code:`0` on Linux
and :code:`30` on macOS.

If you wish to achieve similar looking thickness in light and dark themes, a good way
to experiment is start by setting the value to :code:`1.0 0` and use a dark theme.
Then adjust the second parameter until it looks good. Then switch to a light theme
and adjust the first parameter until the perceived thickness matches the dark theme.
''')

opt('text_fg_override_threshold', '0', option_type='text_fg_override_threshold', long_text='''
A setting to prevent low contrast between foreground and background colors.
Useful when working with applications that use colors that do not contrast
well with your preferred color scheme. The default value is :code:`0`, which means no color overriding is performed.
There are two modes of operation:

A value with the suffix :code:`ratio` represents the minimum accepted contrast ratio between the foreground and background color.
Possible values range from :code:`0.0 ratio` to :code:`21.0 ratio`.
For example, to meet :link:`WCAG level AA <https://en.wikipedia.org/wiki/Web_Content_Accessibility_Guidelines>`
a value of :code:`4.5 ratio` can be provided.
The algorithm is implemented using :link:`HSLuv <https://www.hsluv.org/>` which enables it to change
the perceived lightness of a color just as much as needed without really changing its hue and saturation.

A value with the suffix :code:`%` represents the minimum accepted difference in luminance
between the foreground and background color, below which kitty will override the foreground color.
It is percentage ranging from :code:`0 %` to :code:`100 %`. If the difference in luminance of the
foreground and background is below this threshold, the foreground color will be set
to white if the background is dark or black if the background is light.

WARNING: Some programs use characters (such as block characters) for graphics
display and may expect to be able to set the foreground and background to the
same color (or similar colors). If you see unexpected stripes, dots, lines,
incorrect color, no color where you expect color, or any kind of graphic
display problem try setting :opt:`text_fg_override_threshold` to :code:`0` to
see if this is the cause of the problem or consider using the :code:`ratio` mode of operation
described above instead of the :code:`%` mode of operation.
''')

egr()  # }}}


# cursor {{{
agr('cursor', 'Text cursor customization')

opt('cursor', '#cccccc',
    option_type='to_color_or_none',
    long_text='''
Default text cursor color. If set to the special value :code:`none` the cursor will
be rendered with a "reverse video" effect. Its color will be the color of the
text in the cell it is over and the text will be rendered with the background
color of the cell. Note that if the program running in the terminal sets a
cursor color, this takes precedence. Also, the cursor colors are modified if
the cell background and foreground colors have very low contrast. Note that some
themes set this value, so if you want to override it, place your value after
the lines where the theme file is included.
'''
    )

opt('cursor_text_color', '#111111',
    option_type='cursor_text_color',
    long_text='''
The color of text under the cursor. If you want it rendered with the
background color of the cell underneath instead, use the special keyword:
`background`. Note that if :opt:`cursor` is set to :code:`none` then this option
is ignored. Note that some themes set this value, so if you want to override it,
place your value after the lines where the theme file is included.
'''
    )

opt('cursor_shape', 'block',
    option_type='to_cursor_shape', ctype='int',
    long_text='''
The cursor shape can be one of :code:`block`, :code:`beam`, :code:`underline`.
Note that when reloading the config this will be changed only if the cursor
shape has not been set by the program running in the terminal. This sets the
default cursor shape, applications running in the terminal can override it. In
particular, :ref:`shell integration <shell_integration>` in kitty sets the
cursor shape to :code:`beam` at shell prompts. You can avoid this by setting
:opt:`shell_integration` to :code:`no-cursor`.
'''
    )

opt('cursor_shape_unfocused', 'hollow', option_type='to_cursor_unfocused_shape', ctype='int', long_text='''
Defines the text cursor shape when the OS window is not focused. The unfocused
cursor shape can be one of :code:`block`, :code:`beam`, :code:`underline`,
:code:`hollow` and :code:`unchanged` (leave the cursor shape as it is).
''')

opt('cursor_beam_thickness', '1.5',
    option_type='positive_float', ctype='float',
    long_text='The thickness of the beam cursor (in pts).'
    )

opt('cursor_underline_thickness', '2.0',
    option_type='positive_float', ctype='float',
    long_text='The thickness of the underline cursor (in pts).'
    )

opt('cursor_blink_interval', '-1', option_type='cursor_blink_interval', ctype='!cursor_blink_interval', long_text='''
The interval to blink the cursor (in seconds). Set to zero to disable blinking.
Negative values mean use system default. Note that the minimum interval will be
limited to :opt:`repaint_delay`. You can also animate the cursor blink by specifying
an :term:`easing function`. For example, setting this to option to :code:`0.5 ease-in-out`
will cause the cursor blink to be animated over a second, in the first half of the second
it will go from opaque to transparent and then back again over the next half. You can specify
different easing functions for the two halves, for example: :code:`-1 linear ease-out`. kitty
supports all the :link:`CSS easing functions <https://developer.mozilla.org/en-US/docs/Web/CSS/easing-function>`.
Note that turning on animations uses extra power as it means the screen is redrawn multiple times
per blink interval. See also, :opt:`cursor_stop_blinking_after`.
'''
    )

opt('cursor_stop_blinking_after', '15.0',
    option_type='positive_float', ctype='time',
    long_text='''
Stop blinking cursor after the specified number of seconds of keyboard
inactivity. Set to zero to never stop blinking.
'''
    )

opt('cursor_trail', '0',
    option_type='positive_int', ctype='time-ms',
    long_text='''
Set this to a value larger than zero to enable a "cursor trail" animation.
This is an animation that shows a "trail" following the movement of the text cursor.
It makes it easy to follow large cursor jumps and makes for a cool visual effect
of the cursor zooming around the screen. The actual value of this option
controls when the animation is triggered. It is a number of milliseconds. The
trail animation only follows cursors that have stayed in their position for longer
than the specified number of milliseconds. This prevents trails from appearing
for cursors that rapidly change their positions during UI updates in complex applications.
See :opt:`cursor_trail_decay` to control the animation speed and :opt:`cursor_trail_start_threshold`
to control when a cursor trail is started.
'''
    )

opt('cursor_trail_decay', '0.1 0.4',
    option_type='cursor_trail_decay',
    ctype='!cursor_trail_decay',
    long_text='''
Controls the decay times for the cursor trail effect when the :opt:`cursor_trail`
is enabled. This option accepts two positive float values specifying the
fastest and slowest decay times in seconds. The first value corresponds to the
fastest decay time (minimum), and the second value corresponds to the slowest
decay time (maximum). The second value must be equal to or greater than the
first value. Smaller values result in a faster decay of the cursor trail.
Adjust these values to control how quickly the cursor trail fades away.
''',
    )

opt('cursor_trail_start_threshold', '2',
    option_type='positive_int', ctype='int',
    long_text='''
Set the distance threshold for starting the cursor trail. This option accepts a
positive integer value that represents the minimum number of cells the
cursor must move before the trail is started. When the cursor moves less than
this threshold, the trail is skipped, reducing unnecessary cursor trail
animation.
'''
    )

opt('cursor_trail_color', 'none',
    option_type='to_color_or_none',
    ctype='!cursor_trail_color',
    long_text='''
Set the color of the cursor trail when :opt:`cursor_trail` is enabled.
If set to 'none' (the default), the cursor trail will use the cursor's
background color. Otherwise, specify a color value (e.g., #ff0000 for red,
or a named color like 'red'). This allows you to customize the appearance
of the cursor trail independently of the cursor color.
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

opt('scrollback_indicator_opacity', '1.0',
    option_type='unit_float', ctype='float', long_text='''
The opacity of the scrollback indicator which is a small colored rectangle that moves
along the right hand side of the window as you scroll, indicating what fraction you
have scrolled. The default is one which means fully opaque, aka visible.
Set to a value between zero and one to make the indicator less visible.''')


opt('scrollback_pager', 'less --chop-long-lines --RAW-CONTROL-CHARS +INPUT_LINE_NUMBER',
    option_type='to_cmdline',
    long_text='''
Program with which to view scrollback in a new window. The scrollback buffer is
passed as STDIN to this program. If you change it, make sure the program you use
can handle ANSI escape sequences for colors and text formatting.
INPUT_LINE_NUMBER in the command line above will be replaced by an integer
representing which line should be at the top of the screen. Similarly
CURSOR_LINE and CURSOR_COLUMN will be replaced by the current cursor position or
set to 0 if there is no cursor, for example, when showing the last command
output.
'''
    )

opt('scrollback_pager_history_size', '0',
    option_type='scrollback_pager_history_size', ctype='uint',
    long_text='''
Separate scrollback history size (in MB), used only for browsing the scrollback
buffer with pager. This separate buffer is not available for interactive
scrolling but will be piped to the pager program when viewing scrollback buffer
in a separate window. The current implementation stores the data in UTF-8, so
approximately 10000 lines per megabyte at 100 chars per line, for pure ASCII,
unformatted text. A value of zero or less disables this feature. The maximum
allowed size is 4GB. Note that on config reload if this is changed it will only
affect newly created windows, not existing ones.
'''
    )

opt('scrollback_fill_enlarged_window', 'no',
    option_type='to_bool', ctype='bool',
    long_text='Fill new space with lines from the scrollback buffer after enlarging a window.'
    )

opt('wheel_scroll_multiplier', '5.0',
    option_type='float', ctype='double',
    long_text='''
Multiplier for the number of lines scrolled by the mouse wheel. Note that this
is only used for low precision scrolling devices, not for high precision
scrolling devices on platforms such as macOS and Wayland. Use negative numbers
to change scroll direction. See also :opt:`wheel_scroll_min_lines`.
'''
    )

opt('wheel_scroll_min_lines', '1',
    option_type='int', ctype='int',
    long_text='''
The minimum number of lines scrolled by the mouse wheel. The :opt:`scroll
multiplier <wheel_scroll_multiplier>` only takes effect after it reaches this
number. Note that this is only used for low precision scrolling devices like
wheel mice that scroll by very small amounts when using the wheel. With a
negative number, the minimum number of lines will always be added.
'''
    )

opt('touch_scroll_multiplier', '1.0',
    option_type='float', ctype='double',
    long_text='''
Multiplier for the number of lines scrolled by a touchpad. Note that this is
only used for high precision scrolling devices on platforms such as macOS and
Wayland. Use negative numbers to change scroll direction.
'''
    )
egr()  # }}}


# mouse {{{
agr('mouse', 'Mouse')

opt('mouse_hide_wait', '3.0',
    macos_default='0.0',
    option_type='mouse_hide_wait', ctype='!mouse_hide_wait',
    long_text='''
Hide mouse cursor after the specified number of seconds of the mouse not being
used. Set to zero to disable mouse cursor hiding. Set to a negative value to
hide the mouse cursor immediately when typing text. Disabled by default on macOS
as getting it to work robustly with the ever-changing sea of bugs that is Cocoa
is too much effort.

By default, once the cursor is hidden, it is immediately unhidden on any
further mouse events.

Two formats are supported:
 - :code:`<hide-wait>`
 - :code:`<hide-wait> <unhide-wait> <unhide-threshold> <scroll-unhide>`

To change the unhide behavior, the optional parameters :code:`<unhide-wait>`,
:code:`<unhide-threshold>`, and :code:`<scroll-unhide>` may be set.

:code:`<unhide-wait>`
    Waits for the specified number of seconds after mouse events before unhiding the
    mouse cursor. Set to zero to unhide mouse cursor immediately on mouse activity.
    This is useful to prevent the mouse cursor from unhiding on accidental swipes on
    the trackpad.

:code:`<unhide-threshold>`
    Sets the threshold of mouse activity required to unhide the mouse cursor, when
    the <unhide-wait> option is non-zero. When <unhide-wait> is zero, this has no
    effect.

    For example, if :code:`<unhide-threshold>` is 40 and :code:`<unhide-wait>` is 2.5, when kitty
    detects a mouse event, it records the number of mouse events in the next 2.5
    seconds, and checks if that exceeds 40 * 2.5 = 100. If it does, then the mouse
    cursor is unhidden, otherwise nothing happens.

:code:`<scroll-unhide>`
    Controls what mouse events may unhide the mouse cursor. If enabled, both scroll
    and movement events may unhide the cursor. If disabled, only mouse movements can
    unhide the cursor.

Examples of valid values:
 - :code:`0.0`
 - :code:`1.0`
 - :code:`-1.0`
 - :code:`0.1 3.0 40 yes`
'''
    )

opt('url_color', '#0087bd',
    option_type='to_color', ctype='color_as_int',
    long_text='''
The color and style for highlighting URLs on mouse-over. :opt:`url_style` can
be one of: :code:`none`, :code:`straight`, :code:`double`, :code:`curly`,
:code:`dotted`, :code:`dashed`.
'''
    )

opt('url_style', 'curly',
    option_type='url_style', ctype='uint',
    )

opt('open_url_with', 'default',
    option_type='to_cmdline',
    long_text='''
The program to open clicked URLs. The special value :code:`default` will first
look for any URL handlers defined via the :doc:`open_actions` facility and if
non are found, it will use the Operating System's default URL handler
(:program:`open` on macOS and :program:`xdg-open` on Linux).
'''
    )

opt('url_prefixes', 'file ftp ftps gemini git gopher http https irc ircs kitty mailto news sftp ssh',
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
are still clickable. See also the :opt:`underline_hyperlinks` option to control
how hyperlinks (as opposed to plain text URLs) are displayed.
'''
    )

opt('url_excluded_characters', '',
    option_type='python_string', ctype='!url_excluded_characters',
    long_text='''
Additional characters to be disallowed from URLs, when detecting URLs under the
mouse cursor. By default, all characters that are legal in URLs are allowed.
Additionally, newlines are allowed (but stripped). This is to accommodate
programs such as mutt that add hard line breaks even for continued lines.
:code:`\\\\n` can be added to this option to disable this behavior. Special
characters can be specified using backslash escapes, to specify a backslash use
a double backslash.
'''
    )

opt('show_hyperlink_targets', 'no',
    option_type='to_bool', ctype='bool',
    long_text='''
When the mouse hovers over a terminal hyperlink, show the actual URL that will
be activated when the hyperlink is clicked.
''')


opt('underline_hyperlinks', 'hover', choices=('hover', 'always', 'never'),
    ctype='underline_hyperlinks', long_text='''
Control how hyperlinks are underlined. They can either be underlined on mouse
:code:`hover`, :code:`always` (i.e. permanently underlined) or :code:`never` which means
that kitty will not apply any underline styling to hyperlinks. Note that the value of :code:`always`
only applies to real (OSC 8) hyperlinks not text that is detected to be a URL on mouse hover.
Uses the :opt:`url_style` and :opt:`url_color` settings for the underline style. Note
that reloading the config and changing this value to/from :code:`always` will only
affect text subsequently received by kitty.
''')


opt('copy_on_select', 'no',
    option_type='copy_on_select',
    long_text='''
Copy to clipboard or a private buffer on select. With this set to
:code:`clipboard`, selecting text with the mouse will cause the text to be
copied to clipboard. Useful on platforms such as macOS that do not have the
concept of primary selection. You can instead specify a name such as :code:`a1`
to copy to a private kitty buffer. Map a shortcut with the
:code:`paste_from_buffer` action to paste from this private buffer.
For example::

    copy_on_select a1
    map shift+cmd+v paste_from_buffer a1

Note that copying to the clipboard is a security risk, as all programs,
including websites open in your browser can read the contents of the system
clipboard.
'''
    )

opt('clear_selection_on_clipboard_loss', 'no', option_type='to_bool', long_text='''
When the contents of the clipboard no longer reflect the current selection, clear it.
This is primarily useful on platforms such as Linux where selecting text automatically
copies it to a special "primary selection" clipboard or if you have :opt:`copy_on_select`
set to :code:`clipboard`.

Note that on macOS the system does not provide notifications when the clipboard owner
is changed, so there, copying to clipboard in a non-kitty application will not clear
selections even if :opt:`copy_on_select` is enabled.
''')

opt('paste_actions', 'quote-urls-at-prompt,confirm',
    option_type='paste_actions',
    long_text='''
A comma separated list of actions to take when pasting text into the terminal.
The supported paste actions are:

:code:`quote-urls-at-prompt`:
    If the text being pasted is a URL and the cursor is at a shell prompt,
    automatically quote the URL (needs :opt:`shell_integration`).
:code:`replace-dangerous-control-codes`
    Replace dangerous control codes from pasted text, without confirmation.
:code:`replace-newline`
    Replace the newline character from pasted text, without confirmation.
:code:`confirm`:
    Confirm the paste if the text to be pasted contains any terminal control codes
    as this can be dangerous, leading to code execution if the shell/program running
    in the terminal does not properly handle these.
:code:`confirm-if-large`
    Confirm the paste if it is very large (larger than 16KB) as pasting
    large amounts of text into shells can be very slow.
:code:`filter`:
    Run the filter_paste() function from the file :file:`paste-actions.py` in
    the kitty config directory on the pasted text. The text returned by the
    function will be actually pasted.
:code:`no-op`:
    Has no effect.
'''
    )

opt('strip_trailing_spaces', 'never',
    choices=('always', 'never', 'smart'),
    long_text='''
Remove spaces at the end of lines when copying to clipboard. A value of
:code:`smart` will do it when using normal selections, but not rectangle
selections. A value of :code:`always` will always do it.
'''
    )

opt('select_by_word_characters', '@-./_~?&=%+#',
    ctype='!select_by_word_characters',
    long_text='''
Characters considered part of a word when double clicking. In addition to these
characters any character that is marked as an alphanumeric character in the
Unicode database will be matched.
'''
    )

opt('select_by_word_characters_forward', '',
    ctype='!select_by_word_characters_forward',
    long_text='''
Characters considered part of a word when extending the selection forward on
double clicking. In addition to these characters any character that is marked
as an alphanumeric character in the Unicode database will be matched.

If empty (default) :opt:`select_by_word_characters` will be used for both
directions.
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
Set the active window to the window under the mouse when moving the mouse around.
On macOS, this will also cause the OS Window under the mouse to be focused automatically when the
mouse enters it.
'''
    )

opt('pointer_shape_when_grabbed', 'arrow',
    choices=pointer_shape_names, ctype='pointer_shape',
    long_text='''
The shape of the mouse pointer when the program running in the terminal grabs
the mouse.
'''
    )

opt('default_pointer_shape', 'beam',
    choices=pointer_shape_names, ctype='pointer_shape',
    long_text='''
The default shape of the mouse pointer.
'''
    )

opt('pointer_shape_when_dragging', 'beam crosshair', option_type='pointer_shape_when_dragging', ctype='!dragging_pointer_shape', long_text='''
The default shape of the mouse pointer when dragging across text. The optional second value
sets the shape when dragging in rectangular selection mode.
'''
    )


# mouse.mousemap {{{
agr('mouse.mousemap', 'Mouse actions', '''
Mouse buttons can be mapped to perform arbitrary actions. The syntax is:

.. code-block:: none

    mouse_map button-name event-type modes action

Where :code:`button-name` is one of :code:`left`, :code:`middle`, :code:`right`,
:code:`b1` ... :code:`b8` with added keyboard modifiers. For example:
:code:`ctrl+shift+left` refers to holding the :kbd:`Ctrl+Shift` keys while
clicking with the left mouse button. The value :code:`b1` ... :code:`b8` can be
used to refer to up to eight buttons on a mouse.

:code:`event-type` is one of :code:`press`, :code:`release`,
:code:`doublepress`, :code:`triplepress`, :code:`click`, :code:`doubleclick`.
:code:`modes` indicates whether the action is performed when the mouse is
grabbed by the program running in the terminal, or not. The values are
:code:`grabbed` or :code:`ungrabbed` or a comma separated combination of them.
:code:`grabbed` refers to when the program running in the terminal has requested
mouse events. Note that the click and double click events have a delay of
:opt:`click_interval` to disambiguate from double and triple presses.

You can run kitty with the :option:`kitty --debug-input` command line option
to see mouse events. See the builtin actions below to get a sense of what is
possible.

If you want to unmap a button, map it to nothing. For example, to disable
opening of URLs with a plain click::

    mouse_map left click ungrabbed

See all the mappable actions including mouse actions :doc:`here </actions>`.

.. note::
    Once a selection is started, releasing the button that started it will
    automatically end it and no release event will be dispatched.
''')

opt('clear_all_mouse_actions', 'no',
    option_type='clear_all_mouse_actions',
    long_text='''
Remove all mouse action definitions up to this point. Useful, for instance, to
remove the default mouse actions.
'''
    )

mma('Click the link under the mouse or move the cursor',
    'click_url_or_select left click ungrabbed mouse_handle_click selection link prompt',
    long_text='''
First check for a selection and if one exists do nothing. Then check for a link
under the mouse cursor and if one exists, click it. Finally check if the click
happened at the current shell prompt and if so, move the cursor to the click
location. Note that this requires :ref:`shell integration <shell_integration>`
to work.
'''
    )

mma('Click the link under the mouse or move the cursor even when grabbed',
    'click_url_or_select_grabbed shift+left click grabbed,ungrabbed mouse_handle_click selection link prompt',
    long_text='''
Same as above, except that the action is performed even when the mouse is
grabbed by the program running in the terminal.
'''
    )

mma('Click the link under the mouse cursor',
    'click_url ctrl+shift+left release grabbed,ungrabbed mouse_handle_click link',
    long_text='''
Variant with :kbd:`Ctrl+Shift` is present because the simple click based version
has an unavoidable delay of :opt:`click_interval`, to disambiguate clicks from
double clicks.
'''
    )

mma('Discard press event for link click',
    'click_url_discard ctrl+shift+left press grabbed discard_event',
    long_text='''
Prevent this press event from being sent to the program that has grabbed the
mouse, as the corresponding release event is used to open a URL.
'''
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
    )

mma('Select line from point',
    'select_line_from_point ctrl+alt+left triplepress ungrabbed mouse_selection line_from_point',
    long_text='Select from the clicked point to the end of the line.'
    ' If you would like to select the word at the point and then extend to the rest of the line,'
    ' change `line_from_point` to `word_and_line_from_point`.'
    )

mma('Extend the current selection',
    'extend_selection right press ungrabbed mouse_selection extend',
    long_text='''
If you want only the end of the selection to be moved instead of the nearest
boundary, use :code:`move-end` instead of :code:`extend`.
'''
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
    )

mma('Select line from point even when grabbed',
    'select_line_from_point_grabbed ctrl+shift+alt+left triplepress ungrabbed,grabbed mouse_selection line_from_point',
    long_text='Select from the clicked point to the end of the line even when grabbed.'
    ' If you would like to select the word at the point and then extend to the rest of the line,'
    ' change `line_from_point` to `word_and_line_from_point`.'
    )

mma('Extend the current selection even when grabbed',
    'extend_selection_grabbed shift+right press ungrabbed,grabbed mouse_selection extend',
    )

mma('Show clicked command output in pager',
    'show_clicked_cmd_output_ungrabbed ctrl+shift+right press ungrabbed mouse_show_command_output',
    long_text='Requires :ref:`shell integration <shell_integration>` to work.'
    )
egr()  # }}}
egr()  # }}}


# performance {{{
agr('performance', 'Performance tuning')

opt('repaint_delay', '10',
    option_type='positive_int', ctype='time-ms',
    long_text='''
Delay between screen updates (in milliseconds). Decreasing it, increases
frames-per-second (FPS) at the cost of more CPU usage. The default value yields
~100 FPS which is more than sufficient for most uses. Note that to actually
achieve 100 FPS, you have to either set :opt:`sync_to_monitor` to :code:`no` or
use a monitor with a high refresh rate. Also, to minimize latency when there is
pending input to be processed, this option is ignored.
'''
    )

opt('input_delay', '3',
    option_type='positive_int', ctype='time-ms',
    long_text='''
Delay before input from the program running in the terminal is processed (in
milliseconds). Note that decreasing it will increase responsiveness, but also
increase CPU usage and might cause flicker in full screen programs that redraw
the entire screen on each loop, because kitty is so fast that partial screen
updates will be drawn. This setting is ignored when the input buffer is almost full.
'''
    )

opt('sync_to_monitor', 'yes',
    option_type='to_bool', ctype='bool',
    long_text='''
Sync screen updates to the refresh rate of the monitor. This prevents
:link:`screen tearing <https://en.wikipedia.org/wiki/Screen_tearing>` when
scrolling. However, it limits the rendering speed to the refresh rate of your
monitor. With a very high speed mouse/high keyboard repeat rate, you may notice
some slight input latency. If so, set this to :code:`no`.
'''
    )
egr()  # }}}


# bell {{{
agr('bell', 'Terminal bell')

opt('enable_audio_bell', 'yes',
    option_type='to_bool', ctype='bool',
    long_text='''
The audio bell. Useful to disable it in environments that require silence.
'''
    )

opt('visual_bell_duration', '0.0',
    option_type='visual_bell_duration', ctype='!visual_bell_duration',
    long_text='''
The visual bell duration (in seconds). Flash the screen when a bell occurs for
the specified number of seconds. Set to zero to disable. The flash is animated, fading
in and out over the specified duration. The :term:`easing function` used for the fading can be controlled.
For example, :code:`2.0 linear` will casuse the flash to fade in and out linearly. The default
if unspecified is to use :code:`ease-in-out` which fades slowly at the start, middle and end.
You can specify different easing functions for the fade-in and fade-out parts, like this:
:code:`2.0 ease-in linear`. kitty
supports all the :link:`CSS easing functions <https://developer.mozilla.org/en-US/docs/Web/CSS/easing-function>`.
'''
    )

opt('visual_bell_color', 'none',
    option_type='to_color_or_none',
    long_text='''
The color used by visual bell. Set to :code:`none` will fall back to selection
background color. If you feel that the visual bell is too bright, you can
set it to a darker color.
'''
    )

opt('window_alert_on_bell', 'yes',
    option_type='to_bool', ctype='bool',
    long_text='''
Request window attention on bell. Makes the dock icon bounce on macOS or the
taskbar flash on Linux.
'''
    )

opt('bell_on_tab', '"🔔 "',
    option_type='bell_on_tab',
    long_text='''
Some text or a Unicode symbol to show on the tab if a window in the tab that
does not have focus has a bell. If you want to use leading or trailing
spaces, surround the text with quotes. See :opt:`tab_title_template` for how
this is rendered.

For backwards compatibility, values of :code:`yes`, :code:`y` and :code:`true`
are converted to the default bell symbol and :code:`no`, :code:`n`,
:code:`false` and :code:`none` are converted to the empty string.
'''
    )

opt('command_on_bell', 'none',
    option_type='to_cmdline',
    long_text='''
Program to run when a bell occurs. The environment variable
:envvar:`KITTY_CHILD_CMDLINE` can be used to get the program running in the
window in which the bell occurred.
'''
    )

opt('bell_path', 'none',
    option_type='config_or_absolute_path', ctype='!bell_path',
    long_text='''
Path to a sound file to play as the bell sound. If set to :code:`none`, the
system default bell sound is used. Must be in a format supported by the
operating systems sound API, such as WAV or OGA on Linux (libcanberra) or AIFF,
MP3 or WAV on macOS (NSSound). Relative paths are resolved
with respect to the kitty config directory.
'''
    )

opt('linux_bell_theme', '__custom', ctype='!bell_theme',
    long_text='''
The XDG Sound Theme kitty will use to play the bell sound.
On Wayland, when the compositor supports it, it is asked to play the system default
bell sound, and this setting has no effect. Note that Hyprland claims to support this
protocol, but :link:`does not actually play a sound <https://github.com/hyprwm/Hyprland/issues/10488>`.
This setting defaults to the custom theme name specified in the
:link:`XDG Sound theme specification <https://specifications.freedesktop.org/sound-theme-spec/latest/sound_lookup.html>,
falling back to the default freedesktop theme if it does not exist.
To change your sound theme desktop wide, create :file:`~/.local/share/sounds/__custom/index.theme` with the contents:

    [Sound Theme]

    Inherits=name-of-the-sound-theme-you-want-to-use

Replace :code:`name-of-the-sound-theme-you-want-to-use` with the actual theme name. Now all compliant applications
should use sounds from this theme.
''')

egr()  # }}}


# window {{{
agr('window', 'Window layout')

opt('remember_window_size', 'yes',
    option_type='to_bool',
    long_text='''
If enabled, the :term:`OS Window <os_window>` size will be remembered so that
new instances of kitty will have the same size as the previous instance.
If disabled, the :term:`OS Window <os_window>` will initially have size
configured by initial_window_width/height, in pixels. You can use a suffix of
"c" on the width/height values to have them interpreted as number of cells
instead of pixels.
'''
    )

opt('initial_window_width', '640',
    option_type='window_size',
    )

opt('initial_window_height', '400',
    option_type='window_size',
    )

opt('remember_window_position', 'no',
    option_type='to_bool',
    long_text='''
If enabled, the :term:`OS Window <os_window>` position will be remembered so that
new instances of kitty will have the same position as the previous instance.
If disabled, the :term:`OS Window <os_window>` will be placed by the window manager.
Note that remembering of position only works if the underlying desktop environment/window
manager supports it. It never works on Wayland. See also :option:`kitty --position` to
specify the position when launching kitty.
'''
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
The step size (in units of cell width/cell height) to use when resizing kitty
windows in a layout with the shortcut :sc:`start_resizing_window`. The cells
value is used for horizontal resizing, and the lines value is used for vertical
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
If not specified, the unit is assumed to be pts. Note that borders are displayed
only when more than one window is visible. They are meant to separate multiple
windows.
'''
    )

opt('draw_minimal_borders', 'yes',
    option_type='to_bool',
    long_text='''
Draw only the minimum borders needed. This means that only the borders that
separate the window from a neighbor are drawn. Note that setting a
non-zero :opt:`window_margin_width` overrides this and causes all borders to be
drawn.
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
The window margin to use when only a single window is visible (in pts). Negative
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

opt('single_window_padding_width', '-1',
    option_type='optional_edge_width',
    long_text='''
The window padding to use when only a single window is visible (in pts). Negative
values will cause the value of :opt:`window_padding_width` to be used instead. A
single value sets all four sides. Two values set the vertical and horizontal
sides. Three values set top, horizontal and bottom. Four values set top, right,
bottom and left.
'''
    )

opt('placement_strategy', 'center',
    choices=('top-left', 'top', 'top-right', 'left', 'center', 'right', 'bottom-left', 'bottom', 'bottom-right'),
    long_text='''
When the window size is not an exact multiple of the cell size, the cell area of
the terminal window will have some extra padding on the sides. You can control
how that padding is distributed with this option. Using a value of
:code:`center` means the cell area will be placed centrally. A value of
:code:`top-left` means the padding will be only at the bottom and right edges.
The value can be one of: :code:`top-left`, :code:`top`, :code:`top-right`,
:code:`left`, :code:`center`, :code:`right`, :code:`bottom-left`,
:code:`bottom`, :code:`bottom-right`.
'''
    )

opt('active_border_color', '#00ff00',
    option_type='to_color_or_none', ctype='active_border_color',
    long_text='''
The color for the border of the active window. Set this to :code:`none` to not
draw borders around the active window.
'''
    )

opt('inactive_border_color', '#cccccc',
    option_type='to_color', ctype='color_as_int',
    long_text='The color for the border of inactive windows.'
    )

opt('bell_border_color', '#ff5a00',
    option_type='to_color', ctype='color_as_int',
    long_text='The color for the border of inactive windows in which a bell has occurred.'
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
macOS, :code:`titlebar-only` and :code:`titlebar-and-corners` can be used to only hide the titlebar and the rounded corners.
Whether this works and exactly what effect it has depends on the window manager/operating
system. Note that the effects of changing this option when reloading config
are undefined. When using :code:`titlebar-only`, it is useful to also set
:opt:`window_margin_width` and :opt:`placement_strategy` to prevent the rounded
corners from clipping text. Or use :code:`titlebar-and-corners`.
'''
    )

opt('window_logo_path', 'none',
    option_type='config_or_absolute_path', ctype='!window_logo_path',
    long_text='''
Path to a logo image. Must be in PNG/JPEG/WEBP/GIF/TIFF/BMP format. Relative paths are interpreted
relative to the kitty config directory. The logo is displayed in a corner of
every kitty window. The position is controlled by :opt:`window_logo_position`.
Individual windows can be configured to have different logos either using the
:ac:`launch` action or the :doc:`remote control <remote-control>` facility.
'''
    )

opt('window_logo_position', 'bottom-right',
    choices=('top-left', 'top', 'top-right', 'left', 'center', 'right', 'bottom-left', 'bottom', 'bottom-right'),
    ctype='bganchor',
    long_text='''
Where to position the window logo in the window. The value can be one of:
:code:`top-left`, :code:`top`, :code:`top-right`, :code:`left`, :code:`center`,
:code:`right`, :code:`bottom-left`, :code:`bottom`, :code:`bottom-right`.
'''
    )

opt('window_logo_alpha', '0.5',
    option_type='unit_float', ctype='float',
    long_text='''
The amount the logo should be faded into the background. With zero being fully
faded and one being fully opaque.
'''
    )

opt('window_logo_scale', '0', option_type='window_logo_scale', ctype='!window_logo_scale', long_text='''
The percentage (0-100] of the window size to which the logo should scale. Using a single
number means the logo is scaled to that percentage of the shortest window dimension, while preserving
aspect ratio of the logo image.

Using two numbers means the width and height of the logo are scaled to the respective
percentage of the window's width and height.

Using zero as the percentage disables scaling in that dimension. A single zero (the default)
disables all scaling of the window logo.
''')

opt('resize_debounce_time', '0.1 0.5',
    option_type='resize_debounce_time', ctype='!resize_debounce_time',
    long_text='''
The time to wait (in seconds) before asking the program running in kitty to resize and
redraw the screen during a live resize of the OS window, when no new resize
events have been received, i.e. when resizing is either paused or finished.
On platforms such as macOS, where the operating system sends events corresponding
to the start and end of a live resize, the second number is used for
redraw-after-pause since kitty can distinguish between a pause and end of
resizing. On such systems the first number is ignored and redraw is immediate
after end of resize. On other systems only the first number is used so that kitty
is "ready" quickly after the end of resizing, while not also continuously
redrawing, to save energy.
'''
    )

opt('resize_in_steps', 'no',
    option_type='to_bool', ctype='bool',
    long_text='''
Resize the OS window in steps as large as the cells, instead of with the usual
pixel accuracy. Combined with :opt:`initial_window_width` and
:opt:`initial_window_height` in number of cells, this option can be used to keep
the margins as small as possible when resizing the OS window. Note that this
does not currently work on Wayland.
'''
    )

opt('visual_window_select_characters', defval=string.digits[1:] + '0' + string.ascii_uppercase,
    option_type='visual_window_select_characters',
    long_text=r'''
The list of characters for visual window selection. For example, for selecting a
window to focus on with :sc:`focus_visible_window`. The value should be a series
of unique numbers or alphabets, case insensitive, from the set :code:`0-9A-Z\`-=[];',./\\`.
Specify your preference as a string of characters.
'''
    )

opt('confirm_os_window_close', '-1', option_type='confirm_close', long_text='''
Ask for confirmation when closing an OS window or a tab with at least this
number of kitty windows in it by window manager (e.g. clicking the window close
button or pressing the operating system shortcut to close windows) or by the
:ac:`close_tab` action. A value of zero disables confirmation. This confirmation
also applies to requests to quit the entire application (all OS windows, via the
:ac:`quit` action). Negative values are converted to positive ones, however,
with :opt:`shell_integration` enabled, using negative values means windows
sitting at a shell prompt are not counted, only windows where some command is
currently running. You can also have backgrounded jobs prevent closing,
by adding :code:`count-background` to the setting, for example: :code:`-1 count-background`.
Note that if you want confirmation when closing individual windows,
you can map the :ac:`close_window_with_confirmation` action.
''')
egr()  # }}}


# tabbar {{{
agr('tabbar', 'Tab bar')

opt('tab_bar_edge', 'bottom',
    option_type='tab_bar_edge', ctype='int',
    long_text='The edge to show the tab bar on, :code:`top` or :code:`bottom`.'
    )

opt('tab_bar_margin_width', '0.0',
    option_type='positive_float',
    long_text='The margin to the left and right of the tab bar (in pts).'
    )

opt('tab_bar_margin_height', '0.0 0.0',
    option_type='tab_bar_margin_height', ctype='!tab_bar_margin_height',
    long_text='''
The margin above and below the tab bar (in pts). The first number is the margin
between the edge of the OS Window and the tab bar. The second number is the
margin between the tab bar and the contents of the current tab.
'''
    )

opt('tab_bar_style', 'fade',
    choices=('fade', 'hidden', 'powerline', 'separator', 'slant', 'custom'),
    ctype='!tab_bar_style',
    long_text='''
The tab bar style, can be one of:

:code:`fade`
    Each tab's edges fade into the background color. (See also :opt:`tab_fade`)
:code:`slant`
    Tabs look like the tabs in a physical file.
:code:`separator`
    Tabs are separated by a configurable separator. (See also
    :opt:`tab_separator`)
:code:`powerline`
    Tabs are shown as a continuous line with "fancy" separators.
    (See also :opt:`tab_powerline_style`)
:code:`custom`
    A user-supplied Python function called draw_tab is loaded from the file
    :file:`tab_bar.py` in the kitty config directory. For examples of how to
    write such a function, see the functions named :code:`draw_tab_with_*` in
    kitty's source code: :file:`kitty/tab_bar.py`. See also
    :disc:`this discussion <4447>`
    for examples from kitty users.
:code:`hidden`
    The tab bar is hidden. If you use this, you might want to create
    a mapping for the :ac:`select_tab` action which presents you with a list of
    tabs and allows for easy switching to a tab.
'''
    )

opt('tab_bar_align', 'left',
    choices=('left', 'center', 'right'),
    long_text='''
The horizontal alignment of the tab bar, can be one of: :code:`left`,
:code:`center`, :code:`right`.
'''
    )

opt('tab_bar_min_tabs', '2',
    option_type='tab_bar_min_tabs', ctype='uint',
    long_text='The minimum number of tabs that must exist before the tab bar is shown.'
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
:code:`slanted`, :code:`round`.
'''
    )

opt('tab_activity_symbol', 'none',
    option_type='tab_activity_symbol',
    long_text='''
Some text or a Unicode symbol to show on the tab if a window in the tab that
does not have focus has some activity. If you want to use leading or trailing
spaces, surround the text with quotes. See :opt:`tab_title_template` for how
this is rendered.
'''
    )

opt('tab_title_max_length', '0',
    option_type='positive_int',
    long_text='''
The maximum number of cells that can be used to render the text in a tab.
A value of zero means that no limit is applied.
'''
    )

opt('tab_title_template', '"{fmt.fg.red}{bell_symbol}{activity_symbol}{fmt.fg.tab}{tab.last_focused_progress_percent}{title}"',
    option_type='tab_title_template',
    long_text='''
A template to render the tab title. The default just renders the title with
optional symbols for bell and activity. If you wish to include the tab-index as
well, use something like: :code:`{index}:{title}`. Useful if you have shortcuts
mapped for :code:`goto_tab N`. If you prefer to see the index as a superscript,
use :code:`{sup.index}`. All data available is:

:code:`title`
    The current tab title.
:code:`index`
    The tab index usable with :ac:`goto_tab N <goto_tab>` shortcuts.
:code:`layout_name`
    The current layout name.
:code:`num_windows`
    The number of windows in the tab.
:code:`num_window_groups`
    The number of window groups (a window group is a window and all of its overlay windows) in the tab.
:code:`tab.active_wd`
    The working directory of the currently active window in the tab
    (expensive, requires syscall). Use :code:`tab.active_oldest_wd` to get
    the directory of the oldest foreground process rather than the newest.
:code:`tab.active_exe`
    The name of the executable running in the foreground of the currently
    active window in the tab (expensive, requires syscall). Use
    :code:`tab.active_oldest_exe` for the oldest foreground process.
:code:`max_title_length`
    The maximum title length available.
:code:`keyboard_mode`
    The name of the current :ref:`keyboard mode <modal_mappings>` or the empty string if no keyboard mode is active.
:code:`tab.last_focused_progress_percent`
    If a command running in a window reports the progress for a task, show this progress as a percentage
    from the most recently focused window in the tab. Empty string if no progress is reported.
:code:`tab.progress_percent`
    If a command running in a window reports the progress for a task, show this progress as a percentage
    from all windows in the tab, averaged. Empty string is no progress is reported.

Note that formatting is done by Python's string formatting machinery, so you can
use, for instance, :code:`{layout_name[:2].upper()}` to show only the first two
letters of the layout name, upper-cased. If you want to style the text, you can
use styling directives, for example:
``{fmt.fg.red}red{fmt.fg.tab}normal{fmt.bg._00FF00}greenbg{fmt.bg.tab}``.
Similarly, for bold and italic:
``{fmt.bold}bold{fmt.nobold}normal{fmt.italic}italic{fmt.noitalic}``.
The 256 eight terminal colors can be used as ``fmt.fg.color0`` through ``fmt.fg.color255``.
Note that for backward compatibility, if :code:`{bell_symbol}` or
:code:`{activity_symbol}` are not present in the template, they are prepended to
it.
'''
    )

opt('active_tab_title_template', 'none',
    option_type='active_tab_title_template',
    long_text='''
Template to use for active tabs. If not specified falls back to
:opt:`tab_title_template`.
'''
    )

opt('active_tab_foreground', '#000',
    option_type='to_color',
    long_text='Tab bar colors and styles.'
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
color for margins above and below the tab bar. For side margins the default
color is chosen to match the background color of the neighboring tab.
'''
    )
egr()  # }}}


# colors {{{
agr('colors', 'Color scheme')

opt('foreground', '#dddddd',
    option_type='to_color', ctype='color_as_int',
    long_text='The foreground and background colors.'
    )

opt('background', '#000000',
    option_type='to_color', ctype='color_as_int',
    )

opt(
    'background_opacity',
    '1.0',
    option_type='unit_float',
    ctype='float',
    long_text="""
The opacity of the background. A number between zero and one, where one is
opaque and zero is fully transparent. This will only work if supported by the
OS (for instance, when using a compositor under X11). Note that it only sets
the background color's opacity in cells that have the same background color as
the default terminal background, so that things like the status bar in vim,
powerline prompts, etc. still look good. But it means that if you use a color
theme with a background color in your editor, it will not be rendered as
transparent. Instead you should change the default background color in your
kitty config and not use a background color in the editor color scheme. Or use
the escape codes to set the terminals default colors in a shell script to
launch your editor. See also :opt:`transparent_background_colors`.
Be aware that using a value less than 1.0 is a (possibly
significant) performance hit. When using a low value for this setting, it is
desirable that you set the :opt:`background` color to a color the matches the
general color of the desktop background, for best text rendering. Note that
to workaround window managers not doing gamma-corrected blending kitty
makes background_opacity non-linear which means, especially for light backgrounds
you might need to make the value much lower than you expect to get good results,
see :iss:`6218` for details.

If you want to dynamically change transparency of windows, set
:opt:`dynamic_background_opacity` to :code:`yes` (this is off by default as it
has a performance cost). Changing this option when reloading the config will
only work if :opt:`dynamic_background_opacity` was enabled in the original
config.
""",
)

opt('background_blur', '0', option_type='int', ctype='int',
    long_text='''
Set to a positive value to enable background blur (blurring of the visuals
behind a transparent window) on platforms that support it. Only takes effect
when :opt:`background_opacity` is less than one. On macOS, this will also
control the :italic:`blur radius` (amount of blurring). Setting it to too high
a value will cause severe performance issues and/or rendering artifacts.
Usually, values up to 64 work well. Note that this might cause performance issues,
depending on how the platform implements it, so use with care. Currently supported
on macOS and KDE.
''')

opt('transparent_background_colors', '', option_type='transparent_background_colors', long_text='''
A space separated list of upto 7 colors, with opacity. When the background color of a cell matches one of these colors,
it is rendered semi-transparent using the specified opacity.

Useful in more complex UIs like editors where you could want more than a single background color
to be rendered as transparent, for instance, for a cursor highlight line background or a highlighted block.
Terminal applications can set this color using :ref:`The kitty color control <color_control>`
escape code.

The syntax for specifying colors is: :code:`color@opacity`, where the :code:`@opacity`
part is optional. When unspecified, the value of :opt:`background_opacity` is used. For example::

    transparent_background_colors red@0.5 #00ff00@0.3

'''
)

opt('dynamic_background_opacity', 'no',
    option_type='to_bool', ctype='bool',
    long_text='''
Allow changing of the :opt:`background_opacity` dynamically, using either
keyboard shortcuts (:sc:`increase_background_opacity` and
:sc:`decrease_background_opacity`) or the remote control facility. Changing
this option by reloading the config is not supported.
'''
    )


opt('background_image', 'none',
    option_type='config_or_absolute_path', ctype='!background_image',
    long_text='Path to a background image. Must be in PNG/JPEG/WEBP/TIFF/GIF/BMP format.'
    ' Note that when using :ref:`auto_color_scheme` this option is overridden by the color scheme file and must be set inside it to take effect.'
    )

opt('background_image_layout', 'tiled',
    choices=('mirror-tiled', 'scaled', 'tiled', 'clamped', 'centered', 'cscaled'),
    ctype='bglayout',
    long_text='''
Whether to tile, scale or clamp the background image. The value can be one of
:code:`tiled`, :code:`mirror-tiled`, :code:`scaled`, :code:`clamped`, :code:`centered`
or :code:`cscaled`. The :code:`scaled` and :code:`cscaled` values scale the image to the
window size, with :code:`cscaled` preserving the image aspect ratio.
Note that when using :ref:`auto_color_scheme` this option is overridden by the color scheme file and must be set inside it to take effect.
'''
    )

opt('background_image_linear', 'no',
    option_type='to_bool', ctype='bool',
    long_text='When background image is scaled, whether linear interpolation should be used.'
' Note that when using :ref:`auto_color_scheme` this option is overridden by the color scheme file and must be set inside it to take effect.'
    )

opt('background_tint', '0.0',
    option_type='unit_float', ctype='float',
    long_text='''
How much to tint the background image by the background color. This option
makes it easier to read the text. Tinting is done using the current background
color for each window. This option applies only if :opt:`background_opacity` is
set and transparent windows are supported or :opt:`background_image` is set.
Note that when using :ref:`auto_color_scheme` this option is overridden by the color scheme file and must be set inside it to take effect.
'''
    )

opt('background_tint_gaps', '1.0',
    option_type='unit_float', ctype='float',
    long_text='''
How much to tint the background image at the window gaps by the background
color, after applying :opt:`background_tint`. Since this is multiplicative
with :opt:`background_tint`, it can be used to lighten the tint over the window
gaps for a *separated* look.
Note that when using :ref:`auto_color_scheme` this option is overridden by the color scheme file and must be set inside it to take effect.
'''
    )

opt('dim_opacity', '0.4',
    option_type='unit_float', ctype='float',
    long_text='''
How much to dim text that has the DIM/FAINT attribute set. One means no dimming
and zero means fully dimmed (i.e. invisible).
'''
    )

opt('selection_foreground', '#000000',
    option_type='to_color_or_none',
    long_text='''
The foreground and background colors for text selected with the mouse. Setting
both of these to :code:`none` will cause a "reverse video" effect for
selections, where the selection will be the cell text color and the text will
become the cell background color. Setting only selection_foreground to
:code:`none` will cause the foreground color to be used unchanged. Note that
these colors can be overridden by the program running in the terminal.
'''
    )

opt('selection_background', '#fffacd',
    option_type='to_color_or_none',
    )


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
    option_type='to_color',
    long_text='Color for marks of type 1'
    )

opt('mark1_background', '#98d3cb',
    option_type='to_color',
    long_text='Color for marks of type 1 (light steel blue)'
    )

opt('mark2_foreground', 'black',
    option_type='to_color',
    long_text='Color for marks of type 2'
    )

opt('mark2_background', '#f2dcd3',
    option_type='to_color',
    long_text='Color for marks of type 1 (beige)'
    )

opt('mark3_foreground', 'black',
    option_type='to_color',
    long_text='Color for marks of type 3'
    )

opt('mark3_background', '#f274bc',
    option_type='to_color',
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
The shell program to execute. The default value of :code:`.` means to use
the value of of the :envvar:`SHELL` environment variable or if unset,
whatever shell is set as the default shell for the current user. Note that on
macOS if you change this, you might need to add :code:`--login` and
:code:`--interactive` to ensure that the shell starts in interactive mode and
reads its startup rc files. Environment variables are expanded in this setting.
'''
    )

opt('editor', '.',
    long_text='''
The terminal based text editor (such as :program:`vim` or :program:`nano`) to
use when editing the kitty config file or similar tasks.

The default value of :code:`.` means to use the environment variables
:envvar:`VISUAL` and :envvar:`EDITOR` in that order. If these variables aren't
set, kitty will run your :opt:`shell` (:code:`$SHELL -l -i -c env`) to see if
your shell startup rc files set :envvar:`VISUAL` or :envvar:`EDITOR`. If that
doesn't work, kitty will cycle through various known editors (:program:`vim`,
:program:`emacs`, etc.) and take the first one that exists on your system.
'''
    )

opt('close_on_child_death', 'no',
    option_type='to_bool', ctype='bool',
    long_text='''
Close the window when the child process (usually the shell) exits. With the default value
:code:`no`, the terminal will remain open when the child exits as long as there
are still other processes outputting to the terminal (for example disowned or
backgrounded processes). When enabled with :code:`yes`, the window will close as
soon as the child process exits. Note that setting it to :code:`yes` means that
any background processes still using the terminal can fail silently because
their stdout/stderr/stdin no longer work.
'''
    )

opt('+remote_control_password', '',
    option_type='remote_control_password',
    add_to_default=False, has_secret=True,
    long_text='''
Allow other programs to control kitty using passwords. This option can be
specified multiple times to add multiple passwords. If no passwords are present
kitty will ask the user for permission if a program tries to use remote control
with a password. A password can also *optionally* be associated with a set of
allowed remote control actions. For example::

    remote_control_password "my passphrase" get-colors set-colors focus-window focus-tab

Only the specified actions will be allowed when using this password.
Glob patterns can be used too, for example::

    remote_control_password "my passphrase" set-tab-* resize-*

To get a list of available actions, run::

    kitten @ --help

A set of actions to be allowed when no password is sent can be specified by
using an empty password. For example::

    remote_control_password "" *-colors

Finally, the path to a python module can be specified that provides a function
:code:`is_cmd_allowed` that is used to check every remote control command.
For example::

    remote_control_password "my passphrase" my_rc_command_checker.py

Relative paths are resolved from the kitty configuration directory.
See :ref:`rc_custom_auth` for details.
''')

opt('allow_remote_control', 'no',
    choices=('password', 'socket-only', 'socket', 'no', 'n', 'false', 'yes', 'y', 'true'),
    long_text='''
Allow other programs to control kitty. If you turn this on, other programs can
control all aspects of kitty, including sending text to kitty windows, opening
new windows, closing windows, reading the content of windows, etc. Note that
this even works over SSH connections. The default setting of :code:`no`
prevents any form of remote control. The meaning of the various values are:

:code:`password`
    Remote control requests received over both the TTY device and the socket
    are confirmed based on passwords, see :opt:`remote_control_password`.

:code:`socket-only`
    Remote control requests received over a socket are accepted
    unconditionally. Requests received over the TTY are denied.
    See :opt:`listen_on`.

:code:`socket`
    Remote control requests received over a socket are accepted
    unconditionally. Requests received over the TTY are confirmed based on
    password.

:code:`no`
    Remote control is completely disabled.

:code:`yes`
    Remote control requests are always accepted.
'''
    )

opt('listen_on', 'none',
    long_text='''
Listen to the specified socket for remote control connections. Note that this
will apply to all kitty instances. It can be overridden by the :option:`kitty
--listen-on` command line option. For UNIX sockets, such as
:code:`unix:${TEMP}/mykitty` or :code:`unix:@mykitty` (on Linux). Environment
variables are expanded and relative paths are resolved with respect to the
temporary directory. If :code:`{kitty_pid}` is present, then it is replaced by
the PID of the kitty process, otherwise the PID of the kitty process is
appended to the value, with a hyphen. For TCP sockets such as
:code:`tcp:localhost:0` a random port is always used even if a non-zero port
number is specified.  See the help for :option:`kitty --listen-on` for more
details. Note that this will be ignored unless :opt:`allow_remote_control` is
set to either: :code:`yes`, :code:`socket` or :code:`socket-only`.
Changing this option by reloading the config is not supported.
'''
    )

opt('+env', '',
    option_type='env',
    add_to_default=False,
    long_text='''
Specify the environment variables to be set in all child processes. Using the
name with an equal sign (e.g. :code:`env VAR=`) will set it to the empty string.
Specifying only the name (e.g. :code:`env VAR`) will remove the variable from
the child process' environment. Note that environment variables are expanded
recursively, for example::

    env VAR1=a
    env VAR2=${HOME}/${VAR1}/b

The value of :code:`VAR2` will be :code:`<path to home directory>/a/b`.
'''
    )

opt('+filter_notification', '', option_type='filter_notification', add_to_default=False, long_text='''
Specify rules to filter out notifications sent by applications running in kitty.
Can be specified multiple times to create multiple filter rules. A rule specification
is of the form :code:`field:regexp`. A filter rule
can match on any of the fields: :code:`title`, :code:`body`, :code:`app`, :code:`type`.
The special value of :code:`all` filters out all notifications. Rules can be combined
using Boolean operators. Some examples::

    filter_notification title:hello or body:"abc.*def"
    # filter out notification from vim except for ones about updates, (?i)
    # makes matching case insensitive.
    filter_notification app:"[ng]?vim" and not body:"(?i)update"
    # filter out all notifications
    filter_notification all

The field :code:`app` is the name of the application sending the notification and :code:`type`
is the type of the notification. Not all applications will send these fields, so you can also
match on the title and body of the notification text. More sophisticated programmatic filtering
and custom actions on notifications can be done by creating a notifications.py file in the
kitty config directory (:file:`~/.config/kitty`). An annotated sample is
:link:`available <https://github.com/kovidgoyal/kitty/blob/master/docs/notifications.py>`.
''')

opt('+watcher', '',
    option_type='store_multiple',
    add_to_default=False,
    long_text='''
Path to python file which will be loaded for :ref:`watchers`. Can be specified
more than once to load multiple watchers. The watchers will be added to every
kitty window. Relative paths are resolved relative to the kitty config
directory. Note that reloading the config will only affect windows created after
the reload.
'''
    )

opt('+exe_search_path', '',
    option_type='store_multiple',
    add_to_default=False,
    long_text='''
Control where kitty finds the programs to run. The default search order is:
First search the system wide :code:`PATH`, then :file:`~/.local/bin` and
:file:`~/bin`. If still not found, the :code:`PATH` defined in the login shell
after sourcing all its startup files is tried. Finally, if present, the
:code:`PATH` specified by the :opt:`env` option is tried.

This option allows you to prepend, append, or remove paths from this search
order. It can be specified multiple times for multiple paths. A simple path will
be prepended to the search order. A path that starts with the :code:`+` sign
will be append to the search order, after :file:`~/bin` above. A path that
starts with the :code:`-` sign will be removed from the entire search order.
For example::

    exe_search_path /some/prepended/path
    exe_search_path +/some/appended/path
    exe_search_path -/some/excluded/path

'''
    )

opt('update_check_interval', '24',
    option_type='float',
    long_text='''
The interval to periodically check if an update to kitty is available (in
hours). If an update is found, a system notification is displayed informing you
of the available update. The default is to check every 24 hours, set to zero to
disable. Update checking is only done by the official binary builds. Distro
packages or source builds do not do update checking. Changing this option by
reloading the config is not supported.
'''
    )

opt('startup_session', 'none',
    option_type='config_or_absolute_path',
    long_text='''
Path to a session file to use for all kitty instances. Can be overridden by
using the :option:`kitty --session` :code:`=none` command line option for individual
instances. See :ref:`sessions` in the kitty documentation for details. Note that
relative paths are interpreted with respect to the kitty config directory.
Environment variables in the path are expanded. Changing this option by
reloading the config is not supported. Note that if kitty is invoked with command line
arguments specifying a command to run, this option is ignored.
'''
    )

opt('clipboard_control', 'write-clipboard write-primary read-clipboard-ask read-primary-ask',
    option_type='clipboard_control',
    long_text='''
Allow programs running in kitty to read and write from the clipboard. You can
control exactly which actions are allowed. The possible actions are:
:code:`write-clipboard`, :code:`read-clipboard`, :code:`write-primary`,
:code:`read-primary`, :code:`read-clipboard-ask`, :code:`read-primary-ask`. The
default is to allow writing to the clipboard and primary selection and to ask
for permission when a program tries to read from the clipboard. Note that
disabling the read confirmation is a security risk as it means that any program,
even the ones running on a remote server via SSH can read your clipboard. See
also :opt:`clipboard_max_size`.
'''
    )

opt('clipboard_max_size', '512',
    option_type='positive_float',
    long_text='''
The maximum size (in MB) of data from programs running in kitty that will be
stored for writing to the system clipboard. A value of zero means no size limit
is applied. See also :opt:`clipboard_control`.
'''
    )

opt('file_transfer_confirmation_bypass', '', has_secret=True, long_text='''
The password that can be supplied to the :doc:`file transfer kitten
</kittens/transfer>` to skip the transfer confirmation prompt. This should only
be used when initiating transfers from trusted computers, over trusted networks
or encrypted transports, as it allows any programs running on the remote machine
to read/write to the local filesystem, without permission.
'''
    )

opt('allow_hyperlinks', 'yes',
    option_type='allow_hyperlinks', ctype='bool',
    long_text='''
Process :term:`hyperlink <hyperlinks>` escape sequences (OSC 8). If disabled OSC
8 escape sequences are ignored. Otherwise they become clickable links, that you
can click with the mouse or by using the :doc:`hints kitten </kittens/hints>`.
The special value of :code:`ask` means that kitty will ask before opening the
link when clicked.
'''
    )

opt('shell_integration', 'enabled',
    option_type='shell_integration',
    long_text='''
Enable shell integration on supported shells. This enables features such as
jumping to previous prompts, browsing the output of the previous command in a
pager, etc. on supported shells. Set to :code:`disabled` to turn off shell
integration, completely. It is also possible to disable individual features, set
to a space separated list of these values: :code:`no-rc`, :code:`no-cursor`,
:code:`no-title`, :code:`no-cwd`, :code:`no-prompt-mark`, :code:`no-complete`, :code:`no-sudo`.
See :ref:`Shell integration <shell_integration>` for details.
'''
    )

opt('allow_cloning', 'ask',
    choices=('yes', 'y', 'true', 'no', 'n', 'false', 'ask'),
    long_text='''
Control whether programs running in the terminal can request new windows to be
created. The canonical example is :ref:`clone-in-kitty <clone_shell>`. By
default, kitty will ask for permission for each clone request. Allowing cloning
unconditionally gives programs running in the terminal (including over SSH)
permission to execute arbitrary code, as the user who is running the terminal,
on the computer that the terminal is running on.
'''
    )

opt('clone_source_strategies', 'venv,conda,env_var,path',
    option_type='clone_source_strategies',
    long_text='''
Control what shell code is sourced when running :command:`clone-in-kitty`
in the newly cloned window. The supported strategies are:

:code:`venv`
    Source the file :file:`$VIRTUAL_ENV/bin/activate`. This is used by the
    Python stdlib venv module and allows cloning venvs automatically.
:code:`conda`
    Run :code:`conda activate $CONDA_DEFAULT_ENV`. This supports the virtual
    environments created by :program:`conda`.
:code:`env_var`
    Execute the contents of the environment variable
    :envvar:`KITTY_CLONE_SOURCE_CODE` with :code:`eval`.
:code:`path`
    Source the file pointed to by the environment variable
    :envvar:`KITTY_CLONE_SOURCE_PATH`.

This option must be a comma separated list of the above values. Only the
first valid match, in the order specified, is sourced.
'''
    )

opt('notify_on_cmd_finish', 'never', option_type='notify_on_cmd_finish', long_text='''
Show a desktop notification when a long-running command finishes
(needs :opt:`shell_integration`).
The possible values are:

:code:`never`
    Never send a notification.

:code:`unfocused`
    Only send a notification when the window does not have keyboard focus.

:code:`invisible`
    Only send a notification when the window both is unfocused and not visible
    to the user, for example, because it is in an inactive tab or its OS window
    is not currently visible (on platforms that support OS window visibility querying
    this considers an OS Window visible iff it is active).

:code:`always`
    Always send a notification, regardless of window state.

There are two optional arguments:

First, the minimum duration for what is considered a
long running command. The default is 5 seconds. Specify a second argument
to set the duration. For example: :code:`invisible 15`.
Do not set the value too small, otherwise a command that launches a new OS Window
and exits will spam a notification.

Second, the action to perform. The default is :code:`notify`. The possible values are:

:code:`notify`
    Send a desktop notification. The subsequent arguments are optional and specify when
    the notification is automatically cleared. The set of possible events when the notification is
    cleared are: :code:`focus` and :code:`next`. :code:`focus` means that when the notification
    policy is :code:`unfocused` or :code:`invisible` the notification is automatically cleared
    when the window regains focus. The value of :code:`next` means that the previous notification
    is cleared when the next notification is shown. The default when no arguments are specified
    is: :code:`focus next`.

:code:`bell`
    Ring the terminal bell.

:code:`command`
    Run a custom command. All subsequent arguments are the cmdline to run.

Some more examples::

    # Send a notification when a command takes more than 5 seconds in an unfocused window
    notify_on_cmd_finish unfocused
    # Send a notification when a command takes more than 10 seconds in a invisible window
    notify_on_cmd_finish invisible 10.0
    # Ring a bell when a command takes more than 10 seconds in a invisible window
    notify_on_cmd_finish invisible 10.0 bell
    # Run 'notify-send' when a command takes more than 10 seconds in a invisible window
    # Here %c is replaced by the current command line and %s by the job exit code
    notify_on_cmd_finish invisible 10.0 command notify-send "job finished with status: %s" %c
    # Do not clear previous notification when next command finishes or window regains focus
    notify_on_cmd_finish invisible 5.0 notify

'''
    )

opt('term', 'xterm-kitty',
    long_text='''
The value of the :envvar:`TERM` environment variable to set. Changing this can
break many terminal programs, only change it if you know what you are doing, not
because you read some advice on "Stack Overflow" to change it. The
:envvar:`TERM` variable is used by various programs to get information about the
capabilities and behavior of the terminal. If you change it, depending on what
programs you run, and how different the terminal you are changing it to is,
various things from key-presses, to colors, to various advanced features may not
work. Changing this option by reloading the config will only affect newly
created windows.
'''
    )

opt('terminfo_type', 'path', choices=('path', 'direct', 'none'),
    long_text='''
The value of the :envvar:`TERMINFO` environment variable to set. This variable is
used by programs running in the terminal to search for terminfo databases. The default value
of :code:`path` causes kitty to set it to a filesystem location containing the
kitty terminfo database. A value of :code:`direct` means put the entire database into
the env var directly. This can be useful when connecting to containers, for example. But,
note that not all software supports this. A value of :code:`none` means do not touch the variable.
'''
    )


opt('forward_stdio', 'no', option_type='to_bool', long_text='''
Forward STDOUT and STDERR of the kitty process to child processes.
This is useful for debugging as it
allows child processes to print to kitty's STDOUT directly. For example,
:code:`echo hello world >&$KITTY_STDIO_FORWARDED` in a shell will print
to the parent kitty's STDOUT. Sets the :code:`KITTY_STDIO_FORWARDED=fdnum`
environment variable so child processes know about the forwarding. Note that
on macOS this prevents the shell from being run via the login utility so getlogin()
will not work in programs run in this session.
''')

opt('+menu_map', '',
    option_type='menu_map', add_to_default=False, ctype='!menu_map',
    long_text='''
Specify entries for various menus in kitty. Currently only the global menubar on macOS
is supported. For example::

   menu_map global "Actions::Launch something special" launch --hold --type=os-window sh -c "echo hello world"

This will create a menu entry named "Launch something special" in an "Actions" menu in the macOS global menubar.
Sub-menus can be created by adding more levels separated by the :code:`::` characters.
'''
    )


egr()  # }}}


# os {{{
agr('os', 'OS specific tweaks')

opt('wayland_titlebar_color', 'system', option_type='titlebar_color', ctype='uint', long_text='''
The color of the kitty window's titlebar on Wayland systems with client
side window decorations such as GNOME. A value of :code:`system` means to use
the default system colors, a value of :code:`background` means to use the
background color of the currently active kitty window and finally you can use an
arbitrary color, such as :code:`#12af59` or :code:`red`.
'''
    )

opt('macos_titlebar_color', 'system', option_type='macos_titlebar_color', ctype='int', long_text='''
The color of the kitty window's titlebar on macOS. A value of
:code:`system` means to use the default system color, :code:`light` or
:code:`dark` can also be used to set it explicitly. A value of
:code:`background` means to use the background color of the currently active
window and finally you can use an arbitrary color, such as :code:`#12af59` or
:code:`red`. WARNING: This option works by using a hack when arbitrary color (or
:code:`background`) is configured, as there is no proper Cocoa API for it. It
sets the background color of the entire window and makes the titlebar
transparent. As such it is incompatible with :opt:`background_opacity`. If you
want to use both, you are probably better off just hiding the titlebar with
:opt:`hide_window_decorations`.
'''
    )

opt('macos_option_as_alt', 'no',
    option_type='macos_option_as_alt', ctype='uint',
    long_text='''
Use the :kbd:`Option` key as an :kbd:`Alt` key on macOS. With this set to
:code:`no`, kitty will use the macOS native :kbd:`Option+Key` to enter Unicode
character behavior. This will break any :kbd:`Alt+Key` keyboard shortcuts in
your terminal programs, but you can use the macOS Unicode input technique. You
can use the values: :code:`left`, :code:`right` or :code:`both` to use only the
left, right or both :kbd:`Option` keys as :kbd:`Alt`, instead. Note that kitty
itself always treats :kbd:`Option` the same as :kbd:`Alt`. This means you cannot
use this option to configure different kitty shortcuts for :kbd:`Option+Key`
vs. :kbd:`Alt+Key`. Also, any kitty shortcuts using :kbd:`Option/Alt+Key` will
take priority, so that any such key presses will not be passed to terminal
programs running inside kitty. Changing this option by reloading the config is
not supported.
'''
    )

opt('macos_hide_from_tasks', 'no',
    option_type='to_bool', ctype='bool',
    long_text='''
Hide the kitty window from running tasks on macOS (:kbd:`⌘+Tab` and the Dock).
Changing this option by reloading the config is not supported.
'''
    )

opt('macos_quit_when_last_window_closed', 'no',
    option_type='to_bool', ctype='bool',
    long_text='''
Have kitty quit when all the top-level windows are closed on macOS. By default,
kitty will stay running, even with no open windows, as is the expected behavior
on macOS.
'''
    )

opt('macos_window_resizable', 'yes',
    option_type='to_bool', ctype='bool',
    long_text='''
Disable this if you want kitty top-level OS windows to not be resizable on
macOS.
'''
    )

opt('macos_thicken_font', '0',
    option_type='positive_float', ctype='float',
    long_text='''
Draw an extra border around the font with the given width, to increase
legibility at small font sizes on macOS. For example, a value of :code:`0.75`
will result in rendering that looks similar to sub-pixel antialiasing at common
font sizes. Note that in modern kitty, this option is obsolete (although still
supported). Consider using :opt:`text_composition_strategy` instead.
'''
    )

opt('macos_traditional_fullscreen', 'no',
    option_type='to_bool', ctype='bool',
    long_text='''
Use the macOS traditional full-screen transition, that is faster, but less
pretty.
'''
    )

opt('macos_show_window_title_in', 'all',
    choices=('all', 'menubar', 'none', 'window'), ctype='window_title_in',
    long_text='''
Control where the window title is displayed on macOS. A value of :code:`window`
will show the title of the currently active window at the top of the macOS
window. A value of :code:`menubar` will show the title of the currently active
window in the macOS global menu bar, making use of otherwise wasted space. A
value of :code:`all` will show the title in both places, and :code:`none` hides
the title. See :opt:`macos_menubar_title_max_length` for how to control the
length of the title in the menu bar.
'''
    )

opt('macos_menubar_title_max_length', '0',
    option_type='positive_int', ctype='int',
    long_text='''
The maximum number of characters from the window title to show in the macOS
global menu bar. Values less than one means that there is no maximum limit.
'''
    )

opt('macos_custom_beam_cursor', 'no',
    option_type='to_bool',
    long_text='''
Use a custom mouse cursor for macOS that is easier to see on both light
and dark backgrounds. Nowadays, the default macOS cursor already comes with a
white border. WARNING: this might make your mouse cursor invisible on
dual GPU machines. Changing this option by reloading the config is not supported.
'''
    )

opt('macos_colorspace', 'srgb',
    choices=('srgb', 'default', 'displayp3'), ctype='macos_colorspace',
    long_text='''
The colorspace in which to interpret terminal colors. The default of
:code:`srgb` will cause colors to match those seen in web browsers. The value of
:code:`default` will use whatever the native colorspace of the display is.
The value of :code:`displayp3` will use Apple's special snowflake display P3
color space, which will result in over saturated (brighter) colors with some
color shift. Reloading configuration will change this value only for newly
created OS windows.
''')


opt('linux_display_server', 'auto',
    choices=('auto', 'wayland', 'x11'),
    long_text='''
Choose between Wayland and X11 backends. By default, an appropriate backend
based on the system state is chosen automatically. Set it to :code:`x11` or
:code:`wayland` to force the choice. Changing this option by reloading the
config is not supported.
'''
    )

opt('wayland_enable_ime', 'yes', option_type='to_bool', ctype='bool', long_text='''
Enable Input Method Extension on Wayland. This is typically used for
inputting text in East Asian languages. However, its implementation in
Wayland is often buggy and introduces latency into the input loop,
so disable this if you know you dont need it. Changing this option
by reloading the config is not supported, it will not have any effect.
''')
egr()  # }}}


# shortcuts {{{
agr('shortcuts', 'Keyboard shortcuts', '''
Keys are identified simply by their lowercase Unicode characters. For example:
:code:`a` for the :kbd:`A` key, :code:`[` for the left square bracket key, etc.
For functional keys, such as :kbd:`Enter` or :kbd:`Escape`, the names are present
at :ref:`Functional key definitions <functional>`. For modifier keys, the names
are :kbd:`ctrl` (:kbd:`control`, :kbd:`⌃`), :kbd:`shift` (:kbd:`⇧`), :kbd:`alt`
(:kbd:`opt`, :kbd:`option`, :kbd:`⌥`), :kbd:`super` (:kbd:`cmd`, :kbd:`command`,
:kbd:`⌘`).

Simple shortcut mapping is done with the :code:`map` directive. For full details
on advanced mapping including modal and per application maps, see :doc:`mapping`.
Some quick examples to illustrate common tasks::

    # unmap a keyboard shortcut, passing it to the program running in kitty
    map kitty_mod+space
    # completely ignore a keyboard event
    map ctrl+alt+f1 discard_event
    # combine multiple actions
    map kitty_mod+e combine : new_window : next_layout
    # multi-key shortcuts
    map ctrl+x>ctrl+y>z action

The full list of actions that can be mapped to key presses is available
:doc:`here </actions>`.
''')

opt('kitty_mod', 'ctrl+shift',
    option_type='to_modifiers',
    long_text='''
Special modifier key alias for default shortcuts. You can change the value of
this option to alter all default shortcuts that use :opt:`kitty_mod`.
'''
    )

opt('clear_all_shortcuts', 'no',
    option_type='clear_all_shortcuts',
    long_text='''
Remove all shortcut definitions up to this point. Useful, for instance, to
remove the default shortcuts.
'''
    )

opt('+action_alias', 'launch_tab launch --type=tab --cwd=current',
    option_type='action_alias',
    add_to_default=False,
    long_text='''
Define action aliases to avoid repeating the same options in multiple mappings.
Aliases can be defined for any action and will be expanded recursively. For
example, the above alias allows you to create mappings to launch a new tab in
the current working directory without duplication::

    map f1 launch_tab vim
    map f2 launch_tab emacs

Similarly, to alias kitten invocation::

    action_alias hints kitten hints --hints-offset=0
'''
    )

opt('+kitten_alias', 'hints hints --hints-offset=0',
    option_type='kitten_alias',
    add_to_default=False,
    long_text='''
Like :opt:`action_alias` above, but specifically for kittens. Generally, prefer
to use :opt:`action_alias`. This option is a legacy version, present for
backwards compatibility. It causes all invocations of the aliased kitten to be
substituted. So the example above will cause all invocations of the hints kitten
to have the :option:`--hints-offset=0 <kitty +kitten hints --hints-offset>`
option applied.
'''
    )


# shortcuts.clipboard {{{
agr('shortcuts.clipboard', 'Clipboard')

map('Copy to clipboard',
    'copy_to_clipboard kitty_mod+c copy_to_clipboard',
    long_text='''
There is also a :ac:`copy_or_interrupt` action that can be optionally mapped
to :kbd:`Ctrl+C`. It will copy only if there is a selection and send an
interrupt otherwise. Similarly, :ac:`copy_and_clear_or_interrupt` will copy
and clear the selection or send an interrupt if there is no selection.
'''
    )
map('Copy to clipboard',
    'copy_to_clipboard cmd+c copy_to_clipboard',
    only='macos',
    )

map('Paste from clipboard',
    'paste_from_clipboard kitty_mod+v paste_from_clipboard',
    )
map('Paste from clipboard',
    'paste_from_clipboard cmd+v paste_from_clipboard',
    only='macos',
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
You can also pass the contents of the current selection to any program with
:ac:`pass_selection_to_program`. By default, the system's open program is used,
but you can specify your own, the selection will be passed as a command line
argument to the program. For example::

    map kitty_mod+o pass_selection_to_program firefox

You can pass the current selection to a terminal program running in a new kitty
window, by using the :code:`@selection` placeholder::

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
Use a parameter of :code:`0` for :ac:`scroll_to_prompt` to scroll to the last
jumped to or the last clicked position. Requires :ref:`shell integration
<shell_integration>` to work.
'''
    )

map('Scroll to next shell prompt', 'scroll_to_next_prompt kitty_mod+x scroll_to_prompt 1')

map('Browse scrollback buffer in pager',
    'show_scrollback kitty_mod+h show_scrollback',
    long_text='''
You can pipe the contents of the current screen and history buffer as
:file:`STDIN` to an arbitrary program using :option:`launch --stdin-source`.
For example, the following opens the scrollback buffer in less in an
:term:`overlay` window::

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

To get the command output that was last accessed by a keyboard action or mouse
action::

    map f1 show_last_visited_command_output

You can pipe the output of the last command run in the shell using the
:ac:`launch` action. For example, the following opens the output in less in an
:term:`overlay` window::

    map f1 launch --stdin-source=@last_cmd_output --stdin-add-formatting --type=overlay less +G -R

To get the output of the first command on the screen, use :code:`@first_cmd_output_on_screen`.
To get the output of the last jumped to command, use :code:`@last_visited_cmd_output`.

Requires :ref:`shell integration <shell_integration>` to work.
'''
    )
egr()  # }}}


# shortcuts.window {{{
agr('shortcuts.window', 'Window management')

map('New window',
    'new_window kitty_mod+enter new_window',
    long_text='''
You can open a new :term:`kitty window <window>` running an arbitrary program,
for example::

    map kitty_mod+y launch mutt

You can open a new window with the current working directory set to the working
directory of the current window using::

    map ctrl+alt+enter launch --cwd=current

You can open a new window that is allowed to control kitty via
the kitty remote control facility with :option:`launch --allow-remote-control`.
Any programs running in that window will be allowed to control kitty.
For example::

    map ctrl+enter launch --allow-remote-control some_program

You can open a new window next to the currently active window or as the first
window, with::

    map ctrl+n launch --location=neighbor
    map ctrl+f launch --location=first

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
Works like :ac:`new_window` above, except that it opens a top-level :term:`OS
window <os_window>`. In particular you can use :ac:`new_os_window_with_cwd` to
open a window with the current working directory.
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

map('Eighth window',
    'eighth_window kitty_mod+8 eighth_window',
    )
map('Eighth window',
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

map('Visually select and focus window', 'focus_visible_window kitty_mod+f7 focus_visible_window',
    long_text='''
Display overlay numbers and alphabets on the window, and switch the focus to the
window when you press the key. When there are only two windows, the focus will
be switched directly without displaying the overlay. You can change the overlay
characters and their order with option :opt:`visual_window_select_characters`.
'''
    )
map('Visually swap window with another', 'swap_with_window kitty_mod+f8 swap_with_window',
    long_text='''
Works like :ac:`focus_visible_window` above, but swaps the window.
'''
    )
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
You can also create shortcuts to go to specific :term:`tabs <tab>`, with
:code:`1` being the first tab, :code:`2` the second tab and :code:`-1` being the
previously active tab, :code:`-2` being the tab active before the previously active tab and so on.
Any number larger than the number of tabs goes to the last tab and any number less
than the number of previously used tabs in the history goes to the oldest previously used tab in the history::

    map ctrl+alt+1 goto_tab 1
    map ctrl+alt+2 goto_tab 2

Just as with :ac:`new_window` above, you can also pass the name of arbitrary
commands to run when using :ac:`new_tab` and :ac:`new_tab_with_cwd`. Finally,
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
You can also create shortcuts to switch to specific :term:`layouts <layout>`::

    map ctrl+alt+t goto_layout tall
    map ctrl+alt+s goto_layout stack

Similarly, to switch back to the previous layout::

    map ctrl+alt+p last_used_layout

There is also a :ac:`toggle_layout` action that switches to the named layout or
back to the previous layout if in the named layout. Useful to temporarily "zoom"
the active window by switching to the stack layout::

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

To setup shortcuts to multiply/divide the font size::

    map kitty_mod+f6 change_font_size all *2.0
    map kitty_mod+f6 change_font_size all /2.0
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
run :program:`git` commands on a filename output from a previous :program:`git`
command.
'''
    )

map('Open selected path',
    'open_selected_path kitty_mod+p>shift+f kitten hints --type path',
    long_text='Select a path/filename and open it with the default open program.'
    )

map('Insert selected line',
    'insert_selected_line kitty_mod+p>l kitten hints --type line --program -',
    long_text='''
Select a line of text and insert it into the terminal. Useful for the output of
things like: ``ls -1``.
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
with :program:`git`, which uses SHA1 hashes to identify commits.
'''
    )

map('Open the selected file at the selected line',
    'goto_file_line kitty_mod+p>n kitten hints --type linenum',
    long_text='''
Select something that looks like :code:`filename:linenum` and open it in
your default editor at the specified line number.
'''
    )

map('Open the selected hyperlink',
    'open_selected_hyperlink kitty_mod+p>y kitten hints --type hyperlink',
    long_text='''
Select a :term:`hyperlink <hyperlinks>` (i.e. a URL that has been marked as such
by the terminal program, for example, by ``ls --hyperlink=auto``).
'''
    )
egr('''
The hints kitten has many more modes of operation that you can map to different
shortcuts. For a full description see :doc:`hints kitten </kittens/hints>`.
''')  # }}}


# shortcuts.misc {{{
agr('shortcuts.misc', 'Miscellaneous')

map('Show documentation',
    'show_kitty_doc kitty_mod+f1 show_kitty_doc overview')

map('Toggle fullscreen',
    'toggle_fullscreen kitty_mod+f11 toggle_fullscreen',
    )
map('Toggle fullscreen',
    'toggle_fullscreen ctrl+cmd+f toggle_fullscreen',
    only='macos',
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
Open the kitty shell in a new :code:`window` / :code:`tab` / :code:`overlay` /
:code:`os_window` to control kitty using commands.
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
    long_text=r'''
You can create shortcuts to clear/reset the terminal. For example::

    # Reset the terminal
    map f1 clear_terminal reset active
    # Clear the terminal screen by erasing all contents
    map f1 clear_terminal clear active
    # Clear the terminal scrollback by erasing it
    map f1 clear_terminal scrollback active
    # Scroll the contents of the screen into the scrollback
    map f1 clear_terminal scroll active
    # Clear everything on screen up to the line with the cursor or the start of the current prompt (needs shell integration)
    map f1 clear_terminal to_cursor active
    # Same as above except cleared lines are moved into scrollback
    map f1 clear_terminal to_cursor_scroll active

If you want to operate on all kitty windows instead of just the current one, use
:italic:`all` instead of :italic:`active`.

Some useful functions that can be defined in the shell rc files to perform various kinds of
clearing of the current window:

.. code-block:: sh

    clear-only-screen() {
        printf "\e[H\e[2J"
    }

    clear-screen-and-scrollback() {
        printf "\e[H\e[3J"
    }

    clear-screen-saving-contents-in-scrollback() {
        printf "\e[H\e[22J"
    }

For instance, using these escape codes, it is possible to remap :kbd:`Ctrl+L`
to both scroll the current screen contents into the scrollback buffer and clear
the screen, instead of just clearing the screen. For ZSH, in :file:`~/.zshrc`, add:

.. code-block:: zsh

    ctrl_l() {
        builtin print -rn -- $'\r\e[0J\e[H\e[22J' >"$TTY"
        builtin zle .reset-prompt
        builtin zle -R
    }
    zle -N ctrl_l
    bindkey '^l' ctrl_l

Alternatively, you can just add :code:`map ctrl+l clear_terminal to_cursor_scroll active` to :file:`kitty.conf` which
works with no changes to the shell rc files, but only clears up to the prompt, it does not clear any text at the prompt itself.
'''
    )

map('Reset the terminal',
    'reset_terminal opt+cmd+r clear_terminal reset active',
    only='macos',
    )

map('Clear to start',
    'clear_terminal_and_scrollback cmd+k clear_terminal to_cursor active',
    only='macos',
    )

map('Clear scrollback',
    'clear_scrollback option+cmd+k clear_terminal scrollback active',
    only='macos',
    )

map('Clear screen',
    'clear_screen cmd+ctrl+l clear_terminal to_cursor_scroll active',
    only='macos',
    )



map('Reload kitty.conf',
    'reload_config_file kitty_mod+f5 load_config_file',
    long_text='''
Reload :file:`kitty.conf`, applying any changes since the last time it was
loaded. Note that a handful of options cannot be dynamically changed and
require a full restart of kitty. Particularly, when changing shortcuts for
actions located on the macOS global menu bar, a full restart is needed. You can
also map a keybinding to load a different config file, for example::

    map f5 load_config /path/to/alternative/kitty.conf

Note that all options from the original :file:`kitty.conf` are discarded, in
other words the new configuration *replace* the old ones.
'''
    )

map('Reload kitty.conf',
    'reload_config_file ctrl+cmd+, load_config_file',
    only='macos'
    )

map('Debug kitty configuration',
    'debug_config kitty_mod+f6 debug_config',
    long_text='''
Show details about exactly what configuration kitty is running with and its host
environment. Useful for debugging issues.
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
You can tell kitty to send arbitrary (UTF-8) encoded text to the client program
when pressing specified shortcut keys. For example::

    map ctrl+alt+a send_text all Special text

This will send "Special text" when you press the :kbd:`Ctrl+Alt+A` key
combination. The text to be sent decodes :link:`ANSI C escapes <https://www.gnu.org/software/bash/manual/html_node/ANSI_002dC-Quoting.html>`
so you can use escapes like :code:`\\\\e` to send control codes or :code:`\\\\u21fb` to send
Unicode characters (or you can just input the Unicode characters directly as
UTF-8 text). You can use ``kitten show-key`` to get the key escape
codes you want to emulate.

The first argument to :code:`send_text` is the keyboard modes in which to
activate the shortcut. The possible values are :code:`normal`,
:code:`application`, :code:`kitty` or a comma separated combination of them.
The modes :code:`normal` and :code:`application` refer to the DECCKM
cursor key mode for terminals, and :code:`kitty` refers to the kitty extended
keyboard protocol. The special value :code:`all` means all of them.

Some more examples::

    # Output a word and move the cursor to the start of the line (like typing and pressing Home)
    map ctrl+alt+a send_text normal Word\\e[H
    map ctrl+alt+a send_text application Word\\eOH
    # Run a command at a shell prompt (like typing the command and pressing Enter)
    map ctrl+alt+a send_text normal,application some command with arguments\\r
'''
    )

map('Open kitty Website',
    f'open_kitty_website shift+cmd+/ open_url {website_url()}',
    only='macos',
    )

map('Hide macOS kitty application',
    'hide_macos_app cmd+h hide_macos_app',
    only='macos',
    )

map('Hide macOS other applications',
    'hide_macos_other_apps opt+cmd+h hide_macos_other_apps',
    only='macos',
    )

map('Minimize macOS window',
    'minimize_macos_window cmd+m minimize_macos_window',
    only='macos',
    )

map('Quit kitty',
    'quit cmd+q quit',
    only='macos',
    )
egr()  # }}}
egr()  # }}}
