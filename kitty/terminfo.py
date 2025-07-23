#!/usr/bin/env python
# License: GPL v3 Copyright: 2016, Kovid Goyal <kovid at kovidgoyal.net>

import re
from binascii import hexlify, unhexlify
from collections.abc import Generator
from typing import Literal, cast

from kitty.options.types import Options


def modify_key_bytes(keybytes: bytes, amt: int) -> bytes:
    if amt == 0:
        return keybytes
    ans = bytearray(keybytes)
    samt = str(amt).encode('ascii')
    if ans[-1] == ord('~'):
        return bytes(ans[:-1] + bytearray(b';' + samt + b'~'))
    if ans[1] == ord('O'):
        return bytes(ans[:1] + bytearray(b'[1;' + samt) + ans[-1:])
    raise ValueError(f'Unknown key type in key: {keybytes!r}')


def encode_keystring(keybytes: bytes) -> str:
    return keybytes.decode('ascii').replace('\033', r'\E')


names = Options.term, 'KovIdTTY'

termcap_aliases = {
    'TN': 'name'
}

bool_capabilities = {
    # auto_right_margin (terminal has automatic margins)
    'am',
    # auto_left_margin (cursor wraps on CUB1 from 0 to last column on prev line). This prevents ncurses
    # from using BS (backspace) to position the cursor. See https://github.com/kovidgoyal/kitty/issues/8841
    # It also allows using backspace with multi-line edits in cooked mode. Foot
    # is the only other modern terminal I know of that implements this.
    'bw',
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
    # described at: https://sw.kovidgoyal.net/kitty/underlines/
    'Su',
    # Indicates support for full keyboard mode (non-standard) as
    # described at:
    # https://github.com/kovidgoyal/kitty/blob/master/protocol-extensions.asciidoc
    'fullkbd',
    # Terminal supports focus events: https://lists.gnu.org/archive/html/bug-ncurses/2023-10/msg00117.html
    'XF',

    # The following are entries that we don't use
    # # background color erase
    # 'bce',
}

