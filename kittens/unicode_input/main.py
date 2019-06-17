#!/usr/bin/env python3
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2018, Kovid Goyal <kovid at kovidgoyal.net>

import os
import string
import subprocess
from functools import lru_cache
from gettext import gettext as _
from contextlib import suppress

from kitty.config import cached_values_for
from kitty.constants import config_dir
from kitty.utils import get_editor
from kitty.fast_data_types import wcswidth
from kitty.key_encoding import (
    DOWN, ESCAPE, F1, F2, F3, F4, F12, LEFT, RELEASE, RIGHT, SHIFT, TAB, UP,
    enter_key
)

from ..tui.line_edit import LineEdit
from ..tui.handler import Handler
from ..tui.loop import Loop
from ..tui.operations import (
    clear_screen, colored, cursor, faint, set_line_wrapping,
    set_window_title, sgr, styled
)

HEX, NAME, EMOTICONS, FAVORITES = 'HEX', 'NAME', 'EMOTICONS', 'FAVORITES'
favorites_path = os.path.join(config_dir, 'unicode-input-favorites.conf')
INDEX_CHAR = '.'
DEFAULT_SET = tuple(map(
    ord,
    '‘’“”‹›«»‚„' '😀😛😇😈😉😍😎😮👍👎' '—–§¶†‡©®™' '→⇒•·°±−×÷¼½½¾'
    '…µ¢£€¿¡¨´¸ˆ˜' 'ÀÁÂÃÄÅÆÇÈÉÊË' 'ÌÍÎÏÐÑÒÓÔÕÖØ' 'ŒŠÙÚÛÜÝŸÞßàá' 'âãäåæçèéêëìí'
    'îïðñòóôõöøœš' 'ùúûüýÿþªºαΩ∞'
))
EMOTICONS_SET = tuple(range(0x1f600, 0x1f64f + 1))


def codepoint_ok(code):
    return not (code <= 32 or code == 127 or 128 <= code <= 159 or 0xd800 <= code <= 0xdbff or 0xDC00 <= code <= 0xDFFF)


@lru_cache(maxsize=256)
def points_for_word(w):
    from .unicode_names import codepoints_for_word
    return codepoints_for_word(w.lower())


@lru_cache(maxsize=4096)
def name(cp):
    from .unicode_names import name_for_codepoint
    if isinstance(cp, str):
        cp = ord(cp[0])
    return (name_for_codepoint(cp) or '').capitalize()


@lru_cache(maxsize=256)
def codepoints_matching_search(parts):
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
            codepoints = {c for c in codepoints if word in name(c).lower()}
        if codepoints:
            ans = list(sorted(codepoints))
    return ans


def parse_favorites(raw):
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


def serialize_favorites(favorites):
    ans = '''\
# Favorite characters for unicode input
# Enter the hex code for each favorite character on a new line. Blank lines are
# ignored and anything after a # is considered a comment.

'''.splitlines()
    for cp in favorites:
        ans.append('{:x} # {} {}'.format(cp, chr(cp), name(cp)))
    return '\n'.join(ans)


def load_favorites(refresh=False):
    ans = getattr(load_favorites, 'ans', None)
    if ans is None or refresh:
        try:
            with open(favorites_path, 'rb') as f:
                raw = f.read().decode('utf-8')
            ans = load_favorites.ans = list(parse_favorites(raw)) or list(DEFAULT_SET)
        except FileNotFoundError:
            ans = load_favorites.ans = list(DEFAULT_SET)
    return ans


def encode_hint(num, digits=string.digits + string.ascii_lowercase):
    res = ''
    d = len(digits)
    while not res or num > 0:
        num, i = divmod(num, d)
        res = digits[i] + res
    return res


def decode_hint(x):
    return int(x, 36)


