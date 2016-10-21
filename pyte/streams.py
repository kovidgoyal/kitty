# -*- coding: utf-8 -*-
"""
    pyte.streams
    ~~~~~~~~~~~~

    This module provides three stream implementations with different
    features; for starters, here's a quick example of how streams are
    typically used:

    >>> import pyte
    >>> screen = pyte.Screen(80, 24)
    >>> stream = pyte.Stream(screen)
    >>> stream.feed(b"\x1B[5B")  # Move the cursor down 5 rows.
    >>> screen.cursor.y
    5

    :copyright: (c) 2011-2012 by Selectel.
    :copyright: (c) 2012-2016 by pyte authors and contributors,
                    see AUTHORS for details.
    :license: LGPL, see LICENSE for more details.
"""

from __future__ import absolute_import, unicode_literals

from functools import wraps
import itertools
import os
import re
import sys
from collections import defaultdict

from . import control as ctrl, escape as esc
from .compat import str


class Stream(object):
    """A stream is a state machine that parses a stream of bytes and
    dispatches events based on what it sees.

    :param pyte.screens.Screen screen: a screen to dispatch events to.
    :param bool strict: check if a given screen implements all required
                        events.

    .. note::

       Stream only accepts :func:`bytes` as input. Decoding it into text
       is the responsibility of the :class:`~pyte.screens.Screen`.

    .. versionchanged 0.6.0::

       For performance reasons the binding between stream events and
       screen methods was made static. As a result, the stream **will
       not** dispatch events to methods added to screen **after** the
       stream was created.

    .. seealso::

        `man console_codes <http://linux.die.net/man/4/console_codes>`_
            For details on console codes listed bellow in :attr:`basic`,
            :attr:`escape`, :attr:`csi`, :attr:`sharp` and :attr:`percent`.
    """

    #: Control sequences, which don't require any arguments.
    basic = {
        ctrl.BEL: "bell",
        ctrl.BS: "backspace",
        ctrl.HT: "tab",
        ctrl.LF: "linefeed",
        ctrl.VT: "linefeed",
        ctrl.FF: "linefeed",
        ctrl.CR: "carriage_return",
        ctrl.SO: "shift_out",
        ctrl.SI: "shift_in",
    }

    #: non-CSI escape sequences.
    escape = {
        esc.RIS: "reset",
        esc.IND: "index",
        esc.NEL: "linefeed",
        esc.RI: "reverse_index",
        esc.HTS: "set_tab_stop",
        esc.DECSC: "save_cursor",
        esc.DECRC: "restore_cursor",
        esc.DECPNM: 'normal_keypad_mode',
        esc.DECPAM: 'alternate_keypad_mode',
    }

    #: "sharp" escape sequences -- ``ESC # <N>``.
    sharp = {
        esc.DECALN: "alignment_display",
    }

    #: CSI escape sequences -- ``CSI P1;P2;...;Pn <fn>``.
    csi = {
        esc.ICH: "insert_characters",
        esc.CUU: "cursor_up",
        esc.CUD: "cursor_down",
        esc.CUF: "cursor_forward",
        esc.CUB: "cursor_back",
        esc.CNL: "cursor_down1",
        esc.CPL: "cursor_up1",
        esc.CHA: "cursor_to_column",
        esc.CUP: "cursor_position",
        esc.ED: "erase_in_display",
        esc.EL: "erase_in_line",
        esc.IL: "insert_lines",
        esc.DL: "delete_lines",
        esc.DCH: "delete_characters",
        esc.ECH: "erase_characters",
        esc.HPR: "cursor_forward",
        esc.DA: "report_device_attributes",
        esc.VPA: "cursor_to_line",
        esc.VPR: "cursor_down",
        esc.HVP: "cursor_position",
        esc.TBC: "clear_tab_stop",
        esc.SM: "set_mode",
        esc.RM: "reset_mode",
        esc.SGR: "select_graphic_rendition",
        esc.DSR: "report_device_status",
        esc.DECSTBM: "set_margins",
        esc.HPA: "cursor_to_column",
        esc.DECSCUSR: 'set_cursor_shape',
    }

    #: A set of all events dispatched by the stream.
    events = frozenset(itertools.chain(
        basic.values(), escape.values(), sharp.values(), csi.values(),
        ["define_charset", "select_other_charset"],
        ["set_icon", "set_title", 'set_cursor_color'],  # OSC.
        ["draw", "debug"]))

    #: A regular expression pattern matching everything what can be
    #: considered plain text.
    _special = set([ctrl.ESC, ctrl.CSI, ctrl.NUL, ctrl.DEL, ctrl.OSC])
    _special.update(basic)
    _text_pattern = re.compile(
        b"[^" + b"".join(map(re.escape, _special)) + b"]+")
    del _special

    def __init__(self, screen=None, strict=True):
        self.listener = None
        self.strict = False

        if screen is not None:
            self.attach(screen)

    def attach(self, screen, only=()):
        """Adds a given screen to the listener queue.

        :param pyte.screens.Screen screen: a screen to attach to.
        :param list only: a list of events you want to dispatch to a
                          given screen (empty by default, which means
                          -- dispatch all events).
        """
        if self.strict:
            for event in self.events:
                if not hasattr(screen, event):
                    error_message = "{0} is missing {1}".format(screen, event)
                    raise TypeError(error_message)

        self.listener = screen
        self._parser = self._parser_fsm()
        self._taking_plain_text = next(self._parser)

    def detach(self, screen):
        """Removes a given screen from the listener queue and fails
        silently if it's not attached.

        :param pyte.screens.Screen screen: a screen to detach.
        """
        if screen is self.listener:
            self.listener = None

    def feed(self, data: bytes) -> None:
        """Consumes a string and advances the state as necessary.

        :param bytes data: a blob of data to feed from.
        """
        send = self._parser.send
        draw = self.listener.draw
        match_text = self._text_pattern.match
        taking_plain_text = self._taking_plain_text

        # TODO: use memoryview?
        length = len(data)
        offset = 0
        while offset < length:
            if taking_plain_text:
                match = match_text(data, offset)
                if match is not None:
                    start, offset = match.span()
                    draw(data[start:offset])
                else:
                    taking_plain_text = False
            else:
                taking_plain_text = send(data[offset:offset + 1])
                offset += 1

        self._taking_plain_text = taking_plain_text

    def _parser_fsm(self):
        """An FSM implemented as a coroutine.

        This generator is not the most beautiful, but it is as performant
        as possible. When a process generates a lot of output, then this
        will be the bottleneck, because it processes just one character
        at a time.

        We did many manual optimizations to this function in order to make
        it as efficient as possible. Don't change anything without profiling
        first.
        """
        basic = self.basic
        listener = self.listener
        draw = listener.draw
        debug = listener.debug

        ESC, CSI = ctrl.ESC, ctrl.CSI
        OSC, ST, DCS = ctrl.OSC, ctrl.ST, ctrl.DCS
        SP_OR_GT = ctrl.SP + b">"
        NUL_OR_DEL = ctrl.NUL + ctrl.DEL
        CAN_OR_SUB = ctrl.CAN + ctrl.SUB
        ALLOWED_IN_CSI = b"".join([ctrl.BEL, ctrl.BS, ctrl.HT, ctrl.LF,
                                   ctrl.VT, ctrl.FF, ctrl.CR])

        def create_dispatcher(mapping):
            return defaultdict(lambda: debug, dict(
                (event, getattr(listener, attr))
                for event, attr in mapping.items()))

        basic_dispatch = create_dispatcher(basic)
        sharp_dispatch = create_dispatcher(self.sharp)
        escape_dispatch = create_dispatcher(self.escape)
        csi_dispatch = create_dispatcher(self.csi)

        while True:
            # ``True`` tells ``Screen.feed`` that it is allowed to send
            # chunks of plain text directly to the listener, instead
            # of this generator.)
            char = yield True

            if char == ESC:
                # Most non-VT52 commands start with a left-bracket after the
                # escape and then a stream of parameters and a command; with
                # a single notable exception -- :data:`escape.DECOM` sequence,
                # which starts with a sharp.
                #
                # .. versionchanged:: 0.4.10
                #
                #    For compatibility with Linux terminal stream also
                #    recognizes ``ESC % C`` sequences for selecting control
                #    character set. However, in the current version these
                #    are noop.
                char = yield
                if char == b"[":
                    char = CSI  # Go to CSI.
                elif char == b"]":
                    char = OSC  # Go to OSC.
                elif char == b'P':
                    char = DCS  # Go to DCS
                else:
                    if char == b"#":
                        sharp_dispatch[(yield)]()
                    if char == b"%":
                        listener.select_other_charset((yield))
                    elif char in b"()":
                        listener.define_charset((yield), mode=char)
                    else:
                        escape_dispatch[char]()
                    continue     # Don't go to CSI.

            if char in basic:
                basic_dispatch[char]()
            elif char == CSI:
                # All parameters are unsigned, positive decimal integers, with
                # the most significant digit sent first. Any parameter greater
                # than 9999 is set to 9999. If you do not specify a value, a 0
                # value is assumed.
                #
                # .. seealso::
                #
                #    `VT102 User Guide <http://vt100.net/docs/vt102-ug/>`_
                #        For details on the formatting of escape arguments.
                #
                #    `VT220 Programmer Ref. <http://vt100.net/docs/vt220-rm/>`_
                #        For details on the characters valid for use as
                #        arguments.
                params = []
                current = bytearray()
                private = secondary = False
                while True:
                    char = yield
                    if char == b"?":
                        private = True
                    elif char in ALLOWED_IN_CSI:
                        basic_dispatch[char]()
                    elif char in SP_OR_GT:
                        secondary = char.decode('ascii')  # Added by Kovid
                    elif char in CAN_OR_SUB:
                        # If CAN or SUB is received during a sequence, the
                        # current sequence is aborted; terminal displays
                        # the substitute character, followed by characters
                        # in the sequence received after CAN or SUB.
                        draw(char)
                        break
                    elif char.isdigit():
                        current.extend(char)
                    else:
                        params.append(min(int(bytes(current) or 0), 9999))

                        if char == b";":
                            current = bytearray()
                        else:
                            if private:
                                csi_dispatch[char](*params, private=True)
                            else:
                                if secondary:  # Added by Kovid
                                    csi_dispatch[char](*params, secondary=secondary)
                                else:
                                    csi_dispatch[char](*params)
                            break  # CSI is finished.
            elif char == OSC:
                code = bytearray()
                while True:
                    char = yield
                    if char == ST or char == ctrl.BEL or char == b';':
                        break
                    code.extend(char)
                code = bytes(code)
                param = bytearray()
                if char == b';':
                    while True:
                        char = yield
                        if char == ST or char == ctrl.BEL:
                            break
                        else:
                            param.extend(char)

                param = bytes(param)
                if code in b"01":
                    listener.set_icon_name(param)
                if code in b"02":
                    listener.set_title(param)
                elif code == b"12":
                    listener.set_cursor_color(param)
                elif code == b"112":
                    listener.set_cursor_color(b'')
            elif char == DCS:
                # See http://invisible-island.net/xterm/ctlseqs/ctlseqs.html#h2-Device-Control-functions
                code = yield
                param = bytearray()
                while True:
                    char = yield
                    if char == ST:
                        break
                    else:
                        param.extend(char)
                # TODO: Implement these
            elif char not in NUL_OR_DEL:
                draw(char)