termcap_aliases.update({
    'am': 'am',
    'bw': 'bw',
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
    # Clear scrollback. This is disabled because the clear program on Linux by default, not as
    # an option, uses it and nukes the scrollback. What's more this behavior was silently changed
    # around 2013. Given clear is maintained as part of ncurses this kind of crap is no surprise.
    # 'E3': r'\E[3J',
    # Make cursor appear normal
    'cnorm': r'\E[?12h\E[?25h',
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
    # Mouse event has occurred
    'kmous': r'\E[M',

    # These break mouse events in htop so they are disabled
    # Turn on mouse reporting
    # 'XM': '\E[?1006;1004;1000%?%p1%{1}%=%th%el%;',
    # Expected format for mouse reporting escape codes
    # 'xm': r'\E[<%i%p3%d;%p1%d;%p2%d;%?%p4%tM%em%;',
    # Scroll backwards (reverse index)

    'kri': r'\E[1;2A',
    # scroll forwards (index)
    'kind': r'\E[1;2B',
    # Restore cursor
    'rc': r'\E8',
    # Repeat preceding character
    'rep': r'%p1%c\E[%p2%{1}%-%db',
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
    # Exit strikethrough mode
    'rmxx': r'\E[29m',
    # Reset string1 (empty OSC sequence to exit OSC/OTH modes, and regular reset)
    'rs1': r'\E]\E\\\Ec',
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
    # Enter insert mode
    'smir': r'\E[4h',
    # Enter application keymap mode
    'smkx': r'\E[?1h',
    # Enter standout mode
    'smso': r'\E[7m',
    # Enter underline mode
    'smul': r'\E[4m',
    'Smulx': r'\E[4:%p1%dm',  # this is a non-standard extension that some terminals use, so match them
    # Enter strikethrough mode
    'smxx': r'\E[9m',
    'Sync': r'\EP=%p1%ds\E\\',  # this is a non-standard extension supported by tmux for synchronized updates
    # Clear all tab stops
    'tbc': r'\E[3g',
    # To status line (used to set window titles)
    'tsl': r'\E]2;',
    # From status line (end window title string)
    'fsl': r'^G',
    # Disable status line (clear window title)
    'dsl': r'\E]2;\E\\',
    # Move to specified line
    'vpa': r'\E[%i%p1%dd',
    # Enter italics mode
    'sitm': r'\E[3m',
    # Leave italics mode
    'ritm': r'\E[23m',
    # Select alternate charset
    'smacs': r'\E(0',
    'rmacs': r'\E(B',
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
    # DECSCUSR Set cursor style
    'Ss': r'\E[%p1%d\sq',
    # DECSCUSR Reset cursor style to power-on default
    'Se': r'\E[2\sq',
    # Set cursor color
    'Cs': r'\E]12;%p1%s\007',
    # Reset cursor color
    'Cr': r'\E]112\007',
    # Indicates support for styled and colored underlines (non-standard) as
    # described at: https://sw.kovidgoyal.net/kitty/underlines/
    # 'Setulc' is equivalent to the 'Su' boolean capability. Until
    # standardized, specify both for application compatibility.
    'Setulc': r'\E[58:2:%p1%{65536}%/%d:%p1%{256}%/%{255}%&%d:%p1%{255}%&%d%;m',

    # The following entries are for compatibility with xterm,
    # and shell scripts using e.g. `tput u7` to emit a CPR escape
    # See https://invisible-island.net/ncurses/terminfo.src.html
    # and INTERPRETATION OF USER CAPABILITIES
    'u6': r'\E[%i%d;%dR',
    'u7': r'\E[6n',
    'u8': r'\E[?%[;0123456789]c',
    'u9': r'\E[c',

    # Bracketed paste, added to ncurses 6.4 in 2023
    'PS': r'\E[200~',
    'PE': r'\E[201~',
    'BE': r'\E[?2004h',
    'BD': r'\E[?2004l',

    # XTVERSION
    'XR': r'\E[>0q',
    # OSC 52 clipboard access
    'Ms': r'\E]52;%p1%s;%p2%s\E\\',
    # Send device attributes (report version)
    'RV': r'\E[>c',
    # Focus In and Out events
    'kxIN': r'\E[I',
    'kxOUT': r'\E[O',
    # Enable/disable focus reporting
    # Add to ncurses in: https://lists.gnu.org/archive/html/bug-ncurses/2023-10/msg00117.html
    'fe': r'\E[?1004h',
    'fd': r'\E[?1004l',

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

string_capabilities.update({
    f'kf{n}':
        encode_keystring(modify_key_bytes(b'\033' + value, 0))
    for n, value in zip(range(1, 13),
                        b'OP OQ OR OS [15~ [17~ [18~ [19~ [20~ [21~ [23~ [24~'.split())
})

string_capabilities.update({
    f'kf{offset + n}':
        encode_keystring(modify_key_bytes(b'\033' + value, mod))
    for offset, mod in {12: 2, 24: 5, 36: 6, 48: 3, 60: 4}.items()
    for n, value in zip(range(1, 13),
                        b'OP OQ [13~ OS [15~ [17~ [18~ [19~ [20~ [21~ [23~ [24~'.split())
    if offset + n < 64
})

string_capabilities.update({
    name.format(unmod=unmod, key=key):
        encode_keystring(modify_key_bytes(b'\033' + value, mod))
    for unmod, key, value in zip(
        'cuu1 cud1 cuf1 cub1 beg end home ich1 dch1 pp  np'.split(),
        'UP   DN   RIT  LFT  BEG END HOM  IC   DC   PRV NXT'.split(),
        b'OA  OB   OC   OD   OE  OF  OH   [2~  [3~  [5~ [6~'.split())
    for name, mod in {
        'k{unmod}': 0, 'k{key}': 2, 'k{key}3': 3, 'k{key}4': 4,
        'k{key}5': 5, 'k{key}6': 6, 'k{key}7': 7}.items()
})

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
    'rp': 'rep',
    'mr': 'rev',
    'sr': 'ri',
    'SR': 'rin',
    'RA': 'rmam',
    'te': 'rmcup',
    'ei': 'rmir',
    'se': 'rmso',
    'ue': 'rmul',
    'Te': 'rmxx',
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
    'Ts': 'smxx',
    'ct': 'tbc',
    'cv': 'vpa',
    'ZH': 'sitm',
    'ZR': 'ritm',
    'as': 'smacs',
    'ae': 'rmacs',
    'ks': 'smkx',
    'ke': 'rmkx',
    '#2': 'kHOM',
    '#3': 'kIC',
    '#4': 'kLFT',
    '*4': 'kDC',
    '*7': 'kEND',
    '%c': 'kNXT',
    '%e': 'kPRV',
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

    'u6': 'u6',
    'u7': 'u7',
    'u8': 'u8',
    'u9': 'u9',

    # 'ut': 'bce',
    # 'ds': 'dsl',
    # 'fs': 'fsl',
    # 'mk': 'invis',
    # 'is': 'is2',
    # '@8': 'kent',
    # 'r2': 'rs2',
})