class Table:

    def __init__(self):
        self.layout_dirty = True
        self.last_rows = self.last_cols = -1
        self.codepoints = []
        self.current_idx = 0
        self.text = ''
        self.num_cols = 0
        self.mode = HEX

    @property
    def current_codepoint(self):
        if self.codepoints:
            return self.codepoints[self.current_idx]

    def set_codepoints(self, codepoints, mode=HEX):
        self.codepoints = codepoints
        self.mode = mode
        self.layout_dirty = True
        self.current_idx = 0

    def codepoint_at_hint(self, hint):
        return self.codepoints[decode_hint(hint)]

    def layout(self, rows, cols):
        if not self.layout_dirty and self.last_cols == cols and self.last_rows == rows:
            return self.text
        self.last_cols, self.last_rows = cols, rows
        self.layout_dirty = False

        def safe_chr(codepoint):
            return chr(codepoint).encode('utf-8', 'replace').decode('utf-8')

        if self.mode is NAME:
            def as_parts(i, codepoint):
                return encode_hint(i).ljust(idx_size), safe_chr(codepoint), name(codepoint)

            def cell(i, idx, c, desc):
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
            def as_parts(i, codepoint):
                return encode_hint(i).ljust(idx_size), safe_chr(codepoint), ''

            def cell(i, idx, c, desc):
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
        buf = []
        a = buf.append
        rows_left = rows

        for i, (idx, c, desc) in enumerate(parts):
            if i > 0 and i % num_cols == 0:
                rows_left -= 1
                if rows_left == 0:
                    break
                buf.append('\r\n')
            buf.extend(cell(i, idx, c, desc))
            a('  ')
        self.text = ''.join(buf)
        return self.text

    def move_current(self, rows=0, cols=0):
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


def is_index(w):
    with suppress(Exception):
        int(w.lstrip(INDEX_CHAR), 16)
        return True
    return False


