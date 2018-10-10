#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2016, Kovid Goyal <kovid at kovidgoyal.net>

import re
from binascii import hexlify, unhexlify


names = 'xterm-kitty', 'KovIdTTY'

termcap_aliases = {
    'TN': 'name'
}

bool_capabilities = {
    # auto_right_margin (terminal has automatic margins)
    'am',
    # can_change (terminal can redefine existing colors)
    'ccc',
    # has_meta key (i.e. sets the eight bit)
    'km',
    # prtr_silent (printer will not echo on screen)
    'mc5i',
    # move_insert_mode (safe to move while in insert mode)
    'mir',
    # move_standout_mode (safe to move while in standout mode)
    'msgr',
    # no_pad_char (pad character does not exist)
    'npc',
    # eat_newline_glitch (newline ignored after 80 columns)
    'xenl',
    # has extra status line (window title)
    'hs',
    # Terminfo extension used by tmux to detect true color support (non-standard)
    'Tc',
    # Indicates support for styled and colored underlines (non-standard) as
    # described at:
    # https://github.com/kovidgoyal/kitty/blob/master/protocol-extensions.asciidoc
    'Su',

    # The following are entries that we don't use
    # # background color erase
    # 'bce',
}

termcap_aliases.update({
    'am': 'am',
    'cc': 'ccc',
    'km': 'km',
    '5i': 'mc5i',
    'mi': 'mir',
    'ms': 'msgr',
    'NP': 'npc',
    'xn': 'xenl',
    'hs': 'hs',
})

numeric_capabilities = {
    # maximum number of colors on screen
    'colors': 256,
    'cols': 80,
    'lines': 24,
    # tabs initially every # spaces
    'it': 8,
    # maximum number of color-pairs on the screen
    'pairs': 32767,
}

termcap_aliases.update({
    'Co': 'colors',
    'pa': 'pairs',
    'li': 'lines',
    'co': 'cols',
    'it': 'it',
})

