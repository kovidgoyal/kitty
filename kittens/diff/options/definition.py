#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPLv3 Copyright: 2021, Kovid Goyal <kovid at kovidgoyal.net>

# After editing this file run ./gen-config.py to apply the changes

from kitty.conf.types import Action, Definition


definition = Definition(
    'kittens.diff',
    Action('map', 'parse_map', {'key_definitions': 'kitty.conf.utils.KittensKeyMap'}, ['kitty.types.ParsedShortcut', 'kitty.conf.utils.KeyAction']),
)

agr = definition.add_group
egr = definition.end_group
opt = definition.add_option
map = definition.add_map
mma = definition.add_mouse_map

# diff {{{
agr('diff', 'Diffing')

opt('syntax_aliases', 'pyj:py pyi:py recipe:py',
    option_type='syntax_aliases',
    long_text='''
File extension aliases for syntax highlight For example, to syntax highlight
:file:`file.xyz` as :file:`file.abc` use a setting of :code:`xyz:abc`
'''
    )

opt('num_context_lines', '3',
    option_type='positive_int',
    long_text='The number of lines of context to show around each change.'
    )

opt('diff_cmd', 'auto',
    long_text='''
The diff command to use. Must contain the placeholder :code:`_CONTEXT_` which
will be replaced by the number of lines of context. The default is to search the
system for either git or diff and use that, if found.
'''
    )

opt('replace_tab_by', '\\x20\\x20\\x20\\x20',
    option_type='python_string',
    long_text='The string to replace tabs with. Default is to use four spaces.'
    )
egr()  # }}}

# colors {{{
agr('colors', 'Colors')

opt('pygments_style', 'default',
    long_text='''
The pygments color scheme to use for syntax highlighting. See :link:`pygments
colors schemes <https://help.farbox.com/pygments.html>` for a list of schemes.
'''
    )

opt('foreground', 'black',
    option_type='to_color',
    long_text='Basic colors'
    )

opt('background', 'white',
    option_type='to_color',
    )

opt('title_fg', 'black',
    option_type='to_color',
    long_text='Title colors'
    )

opt('title_bg', 'white',
    option_type='to_color',
    )

opt('margin_bg', '#fafbfc',
    option_type='to_color',
    long_text='Margin colors'
    )

opt('margin_fg', '#aaaaaa',
    option_type='to_color',
    )

opt('removed_bg', '#ffeef0',
    option_type='to_color',
    long_text='Removed text backgrounds'
    )

opt('highlight_removed_bg', '#fdb8c0',
    option_type='to_color',
    )

opt('removed_margin_bg', '#ffdce0',
    option_type='to_color',
    )

opt('added_bg', '#e6ffed',
    option_type='to_color',
    long_text='Added text backgrounds'
    )

opt('highlight_added_bg', '#acf2bd',
    option_type='to_color',
    )

opt('added_margin_bg', '#cdffd8',
    option_type='to_color',
    )

opt('filler_bg', '#fafbfc',
    option_type='to_color',
    long_text='Filler (empty) line background'
    )

opt('margin_filler_bg', 'none',
    option_type='to_color_or_none',
    long_text='Filler (empty) line background in margins, defaults to the filler background'
    )

opt('hunk_margin_bg', '#dbedff',
    option_type='to_color',
    long_text='Hunk header colors'
    )

opt('hunk_bg', '#f1f8ff',
    option_type='to_color',
    )

opt('search_bg', '#444',
    option_type='to_color',
    long_text='Highlighting'
    )

opt('search_fg', 'white',
    option_type='to_color',
    )

opt('select_bg', '#b4d5fe',
    option_type='to_color',
    )

opt('select_fg', 'black',
    option_type='to_color_or_none',
    )
egr()  # }}}

# shortcuts {{{
agr('shortcuts', 'Keyboard shortcuts')

map('Quit',
    'quit q quit',
    )
map('Quit',
    'quit esc quit',
    )

map('Scroll down',
    'scroll_down j scroll_by 1',
    )
map('Scroll down',
    'scroll_down down scroll_by 1',
    )

map('Scroll up',
    'scroll_up k scroll_by -1',
    )
map('Scroll up',
    'scroll_up up scroll_by -1',
    )

map('Scroll to top',
    'scroll_top home scroll_to start',
    )

map('Scroll to bottom',
    'scroll_bottom end scroll_to end',
    )

map('Scroll to next page',
    'scroll_page_down page_down scroll_to next-page',
    )
map('Scroll to next page',
    'scroll_page_down space scroll_to next-page',
    )

map('Scroll to previous page',
    'scroll_page_up page_up scroll_to prev-page',
    )

map('Scroll to next change',
    'next_change n scroll_to next-change',
    )

map('Scroll to previous change',
    'prev_change p scroll_to prev-change',
    )

map('Show all context',
    'all_context a change_context all',
    )

map('Show default context',
    'default_context = change_context default',
    )

map('Increase context',
    'increase_context + change_context 5',
    )

map('Decrease context',
    'decrease_context - change_context -5',
    )

map('Search forward',
    'search_forward / start_search regex forward',
    )

map('Search backward',
    'search_backward ? start_search regex backward',
    )

map('Scroll to next search match',
    'next_match . scroll_to next-match',
    )
map('Scroll to next search match',
    'next_match > scroll_to next-match',
    )

map('Scroll to previous search match',
    'prev_match , scroll_to prev-match',
    )
map('Scroll to previous search match',
    'prev_match < scroll_to prev-match',
    )

map('Search forward (no regex)',
    'search_forward_simple f start_search substring forward',
    )

map('Search backward (no regex)',
    'search_backward_simple b start_search substring backward',
    )
egr()  # }}}