termcap_aliases.update({
    tc: f'kf{n}'
    for n, tc in enumerate(
        'k1 k2 k3 k4 k5 k6 k7 k8 k9 k; F1 F2 F3 F4 F5 F6 F7 F8 F9 FA '
        'FB FC FD FE FF FG FH FI FJ FK FL FM FN FO FP FQ FR FS FT FU '
        'FV FW FX FY FZ Fa Fb Fc Fd Fe Ff Fg Fh Fi Fj Fk Fl Fm Fn Fo '
        'Fp Fq Fr'.split(), 1)})

queryable_capabilities = cast(dict[str, str], numeric_capabilities.copy())
queryable_capabilities.update(string_capabilities)
extra = (bool_capabilities | numeric_capabilities.keys() | string_capabilities.keys()) - set(termcap_aliases.values())
no_termcap_for = frozenset(
    'XR XM xm Ms RV kxIN kxOUT Cr Cs Se Ss Setulc Su Smulx Sync Tc PS PE BE BD setrgbf setrgbb fullkbd kUP kDN kbeg kBEG fe fd XF'.split() + [
        f'k{key}{mod}'
        for key in 'UP DN RIT LFT BEG END HOM IC DC PRV NXT'.split()
        for mod in range(3, 8)])
if extra - no_termcap_for:
    raise Exception(f'Termcap aliases not complete, missing: {extra - no_termcap_for}')
del extra


def generate_terminfo() -> str:
    # Use ./build-terminfo to update definition files
    ans = ['|'.join(names)]
    ans.extend(sorted(bool_capabilities))
    ans.extend(f'{k}#{numeric_capabilities[k]}' for k in sorted(numeric_capabilities))
    ans.extend(f'{k}={string_capabilities[k]}' for k in sorted(string_capabilities))
    return ',\n\t'.join(ans) + ',\n'


octal_escape = re.compile(r'\\([0-7]{3})')
escape_escape = re.compile(r'\\[eE]')


def key_as_bytes(name: str) -> bytes:
    ans = string_capabilities[name]
    ans = octal_escape.sub(lambda m: chr(int(m.group(1), 8)), ans)
    ans = escape_escape.sub('\033', ans)
    return ans.encode('ascii')


def get_capabilities(query_string: str, opts: 'Options', window_id: int = 0, os_window_id: int = 0) -> Generator[str, None, None]:
    from .fast_data_types import ERROR_PREFIX

    def result(encoded_query_name: str, x: str | Literal[True] | None = None) -> str:
        if x is None:
            return f'0+r{encoded_query_name}'
        if x is True:
            return f'1+r{encoded_query_name}'
        return f'1+r{encoded_query_name}={hexlify(str(x).encode("utf-8")).decode("ascii")}'

    for encoded_query_name in query_string.split(';'):
        name = qname = unhexlify(encoded_query_name).decode('utf-8')
        if name in ('TN', 'name'):
            yield result(encoded_query_name, names[0])
        elif name.startswith('kitty-query-'):
            from kittens.query_terminal.main import get_result
            name = name[len('kitty-query-'):]
            rval = get_result(name, window_id, os_window_id)
            if rval is None:
                from .utils import log_error
                log_error('Unknown kitty terminfo query:', name)
                yield result(encoded_query_name)
            else:
                yield result(encoded_query_name, rval)
        else:
            if name in bool_capabilities:
                yield result(encoded_query_name, True)
                continue
            try:
                val = queryable_capabilities[name]
            except KeyError:
                try:
                    qname = termcap_aliases[name]
                    val = queryable_capabilities[qname]
                except Exception:
                    from .utils import log_error
                    log_error(ERROR_PREFIX, 'Unknown terminfo property:', name)
                    yield result(encoded_query_name)
                    continue
            if qname in string_capabilities and '%' not in val:
                val = key_as_bytes(qname).decode('ascii')
            yield result(encoded_query_name, val)
