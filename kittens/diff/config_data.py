#!/usr/bin/env python3
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2018, Kovid Goyal <kovid at kovidgoyal.net>


# Utils  {{{
from gettext import gettext as _
from functools import partial

from kitty.conf.definition import option_func
from kitty.conf.utils import (
    positive_int, python_string, to_color
)

# }}}

all_options = {}
o, k, g, all_groups = option_func(all_options, {
    'colors': [_('Colors')],
    'diff': [_('Diffing'), ],
    'shortcuts': [_('Keyboard shortcuts')],
})


g('diff')


def syntax_aliases(raw):
    ans = {}
    for x in raw.split():
        a, b = x.partition(':')[::2]
        if a and b:
            ans[a.lower()] = b
    return ans


o('syntax_aliases', 'pyj:py recipe:py', option_type=syntax_aliases, long_text=_('''
File extension aliases for syntax highlight
For example, to syntax highlight :file:`file.xyz` as
:file:`file.abc` use a setting of :code:`xyz:abc`
'''))

o('num_context_lines', 3, option_type=positive_int, long_text=_('''
The number of lines of context to show around each change.'''))

o('diff_cmd', 'auto', long_text=_('''
The diff command to use. Must contain the placeholder :code:`_CONTEXT_`
which will be replaced by the number of lines of context. The default
is to search the system for either git or diff and use that, if found.
'''))

o('replace_tab_by', r'\x20\x20\x20\x20', option_type=python_string, long_text=_('''
The string to replace tabs with. Default is to use four spaces.'''))


g('colors')

o('pygments_style', 'default', long_text=_('''
The pygments color scheme to use for syntax highlighting.
See :link:`pygments colors schemes <https://help.farbox.com/pygments.html>` for a list of schemes.'''))


c = partial(o, option_type=to_color)
c('foreground', 'black', long_text=_('Basic colors'))
c('background', 'white')

c('title_fg', 'black', long_text=_('Title colors'))
c('title_bg', 'white')

c('margin_bg', '#fafbfc', long_text=_('Margin colors'))
c('margin_fg', '#aaaaaa')

c('removed_bg', '#ffeef0', long_text=_('Removed text backgrounds'))
c('highlight_removed_bg', '#fdb8c0')
c('removed_margin_bg', '#ffdce0')

c('added_bg', '#e6ffed', long_text=_('Added text backgrounds'))
c('highlight_added_bg', '#acf2bd')
c('added_margin_bg', '#cdffd8')

c('filler_bg', '#fafbfc', long_text=_('Filler (empty) line background'))

c('hunk_margin_bg', '#dbedff', long_text=_('Hunk header colors'))
c('hunk_bg', '#f1f8ff')

c('search_bg', '#444', long_text=_('Highlighting'))
c('search_fg', 'white')
c('select_bg', '#b4d5fe')
c('select_fg', 'black')

g('shortcuts')
k('quit', 'q', 'quit', _('Quit'))
k('quit', 'esc', 'quit', _('Quit'))

k('scroll_down', 'j', 'scroll_by 1', _('Scroll down'))
k('scroll_down', 'down', 'scroll_by 1', _('Scroll down'))
k('scroll_up', 'k', 'scroll_by -1', _('Scroll up'))
k('scroll_up', 'up', 'scroll_by -1', _('Scroll up'))

k('scroll_top', 'home', 'scroll_to start', _('Scroll to top'))
k('scroll_bottom', 'end', 'scroll_to end', _('Scroll to bottom'))

k('scroll_page_down', 'page_down', 'scroll_to next-page', _('Scroll to next page'))
k('scroll_page_down', 'space', 'scroll_to next-page', _('Scroll to next page'))
k('scroll_page_up', 'page_up', 'scroll_to prev-page', _('Scroll to previous page'))

k('next_change', 'n', 'scroll_to next-change', _('Scroll to next change'))
k('prev_change', 'p', 'scroll_to prev-change', _('Scroll to previous change'))

k('all_context', 'a', 'change_context all', _('Show all context'))
k('default_context', '=', 'change_context default', _('Show default context'))
k('increase_context', '+', 'change_context 5', _('Increase context'))
k('decrease_context', '-', 'change_context -5', _('Decrease context'))

k('search_forward', '/', 'start_search regex forward', _('Search forward'))
k('search_backward', '?', 'start_search regex backward', _('Search backward'))
k('next_match', '.', 'scroll_to next-match', _('Scroll to next search match'))
k('prev_match', ',', 'scroll_to prev-match', _('Scroll to previous search match'))
k('next_match', '>', 'scroll_to next-match', _('Scroll to next search match'))
k('prev_match', '<', 'scroll_to prev-match', _('Scroll to previous search match'))
k('search_forward_simple', 'f', 'start_search substring forward', _('Search forward (no regex)'))
k('search_backward_simple', 'b', 'start_search substring backward', _('Search backward (no regex)'))

type_map = {o.name: o.option_type for o in all_options.values() if hasattr(o, 'option_type')}