string_capabilities = {
    # graphics charset pairs
    'acsc': r'++\,\,--..00``aaffgghhiijjkkllmmnnooppqqrrssttuuvvwwxxyyzz{{||}}~~',
    # The audible bell character
    'bel': r'^G',
    # Escape code for bold
    'bold': r'\E[1m',
    # Back tab
    'cbt': r'\E[Z',
    'kcbt': r'\E[Z',
    # Make cursor invisible
    'civis': r'\E[?25l',
    # Clear screen
    'clear': r'\E[H\E[2J',
    # Make cursor appear normal
    'cnorm': r'\E[?12l\E[?25h',
    # Carriage return
    'cr': r'^M',  # CR (carriage return \r)
    # Change scroll region
    'csr': r'\E[%i%p1%d;%p2%dr',
    # Move cursor to the left by the specified amount
    'cub': r'\E[%p1%dD',
    'cub1': r'^H',  # BS (backspace)
    # Move cursor down specified number of lines
    'cud': r'\E[%p1%dB',
    'cud1': r'^J',  # LF (line-feed \n)
    # Move cursor to the right by the specified amount
    'cuf': r'\E[%p1%dC',
    'cuf1': r'\E[C',
    # Move cursor up specified number of lines
    'cuu': r'\E[%p1%dA',
    'cuu1': r'\E[A',
    # Move cursor to specified location
    'cup': r'\E[%i%p1%d;%p2%dH',
    # Make cursor very visible
    'cvvis': r'\E[?12;25h',
    # Delete the specified number of characters
    'dch': r'\E[%p1%dP',
    'dch1': r'\E[P',
    # Turn on half bright mode
    'dim': r'\E[2m',
    # Delete the specified number of lines
    'dl': r'\E[%p1%dM',
    'dl1': r'\E[M',
    # Erase specified number of characters
    'ech': r'\E[%p1%dX',
    # Clear to end of screen
    'ed': r'\E[J',
    # Clear to end of line
    'el': r'\E[K',
    # Clear to start of line
    'el1': r'\E[1K',
    # visible bell
    'flash': r'\E[?5h$<100/>\E[?5l',
    # Home cursor
    'home': r'\E[H',
    # Move cursor to column
    'hpa': r'\E[%i%p1%dG',
    # Move to next tab
    'ht': r'^I',
    # Set tabstop at current position
    'hts': r'\EH',
    # Insert specified number of characters
    'ich': r'\E[%p1%d@',
    # Insert specified number of lines
    'il': r'\E[%p1%dL',
    'il1': r'\E[L',
    # scroll up by specified amount
    'ind': r'^J',
    'indn': r'\E[%p1%dS',
    # initialize color (set dynamic colors)
    'initc': r'\E]4;%p1%d;rgb\:%p2%{255}%*%{1000}%/%2.2X/%p3%{255}%*%{1000}%/%2.2X/%p4%{255}%*%{1000}%/%2.2X\E\\',
    # Set all colors to original values
    'oc': r'\E]104\007',
    # turn on blank mode (characters invisible)
    # 'invis': r'\E[8m',
    # Backspace
    'kbs': r'\177',
    # Left
    'kcub1': r'\EOD',
    # Down
    'kcud1': r'\EOB',
    # Right
    'kcuf1': r'\EOC',
    # Up
    'kcuu1': r'\EOA',
    # Function keys
    'kf1': r'\EOP',
    'kf2': r'\EOQ',
    'kf3': r'\EOR',
    'kf4': r'\EOS',
    'kf5': r'\E[15~',
    'kf6': r'\E[17~',
    'kf7': r'\E[18~',
    'kf8': r'\E[19~',
    'kf9': r'\E[20~',
    'kf10': r'\E[21~',
    'kf11': r'\E[23~',
    'kf12': r'\E[24~',
    'kf13': r'\E[1;2P',
    'kf14': r'\E[1;2Q',
    'kf15': r'\E[1;2R',
    'kf16': r'\E[1;2S',
    'kf17': r'\E[15;2~',
    'kf18': r'\E[17;2~',
    'kf19': r'\E[18;2~',
    'kf20': r'\E[19;2~',
    'kf21': r'\E[20;2~',
    'kf22': r'\E[21;2~',
    'kf23': r'\E[23;2~',
    'kf24': r'\E[24;2~',
    'kf25': r'\E[1;5P',
    # Home
    'khome': r'\EOH',
    # End
    'kend': r'\EOF',
    # Insert character key
    'kich1': r'\E[2~',
    # Delete character key
    'kdch1': r'\E[3~',
    # Mouse event has occurred
    'kmous': r'\E[M',
    # Page down
    'knp': r'\E[6~',
    # Page up
    'kpp': r'\E[5~',
    # Scroll backwards (reverse index)
    'kri': r'\E[1;2A',
    # scroll forwards (index)
    'kind': r'\E[1;2B',
    # Restore cursor
    'rc': r'\E8',
    # Reverse video
    'rev': r'\E[7m',
    # Scroll backwards the specified number of lines (reverse index)
    'ri': r'\EM',
    'rin': r'\E[%p1%dT',
    # Turn off automatic margins
    'rmam': r'\E[?7l',
    # Exit alternate screen
    'rmcup': r'\E[?1049l',
    # Exit insert mode
    'rmir': r'\E[4l',
    # Exit application keypad mode
    'rmkx': r'\E[?1l',
    # Exit standout mode
    'rmso': r'\E[27m',
    # Exit underline mode
    'rmul': r'\E[24m',
    # Reset string1
    'rs1': r'\Ec',
    # Save cursor
    'sc': r'\E7',
    # Set background color
    'setab': r'\E[%?%p1%{8}%<%t4%p1%d%e%p1%{16}%<%t10%p1%{8}%-%d%e48;5;%p1%d%;m',
    # Set foreground color
    'setaf': r'\E[%?%p1%{8}%<%t3%p1%d%e%p1%{16}%<%t9%p1%{8}%-%d%e38;5;%p1%d%;m',
    # Set attributes
    'sgr': r'%?%p9%t\E(0%e\E(B%;\E[0%?%p6%t;1%;%?%p2%t;4%;%?%p1%p3%|%t;7%;%?%p4%t;5%;%?%p7%t;8%;m',
    # Clear all attributes
    'sgr0': r'\E(B\E[m',
    # Reset color pair to its original value
    'op': r'\E[39;49m',
    # Turn on automatic margins
    'smam': r'\E[?7h',
    # Start alternate screen
    'smcup': r'\E[?1049h',
    # Enster insert mode
    'smir': r'\E[4h',
    # Enter application keymap mode
    'smkx': r'\E[?1h',
    # Enter standout mode
    'smso': r'\E[7m',
    # Enter underline mode
    'smul': r'\E[4m',
    # Clear all tab stops
    'tbc': r'\E[3g',
    # To status line (used to set window titles)
    'tsl': r'\E]2;',
    # From status line (end window title string)
    'fsl': r'^G',
    # Disable status line (clear window title)
    'dsl': r'\E]2;\007',
    # Move to specified line
    'vpa': r'\E[%i%p1%dd',
    # Enter italics mode
    'sitm': r'\E[3m',
    # Leave italics mode
    'ritm': r'\E[23m',
    # Select alternate charset
    'smacs': r'\E(0',
    'rmacs': r'\E(B',
    # Shifted keys
    'kRIT': r'\E[1;2C',
    'kLFT': r'\E[1;2D',
    'kEND': r'\E[1;2F',
    'kHOM': r'\E[1;2H',
    # Special keys
    'khlp': r'',
    'kund': r'',
    'ka1': r'',
    'ka3': r'',
    'kc1': r'',
    'kc3': r'',
    # Set RGB foreground color (non-standard used by neovim)
    'setrgbf': r'\E[38:2:%p1%d:%p2%d:%p3%dm',
    # Set RGB background color (non-standard used by neovim)
    'setrgbb': r'\E[48:2:%p1%d:%p2%d:%p3%dm',

    # The following are entries that we don't use
    # # turn on blank mode, (characters invisible)
    # 'invis': r'\E[8m',
    # # init2 string
    # 'is2': r'\E[!p\E[?3;4l\E[4l\E>',
    # # Enter/send key
    # 'kent': r'\EOM',
    # # reset2
    # 'rs2': r'\E[!p\E[?3;4l\E[4l\E>',
}

