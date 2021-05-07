#!/usr/bin/env python3
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2018, Kovid Goyal <kovid at kovidgoyal.net>
import os
import string
import subprocess
import sys
from contextlib import suppress
from functools import lru_cache
from gettext import gettext as _
from typing import (
    Any, Dict, FrozenSet, Generator, Iterable, List, Optional, Sequence, Tuple,
    Union
)

from kitty.cli import parse_args
from kitty.cli_stub import UnicodeCLIOptions
from kitty.config import cached_values_for
from kitty.constants import config_dir
from kitty.fast_data_types import is_emoji_presentation_base, wcswidth
from kitty.key_encoding import EventType, KeyEvent
from kitty.typing import BossType
from kitty.utils import ScreenSize, get_editor

from ..tui.handler import Handler, result_handler
from ..tui.line_edit import LineEdit
from ..tui.loop import Loop
from ..tui.operations import (
    clear_screen, colored, cursor, faint, set_line_wrapping, set_window_title,
    sgr, styled
)

HEX, NAME, EMOTICONS, FAVORITES = 'HEX', 'NAME', 'EMOTICONS', 'FAVORITES'
favorites_path = os.path.join(config_dir, 'unicode-input-favorites.conf')
INDEX_CHAR = '.'
INDEX_BASE = 36
DEFAULT_SET = tuple(map(
    ord,
    '‘’“”‹›«»‚„' '😀😛😇😈😉😍😎😮👍👎' '—–§¶†‡©®™' '→⇒•·°±−×÷¼½½¾'
    '…µ¢£€¿¡¨´¸ˆ˜' 'ÀÁÂÃÄÅÆÇÈÉÊË' 'ÌÍÎÏÐÑÒÓÔÕÖØ' 'ŒŠÙÚÛÜÝŸÞßàá' 'âãäåæçèéêëìí'
    'îïðñòóôõöøœš' 'ùúûüýÿþªºαΩ∞'
))
EMOTICONS_SET = tuple(range(0x1f600, 0x1f64f + 1))
all_modes = (
    (_('Code'), 'F1', HEX),
    (_('Name'), 'F2', NAME),
    (_('Emoji'), 'F3', EMOTICONS),
    (_('Favorites'), 'F4', FAVORITES),
)


def codepoint_ok(code: int) -> bool:
    return not (code <= 32 or code == 127 or 128 <= code <= 159 or 0xd800 <= code <= 0xdbff or 0xDC00 <= code <= 0xDFFF)


@lru_cache(maxsize=256)
def points_for_word(w: str) -> FrozenSet[int]:
    from .unicode_names import codepoints_for_word
    return codepoints_for_word(w.lower())


@lru_cache(maxsize=4096)
def name(cp: Union[int, str]) -> str:
    from .unicode_names import name_for_codepoint
    c = ord(cp[0]) if isinstance(cp, str) else cp
    return (name_for_codepoint(c) or '').capitalize()


@lru_cache(maxsize=256)
def codepoints_matching_search(parts: Sequence[str]) -> List[int]:
    ans = []
    if parts and parts[0] and len(parts[0]) > 1:
        codepoints = points_for_word(parts[0])
        for word in parts[1:]:
            pts = points_for_word(word)
            if pts:
                intersection = codepoints & pts
                if intersection:
                    codepoints = intersection
                    continue
            codepoints = frozenset(c for c in codepoints if word in name(c).lower())
        if codepoints:
            ans = list(sorted(codepoints))
    return ans


def parse_favorites(raw: str) -> Generator[int, None, None]:
    for line in raw.splitlines():
        line = line.strip()
        if line.startswith('#') or not line:
            continue
        idx = line.find('#')
        if idx > -1:
            line = line[:idx]
        code_text = line.partition(' ')[0]
        try:
            code = int(code_text, 16)
        except Exception:
            pass
        else:
            if codepoint_ok(code):
                yield code


def serialize_favorites(favorites: Iterable[int]) -> str:
    ans = '''\
# Favorite characters for unicode input
# Enter the hex code for each favorite character on a new line. Blank lines are
# ignored and anything after a # is considered a comment.

'''.splitlines()
    for cp in favorites:
        ans.append('{:x} # {} {}'.format(cp, chr(cp), name(cp)))
    return '\n'.join(ans)