class UnicodeInput(Handler):

    def __init__(self, cached_values):
        self.cached_values = cached_values
        self.line_edit = LineEdit()
        self.recent = list(self.cached_values.get('recent', DEFAULT_SET))
        self.current_char = None
        self.prompt_template = '{}> '
        self.last_updated_code_point_at = None
        self.choice_line = ''
        self.mode = globals().get(cached_values.get('mode', 'HEX'), 'HEX')
        self.table = Table()
        self.update_prompt()

    def update_codepoints(self):
        codepoints = None
        if self.mode is HEX:
            q = self.mode, None
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
                codepoints = codepoints_matching_search(tuple(words))
                if index_words:
                    index_word = int(index_word.lstrip(INDEX_CHAR), 16)
                    if index_word < len(codepoints):
                        codepoints = [codepoints[index_word]]
        if q != self.last_updated_code_point_at:
            self.last_updated_code_point_at = q
            self.table.set_codepoints(codepoints, self.mode)

    def update_current_char(self):
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

    def update_prompt(self):
        self.update_current_char()
        if self.current_char is None:
            c, color = '??', 'red'
            self.choice_line = ''
        else:
            c, color = self.current_char, 'green'
            self.choice_line = _('Chosen:') + ' {} U+{} {}'.format(
                colored(c, 'green'), hex(ord(c))[2:], faint(styled(name(c) or '', italic=True)))
        self.prompt = self.prompt_template.format(colored(c, color))

    def init_terminal_state(self):
        self.write(set_line_wrapping(False))
        self.write(set_window_title(_('Unicode input')))

    def initialize(self):
        self.init_terminal_state()
        self.draw_screen()

    def draw_title_bar(self):
        entries = []
        for name, key, mode in [
                (_('Code'), 'F1', HEX),
                (_('Name'), 'F2', NAME),
                (_('Emoji'), 'F3', EMOTICONS),
                (_('Favorites'), 'F4', FAVORITES),
        ]:
            entry = ' {} ({}) '.format(name, key)
            if mode is self.mode:
                entry = styled(entry, reverse=False, bold=True)
            entries.append(entry)
        text = _('Search by:{}').format(' '.join(entries))
        extra = self.screen_size.cols - wcswidth(text)
        if extra > 0:
            text += ' ' * extra
        self.print(styled(text, reverse=True))

    def draw_screen(self):
        self.write(clear_screen())
        self.draw_title_bar()
        y = 1

        def writeln(text=''):
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
            self.write(self.table.layout(self.screen_size.rows - self.table_at, self.screen_size.cols))

    def refresh(self):
        self.update_prompt()
        self.draw_screen()

    def on_text(self, text, in_bracketed_paste):
        self.line_edit.on_text(text, in_bracketed_paste)
        self.refresh()

    def on_key(self, key_event):
        if self.mode is HEX and key_event.type is not RELEASE and not key_event.mods:
            try:
                val = int(self.line_edit.current_input, 16)
            except Exception:
                pass
            else:
                if key_event.key is TAB:
                    self.line_edit.current_input = hex(val + 0x10)[2:]
                    self.refresh()
                    return
                if key_event.key is UP:
                    self.line_edit.current_input = hex(val + 1)[2:]
                    self.refresh()
                    return
                if key_event.key is DOWN:
                    self.line_edit.current_input = hex(val - 1)[2:]
                    self.refresh()
                    return
        if self.mode is NAME and key_event.type is not RELEASE and not key_event.mods:
            if key_event.key is TAB:
                if key_event.mods == SHIFT:
                    self.table.move_current(cols=-1), self.refresh()
                elif not key_event.mods:
                    self.table.move_current(cols=1), self.refresh()
                return
            elif key_event.key is LEFT and not key_event.mods:
                self.table.move_current(cols=-1), self.refresh()
                return
            elif key_event.key is RIGHT and not key_event.mods:
                self.table.move_current(cols=1), self.refresh()
                return
            elif key_event.key is UP and not key_event.mods:
                self.table.move_current(rows=-1), self.refresh()
                return
            elif key_event.key is DOWN and not key_event.mods:
                self.table.move_current(rows=1), self.refresh()
                return

        if self.line_edit.on_key(key_event):
            self.refresh()
            return
        if key_event is enter_key:
            self.quit_loop(0)
        elif key_event.type is RELEASE and not key_event.mods:
            if key_event.key is ESCAPE:
                self.quit_loop(1)
            elif key_event.key is F1:
                self.switch_mode(HEX)
            elif key_event.key is F2:
                self.switch_mode(NAME)
            elif key_event.key is F3:
                self.switch_mode(EMOTICONS)
            elif key_event.key is F4:
                self.switch_mode(FAVORITES)
            elif key_event.key is F12 and self.mode is FAVORITES:
                self.edit_favorites()

    def edit_favorites(self):
        if not os.path.exists(favorites_path):
            with open(favorites_path, 'wb') as f:
                f.write(serialize_favorites(load_favorites()).encode('utf-8'))
        with self.suspend():
            p = subprocess.Popen(get_editor() + [favorites_path])
            if p.wait() == 0:
                load_favorites(refresh=True)
        self.init_terminal_state()
        self.refresh()

    def switch_mode(self, mode):
        if mode is not self.mode:
            self.mode = mode
            self.cached_values['mode'] = mode
            self.line_edit.clear()
            self.current_char = None
            self.choice_line = ''
            self.refresh()

    def on_interrupt(self):
        self.quit_loop(1)

    def on_eot(self):
        self.quit_loop(1)

    def on_resize(self, new_size):
        self.refresh()


def main(args):
    loop = Loop()
    with cached_values_for('unicode-input') as cached_values:
        handler = UnicodeInput(cached_values)
        loop.loop(handler)
        if handler.current_char and loop.return_code == 0:
            with suppress(Exception):
                handler.recent.remove(ord(handler.current_char))
            recent = [ord(handler.current_char)] + handler.recent
            cached_values['recent'] = recent[:len(DEFAULT_SET)]
            return handler.current_char
    if loop.return_code != 0:
        raise SystemExit(loop.return_code)


def handle_result(args, current_char, target_window_id, boss):
    w = boss.window_id_map.get(target_window_id)
    if w is not None:
        w.paste(current_char)


if __name__ == '__main__':
    import sys
    if '-h' in sys.argv or '--help' in sys.argv:
        print('Choose a unicode character to input into the terminal')
        raise SystemExit(0)
    ans = main(sys.argv)
    if ans:
        print(ans)