termcap_aliases.update({
    'ac': 'acsc',
    'bl': 'bel',
    'md': 'bold',
    'bt': 'cbt',
    'kB': 'kcbt',
    'cl': 'clear',
    'vi': 'civis',
    'vs': 'cvvis',
    've': 'cnorm',
    'cr': 'cr',
    'cs': 'csr',
    'LE': 'cub',
    'le': 'cub1',
    'DO': 'cud',
    'do': 'cud1',
    'UP': 'cuu',
    'up': 'cuu1',
    'nd': 'cuf1',
    'RI': 'cuf',
    'cm': 'cup',
    'DC': 'dch',
    'dc': 'dch1',
    'mh': 'dim',
    'DL': 'dl',
    'dl': 'dl1',
    'ec': 'ech',
    'cd': 'ed',
    'ce': 'el',
    'cb': 'el1',
    'vb': 'flash',
    'ho': 'home',
    'ch': 'hpa',
    'ta': 'ht',
    'st': 'hts',
    'IC': 'ich',
    'AL': 'il',
    'al': 'il1',
    'sf': 'ind',
    'SF': 'indn',
    'Ic': 'initc',
    'oc': 'oc',
    # 'mk': 'invis',
    'kb': 'kbs',
    'kl': 'kcub1',
    'kd': 'kcud1',
    'kr': 'kcuf1',
    'ku': 'kcuu1',
    'k1': 'kf1',
    'k2': 'kf2',
    'k3': 'kf3',
    'k4': 'kf4',
    'k5': 'kf5',
    'k6': 'kf6',
    'k7': 'kf7',
    'k8': 'kf8',
    'k9': 'kf9',
    'k;': 'kf10',
    'F1': 'kf11',
    'F2': 'kf12',
    'F3': 'kf13',
    'F4': 'kf14',
    'F5': 'kf15',
    'F6': 'kf16',
    'F7': 'kf17',
    'F8': 'kf18',
    'F9': 'kf19',
    'FA': 'kf20',
    'FB': 'kf21',
    'FC': 'kf22',
    'FD': 'kf23',
    'FE': 'kf24',
    'FF': 'kf25',
    'kh': 'khome',
    '@7': 'kend',
    'kI': 'kich1',
    'kD': 'kdch1',
    'Km': 'kmous',
    'kN': 'knp',
    'kP': 'kpp',
    'kR': 'kri',
    'kF': 'kind',
    'rc': 'rc',
    'mr': 'rev',
    'sr': 'ri',
    'SR': 'rin',
    'RA': 'rmam',
    'te': 'rmcup',
    'ei': 'rmir',
    'se': 'rmso',
    'ue': 'rmul',
    'r1': 'rs1',
    'sc': 'sc',
    'AB': 'setab',
    'AF': 'setaf',
    'sa': 'sgr',
    'me': 'sgr0',
    'op': 'op',
    'SA': 'smam',
    'ti': 'smcup',
    'im': 'smir',
    'so': 'smso',
    'us': 'smul',
    'ct': 'tbc',
    'cv': 'vpa',
    'ZH': 'sitm',
    'ZR': 'ritm',
    'as': 'smacs',
    'ae': 'rmacs',
    'ks': 'smkx',
    'ke': 'rmkx',
    '#2': 'kHOM',
    '#4': 'kLFT',
    '*7': 'kEND',
    '%i': 'kRIT',
    '%1': 'khlp',
    '&8': 'kund',
    'K1': 'ka1',
    'K3': 'ka3',
    'K4': 'kc1',
    'K5': 'kc3',
    'ts': 'tsl',
    'fs': 'fsl',
    'ds': 'dsl',


    # 'ut': 'bce',
    # 'ds': 'dsl',
    # 'fs': 'fsl',
    # 'mk': 'invis',
    # 'is': 'is2',
    # '@8': 'kent',
    # 'r2': 'rs2',
})