def load_favorites(refresh: bool = False) -> List[int]:
    ans: Optional[List[int]] = getattr(load_favorites, 'ans', None)
    if ans is None or refresh:
        try:
            with open(favorites_path, 'rb') as f:
                raw = f.read().decode('utf-8')
            ans = list(parse_favorites(raw)) or list(DEFAULT_SET)
        except FileNotFoundError:
            ans = list(DEFAULT_SET)
        setattr(load_favorites, 'ans', ans)
    return ans


def encode_hint(num: int, digits: str = string.digits + string.ascii_lowercase) -> str:
    res = ''
    d = len(digits)
    while not res or num > 0:
        num, i = divmod(num, d)
        res = digits[i] + res
    return res


def decode_hint(x: str) -> int:
    return int(x, INDEX_BASE)


class Table:

    def __init__(self, emoji_variation: str) -> None:
        self.emoji_variation = emoji_variation
        self.layout_dirty: bool = True
        self.last_rows = self.last_cols = -1
        self.codepoints: List[int] = []
        self.current_idx = 0
        self.text = ''
        self.num_cols = 0
        self.mode = HEX

    @property
    def current_codepoint(self) -> Optional[int]:
        if self.codepoints:
            return self.codepoints[self.current_idx]

    def set_codepoints(self, codepoints: List[int], mode: str = HEX, current_idx: int = 0) -> None:
        self.codepoints = codepoints
        self.mode = mode
        self.layout_dirty = True
        self.current_idx = current_idx if current_idx < len(codepoints) else 0

    def codepoint_at_hint(self, hint: str) -> int:
        return self.codepoints[decode_hint(hint)]

    def layout(self, rows: int, cols: int) -> Optional[str]:
        if not self.layout_dirty and self.last_cols == cols and self.last_rows == rows:
            return self.text
        self.last_cols, self.last_rows = cols, rows
        self.layout_dirty = False

        def safe_chr(codepoint: int) -> str:
            ans = chr(codepoint).encode('utf-8', 'replace').decode('utf-8')
            if self.emoji_variation and is_emoji_presentation_base(codepoint):
                ans += self.emoji_variation
            return ans

        if self.mode is NAME:
            def as_parts(i: int, codepoint: int) -> Tuple[str, str, str]:
                return encode_hint(i).ljust(idx_size), safe_chr(codepoint), name(codepoint)

            def cell(i: int, idx: str, c: str, desc: str) -> Generator[str, None, None]:
                is_current = i == self.current_idx
                text = colored(idx, 'green') + ' ' + sgr('49') + c + ' '
                w = wcswidth(c)
                if w < 2:
                    text += ' ' * (2 - w)
                if len(desc) > space_for_desc:
                    text += desc[:space_for_desc - 1] + '…'
                else:
                    text += desc
                extra = space_for_desc - len(desc)
                if extra > 0:
                    text += ' ' * extra

                yield styled(text, reverse=True if is_current else None)

        else:
            def as_parts(i: int, codepoint: int) -> Tuple[str, str, str]:
                return encode_hint(i).ljust(idx_size), safe_chr(codepoint), ''

            def cell(i: int, idx: str, c: str, desc: str) -> Generator[str, None, None]:
                yield colored(idx, 'green') + ' '
                yield colored(c, 'gray', True)
                w = wcswidth(c)
                if w < 2:
                    yield ' ' * (2 - w)

        num = len(self.codepoints)
        if num < 1:
            self.text = ''
            self.num_cols = 0
            return self.text
        idx_size = len(encode_hint(num - 1))

        parts = [as_parts(i, c) for i, c in enumerate(self.codepoints)]
        if self.mode is NAME:
            sizes = [idx_size + 2 + len(p[2]) + 2 for p in parts]
        else:
            sizes = [idx_size + 3]
        longest = max(sizes) if sizes else 0
        col_width = longest + 2
        col_width = min(col_width, 40)
        space_for_desc = col_width - 2 - idx_size - 4
        num_cols = self.num_cols = max(cols // col_width, 1)
        buf: List[str] = []
        a = buf.append
        rows_left = rows

        for i, (idx, c, desc) in enumerate(parts):
            if i > 0 and i % num_cols == 0:
                rows_left -= 1
                if rows_left == 0:
                    break
                a('\r\n')
            buf.extend(cell(i, idx, c, desc))
            a('  ')
        self.text = ''.join(buf)
        return self.text

    def move_current(self, rows: int = 0, cols: int = 0) -> None:
        if len(self.codepoints) == 0:
            return
        if cols:
            self.current_idx = (self.current_idx + len(self.codepoints) + cols) % len(self.codepoints)
            self.layout_dirty = True
        if rows:
            amt = rows * self.num_cols
            self.current_idx += amt
            self.current_idx = max(0, min(self.current_idx, len(self.codepoints) - 1))
            self.layout_dirty = True


def is_index(w: str) -> bool:
    if w[0] != INDEX_CHAR:
        return False
    try:
        int(w.lstrip(INDEX_CHAR), INDEX_BASE)
        return True
    except Exception:
        return False


class UnicodeInput(Handler):

    def __init__(self, cached_values: Dict[str, Any], emoji_variation: str = 'none') -> None:
        self.cached_values = cached_values
        self.emoji_variation = ''
        if emoji_variation == 'text':
            self.emoji_variation = '\ufe0e'
        elif emoji_variation == 'graphic':
            self.emoji_variation = '\ufe0f'
        self.line_edit = LineEdit()
        self.recent = list(self.cached_values.get('recent', DEFAULT_SET))
        self.current_char: Optional[str] = None
        self.prompt_template = '{}> '
        self.last_updated_code_point_at: Optional[Tuple[str, Union[Sequence[int], None, str]]] = None
        self.choice_line = ''
        self.mode = globals().get(cached_values.get('mode', 'HEX'), 'HEX')
        self.table = Table(self.emoji_variation)
        self.update_prompt()

    @property
    def resolved_current_char(self) -> Optional[str]:
        ans = self.current_char
        if ans:
            if self.emoji_variation and is_emoji_presentation_base(ord(ans[0])):
                ans += self.emoji_variation
        return ans

    def update_codepoints(self) -> None:
        codepoints = None
        iindex_word = 0
        if self.mode is HEX:
            q: Tuple[str, Optional[Union[str, Sequence[int]]]] = (self.mode, None)
            codepoints = self.recent
        elif self.mode is EMOTICONS:
            q = self.mode, None
            codepoints = list(EMOTICONS_SET)
        elif self.mode is FAVORITES:
            codepoints = load_favorites()
            q = self.mode, tuple(codepoints)
        elif self.mode is NAME:
            q = self.mode, self.line_edit.current_input
            if q != self.last_updated_code_point_at:
                words = self.line_edit.current_input.split()
                words = [w for w in words if w != INDEX_CHAR]
                index_words = [i for i, w in enumerate(words) if i > 0 and is_index(w)]
                if index_words:
                    index_word = words[index_words[0]]
                    words = words[:index_words[0]]
                    iindex_word = int(index_word.lstrip(INDEX_CHAR), INDEX_BASE)
                codepoints = codepoints_matching_search(tuple(words))
        if q != self.last_updated_code_point_at:
            self.last_updated_code_point_at = q
            self.table.set_codepoints(codepoints or [], self.mode, iindex_word)

    def update_current_char(self) -> None:
        self.update_codepoints()
        self.current_char = None
        if self.mode is HEX:
            with suppress(Exception):
                if self.line_edit.current_input.startswith(INDEX_CHAR):
                    if len(self.line_edit.current_input) > 1:
                        self.current_char = chr(self.table.codepoint_at_hint(self.line_edit.current_input[1:]))
                elif self.line_edit.current_input:
                    code = int(self.line_edit.current_input, 16)
                    self.current_char = chr(code)
        elif self.mode is NAME:
            cc = self.table.current_codepoint
            if cc:
                self.current_char = chr(cc)
        else:
            with suppress(Exception):
                if self.line_edit.current_input:
                    self.current_char = chr(self.table.codepoint_at_hint(self.line_edit.current_input.lstrip(INDEX_CHAR)))
        if self.current_char is not None:
            code = ord(self.current_char)
            if not codepoint_ok(code):
                self.current_char = None

    def update_prompt(self) -> None:
        self.update_current_char()
        if self.current_char is None:
            c, color = '??', 'red'
            self.choice_line = ''
        else:
            c, color = self.current_char, 'green'
            if self.emoji_variation and is_emoji_presentation_base(ord(c[0])):
                c += self.emoji_variation
            self.choice_line = _('Chosen:') + ' {} U+{} {}'.format(
                colored(c, 'green'), hex(ord(c[0]))[2:], faint(styled(name(c) or '', italic=True)))
        self.prompt = self.prompt_template.format(colored(c, color))

    def init_terminal_state(self) -> None:
        self.write(set_line_wrapping(False))
        self.write(set_window_title(_('Unicode input')))

    def initialize(self) -> None:
        self.init_terminal_state()
        self.draw_screen()

    def draw_title_bar(self) -> None:
        entries = []
        for name, key, mode in all_modes:
            entry = ' {} ({}) '.format(name, key)
            if mode is self.mode:
                entry = styled(entry, reverse=False, bold=True)
            entries.append(entry)
        text = _('Search by:{}').format(' '.join(entries))
        extra = self.screen_size.cols - wcswidth(text)
        if extra > 0:
            text += ' ' * extra
        self.print(styled(text, reverse=True))

    def draw_screen(self) -> None:
        self.write(clear_screen())
        self.draw_title_bar()
        y = 1

        def writeln(text: str = '') -> None:
            nonlocal y
            self.print(text)
            y += 1

        if self.mode is NAME:
            writeln(_('Enter words from the name of the character'))
        elif self.mode is HEX:
            writeln(_('Enter the hex code for the character'))
        else:
            writeln(_('Enter the index for the character you want from the list below'))
        self.line_edit.write(self.write, self.prompt)
        with cursor(self.write):
            writeln()
            writeln(self.choice_line)
            if self.mode is HEX:
                writeln(faint(_('Type {} followed by the index for the recent entries below').format(INDEX_CHAR)))
            elif self.mode is NAME:
                writeln(faint(_('Use Tab or the arrow keys to choose a character from below')))
            elif self.mode is FAVORITES:
                writeln(faint(_('Press F12 to edit the list of favorites')))
            self.table_at = y
            q = self.table.layout(self.screen_size.rows - self.table_at, self.screen_size.cols)
            if q:
                self.write(q)

    def refresh(self) -> None:
        self.update_prompt()
        self.draw_screen()

    def on_text(self, text: str, in_bracketed_paste: bool = False) -> None:
        self.line_edit.on_text(text, in_bracketed_paste)
        self.refresh()

    def on_key(self, key_event: KeyEvent) -> None:
        if self.mode is HEX and key_event.type is not EventType.RELEASE and not key_event.has_mods:
            try:
                val = int(self.line_edit.current_input, 16)
            except Exception:
                pass
            else:
                if key_event.matches('tab'):
                    self.line_edit.current_input = hex(val + 0x10)[2:]
                    self.refresh()
                    return
                if key_event.matches('up'):
                    self.line_edit.current_input = hex(val + 1)[2:]
                    self.refresh()
                    return
                if key_event.matches('down'):
                    self.line_edit.current_input = hex(val - 1)[2:]
                    self.refresh()
                    return
        if self.mode is NAME and key_event.type is not EventType.RELEASE and not key_event.has_mods:
            if key_event.matches('shift+tab'):
                self.table.move_current(cols=-1)
                self.refresh()
                return
            if key_event.matches('tab'):
                self.table.move_current(cols=1)
                self.refresh()
                return
            if key_event.matches('left'):
                self.table.move_current(cols=-1)
                self.refresh()
                return
            if key_event.matches('right'):
                self.table.move_current(cols=1)
                self.refresh()
                return
            if key_event.matches('up'):
                self.table.move_current(rows=-1)
                self.refresh()
                return
            if key_event.matches('down'):
                self.table.move_current(rows=1)
                self.refresh()
                return

        if self.line_edit.on_key(key_event):
            self.refresh()
            return
        if key_event.matches('enter'):
            self.quit_loop(0)
            return
        if key_event.matches('esc'):
            self.quit_loop(1)
            return
        if key_event.matches('f1'):
            self.switch_mode(HEX)
            return
        if key_event.matches('f2'):
            self.switch_mode(NAME)
            return
        if key_event.matches('f3'):
            self.switch_mode(EMOTICONS)
            return
        if key_event.matches('f4'):
            self.switch_mode(FAVORITES)
            return
        if key_event.matches('f12') and self.mode is FAVORITES:
            self.edit_favorites()
            return
        if key_event.matches('ctrl+shift+tab'):
            self.next_mode(-1)
            return
        for key in ('tab', '[', ']'):
            if key_event.matches(f'ctrl+{key}'):
                self.next_mode(-1 if key == '[' else 1)
                return

    def edit_favorites(self) -> None:
        if not os.path.exists(favorites_path):
            with open(favorites_path, 'wb') as f:
                f.write(serialize_favorites(load_favorites()).encode('utf-8'))
        with self.suspend():
            p = subprocess.Popen(get_editor() + [favorites_path])
            if p.wait() == 0:
                load_favorites(refresh=True)
        self.init_terminal_state()
        self.refresh()

    def switch_mode(self, mode: str) -> None:
        if mode is not self.mode:
            self.mode = mode
            self.cached_values['mode'] = mode
            self.line_edit.clear()
            self.current_char = None
            self.choice_line = ''
            self.refresh()

    def next_mode(self, delta: int = 1) -> None:
        modes = tuple(x[-1] for x in all_modes)
        idx = (modes.index(self.mode) + delta + len(modes)) % len(modes)
        self.switch_mode(modes[idx])

    def on_interrupt(self) -> None:
        self.quit_loop(1)

    def on_eot(self) -> None:
        self.quit_loop(1)

    def on_resize(self, new_size: ScreenSize) -> None:
        self.refresh()


help_text = 'Input a unicode character'
usage = ''
OPTIONS = '''
--emoji-variation
type=choices
default=none
choices=none,graphic,text
Whether to use the textual or the graphical form for emoji. By default the
default form specified in the unicode standard for the symbol is used.


'''.format


def parse_unicode_input_args(args: List[str]) -> Tuple[UnicodeCLIOptions, List[str]]:
    return parse_args(args, OPTIONS, usage, help_text, 'kitty +kitten unicode_input', result_class=UnicodeCLIOptions)


def main(args: List[str]) -> Optional[str]:
    try:
        cli_opts, items = parse_unicode_input_args(args[1:])
    except SystemExit as e:
        if e.code != 0:
            print(e.args[0], file=sys.stderr)
            input(_('Press Enter to quit'))
        return None

    loop = Loop()
    with cached_values_for('unicode-input') as cached_values:
        handler = UnicodeInput(cached_values, cli_opts.emoji_variation)
        loop.loop(handler)
        if handler.current_char and loop.return_code == 0:
            with suppress(Exception):
                handler.recent.remove(ord(handler.current_char))
            recent = [ord(handler.current_char)] + handler.recent
            cached_values['recent'] = recent[:len(DEFAULT_SET)]
            return handler.resolved_current_char
    if loop.return_code != 0:
        raise SystemExit(loop.return_code)
    return None


@result_handler()
def handle_result(args: List[str], current_char: str, target_window_id: int, boss: BossType) -> None:
    w = boss.window_id_map.get(target_window_id)
    if w is not None:
        w.paste(current_char)


if __name__ == '__main__':
    ans = main(sys.argv)
    if ans:
        print(ans)
elif __name__ == '__doc__':
    cd = sys.cli_docs  # type: ignore
    cd['usage'] = usage
    cd['options'] = OPTIONS
    cd['help_text'] = help_text