class DebugStream(Stream):
    r"""Stream, which dumps a subset of the dispatched events to a given
    file-like object (:data:`sys.stdout` by default).

    >>> import io
    >>> with io.StringIO() as buf:
    ...     stream = DebugStream(to=buf)
    ...     stream.feed(b"\x1b[1;24r\x1b[4l\x1b[24;1H\x1b[0;10m")
    ...     print(buf.getvalue())
    ...
    ... # doctest: +NORMALIZE_WHITESPACE
    SET_MARGINS 1; 24
    RESET_MODE 4
    CURSOR_POSITION 24; 1
    SELECT_GRAPHIC_RENDITION 0; 10

    :param file to: a file-like object to write debug information to.
    :param list only: a list of events you want to debug (empty by
                      default, which means -- debug all events).
    """

    def __init__(self, screen, to=sys.stdout, only=()):
        stream = super(DebugStream, self)

        def safe_str(chunk):
            if isinstance(chunk, bytes):
                chunk = chunk.decode("utf-8")
            elif not isinstance(chunk, str):
                chunk = str(chunk)

            return chunk

        class Bugger:

            def __getattr__(self, event):

                @wraps(getattr(screen, event))
                def inner(*args, **kwargs):
                    if not only or event in only:
                        to.write(event.upper() + " ")
                        to.write("; ".join(map(safe_str, args)))
                        to.write(" ")
                        to.write(", ".join("{0}: {1}".format(k, safe_str(v))
                                           for k, v in kwargs.items()))
                        to.write(os.linesep)
                    getattr(screen, event)(*args, **kwargs)

                return inner
        stream.__init__(Bugger())
