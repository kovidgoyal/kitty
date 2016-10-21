#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2016, Kovid Goyal <kovid at kovidgoyal.net>


import codecs
import unicodedata
from collections import deque, namedtuple
from typing import Sequence

from PyQt5.QtCore import QObject, pyqtSignal

from pyte import charsets as cs, graphics as g, modes as mo
from .data_types import Line, Cursor, rewrap_lines
from .utils import wcwidth, is_simple_string, sanitize_title
from .unicode import ignore_pat


#: A container for screen's scroll margins.
Margins = namedtuple("Margins", "top bottom")

#: A container for savepoint, created on :data:`~pyte.escape.DECSC`.
Savepoint = namedtuple("Savepoint", [
    "cursor",
    "g0_charset",
    "g1_charset",
    "charset",
    "use_utf8",
    "origin",
    "wrap"
])


def wrap_cursor_position(x, y, lines, columns):
    if x >= columns:
        if y < lines - 1:
            x, y = 0, y + 1
        else:
            x, y = x - 1, y
    return x, y


class Screen(QObject):
    """
       See standard ECMA-48, Section 6.1.1 http://www.ecma-international.org/publications/standards/Ecma-048.htm
       for a description of the presentational component, implemented by ``Screen``.
    """

    title_changed = pyqtSignal(object)
    icon_changed = pyqtSignal(object)
    write_to_child = pyqtSignal(object)
    change_default_color = pyqtSignal(object, object)
    _notify_cursor_position = True

    def __init__(self, opts, tracker, columns: int=80, lines: int=24, parent=None):
        QObject.__init__(self, parent)
        self.write_process_input = self.write_to_child.emit
        for attr in 'cursor_changed cursor_position_changed update_screen update_line_range update_cell_range line_added_to_history'.split():
            setattr(self, attr, getattr(tracker, attr))
        self.main_savepoints, self.alt_savepoints = deque(), deque()
        self.savepoints = self.main_savepoints
        self.columns = columns
        self.lines = lines
        sz = max(1000, opts.scrollback_lines)
        self.tophistorybuf = deque(maxlen=sz)
        self.main_linebuf, self.alt_linebuf = list(Line(self.columns) for i in range(self.lines)), list(Line(self.columns) for i in range(self.lines))
        self.linebuf = self.main_linebuf
        self.reset(notify=False)

    def apply_opts(self, opts):
        sz = max(1000, opts.scrollback_lines)
        if sz != self.tophistorybuf.maxlen:
            self.tophistorybuf = deque(self.tophistorybuf, maxlen=sz)

    def line(self, i):
        return self.linebuf[i]

    def __repr__(self):
        return ("{0}({1}, {2})".format(self.__class__.__name__,
                                       self.columns, self.lines))

    def notify_cursor_position(self):
        if self._notify_cursor_position:
            self.cursor_position_changed(self.cursor)

    @property
    def display(self) -> Sequence[str]:
        return tuple(map(str, self.linebuf))

    def toggle_screen_buffer(self):
        self.save_cursor()
        if self.linebuf is self.main_linebuf:
            self.linebuf, self.savepoints = self.alt_linebuf, self.alt_savepoints
        else:
            self.linebuf, self.savepoints = self.main_linebuf, self.main_savepoints
        self.restore_cursor()
        self.update_screen()

    def reset(self, notify=True):
        """Resets the terminal to its initial state.

        * Scroll margins are reset to screen boundaries.
        * Cursor is moved to home location -- ``(0, 0)`` and its
          attributes are set to defaults (see :attr:`default_char`).
        * Screen is cleared -- each character is reset to
          :attr:`default_char`.
        * Tabstops are reset to "every eight columns".

        .. note::

           Neither VT220 nor VT102 manuals mentioned that terminal modes
           and tabstops should be reset as well, thanks to
           :manpage:`xterm` -- we now know that.
        """
        if self.linebuf is self.alt_linebuf:
            self.toggle_screen_buffer()
        self.linebuf.clear()
        self.linebuf[:] = (Line(self.columns) for i in range(self.lines))
        self.mode = {mo.DECAWM, mo.DECTCEM}
        self.margins = Margins(0, self.lines - 1)

        self.charset = 0
        self.g0_charset = cs.LAT1_MAP
        self.g1_charset = cs.VT100_MAP
        self.use_utf8 = True
        self.utf8_decoder = codecs.getincrementaldecoder("utf-8")("replace")

        # From ``man terminfo`` -- "... hardware tabs are initially
        # set every `n` spaces when the terminal is powered up. Since
        # we aim to support VT102 / VT220 and linux -- we use n = 8.
        self.tabstops = set(range(7, self.columns, 8))
        self.normal_keypad_mode()

        self.cursor = Cursor(0, 0)
        self.cursor_changed(self.cursor)
        self.cursor_position()
        self.change_default_color.emit('fg', None)
        self.change_default_color.emit('bg', None)
        if notify:
            self.update_screen()

    def resize(self, lines: int, columns: int):
        """Resize the screen to the given dimensions.

        .. note:: According to `xterm`, we should also reset origin
                  mode and screen margins, see ``xterm/screen.c:1761``.

        """
        self.lines, self.columns = lines, columns
        for hb in (self.tophistorybuf, ):
            old = hb.copy()
            hb.clear(), hb.extend(rewrap_lines(old, columns))
        for lb in (self.main_linebuf, self.alt_linebuf):
            old_lines = lb[:]
            lb.clear()
            lb[:] = rewrap_lines(old_lines, self.columns)
            while len(lb) < self.lines:
                lb.append(Line(self.columns))
            if len(lb) > self.lines:
                extra = len(lb) - self.lines
                slc = lb[:extra]
                del lb[:extra]
                if lb is self.main_linebuf:
                    self.tophistorybuf.extend(slc)

        self.margins = Margins(0, self.lines - 1)
        self._notify_cursor_position = False
        try:
            x, y = self.cursor.x, self.cursor.y
            self.reset_mode(mo.DECOM)
            self.cursor.x, self.cursor.y = x, y
        finally:
            self._notify_cursor_position = True
        self.ensure_bounds()

    def set_margins(self, top=None, bottom=None):
        """Selects top and bottom margins for the scrolling region.

        Margins determine which screen lines move during scrolling
        (see :meth:`index` and :meth:`reverse_index`). Characters added
        outside the scrolling region do not cause the screen to scroll.

        :param int top: the smallest line number that is scrolled.
        :param int bottom: the biggest line number that is scrolled.
        """
        if top is None or bottom is None:
            return

        # Arguments are 1-based, while :attr:`margins` are zero based --
        # so we have to decrement them by one. We also make sure that
        # both of them is bounded by [0, lines - 1].
        top = max(0, min(top - 1, self.lines - 1))
        bottom = max(0, min(bottom - 1, self.lines - 1))

        # Even though VT102 and VT220 require DECSTBM to ignore regions
        # of width less than 2, some programs (like aptitude for example)
        # rely on it. Practicality beats purity.
        if bottom - top >= 1:
            self.margins = Margins(top, bottom)

            # The cursor moves to the home position when the top and
            # bottom margins of the scrolling region (DECSTBM) changes.
            self.cursor_position()

    def set_mode(self, *modes, private=False):
        """Sets (enables) a given list of modes.

        :param list modes: modes to set, where each mode is a constant
                           from :mod:`pyte.modes`.
        """
        # Private mode codes are shifted, to be distingiushed from non
        # private ones.
        if private:
            modes = [mode << 5 for mode in modes]

        self.mode.update(modes)

        # When DECOLM mode is set, the screen is erased and the cursor
        # moves to the home position.
        if mo.DECCOLM in modes:
            # self.resize(columns=132)  Disabled since we only allow resizing
            # by the user
            self.erase_in_display(2)
            self.cursor_position()

        # According to `vttest`, DECOM should also home the cursor, see
        # vttest/main.c:303.
        if mo.DECOM in modes:
            self.cursor_position()

        # Mark all displayed characters as reverse.
        if mo.DECSCNM in modes:
            for line in self.linebuf:
                for i in range(len(line)):
                    line.reverse[i] = True
            self.update_screen()
            self.select_graphic_rendition(7)  # +reverse.

        # Show/hide the cursor.
        previous, self.cursor.hidden = self.cursor.hidden, mo.DECTCEM not in self.mode
        if previous != self.cursor.hidden:
            self.cursor_changed(self.cursor)

        if mo.ALTERNATE_SCREEN in self.mode and self.linebuf is self.main_linebuf:
            self.toggle_screen_buffer()

    @property
    def in_bracketed_paste_mode(self):
        return mo.BRACKETED_PASTE in self.mode

    @property
    def enable_focus_tracking(self):
        return mo.FOCUS_TRACKING in self.mode

    def reset_mode(self, *modes, private=False):
        """Resets (disables) a given list of modes.

        :param list modes: modes to reset -- hopefully, each mode is a
                           constant from :mod:`pyte.modes`.
        """
        # Private mode codes are shifted, to be distinguished from non
        # private ones.
        if private:
            modes = [mode << 5 for mode in modes]

        self.mode.difference_update(modes)

        # Lines below follow the logic in :meth:`set_mode`.
        if mo.DECCOLM in modes:
            # self.resize(columns=80)  Disabled since we only allow resizing by
            # the user
            self.erase_in_display(2)
            self.cursor_position()

        if mo.DECOM in modes:
            self.cursor_position()

        if mo.DECSCNM in modes:
            for line in self.linebuf:
                for i in range(len(line)):
                    line.reverse[i] = False
            self.update_screen()
            self.select_graphic_rendition(27)  # -reverse.

        # Show/hide the cursor.
        previous, self.cursor.hidden = self.cursor.hidden, mo.DECTCEM not in self.mode
        if previous != self.cursor.hidden:
            self.cursor_changed(self.cursor)

        if mo.ALTERNATE_SCREEN not in self.mode and self.linebuf is not self.main_linebuf:
            self.toggle_screen_buffer()

    def define_charset(self, code, mode):
        """Defines ``G0`` or ``G1`` charset.

        :param str code: character set code, should be a character
                         from ``b"B0UK"``, otherwise ignored.
        :param str mode: if ``"("`` ``G0`` charset is defined, if
                         ``")"`` -- we operate on ``G1``.

        .. warning:: User-defined charsets are currently not supported.
        """
        if code in cs.MAPS:
            if mode == b"(":
                self.g0_charset = cs.MAPS[code]
            elif mode == b")":
                self.g1_charset = cs.MAPS[code]

    def shift_in(self):
        """Selects ``G0`` character set."""
        self.charset = 0

    def shift_out(self):
        """Selects ``G1`` character set."""
        self.charset = 1

    def select_other_charset(self, code):
        """Selects other (non G0 or G1) charset.

        :param str code: character set code, should be a character from
                         ``b"@G8"``, otherwise ignored.

        .. note:: We currently follow ``"linux"`` and only use this
                  command to switch from ISO-8859-1 to UTF-8 and back.

        .. seealso::

        `Standard ECMA-35, Section 15.4 \
        <http://www.ecma-international.org/publications/standards/Ecma-035.htm>`_
        for a description of VTXXX character set machinery.
        """
        if code == b"@":
            self.use_utf8 = False
            self.utf8_decoder.reset()
        elif code in b"G8":
            self.use_utf8 = True

    def _decode(self, data):
        """Decodes bytes to text according to the selected charset.

        :param bytes data: bytes to decode.
        """
        if self.charset:
            return "".join(self.g1_charset[b] for b in data)
        if self.use_utf8:
            return self.utf8_decoder.decode(data)
        return "".join(self.g0_charset[b] for b in data)

    def _draw_fast(self, data: str) -> None:
        do_insert = mo.IRM in self.mode
        pos = 0
        while pos < len(data):
            space_left_in_line = self.columns - self.cursor.x
            len_left = len(data) - pos
            if space_left_in_line < 1:
                if mo.DECAWM in self.mode:
                    self.carriage_return()
                    self.linefeed()
                    self.linebuf[self.cursor.y].continued = True
                    space_left_in_line = self.columns
                else:
                    space_left_in_line = 1
                    len_left = 1
                    pos = len(data) - 1
                    self.cursor.x = self.columns - 1
            write_sz = min(len_left, space_left_in_line)
            line = self.linebuf[self.cursor.y]
            if do_insert:
                line.right_shift(self.cursor.x, write_sz)
            line.set_text(data, pos, write_sz, self.cursor)
            pos += write_sz
            cx = self.cursor.x
            self.cursor.x += write_sz
            right = self.columns - 1 if do_insert else max(0, min(self.cursor.x - 1, self.columns - 1))
            self.update_cell_range(self.cursor.y, cx, right)

    def _draw_char(self, char: str, char_width: int) -> None:
        space_left_in_line = self.columns - self.cursor.x
        if space_left_in_line < char_width:
            if mo.DECAWM in self.mode:
                self.carriage_return()
                self.linefeed()
                self.linebuf[self.cursor.y].continued = True
            else:
                self.cursor.x = self.columns - char_width

        do_insert = mo.IRM in self.mode

        cx = self.cursor.x
        line = self.linebuf[self.cursor.y]
        if char_width > 0:
            if do_insert:
                line.right_shift(self.cursor.x, char_width)
            line.set_char(cx, char, char_width, self.cursor)
            self.cursor.x += 1
            if char_width == 2:
                line.set_char(self.cursor.x, '\0', 0, self.cursor)
                self.cursor.x += 1
            right = self.columns - 1 if do_insert else max(0, min(self.cursor.x - 1, self.columns - 1))
            self.update_cell_range(self.cursor.y, cx, right)
        elif unicodedata.combining(char):
            # A zero-cell character is combined with the previous
            # character either on this or the preceeding line.
            if cx > 0:
                line.add_combining_char(cx - 1, char)
                self.update_cell_range(self.cursor.y, cx - 1, cx - 1)
            elif self.cursor.y > 0:
                lline = self.linebuf[self.cursor.y - 1]
                lline.add_combining_char(self.columns - 1, char)
                self.update_cell_range(self.cursor.y - 1, self.columns - 1, self.columns - 1)

    def draw(self, data: bytes) -> None:
        """ Displays decoded characters at the current cursor position and
        creates new lines as need if DECAWM is set.  """
        orig_x, orig_y = self.cursor.x, self.cursor.y
        self._notify_cursor_position = False
        data = self._decode(data)
        try:
            if is_simple_string(data):
                return self._draw_fast(data)
            data = ignore_pat.sub('', data)
            if data:
                widths = list(map(wcwidth, data))
                if sum(widths) == len(data):
                    return self._draw_fast(data)
                for char, char_width in zip(data, widths):
                    self._draw_char(char, char_width)
        finally:
            self._notify_cursor_position = True
            if orig_x != self.cursor.x or orig_y != self.cursor.y:
                self.notify_cursor_position()

    def set_title(self, param):
        """Sets terminal title.

        .. note:: This is an XTerm extension supported by the Linux terminal.
        """
        self.title_changed.emit(sanitize_title(self._decode(param)))

    def set_icon_name(self, param):
        """Sets icon name.

        .. note:: This is an XTerm extension supported by the Linux terminal.
        """
        self.icon_changed.emit(sanitize_title(self._decode(param)))

    def carriage_return(self):
        """Move the cursor to the beginning of the current line."""
        x, self.cursor.x = self.cursor.x, 0
        if x != self.cursor.x:
            self.notify_cursor_position()

    def index(self):
        """Move the cursor down one line in the same column. If the
        cursor is at the last line, create a new line at the bottom.
        """
        top, bottom = self.margins

        if self.cursor.y == bottom:
            l = self.linebuf.pop(top)
            if self.linebuf is self.main_linebuf:
                self.tophistorybuf.append(l)
                self.line_added_to_history()
            self.linebuf.insert(bottom, Line(self.columns))
            self.update_screen()
        else:
            self.cursor_down()

    def reverse_index(self):
        """Move the cursor up one line in the same column. If the cursor
        is at the first line, create a new line at the top.
        """
        top, bottom = self.margins

        if self.cursor.y == top:
            self.linebuf.pop(bottom)
            self.linebuf.insert(top, Line(self.columns))
            self.update_screen()
        else:
            self.cursor_up()

    def linefeed(self):
        """Performs an index and, if :data:`~pyte.modes.LNM` is set, a
        carriage return.
        """
        self.index()

        if mo.LNM in self.mode:
            self.carriage_return()

        self.ensure_bounds()

    def tab(self):
        """Move to the next tab space, or the end of the screen if there
        aren't anymore left.
        """
        for stop in sorted(self.tabstops):
            if self.cursor.x < stop:
                column = stop
                break
        else:
            column = self.columns - 1

        if column != self.cursor.x:
            self.cursor.x = column
            self.notify_cursor_position()

    def backspace(self):
        """Move cursor to the left one or keep it in it's position if
        it's at the beginning of the line already.
        """
        self.cursor_back()

    def save_cursor(self):
        """Push the current cursor position onto the stack."""
        self.savepoints.append(Savepoint(self.cursor.copy(),
                                         self.g0_charset,
                                         self.g1_charset,
                                         self.charset,
                                         self.use_utf8,
                                         mo.DECOM in self.mode,
                                         mo.DECAWM in self.mode))

    def restore_cursor(self):
        """Set the current cursor position to whatever cursor is on top
        of the stack.
        """
        if self.savepoints:
            savepoint = self.savepoints.pop()

            self.g0_charset = savepoint.g0_charset
            self.g1_charset = savepoint.g1_charset
            self.charset = savepoint.charset
            self.use_utf8 = savepoint.use_utf8

            if savepoint.origin:
                self.set_mode(mo.DECOM)
            if savepoint.wrap:
                self.set_mode(mo.DECAWM)

            self.cursor = savepoint.cursor
            self.cursor_changed(self.cursor)
            self.ensure_bounds(use_margins=True)
        else:
            # If nothing was saved, the cursor moves to home position;
            # origin mode is reset. TODO: DECAWM?
            self.reset_mode(mo.DECOM)
            self.cursor_position()

    def insert_lines(self, count=1):
        """Inserts the indicated # of lines at line with cursor. Lines
        displayed **at** and below the cursor move down. Lines moved
        past the bottom margin are lost.

        :param count: number of lines to delete.
        """
        count = count or 1
        top, bottom = self.margins

        # If cursor is outside scrolling margins -- do nothin'.
        if top <= self.cursor.y <= bottom:
            #                           v +1, because range() is exclusive.
            for line in range(self.cursor.y,
                              min(bottom + 1, self.cursor.y + count)):
                self.linebuf.pop(bottom)
                self.linebuf.insert(line, Line(self.columns))
            self.update_line_range(self.cursor.y, bottom)

            self.carriage_return()

    def delete_lines(self, count=1):
        """Deletes the indicated # of lines, starting at line with
        cursor. As lines are deleted, lines displayed below cursor
        move up.

        :param int count: number of lines to delete.
        """
        count = count or 1
        top, bottom = self.margins

        # If cursor is outside scrolling margins it -- do nothin'.
        if top <= self.cursor.y <= bottom:
            #                v -- +1 to include the bottom margin.
            for _ in range(min(bottom - self.cursor.y + 1, count)):
                self.linebuf.pop(self.cursor.y)
                self.linebuf.insert(bottom, Line(self.columns))
            self.update_line_range(self.cursor.y, bottom)

            self.carriage_return()

    def insert_characters(self, count=1):
        """Inserts the indicated # of blank characters at the cursor
        position. The cursor does not move and remains at the beginning
        of the inserted blank characters. Data on the line is shifted
        forward.

        :param int count: number of characters to insert.
        """
        count = count or 1
        top, bottom = self.margins

        y = self.cursor.y
        if top <= y <= bottom:
            x = self.cursor.x
            # TODO: Check what to do if x is on the second char of a wide char
            # pair.
            num = min(self.columns - x, count)
            line = self.linebuf[y]
            line.right_shift(x, num)
            line.apply_cursor(self.cursor, x, num, clear_char=True)
            self.update_cell_range(y, x, self.columns - 1)

    def delete_characters(self, count=1):
        """Deletes the indicated # of characters, starting with the
        character at cursor position. When a character is deleted, all
        characters to the right of cursor move left. Character attributes
        move with the characters.

        :param int count: number of characters to delete.
        """
        count = count or 1
        top, bottom = self.margins

        y = self.cursor.y
        if top <= y <= bottom:
            x = self.cursor.x
            num = min(self.columns - x, count)
            # TODO: Check if we need to count wide chars as one or two chars
            # for this control code. Also, what happens if we start deleting
            # at the second cell of a wide character, or delete only the first
            # cell of a wide character?
            line = self.linebuf[y]
            line.left_shift(x, num)
            line.apply_cursor(self.cursor, self.columns - num, num, clear_char=True)
            self.update_cell_range(y, x, self.columns - 1)

    def erase_characters(self, count=1):
        """Erases the indicated # of characters, starting with the
        character at cursor position. Character attributes are set
        to cursor attributes. The cursor remains in the same position.

        :param int count: number of characters to erase.

        .. warning::

           Even though *ALL* of the VTXXX manuals state that character
           attributes **should be reset to defaults**, ``libvte``,
           ``xterm`` and ``ROTE`` completely ignore this. Same applies
           to all ``erase_*()`` and ``delete_*()`` methods.
        """
        count = count or 1
        x, y = self.cursor.x, self.cursor.y
        # TODO: Same set of wide character questions as for delete_characters()
        num = min(self.columns - x, count)
        self.linebuf[y].apply_cursor(self.cursor, x, num, clear_char=True)
        self.update_cell_range(y, x, min(x + num, self.columns) - 1)

    def erase_in_line(self, how=0, private=False):
        """Erases a line in a specific way.

        :param int how: defines the way the line should be erased in:

            * ``0`` -- Erases from cursor to end of line, including cursor
              position.
            * ``1`` -- Erases from beginning of line to cursor,
              including cursor position.
            * ``2`` -- Erases complete line.
        :param bool private: when ``True`` character attributes are left
                             unchanged.
        """
        s = n = 0
        if how == 0:
            # a) erase from the cursor to the end of line, including
            #    the cursor,
            s, n = self.cursor.x, self.columns - self.cursor.x
        elif how == 1:
            # b) erase from the beginning of the line to the cursor,
            #    including it,
            s, n = 0, self.cursor.x + 1
        elif how == 2:
            # c) erase the entire line.
            s, n = 0, self.columns
        if n - s:
            # TODO: Same set of questions as for delete_characters()
            y = self.cursor.y
            line = self.linebuf[y]
            c = None if private else self.cursor
            if private:
                line.clear_text(s, n)
            else:
                line.apply_cursor(c, s, n, clear_char=True)
            self.update_cell_range(y, s, min(s + n, self.columns) - 1)

    def erase_in_display(self, how=0, private=False):
        """Erases display in a specific way.

        :param int how: defines the way the line should be erased in:

            * ``0`` -- Erases from cursor to end of screen, including
              cursor position.
            * ``1`` -- Erases from beginning of screen to cursor,
              including cursor position.
            * ``2`` -- Erases complete display. All lines are erased
              and changed to single-width. Cursor does not move.
        :param bool private: when ``True`` character attributes are left unchanged
        """
        if how == 0:
            # a) erase from cursor to the end of the display, including
            #    the cursor,
            interval = self.cursor.y + 1, self.lines
        elif how == 1:
            # b) erase from the beginning of the display to the cursor,
            #    including it,
            interval = 0, self.cursor.y
        elif how == 2:
            # c) erase the whole display.
            interval = 0, self.lines
        else:
            return

        if interval[1] > interval[0]:
            for line in range(*interval):
                if private:
                    self.linebuf[line].clear_text(0, self.columns)
                else:
                    self.linebuf[line].apply_cursor(self.cursor, 0, self.columns, clear_char=True)
            self.update_line_range(interval[0], interval[1] - 1)

        # In case of 0 or 1 we have to erase the line with the cursor also
        if how != 2:
            self.erase_in_line(how, private=private)

    def set_tab_stop(self):
        """Sets a horizontal tab stop at cursor position."""
        self.tabstops.add(self.cursor.x)

    def clear_tab_stop(self, how=0):
        """Clears a horizontal tab stop.

        :param int how: defines a way the tab stop should be cleared:

            * ``0`` or nothing -- Clears a horizontal tab stop at cursor
              position.
            * ``3`` -- Clears all horizontal tab stops.
        """
        if how == 0:
            # Clears a horizontal tab stop at cursor position, if it's
            # present, or silently fails if otherwise.
            self.tabstops.discard(self.cursor.x)
        elif how == 3:
            self.tabstops = set()  # Clears all horizontal tab stops.

    def ensure_bounds(self, use_margins=False):
        """Ensure that current cursor position is within screen bounds.

        :param bool use_margins: when ``True`` or when
                                 :data:`~pyte.modes.DECOM` is set,
                                 cursor is bounded by top and and bottom
                                 margins, instead of ``[0; lines - 1]``.
        """
        if use_margins or mo.DECOM in self.mode:
            top, bottom = self.margins
        else:
            top, bottom = 0, self.lines - 1

        self.cursor.x = max(0, min(self.cursor.x, self.columns - 1))
        self.cursor.y = max(top, min(self.cursor.y, bottom))

    def cursor_up(self, count=1, do_carriage_return=False, move_direction=-1):
        """Moves cursor up the indicated # of lines in same column.
        Cursor stops at top margin.

        :param int count: number of lines to skip.
        """
        x, y = self.cursor.x, self.cursor.y
        self.cursor.y += move_direction * (count or 1)
        self.ensure_bounds(use_margins=True)
        if do_carriage_return:
            self.cursor.x = 0
        if y != self.cursor.y or x != self.cursor.x:
            self.notify_cursor_position()

    def cursor_up1(self, count=1):
        """Moves cursor up the indicated # of lines to column 1. Cursor
        stops at bottom margin.

        :param int count: number of lines to skip.
        """
        self.cursor_up(count, do_carriage_return=True)

    def cursor_down(self, count=1):
        """Moves cursor down the indicated # of lines in same column.
        Cursor stops at bottom margin.

        :param int count: number of lines to skip.
        """
        self.cursor_up(count, move_direction=1)

    def cursor_down1(self, count=1):
        """Moves cursor down the indicated # of lines to column 1.
        Cursor stops at bottom margin.

        :param int count: number of lines to skip.
        """
        self.cursor_up(count, do_carriage_return=True, move_direction=1)

    def cursor_back(self, count=1, move_direction=-1):
        """Moves cursor left the indicated # of columns. Cursor stops
        at left margin.

        :param int count: number of columns to skip.
        """
        x = self.cursor.x
        self.cursor.x += move_direction * (count or 1)
        self.ensure_bounds()
        if x != self.cursor.x:
            self.notify_cursor_position()

    def cursor_forward(self, count=1):
        """Moves cursor right the indicated # of columns. Cursor stops
        at right margin.

        :param int count: number of columns to skip.
        """
        self.cursor_back(count, move_direction=1)

    def cursor_position(self, line=1, column=1):
        """Set the cursor to a specific `line` and `column`.

        Cursor is allowed to move out of the scrolling region only when
        :data:`~pyte.modes.DECOM` is reset, otherwise -- the position
        doesn't change.

        :param int line: line number to move the cursor to.
        :param int column: column number to move the cursor to.
        """
        column = (column or 1) - 1
        line = (line or 1) - 1
        x, y = self.cursor.x, self.cursor.y

        # If origin mode (DECOM) is set, line number are relative to
        # the top scrolling margin.
        if mo.DECOM in self.mode:
            line += self.margins.top

            # Cursor is not allowed to move out of the scrolling region.
            if not self.margins.top <= line <= self.margins.bottom:
                return

        self.cursor.x, self.cursor.y = column, line
        self.ensure_bounds()
        if y != self.cursor.y or x != self.cursor.x:
            self.notify_cursor_position()

    def cursor_to_column(self, column=1):
        """Moves cursor to a specific column in the current line.

        :param int column: column number to move the cursor to.
        """
        x, self.cursor.x = self.cursor.x, (column or 1) - 1
        self.ensure_bounds()
        if x != self.cursor.x:
            self.notify_cursor_position()

    def cursor_to_line(self, line=1):
        """Moves cursor to a specific line in the current column.

        :param int line: line number to move the cursor to.
        """
        y, self.cursor.y = self.cursor.y, (line or 1) - 1

        # If origin mode (DECOM) is set, line number are relative to
        # the top scrolling margin.
        if mo.DECOM in self.mode:
            self.cursor.y += self.margins.top

            # TODO: should we also restrict the cursor to the scrolling
            # region?

        self.ensure_bounds()
        if y != self.cursor.y:
            self.notify_cursor_position()

    def bell(self, *args):
        """ Audbile bell """
        try:
            with open('/dev/tty', 'wb') as f:
                f.write(b'\x07')
        except EnvironmentError:
            pass

    def alignment_display(self):
        """Fills screen with uppercase E's for screen focus and alignment."""
        for i in range(self.lines):
            self.linebuf[i].clear_text(0, self.columns, 'E')

    def select_graphic_rendition(self, *attrs):
        """Set display attributes.

        :param list attrs: a list of display attributes to set.
        """
        attrs = list(reversed(attrs or (0,)))

        c = self.cursor

        while attrs:
            attr = attrs.pop()
            if attr in g.FG_ANSI:
                c.fg = (attr << 8) | 1
            elif attr in g.BG_ANSI:
                c.bg = (attr << 8) | 1
            elif attr in g.DISPLAY:
                attr, val = g.DISPLAY[attr]
                setattr(c, attr, val)
            elif not attr:
                c.reset_display_attrs()
            elif attr in g.FG_AIXTERM:
                c.fg = (attr << 8) | 1
            elif attr in g.BG_AIXTERM:
                c.bg = (attr << 8) | 1
            elif attr in (g.FG_256, g.BG_256):
                key = "fg" if attr == g.FG_256 else "bg"
                n = attrs.pop()
                try:
                    if n == 5:    # 256.
                        setattr(c, key, (attrs.pop() << 8) | 2)
                    elif n == 2:  # 24bit.
                        # This is somewhat non-standard but is nonetheless
                        # supported in quite a few terminals. See discussion
                        # here https://gist.github.com/XVilka/8346728.
                        r, gr, b = attrs.pop() << 8, attrs.pop() << 16, attrs.pop() << 24
                        setattr(c, key, r | gr | b | 3)
                except IndexError:
                    pass

    def report_device_attributes(self, mode=0, **kwargs):
        """Reports terminal identity.

        .. versionadded:: 0.5.0
        """
        # Use the same responses as libvte v0.46 running in termite
        # Ignore mode since vte seems to ignore it
        if False and kwargs.get('secondary') == '>':
            # http://www.vt100.net/docs/vt510-rm/DA2.html
            # If you implement xterm keycode querying
            # http://invisible-island.net/xterm/ctlseqs/ctlseqs.html#h2-Device-Control-functions
            # you can enable this.
            self.write_process_input(b'\x1b[>1;4600;0c')
        else:
            # xterm gives: [[?64;1;2;6;9;15;18;21;22c
            # use the simpler vte response, since we dont support
            # windowing/horizontal scrolling etc.
            # [[?64;1;2;6;9;15;18;21;22c
            self.write_process_input(b"\x1b[?62c")

    def report_device_status(self, mode):
        """Reports terminal status or cursor position.

        :param int mode: if 5 -- terminal status, 6 -- cursor position,
                         otherwise a noop.

        .. versionadded:: 0.5.0
        """
        if mode == 5:    # Request for terminal status.
            self.write_process_input(b"\x1b[0n")
        elif mode == 6:  # Request for cursor position.
            x, y = wrap_cursor_position(self.cursor.x, self.cursor.y, self.lines, self.columns)
            x, y = x + 1, y + 1

            # "Origin mode (DECOM) selects line numbering."
            if mo.DECOM in self.mode:
                y -= self.margins.top
            self.write_process_input("\x1b[{0};{1}R".format(y, x).encode('ascii'))

    def set_cursor_shape(self, mode, secondary=None):
        if secondary == ' ':
            shape = blink = None
            if mode > 0:
                blink = bool(mode % 2)
                shape = 'block' if mode < 3 else 'underline' if mode < 5 else 'beam' if mode < 7 else None
            if shape != self.cursor.shape or blink != self.cursor.blink:
                self.cursor.shape, self.cursor.blink = shape, blink
                self.cursor_changed(self.cursor)
        elif secondary == '"':  # DECSCA
            pass
        else:  # DECLL
            pass

    def set_dynamic_color(self, base, color_names=None):
        # See http://invisible-island.net/xterm/ctlseqs/ctlseqs.html#h2-Operating-System-Commands
        try:
            color_names = color_names.decode('utf-8') if color_names else ''
        except Exception:
            return

        def handle_val(val, param=None):
            val %= 100
            if val == 10:  # foreground
                self.change_default_color.emit('fg', param)
            elif val == 11:  # background
                self.change_default_color.emit('bg', param)
            elif val == 12:  # cursor color
                old, self.cursor.color = self.cursor.color, param
                if old != self.cursor.color:
                    self.cursor_changed(self.cursor)

        if color_names:
            for i, cn in enumerate(filter(None, color_names.split(';'))):
                handle_val(base + i, cn)
        else:
            handle_val(base)

    def normal_keypad_mode(self):
        pass  # Useless for us, since Qt takes care of handling the numpad

    def alternate_keypad_mode(self):
        pass  # Useless for us, since Qt takes care of handling the numpad

    def debug(self, *args, **kwargs):
        """Endpoint for unrecognized escape sequences.

        By default is a noop.
        """
        import traceback
        traceback.print_stack()
        print('unknown escape code:', args, kwargs)