queryable_capabilities = numeric_capabilities.copy()
queryable_capabilities.update(string_capabilities)
extra = (bool_capabilities | numeric_capabilities.keys() | string_capabilities.keys()) - set(termcap_aliases.values())
no_termcap_for = frozenset('Su Tc setrgbf setrgbb'.split())
if extra - no_termcap_for:
    raise Exception('Termcap aliases not complete, missing: {}'.format(extra - no_termcap_for))
del extra


def generate_terminfo():
    # Use ./build-terminfo to update definition files
    ans = ['|'.join(names)]
    ans.extend(sorted(bool_capabilities))
    ans.extend('{}#{}'.format(k, numeric_capabilities[k]) for k in sorted(numeric_capabilities))
    ans.extend('{}={}'.format(k, string_capabilities[k]) for k in sorted(string_capabilities))
    return ',\n\t'.join(ans) + ',\n'


octal_escape = re.compile(r'\\([0-7]{3})')
escape_escape = re.compile(r'\\[eE]')


def key_as_bytes(name):
    ans = string_capabilities[name]
    ans = octal_escape.sub(lambda m: chr(int(m.group(1), 8)), ans)
    ans = escape_escape.sub('\033', ans)
    return ans.encode('ascii')


def get_capabilities(query_string):
    from .fast_data_types import ERROR_PREFIX
    ans = []
    try:
        for q in query_string.split(';'):
            name = qname = unhexlify(q).decode('utf-8')
            if name in ('TN', 'name'):
                val = names[0]
            else:
                try:
                    val = queryable_capabilities[name]
                except KeyError:
                    try:
                        qname = termcap_aliases[name]
                        val = queryable_capabilities[qname]
                    except Exception:
                        from .utils import log_error
                        log_error(ERROR_PREFIX, 'Unknown terminfo property:', name)
                        raise
                if qname in string_capabilities and '%' not in val:
                    val = key_as_bytes(qname).decode('ascii')
            ans.append(q + '=' + hexlify(str(val).encode('utf-8')).decode('ascii'))
        return '1+r' + ';'.join(ans)
    except Exception:
        return '0+r' + query_string
