#!/usr/bin/env python
# License: GPL v3 Copyright: 2016, Kovid Goyal <kovid at kovidgoyal.net>

import re
from functools import partial
from time import sleep

from kitty.config import load_config
from kitty.fast_data_types import (
    GLFW_MOD_ALT,
    GLFW_MOD_CAPS_LOCK,
    GLFW_MOD_CONTROL,
    GLFW_MOD_SHIFT,
    GLFW_MOD_SUPER,
    GLFW_MOUSE_BUTTON_LEFT,
    GLFW_MOUSE_BUTTON_MIDDLE,
    GLFW_MOUSE_BUTTON_RIGHT,
    MOUSE_SELECTION_WORD_AND_LINE_FROM_POINT,
    PRESS,
    RELEASE,
    create_mock_window,
    mock_mouse_selection,
    send_mock_mouse_event_to_window,
    send_mock_mouse_events,
    send_mock_scroll_event_to_window,
    set_options,
    update_mock_pointer,
)
from kitty.fast_data_types import (
    send_mouse_event as send_simulated_mouse_event,
)

from .base import BaseTest, parse_bytes


def send_mouse_event(
    window,
    button=-1,
    modifiers=0,
    is_release=False,
    x=0.0,
    y=0,
    clear_click_queue=False,
    pixel_x=None,
    pixel_y=None,
):
    ix = int(x)
    in_left_half_of_cell = x - ix < 0.5
    return send_mock_mouse_event_to_window(window, button, modifiers, is_release, ix, y, clear_click_queue, in_left_half_of_cell, pixel_x, pixel_y)


def strip_serials(text):
    # Replaces the serials of detailed mouse events with S
    return re.sub(r'(\x1b\[>\d+):\d+;', r'\1:S;', text)


class TestMouse(BaseTest):
    def test_link_hover_modifiers(self):
        s = self.create_screen(cols=60)
        s.draw('https://example.invalid/')
        parse_bytes(s, b'\r\n\x1b]8;;https://example.invalid/\x1b\\hyperlink\x1b]8;;\x1b\\\r\nsrc/file.py:42')
        w = create_mock_window(s)
        hover = partial(send_mouse_event, w, x=2)
        normal_shape = send_mouse_event(w, x=50)
        link_shape = hover()
        self.assertNotEqual(normal_shape, link_shape)

        def configure(*lines):
            set_options(load_config(overrides=('clear_all_mouse_actions yes', 'detect_url_regex [[:alnum:]_./-]+:[0-9]+', *lines)))

        def check(mods, clickable, y=0):
            self.ae(hover(modifiers=mods, y=y), link_shape if clickable else normal_shape)
            expected = ('https://example.invalid/', 'hyperlink', 'src/file.py:42')[y] if clickable else ''
            self.ae(''.join(s.text_for_marked_url()), expected)
            # The renderer uses bit 1 of the selection buffer for URL underlines.
            self.ae(sum(bool(cell & 2) for cell in s.current_selections()), len(expected))

        mods = GLFW_MOD_CONTROL | GLFW_MOD_SHIFT
        configure('mouse_map ctrl+shift+left release grabbed,ungrabbed mouse_handle_click link')
        for y in (0, 1, 2):
            for held, clickable in (
                (0, False),
                (GLFW_MOD_CONTROL, False),
                (mods, True),
                (mods | GLFW_MOD_ALT, False),
                (mods | GLFW_MOD_CAPS_LOCK, True),
                (0, False),
            ):
                # Repeated events in the same cell must respond to modifier changes.
                check(held, clickable, y)

        configure('mouse_map left click ungrabbed mouse_handle_click selection link prompt')
        check(0, True)
        check(mods, False)
        parse_bytes(s, b'\x1b[?1000h')
        normal_shape = send_mouse_event(w, x=50)
        check(0, False)
        configure('mouse_map alt+left release grabbed mouse_click_url')
        check(GLFW_MOD_ALT, True)
        check(0, False)
        parse_bytes(s, b'\x1b[?1000l')
        normal_shape = send_mouse_event(w, x=50)
        check(GLFW_MOD_ALT, False)

        configure('action_alias follow_link mouse_handle_click link', 'mouse_map alt+left release ungrabbed follow_link')
        check(GLFW_MOD_ALT, True)
        check(0, False)
        configure('mouse_map left click ungrabbed combine : mouse_handle_click link : discard_event')
        check(0, True)
        configure('mouse_map left click ungrabbed mouse_click_url_or_select')
        check(0, True)
        configure('mouse_map left click ungrabbed mouse_click_url', 'mouse_map left click ungrabbed')
        check(0, False)

        for event in ('press', 'release', 'click'):
            configure(f'mouse_map cmd+left {event} ungrabbed mouse_handle_click link')
            check(GLFW_MOD_SUPER, True)
            check(0, False)
        for event in ('doublepress', 'triplepress', 'doubleclick'):
            configure(f'mouse_map left {event} ungrabbed mouse_click_url')
            check(0, False)

    def test_link_hover_key_events(self):
        s = self.create_screen(cols=60)
        s.draw('https://example.invalid/')
        w = create_mock_window(s)
        link_shape = send_mouse_event(w, x=2)
        mods = GLFW_MOD_CONTROL | GLFW_MOD_SHIFT
        set_options(
            load_config(
                overrides=(
                    'clear_all_mouse_actions yes',
                    'mouse_map ctrl+shift+left release grabbed,ungrabbed mouse_handle_click link',
                    'mouse_map cmd+left release grabbed,ungrabbed mouse_handle_click link',
                )
            )
        )
        for tracking in (False, True):
            parse_bytes(s, b'\x1b[?1000h' if tracking else b'\x1b[?1000l')
            normal_shape = send_mouse_event(w, x=50)
            send_mouse_event(w, x=2)
            for held in (mods, GLFW_MOD_SUPER):
                for old, new, highlighted in ((0, held, True), (held, 0, False)):
                    self.ae(update_mock_pointer(w, old, new), (link_shape if highlighted else normal_shape, True))
                    self.ae(bool(''.join(s.text_for_marked_url())), highlighted)
                self.ae(update_mock_pointer(w, 0, held, False)[1], False)
                self.ae(''.join(s.text_for_marked_url()), '')
            for old, new in ((0, GLFW_MOD_SHIFT), (mods, GLFW_MOD_SUPER), (mods, mods | GLFW_MOD_CAPS_LOCK)):
                self.ae(update_mock_pointer(w, old, new)[1], False)
            for drag in (1, 2):
                self.ae(update_mock_pointer(w, 0, mods, True, drag)[1], False)

    def test_link_hover_preserves_border_cursor(self):
        s = self.create_screen(cols=60)
        s.draw('https://example.invalid/')
        w = create_mock_window(s)
        send_mouse_event(w, x=2)
        mods = GLFW_MOD_CONTROL | GLFW_MOD_SHIFT
        for border in (1, 2):
            shape, updated = update_mock_pointer(w, 0, 0, True, 0, border)
            self.ae(updated, False)
            self.ae(update_mock_pointer(w, 0, mods, True, 0, border), (shape, False))

    def test_link_hover_cleared_by_output(self):
        s = self.create_screen(cols=60)
        w = create_mock_window(s)
        mods = GLFW_MOD_CONTROL | GLFW_MOD_SHIFT
        set_options(load_config(overrides=('clear_all_mouse_actions yes', 'mouse_map ctrl+shift+left release ungrabbed mouse_handle_click link')))

        def marked():
            return ''.join(s.text_for_marked_url())

        def setup():
            s.reset()
            s.draw('https://example.invalid/')
            return send_mouse_event(w, x=2, modifiers=mods)

        parse_bytes(s, b'\x1b[?1000h')
        grabbed_shape = send_mouse_event(w, x=50)
        s.reset()
        normal_shape = send_mouse_event(w, x=50)
        for output, expected in (
            (b' suffix', normal_shape),
            (b'\r\x1b[Kplain text', normal_shape),
            (b'\x1b[2J', normal_shape),
            (b'\x1b[?1000h\r\x1b[K', grabbed_shape),
            (b'\x1b[?1000h', None),
            (b'\x1b[3;1Hother line', None),
        ):
            with self.subTest(output=output):
                link_shape = setup()
                self.assertNotIn(link_shape, (normal_shape, grabbed_shape))
                self.ae(marked(), 'https://example.invalid/')
                # Output alone, with the modifiers still held, must update the pointer
                shape = update_mock_pointer(w, mods, mods, True, 0, 0, None, False, partial(parse_bytes, s, output))[0]
                self.ae(shape, expected or link_shape)
                self.ae(bool(marked()), expected is None)
                if expected is not None:
                    # Releasing the modifiers after the output changes nothing
                    setup()
                    self.ae(update_mock_pointer(w, mods, 0, True, 0, 0, None, False, partial(parse_bytes, s, output)), (expected, False))
                    self.ae(marked(), '')

    def test_link_hover_stays_consistent(self):
        s = self.create_screen(cols=30)
        s.draw('x' * 6 + 'https://example.invalid/')
        w = create_mock_window(s)
        normal_shape = send_mouse_event(w, x=2)
        link_shape = send_mouse_event(w, x=29)
        mods = GLFW_MOD_CONTROL | GLFW_MOD_SHIFT

        def configure(*lines):
            set_options(load_config(overrides=('clear_all_mouse_actions yes', *lines)))

        def marked():
            return ''.join(s.text_for_marked_url())

        # The cell under the mouse is stale once it moves into the padding
        configure('mouse_map ctrl+shift+left release ungrabbed mouse_handle_click link')
        send_mouse_event(w, x=29)
        self.ae(update_mock_pointer(w, 0, mods, True, 0, 0, None, True), (normal_shape, False))
        self.ae(marked(), '')
        send_mouse_event(w, x=29)
        self.ae(update_mock_pointer(w, mods, 0, True, 0, 0, None, True), (normal_shape, True))
        self.ae(marked(), '')

        # The mouse tracking mode can change without the mouse moving
        configure('mouse_map left click ungrabbed mouse_click_url')
        send_mouse_event(w, x=10)
        self.ae(update_mock_pointer(w, 0, GLFW_MOD_ALT, True, 0, 0, None, False, partial(parse_bytes, s, b'\x1b[?1000h'))[1], True)
        self.ae(marked(), '')
        parse_bytes(s, b'\x1b[?1000l')

        # Pointer shape changes from the program keep the hand over a highlighted link
        send_mouse_event(w, x=10)
        self.ae(update_mock_pointer(w, 0, 0, True, 0, 0, 'wait')[0], link_shape)
        self.ae(marked(), 'https://example.invalid/')

    def test_pointer_shape_during_mouse_drag(self):
        s = self.create_screen(cols=60)
        parse_bytes(s, b'\x1b[?1000h')
        w = create_mock_window(s)
        for drag in (1, 2):
            for name in ('grabbing', 'ew-resize'):
                s.change_pointer_shape('=', name)
                expected = send_mouse_event(w, x=2)
                s.change_pointer_shape('=', 'text')
                self.ae(update_mock_pointer(w, 0, 0, True, drag, 0, name)[0], expected)

    def test_mouse_selection(self):
        s = self.create_screen(options=dict(rectangle_select_modifiers=GLFW_MOD_ALT | GLFW_MOD_CONTROL))
        w = create_mock_window(s)
        ev = partial(send_mouse_event, w)

        def mouse_selection(code: int) -> None:
            mock_mouse_selection(w, s.callbacks.current_mouse_button, code)

        s.callbacks.mouse_selection = mouse_selection

        def sel():
            return ''.join(s.text_for_selection())

        def init():
            s.reset()
            s.draw('pqrst')
            s.draw('uvwxy')
            s.draw('ABCDE')
            s.draw('FGHIJ')
            s.draw('KLMNO')
            s.draw('12345')
            s.draw('67890')
            s.draw('abcde')
            s.draw('fghij')
            s.draw('klmno')

        def press(x=0, y=0, modifiers=0, button=GLFW_MOUSE_BUTTON_LEFT):
            ev(button, x=x, y=y, modifiers=modifiers)

        def release(x=0, y=0, button=GLFW_MOUSE_BUTTON_LEFT):
            ev(button, x=x, y=y, is_release=True, clear_click_queue=True)

        def move(x=0, y=0, button=-1, q=None):
            ev(x=x, y=y, button=button)
            if q is not None:
                sl = sel()
                from kitty.window import as_text

                self.ae(sl, q, f'{sl!r} != {q!r} after movement to x={x} y={y}. Screen contents: {as_text(s)!r}')

        def multi_click(x=0, y=0, count=2, modifiers=0):
            clear_click_queue = True
            while count > 0:
                count -= 1
                ev(GLFW_MOUSE_BUTTON_LEFT, x=x, y=y, modifiers=modifiers, clear_click_queue=clear_click_queue)
                clear_click_queue = False

        def scroll(x=0, y=0, up=True):
            move(x=x, y=y, button=-2 if up else -3)

        # Single line click, move, release test
        init()
        press()
        move(x=3.6, q='1234')
        release(x=3.6)
        self.ae(sel(), '1234')
        press(x=4), release(x=0.6)
        self.ae(sel(), '234')

        # multi line movement
        init()
        press(x=2, y=2)
        move(x=2, y=1, q='890ab')
        move(x=2.6, y=1, q='90ab')
        move(y=1, q='67890ab')
        move(x=4, y=1, q='0ab')
        move(x=4.6, y=1, q='ab')
        move(q='1234567890ab')
        move(x=2, y=3, q='cdefg')
        move(y=3, q='cde')
        move(x=0.6, y=3, q='cdef')
        move(x=2.6, y=3, q='cdefgh')
        move(x=4.6, y=3, q='cdefghij')

        # Single cell select
        init()
        press(), release(1)
        self.ae(sel(), '1')
        press(3), release(2)
        self.ae(sel(), '3')

        # Multi-line click release
        init()
        press(1, 1), release(3.6, 2)
        self.ae(sel(), '7890abcd')
        press(1.6, 1), release(3, 2)
        self.ae(sel(), '890abc')
        press(3.6, 4), release(2, 2)
        self.ae(sel(), 'cdefghijklmn')
        press(3, 4), release(2.6, 2)
        self.ae(sel(), 'defghijklm')

        # Word select with drag
        s.reset()
        s.draw('ab cd')
        s.draw(' f gh')
        s.draw(' stuv')
        s.draw('X Y')
        multi_click(x=1.4)
        self.ae(sel(), 'ab')
        move(2.6)
        self.ae(sel(), 'ab ')
        move(3.6)
        self.ae(sel(), 'ab cd')
        move(2.6)
        self.ae(sel(), 'ab ')
        release(3.6, 1)
        self.ae(sel(), 'ab cd f gh')
        multi_click(x=1, y=2)
        self.ae(sel(), 'stuvX')
        release()
        multi_click(x=3.6)
        self.ae(sel(), 'cd')
        move(0.2)
        release()
        self.ae(sel(), 'ab cd')
        multi_click(x=4.4)
        self.ae(sel(), 'cd')
        move(x=4.4, y=1)
        self.ae(sel(), 'cd f gh')
        move(x=4.4, y=0)
        self.ae(sel(), 'cd')
        release()
        multi_click(x=4.4, y=1)
        self.ae(sel(), 'gh')
        move(x=4.4, y=0)
        self.ae(sel(), 'cd f gh')
        move(x=4.4, y=1)
        self.ae(sel(), 'gh')
        release()
        multi_click(x=4.4)
        self.ae(sel(), 'cd')
        move()
        self.ae(sel(), 'ab cd')
        move(x=1, y=1)
        self.ae(sel(), 'ab cd f')
        move()
        self.ae(sel(), 'ab cd')
        release()
        multi_click(x=1.4)
        self.ae(sel(), 'ab')
        move(x=4.4)
        self.ae(sel(), 'ab cd')
        move(x=4.4, y=1)
        self.ae(sel(), 'ab cd f gh')
        move(x=4.4)
        self.ae(sel(), 'ab cd')

        # Line select with drag
        s.reset()
        s.draw('1 2 3')
        s.linefeed(), s.carriage_return()
        s.draw('4 5 6')
        s.linefeed(), s.carriage_return()
        s.draw('7 8 9X')
        multi_click(x=1, count=3)
        self.ae(sel(), str(s.line(0)))
        move(y=1)
        self.ae(sel(), '1 2 3\n4 5 6')
        move(y=2)
        self.ae(sel(), '1 2 3\n4 5 6\n7 8 9X')
        move(y=1)
        self.ae(sel(), '1 2 3\n4 5 6')
        move()
        self.ae(sel(), str(s.line(0)))
        release()
        multi_click(y=1, count=3)
        self.ae(sel(), '4 5 6')
        move(y=0)
        self.ae(sel(), '1 2 3\n4 5 6')
        move(y=1)
        self.ae(sel(), '4 5 6')
        move(y=2)
        self.ae(sel(), '4 5 6\n7 8 9X')
        release()
        s.reset()
        s.draw(' 123')
        s.linefeed(), s.carriage_return()
        s.draw(' 456')
        s.linefeed(), s.carriage_return()
        multi_click(x=1, count=3)
        self.ae(sel(), '123')
        move(x=2, y=1)
        self.ae(sel(), '123\n 456')
        release()
        press(x=2, y=1, button=GLFW_MOUSE_BUTTON_RIGHT)
        release(x=2, y=1, button=GLFW_MOUSE_BUTTON_RIGHT)
        self.ae(sel(), '123\n 456')
        press(button=GLFW_MOUSE_BUTTON_RIGHT)
        self.ae(sel(), ' 123\n 456')
        release(button=GLFW_MOUSE_BUTTON_RIGHT)

        # line select for wrapped lines in scrollback
        s.reset()
        s.draw('ABCDE12345')
        s.linefeed(), s.carriage_return()
        s.draw(('X' * s.columns) * (s.lines - 1))
        multi_click(x=1, count=3)
        self.ae(sel(), 'ABCDE12345')
        s.reset()
        s.draw('ABCDE12345')
        s.linefeed(), s.carriage_return()
        s.draw('678')
        s.linefeed(), s.carriage_return()
        s.draw(('X' * s.columns) * (s.lines - 2))
        multi_click(x=1, y=1, count=3)
        self.ae(sel(), '678')
        press(x=2, button=GLFW_MOUSE_BUTTON_RIGHT)
        release(x=2, button=GLFW_MOUSE_BUTTON_RIGHT)
        self.ae(sel(), 'ABCDE12345\n678')

        # line select for wrapped lines below viewport
        s.reset()
        s.scroll(100, False)
        # draw enough content to enable scrolling: fill lines-1 visual lines, then draw a long wrapped line
        s.draw(('X' * s.columns) * (s.lines - 1))
        s.linefeed(), s.carriage_return()
        s.draw('ABCDE12345')  # wraps to 2 visual lines, second one pushed below viewport
        # scroll up by 1 so top visual line of the wrapped text is visible but bottom wraps off-screen
        s.scroll(1, True)
        multi_click(x=1, y=s.lines - 1, count=3)
        self.ae(sel(), 'ABCDE12345')
        # extending selection to a line that wraps below viewport
        s.reset()
        s.scroll(100, False)
        s.draw(('X' * s.columns) * (s.lines - 2))
        s.linefeed(), s.carriage_return()
        s.draw('678')
        s.linefeed(), s.carriage_return()
        s.draw('ABCDE12345')
        s.scroll(1, True)
        multi_click(x=1, y=3, count=3)
        self.ae(sel(), '678')
        press(x=2, y=s.lines - 1, button=GLFW_MOUSE_BUTTON_RIGHT)
        release(x=2, y=s.lines - 1, button=GLFW_MOUSE_BUTTON_RIGHT)
        self.ae(sel(), '678\nABCDE12345')
        s.scroll(100, False)

        # word select for wrapped words in scrollback
        s.reset()
        s.draw('abcde12345')
        s.linefeed(), s.carriage_return()
        s.draw(('X' * s.columns) * (s.lines - 1))
        multi_click(x=1)
        self.ae(sel(), 'abcde12345')

        # word select for wrapped words below viewport
        s.reset()
        s.scroll(100, False)
        s.draw(('X' * s.columns) * (s.lines - 1))
        s.linefeed(), s.carriage_return()
        s.draw('abcde12345')
        s.scroll(1, True)
        multi_click(x=1, y=s.lines - 1)
        self.ae(sel(), 'abcde12345')
        s.scroll(100, False)

        # Rectangle select
        init()
        press(x=1, y=1, modifiers=GLFW_MOD_ALT | GLFW_MOD_CONTROL)
        move(x=3.6, y=3)
        self.ae(sel(), '789bcdghi')
        release(x=3, y=3)
        self.ae(sel(), '78bcgh')
        press(x=3.6, y=1, modifiers=GLFW_MOD_ALT | GLFW_MOD_CONTROL)
        self.ae(sel(), '')
        move(x=1, y=3)
        self.ae(sel(), '789bcdghi')
        release(x=1.6)
        self.ae(sel(), '3489')

        # scrolling
        init()
        press(x=1.6)
        scroll(x=1)
        self.ae(sel(), 'LMNO12')
        scroll(x=1)
        self.ae(sel(), 'GHIJKLMNO12')
        scroll(x=1, up=False)
        self.ae(sel(), 'LMNO12')
        scroll(x=2.6, up=False)
        self.ae(sel(), '3')
        release()
        # fractional scrolling
        init()
        s.fractional_scroll(-0.5)
        press()
        move(x=3.6, q='1234')
        release(x=3.6)
        self.ae(sel(), '1234')

        # extending selections
        init()
        press()
        move(x=3.6, q='1234')
        release(x=3.6)
        self.ae(sel(), '1234')
        press(x=1, y=1, button=GLFW_MOUSE_BUTTON_RIGHT)
        self.ae(sel(), '123456')
        move(x=2, y=1, q='1234567')
        release(x=3, y=1, button=GLFW_MOUSE_BUTTON_RIGHT)
        self.ae(sel(), '12345678')
        init()
        press(y=2)
        move(x=3.6, y=2, q='abcd')
        press(x=3, y=0, button=GLFW_MOUSE_BUTTON_RIGHT)
        self.ae(sel(), '4567890abcd')

        # blank line select
        s.reset()
        s.draw('abcde')
        s.linefeed(), s.carriage_return()
        s.linefeed(), s.carriage_return()
        s.draw('12345')
        press(x=0, y=0)
        move(x=2, y=2, q='abcde\n\n12')

        # Line from begin select (alt+triple click): selects from column 0
        # (including any leading whitespace), unlike normal triple click which strips it
        s.reset()
        s.draw(' 123')
        s.linefeed(), s.carriage_return()
        s.draw(' 456')
        s.linefeed(), s.carriage_return()
        multi_click(x=1, count=3, modifiers=GLFW_MOD_ALT)
        self.ae(sel(), ' 123')
        multi_click(x=1, count=3)
        self.ae(sel(), '123')
        multi_click(x=1, count=3, modifiers=GLFW_MOD_ALT)
        move(y=1)
        self.ae(sel(), ' 123\n 456')
        release()

        # Line from point select (ctrl+alt+triple click): selects from click
        # position to end of line; cannot start before the first non-blank char
        s.reset()
        s.draw(' 123')
        s.linefeed(), s.carriage_return()
        s.draw(' 456')
        s.linefeed(), s.carriage_return()
        multi_click(x=2, count=3, modifiers=GLFW_MOD_ALT | GLFW_MOD_CONTROL)
        self.ae(sel(), '23')
        # click before first non-blank: selection starts at first non-blank
        multi_click(x=0, count=3, modifiers=GLFW_MOD_ALT | GLFW_MOD_CONTROL)
        self.ae(sel(), '123')
        # click past last non-blank char: no selection created
        multi_click(x=4, count=3, modifiers=GLFW_MOD_ALT | GLFW_MOD_CONTROL)
        self.ae(sel(), '')
        # drag to next line
        multi_click(x=2, count=3, modifiers=GLFW_MOD_ALT | GLFW_MOD_CONTROL)
        move(y=1)
        self.ae(sel(), '23\n 456')
        release()

        # Word and line from point: selects the word at the click point and
        # extends the selection to the end of the line
        sel_word_and_line = MOUSE_SELECTION_WORD_AND_LINE_FROM_POINT
        s.reset()
        s.draw('ab cd')
        press(x=0)
        mock_mouse_selection(w, GLFW_MOUSE_BUTTON_LEFT, sel_word_and_line)
        self.ae(sel(), 'ab cd')
        press(x=3)
        mock_mouse_selection(w, GLFW_MOUSE_BUTTON_LEFT, sel_word_and_line)
        self.ae(sel(), 'cd')
        # click on space: no word, selects from space to end of line
        press(x=2)
        mock_mouse_selection(w, GLFW_MOUSE_BUTTON_LEFT, sel_word_and_line)
        self.ae(sel(), ' cd')
        # click past last non-blank char: no selection created
        press(x=4)
        mock_mouse_selection(w, GLFW_MOUSE_BUTTON_LEFT, sel_word_and_line)
        self.ae(sel(), '')

        # Double-click on whitespace: no word found, no selection created
        s.reset()
        s.draw('ab cd')
        multi_click(x=2)
        self.ae(sel(), '')
        multi_click(x=2.4)
        self.ae(sel(), '')

    def test_v120_scroll_direction_reversal(self):
        # A high resolution wheel delivers one physical detent as several
        # VALUE120 events, and the fractional remainder is carried between them.
        # Detents do not reliably total 120 units, so that carry is what lets an
        # undersized detent still scroll a line. But when the direction changes
        # the residual has the wrong sign, and the first detent of the new
        # direction gets spent cancelling it instead of scrolling.
        # The fragment sequences below were captured from a Logitech MX Master 3.
        from kitty.fast_data_types import test_scale_scroll

        self.set_options()  # scale_scroll reads wheel_scroll_multiplier
        cell = 40

        def run(*v120):
            # scale_scroll is exercised in mouse tracking mode, which reduces
            # wheel_scroll_multiplier to its sign, so the result does not depend
            # on the configured multiplier.
            return test_scale_scroll([float(v) for v in v120], cell)

        down = (-48, -32, -24, -24)  # 128 units
        up = (48, 32, 24, 24)

        # Five detents down, then one up. Every detent must scroll, including
        # the one that reverses direction. Before the residual was discarded on
        # a reversal, that last detent scrolled nothing.
        res = run(*(down * 5), *up)
        self.ae(-5, sum(res[:20]), f'detents before the reversal: {res}')
        self.ae(1, sum(res[20:]), f'detent that reversed direction: {res}')

        # Repeated reversals keep working.
        res = run(*(down * 2), *(up * 2), *(down * 2))
        self.ae([-2, 2, -2], [sum(res[i : i + 8]) for i in range(0, 24, 8)])

        # Scrolling in one direction is unaffected: the carry is retained, so a
        # run of undersized detents still scrolls about one line each.
        self.ae(-9, sum(run(*((-48, -24, -24, -16) * 10))))

        # A fragment too small to be a detent does not scroll.
        self.ae(0, sum(run(8)))

    def test_mapped_scroll_steps(self):
        from kitty.fast_data_types import test_mapped_scroll_steps as steps

        LINES, V120, HIGHRES = 0, 1, 2  # GLFWOffsetType
        self.set_options()
        # Classic wheel: one step per click, whatever wheel_scroll_multiplier is
        self.ae(steps(LINES, [1.0, 1.0, -1.0]), [1, 1, -1])
        # High resolution wheel: one step per 120 units, however they are split
        self.ae(sum(steps(V120, [15.0] * 16)), 2)
        # Touchpad: one step per 100 logical pixels, independent of the font size
        self.ae(steps(HIGHRES, [30.0] * 10), [0, 0, 0, 1, 0, 0, 1, 0, 0, 1])
        # Reversing direction starts a fresh step instead of first cancelling the remainder
        self.ae(steps(HIGHRES, [150.0, -60.0, -40.0]), [1, 0, -1])
        # touch_scroll_multiplier scales touchpad steps and its sign flips them
        self.set_options({'touch_scroll_multiplier': -2.0})
        self.ae(steps(HIGHRES, [30.0, 30.0]), [0, -1])
        # Wheels only take the sign of wheel_scroll_multiplier and every click is a step
        self.set_options({'wheel_scroll_multiplier': -3.0})
        self.ae(steps(LINES, [1.0, 0.1]), [-1, -1])
        self.ae(steps(V120, [120.0, 240.0]), [-1, -2])

    def test_wheel_events(self):
        LINES, V120, HIGHRES = 0, 1, 2  # GLFWOffsetType
        MOMENTUM_BEGAN, MOMENTUM_ACTIVE, MOMENTUM_ENDED = 1, 3, 4  # GLFWMomentumType
        WHEEL, FINGER = 1, 2  # GLFWScrollSource
        BEGAN, CHANGED, ENDED = 1, 2, 3  # GLFWScrollPhase
        s = self.create_screen(lines=5, scrollback=50)
        self.set_options({'pixel_scroll': False, 'wheel_scroll_multiplier': 5.0, 'touch_scroll_multiplier': 1.5})
        w = create_mock_window(s)

        def scroll(y=0.0, x=0.0, offset_type=LINES, mods=0, momentum=0, source=0, phase=0, inverted=False, t=0):
            # t is the time of the event in microseconds since the mode was turned on
            s.callbacks.wtcbuf = b''
            send_mock_scroll_event_to_window(w, offset_type, float(x), float(y), mods, momentum, source, phase, inverted, t)
            return strip_serials(s.callbacks.wtcbuf.decode())

        def ae(expected, mods=1, t='0:0', **kw):
            # The common parameters: the position of the mouse, the buttons held, the modifiers and the time
            self.ae(scroll(mods=kw.pop('glfw_mods', 0), **kw), ''.join(f'\x1b[>4:S;1;1;0;0;0;{mods};{t};{e}M' for e in expected))

        # Without mouse tracking the mode has no effect and the scrollback scrolls
        parse_bytes(s, b'\x1b[?5523h')
        self.assertTrue(s.detailed_mouse_events)
        self.ae(scroll(y=1), '')
        parse_bytes(s, b'\x1b[?1000h')
        # Wheels report whole clicks as 120, positive is downwards, the
        # multiplier is only a hint and the deltas are not repeated. As the
        # mouse never entered the window, entering is reported first.
        self.ae(scroll(y=3, source=WHEEL), '\x1b[>5:S;1;1;0;0;0;1;0:0M\x1b[>4:S;1;1;0;0;0;1;0:0;0;360:1;1:5000;1;0;0M')
        ae(['0;120;1:5000;1;0;0'], y=-1, source=WHEEL)
        # Horizontal scrolling, positive is rightwards
        ae(['120:1;0;1:5000;1;0;0'], x=1, source=WHEEL)
        # High resolution wheels
        ae(['0;30;1:5000;0;0;0'], y=-30, offset_type=V120)
        # Modifiers use the keyboard protocol encoding
        ae(['0;120;1:5000;0;0;0'], y=-1, glfw_mods=GLFW_MOD_CONTROL | GLFW_MOD_ALT, mods=7)
        ae(['0;120;1:5000;0;0;0'], y=-1, glfw_mods=GLFW_MOD_CAPS_LOCK, mods=65)
        # A touchpad gesture with fractional pixels, which are accumulated
        ae(['0;0;2:1500;2;1;0'], y=0, offset_type=HIGHRES, source=FINGER, phase=BEGAN)
        ae(['3;2:1;2:1500;2;2;0'], x=-3.5, y=2.5, offset_type=HIGHRES, source=FINGER, phase=CHANGED)
        ae(['1;1:1;2:1500;2;2;0'], x=-0.5, y=0.5, offset_type=HIGHRES, source=FINGER, phase=CHANGED)
        # Less than a pixel in the same phase has nothing to report
        ae([], y=0.25, offset_type=HIGHRES, source=FINGER, phase=CHANGED)
        ae(['0;1:1;2:1500;2;2;0'], y=0.75, offset_type=HIGHRES, source=FINGER, phase=CHANGED)
        # A change of phase is always reported
        ae(['0;0;2:1500;2;3;0'], offset_type=HIGHRES, source=FINGER, phase=ENDED)
        # Momentum
        ae(['0;10:1;2:1500;2;1;1'], y=10, offset_type=HIGHRES, source=FINGER, momentum=MOMENTUM_BEGAN)
        ae(['0;5:1;2:1500;2;2;1'], y=5, offset_type=HIGHRES, source=FINGER, momentum=MOMENTUM_ACTIVE)
        ae(['0;0;2:1500;2;3;1'], offset_type=HIGHRES, source=FINGER, momentum=MOMENTUM_ENDED)
        # Natural scrolling
        ae(['0;10:1;2:1500;2;1;2'], y=10, offset_type=HIGHRES, source=FINGER, phase=BEGAN, inverted=True)
        # A negative multiplier reverses the deltas and the inverted flag
        self.set_options({'pixel_scroll': False, 'wheel_scroll_multiplier': -2.25})
        ae(['0;120:1;1:2250;1;0;2'], y=-1, source=WHEEL)
        ae(['0;120:1;1:2250;1;0;0'], y=-1, source=WHEEL, inverted=True)
        # The time of the event, as seconds:microseconds since the mode was
        # turned on, rounded down to a whole millisecond
        self.ae(scroll(y=-1, source=WHEEL, t=1520042), '\x1b[>4:S;1;1;0;0;0;1;1:520000;0;120:1;1:2250;1;0;2M')
        # Times never decrease, even if events arrive out of order
        self.ae(scroll(y=-1, source=WHEEL, t=1000), '\x1b[>4:S;1;1;0;0;0;1;1:520000;0;120:1;1:2250;1;0;2M')
        self.ae(scroll(y=-1, source=WHEEL, t=1520999), '\x1b[>4:S;1;1;0;0;0;1;1:520000;0;120:1;1:2250;1;0;2M')
        self.ae(scroll(y=-1, source=WHEEL, t=1521000), '\x1b[>4:S;1;1;0;0;0;1;1:521000;0;120:1;1:2250;1;0;2M')
        # Unreported events do not affect the time
        self.ae(scroll(y=0.25, offset_type=HIGHRES, source=FINGER, phase=CHANGED, t=9000000), '')
        self.ae(scroll(y=0.75, offset_type=HIGHRES, source=FINGER, phase=CHANGED, t=2000000), '\x1b[>4:S;1;1;0;0;0;1;2:0;0;1:1;2:1000;2;2;0M')
        # Turning the mode on again resets the origin, events from before it are
        # at zero, and the mouse has to enter the window again
        parse_bytes(s, b'\x1b[?5523l\x1b[?5523h')
        self.ae(scroll(y=-1, source=WHEEL, t=-5000), '\x1b[>5:S;1;1;0;0;0;1;0:0M\x1b[>4:S;1;1;0;0;0;1;0:0;0;120:1;1:2250;1;0;2M')
        self.ae(scroll(y=-1, source=WHEEL, t=7300), '\x1b[>4:S;1;1;0;0;0;1;0:7000;0;120:1;1:2250;1;0;2M')
        # Setting the mode while it is on does not reset the origin
        parse_bytes(s, b'\x1b[?5523h')
        self.ae(scroll(y=-1, source=WHEEL, t=3000), '\x1b[>4:S;1;1;0;0;0;1;0:7000;0;120:1;1:2250;1;0;2M')
        # Turning the mode off restores legacy reporting
        parse_bytes(s, b'\x1b[?1006h\x1b[?5523l')
        self.assertFalse(s.detailed_mouse_events)
        self.ae(scroll(y=-1, source=WHEEL), '\x1b[<64;1;1M')
        # DECRQM
        s.callbacks.wtcbuf = b''
        parse_bytes(s, b'\x1b[?5523$p')
        self.ae(s.callbacks.wtcbuf, b'\x1b[?5523;2$y')
        s.callbacks.wtcbuf = b''
        parse_bytes(s, b'\x1b[?5523h\x1b[?5523$p')
        self.ae(s.callbacks.wtcbuf, b'\x1b[?5523;1$y')

    def test_detailed_mouse_events(self):
        L, M, R = GLFW_MOUSE_BUTTON_LEFT, GLFW_MOUSE_BUTTON_MIDDLE, GLFW_MOUSE_BUTTON_RIGHT
        s = self.create_screen(cols=10, lines=5, options={'wheel_scroll_multiplier': 5.0, 'click_interval': 0.5})
        w = create_mock_window(s)
        selections = []
        s.callbacks.mouse_selection = selections.append
        send_mock_mouse_events(w, [], True)
        last_serial = 0

        # The mock window has cells 10x20 pixels, the first one at (20, 20),
        # and padding of 10 pixels, so it spans from (10, 10) to (130, 130).
        # t is in microseconds since the mode was turned on.
        def e(kind, x=0, y=0, t=-1, button=0, mods=0):
            if kind == 'call':
                return (kind, x)
            return (kind, button, float(x), float(y), t, mods)

        def ae(events, *expected, serials_restart=False):
            nonlocal last_serial
            s.callbacks.wtcbuf = b''
            send_mock_mouse_events(w, list(events))
            actual = s.callbacks.wtcbuf.decode()
            if serials_restart:  # the mode was turned on again
                last_serial = 0
            # Every event has the next serial
            for serial in map(int, re.findall(r'\x1b\[>\d+:(\d+);', actual)):
                self.ae(serial, last_serial + 1)
                last_serial = serial
            self.ae(re.sub(r'\x1b\[>?', ' ', strip_serials(actual)).split(), [x.rstrip('M') + 'M' for x in expected])

        # Without mouse tracking nothing is reported
        parse_bytes(s, b'\x1b[?5523h')
        ae([e('move', 65, 50, 1000), e('press', 65, 50, 1000, L), e('release', 65, 50, 1000, L)])
        parse_bytes(s, b'\x1b[?1003h')
        # The mouse moving into the window is reported as entering, motion is
        # reported when the position in pixels changes
        ae(
            [e('move', 0, 0, 0), e('move', 65, 50, 1000), e('move', 65.2, 50, 1500), e('move', 66, 50, 2000)],
            '5:S;5;2;45;30;0;1;0:1000',
            '3:S;5;2;46;30;0;1;0:2000',
        )
        # A press grabs the mouse: events are reported wherever the mouse is,
        # with the cell nearest to it and the position in pixels, which is
        # negative to the left of the first cell. Leaving is reported after
        # the release outside the window.
        ae(
            [e('press', 66, 50, 3000, L), e('move', 5, 50, 4000), e('release', 5, 50, 5000, L)],
            '1:S;5;2;46;30;1;1;0:3000;1;1',
            '3:S;1;2;15:1;30;1;1;0:4000',
            '2:S;1;2;15:1;30;0;1;0:5000;1;1',
            '6:S;1;2;15:1;30;0;1;0:5000',
        )
        # The padding is in the window
        ae([e('move', 15, 50, 6000), e('move', 14, 50, 7000)], '5:S;1;2;5:1;30;0;1;0:6000', '3:S;1;2;6:1;30;0;1;0:7000')
        # Times are seconds:microseconds
        ae([e('move', 66, 50, 1000000)], '3:S;5;2;46;30;0;1;1:0')
        # Click counts: presses of the same button, each within the double
        # click interval and a small distance of the previous one, keep
        # counting up. Releases have the count of their press.
        ae(
            [
                e('press', 66, 50, 1000000, L),
                e('release', 66, 50, 1100000, L),
                e('press', 67, 51, 1300000, L),
                e('release', 67, 51, 1350000, L),
                e('press', 66, 50, 1700000, L),
                e('release', 66, 50, 1750000, L),
                e('press', 66, 50, 1800000, L),
                e('release', 66, 50, 1850000, L),
            ],
            '1:S;5;2;46;30;1;1;1:0;1;1',
            '2:S;5;2;46;30;0;1;1:100000;1;1',
            '1:S;5;2;47;31;1;1;1:300000;1;2',
            '2:S;5;2;47;31;0;1;1:350000;1;2',
            '1:S;5;2;46;30;1;1;1:700000;1;3',
            '2:S;5;2;46;30;0;1;1:750000;1;3',
            '1:S;5;2;46;30;1;1;1:800000;1;4',
            '2:S;5;2;46;30;0;1;1:850000;1;4',
        )
        # Another button, a press after the interval and one too far away start counting again
        ae(
            [
                e('press', 66, 50, 1900000, R),
                e('release', 66, 50, 1950000, R),
                e('press', 66, 50, 2600000, R),
                e('release', 66, 50, 2650000, R),
                e('press', 80, 50, 2700000, R),
                e('release', 80, 50, 2750000, R),
            ],
            '1:S;5;2;46;30;4;1;1:900000;3;1',
            '2:S;5;2;46;30;0;1;1:950000;3;1',
            '1:S;5;2;46;30;4;1;2:600000;3;1',
            '2:S;5;2;46;30;0;1;2:650000;3;1',
            '1:S;7;2;60;30;4;1;2:700000;3;1',
            '2:S;7;2;60;30;0;1;2:750000;3;1',
        )
        # Several buttons: the buttons held are reported with every event and
        # the mouse stays grabbed until all of them are released, scroll events
        # too go to the window that has grabbed the mouse
        ae(
            [
                e('press', 80, 50, 3000000, L),
                e('press', 140, 50, 3100000, R),
                e('release', 140, 50, 3200000, L),
                e('scroll', 140, 50, 3300000, 1),
                e('release', 140, 50, 3400000, R),
            ],
            '1:S;7;2;60;30;1;1;3:0;1;1',
            '1:S;10;2;120;30;5;1;3:100000;3;1',
            '2:S;10;2;120;30;4;1;3:200000;1;1',
            '4:S;10;2;120;30;4;1;3:300000;0;120;1:5000;1;0;0',
            '2:S;10;2;120;30;0;1;3:400000;3;1',
            '6:S;10;2;120;30;0;1;3:400000',
        )
        # Neither the press nor the release of a click kitty handles is reported
        ae(
            [e('move', 66, 50, 4000000), e('press', 66, 50, 4100000, L, GLFW_MOD_SHIFT), e('release', 66, 50, 4200000, L, GLFW_MOD_SHIFT)],
            '5:S;5;2;46;30;0;1;4:0',
        )
        self.assertTrue(selections)
        # The lock modifiers are reported
        ae(
            [e('press', 66, 50, 5000000, M, GLFW_MOD_CAPS_LOCK), e('release', 66, 50, 5100000, M, GLFW_MOD_CAPS_LOCK)],
            '1:S;5;2;46;30;2;65;5:0;2;1',
            '2:S;5;2;46;30;0;65;5:100000;2;1',
        )
        # The mouse leaving and entering the OS window, these events have the
        # time they are processed, which is just after the mode was turned on
        ae([e('leave', 66, 50), e('enter', 66, 50)], '6:S;5;2;46;30;0;1;5:100000', '5:S;5;2;46;30;0;1;5:100000')
        # The window disappearing from under the mouse, the position of leaving
        # is the last reported one. Entering is always reported before other events.
        ae([e('hide', 66, 50), e('show', 66, 50), e('move', 67, 50, 7000000)], '6:S;5;2;46;30;0;1;5:100000', '5:S;5;2;47;30;0;1;7:0')
        # Turning mouse tracking off and on with the mouse in the window
        # reports entering. In mode 1000, motion is not reported.
        ae(
            [
                e('call', lambda: parse_bytes(s, b'\x1b[?1003l')),
                e('move', 68, 50, 8000000),
                e('call', lambda: parse_bytes(s, b'\x1b[?1000h')),
                e('move', 69, 50, 8100000),
                e('press', 69, 50, 8200000, L),
                e('move', 70, 50, 8300000),
                e('release', 70, 50, 8400000, L),
            ],
            '5:S;5;2;48;30;0;1;7:0',
            '1:S;5;2;49;30;1;1;8:200000;1;1',
            '2:S;6;2;50;30;0;1;8:400000;1;1',
        )
        # In mode 1002, only motion with a button held is reported
        ae(
            [
                e('call', lambda: parse_bytes(s, b'\x1b[?1002h')),
                e('move', 71, 50, 9000000),
                e('press', 71, 50, 9100000, L),
                e('move', 72, 50, 9200000),
                e('release', 72, 50, 9300000, L),
                e('move', 73, 50, 9400000),
            ],
            '1:S;6;2;51;30;1;1;9:100000;1;1',
            '3:S;6;2;52;30;1;1;9:200000',
            '2:S;6;2;52;30;0;1;9:300000;1;1',
        )
        # Turning mouse tracking off while a button is held: its release is not
        # reported, and when it is turned on again, nothing is held
        ae(
            [
                e('press', 73, 50, 10000000, L),
                e('call', lambda: parse_bytes(s, b'\x1b[?1002l')),
                e('release', 73, 50, 10100000, L),
                e('call', lambda: parse_bytes(s, b'\x1b[?1003h')),
                e('move', 75, 50, 10200000),
            ],
            '1:S;6;2;53;30;1;1;10:0;1;1',
            '5:S;6;2;53;30;0;1;10:0',
            '3:S;6;2;55;30;0;1;10:200000',
        )
        # A press of a button that is held means its release was lost, which is reported first
        ae(
            [e('press', 75, 50, 11000000, L), e('press', 75, 50, 11100000, L), e('release', 75, 50, 11200000, L)],
            '1:S;6;2;55;30;1;1;11:0;1;1',
            '2:S;6;2;55;30;0;1;11:100000;1;1',
            '1:S;6;2;55;30;1;1;11:100000;1;2',
            '2:S;6;2;55;30;0;1;11:200000;1;2',
        )
        # Scrolling outside the window is not reported, even though kitty scrolls the active window
        ae([e('move', 5, 50, 12000000), e('scroll', 5, 50, 12100000, 1), e('move', 75, 50, 12200000)], '6:S;6;2;55;30;0;1;12:0', '5:S;6;2;55;30;0;1;12:200000')
        # In mode 1002, motion with a button held whose press kitty handled is not reported
        ae(
            [
                e('call', lambda: parse_bytes(s, b'\x1b[?1002h')),
                e('press', 75, 50, 13000000, L, GLFW_MOD_SHIFT),
                e('move', 85, 50, 13100000),
                e('release', 85, 50, 13200000, L, GLFW_MOD_SHIFT),
                e('call', lambda: parse_bytes(s, b'\x1b[?1003h')),
            ],
        )
        # A drag tracked for the legacy encodings whose release was lost does not prevent the grab
        ae(
            [
                e('call', lambda: parse_bytes(s, b'\x1b[?5523l\x1b[?1006h\x1b[?1016h')),
                e('move', 75, 50),
                e('press', 75, 50, -1, L),
                e('move', 5, 50),
                e('call', lambda: parse_bytes(s, b'\x1b[?1016l\x1b[?1006l\x1b[?5523h')),
                e('move', 75, 50, 14000000),
                e('press', 75, 50, 14100000, L),
                e('move', 5, 50, 14200000),
                e('release', 5, 50, 14300000, L),
            ],
            # The legacy SGR pixel encoding uses negative positions
            '<35;55;30M',
            '<0;55;30M',
            '<32;-15;30M',
            '5:S;6;2;55;30;0;1;14:0',
            '1:S;6;2;55;30;1;1;14:100000;1;1',
            '3:S;1;2;15:1;30;1;1;14:200000',
            '2:S;1;2;15:1;30;0;1;14:300000;1;1',
            '6:S;1;2;15:1;30;0;1;14:300000',
            serials_restart=True,
        )
        # Events simulated by kittens, buttons are numbered as in X11
        for args, expected in (
            ((PRESS, 0), '1:S;3;4;25;65;1;1;14:300000;1;1'),
            ((RELEASE, GLFW_MOD_SHIFT), '2:S;3;4;25;65;0;2;14:300000;1;1'),
            ((PRESS, 0, 5), '4:S;3;4;25;65;0;1;14:300000;0;120;1;0;0;0'),
            ((PRESS, 0, 8), '1:S;3;4;25;65;8;1;14:300000;4;1'),
        ):
            s.callbacks.wtcbuf = b''
            action, mods, *button = args
            self.assertTrue(send_simulated_mouse_event(s, 2, 3, button[0] if button else 1, action, mods, 25, 65))
            self.ae(strip_serials(s.callbacks.wtcbuf.decode()), f'\x1b[>{expected}M')
        # Turning the mode off restores the other encodings
        parse_bytes(s, b'\x1b[?1006h\x1b[?5523l')
        ae([e('move', 86, 50)], '<35;7;2M')

    def test_mapped_scroll(self):
        from kitty.config import load_config

        LINES, HIGHRES = 0, 2  # GLFWOffsetType
        MOMENTUM_BEGAN, MOMENTUM_ACTIVE, MOMENTUM_ENDED = 1, 3, 4  # GLFWMomentumType
        s = self.create_screen(lines=5, scrollback=50)
        errors = []
        opts = load_config(
            overrides=(
                'pixel_scroll no',
                'wheel_scroll_multiplier 1',
                'mouse_map ctrl+wheel_up press ungrabbed change_font_size all +1',
                'mouse_map ctrl+wheel_down press ungrabbed change_font_size all -1',
                'mouse_map alt+wheel_up press ungrabbed mouse_selection normal',
                'mouse_map ctrl+wheel_left press ungrabbed previous_tab',
                'mouse_map shift+wheel_left press ungrabbed previous_tab',
                'mouse_map shift+wheel_right press ungrabbed next_tab',
            ),
            accumulate_bad_lines=errors,
        )
        self.ae(errors, [])
        set_options(opts)
        w = create_mock_window(s)
        for i in range(50):
            s.draw(f'{i}')
            s.carriage_return()
            s.linefeed()
        calls = []
        s.callbacks.change_font_size = lambda *a: calls.append(a[1])
        s.callbacks.mouse_selection = lambda code: mock_mouse_selection(w, s.callbacks.current_mouse_button, code)
        s.callbacks.previous_tab = lambda: calls.append('left')
        s.callbacks.next_tab = lambda: calls.append('right')

        def scroll(y, mods=0, offset_type=LINES, momentum=0, x=0.0):
            send_mock_scroll_event_to_window(w, offset_type, x, float(y), mods, momentum)

        def ac(expected_calls, scrolled_by):
            self.ae(calls, expected_calls)
            self.ae(s.scrolled_by, scrolled_by)
            del calls[:]

        # Unmapped scrolling still scrolls the screen
        scroll(2)
        ac([], 2)
        # Mapped scrolling fires the action once per step instead
        scroll(1, GLFW_MOD_CONTROL)
        ac(['+'], 2)
        scroll(3, GLFW_MOD_CONTROL)
        ac(['+'] * 3, 2)
        scroll(-1, GLFW_MOD_CONTROL)
        ac(['-'], 2)
        # Touchpad events that do not complete a step are consumed
        scroll(60, GLFW_MOD_CONTROL, HIGHRES)
        ac([], 2)
        scroll(40, GLFW_MOD_CONTROL, HIGHRES)
        ac(['+'], 2)
        # A partial step does not survive unmapped scrolling in between
        scroll(60, GLFW_MOD_CONTROL, HIGHRES)
        scroll(1)
        ac([], 3)
        scroll(40, GLFW_MOD_CONTROL, HIGHRES)
        ac([], 3)
        # Momentum after a mapped gesture neither fires the action nor scrolls
        scroll(100, GLFW_MOD_CONTROL, HIGHRES)
        scroll(200, GLFW_MOD_CONTROL, HIGHRES, MOMENTUM_BEGAN)
        scroll(200, GLFW_MOD_CONTROL, HIGHRES, MOMENTUM_ACTIVE)
        ac(['+'], 3)
        # A horizontal unmapped gesture ends the mapped gesture, so its momentum scrolls
        scroll(0, x=10, offset_type=HIGHRES)
        scroll(-40, 0, HIGHRES, MOMENTUM_BEGAN)
        ac([], 1)
        # Modifiers or modes without a mapping scroll normally
        scroll(1, GLFW_MOD_ALT | GLFW_MOD_CONTROL)
        ac([], 2)
        parse_bytes(s, b'\x1b[?1000h')  # grab the mouse
        scroll(1, GLFW_MOD_CONTROL)
        ac([], 2)
        parse_bytes(s, b'\x1b[?1000l')
        # The wheel cannot start a selection, it never releases
        scroll(1, GLFW_MOD_ALT)
        self.assertFalse(s.has_selection())
        ac([], 2)
        # Horizontal scrolling, positive offsets are leftwards
        scroll(0, GLFW_MOD_SHIFT, x=1)
        ac(['left'], 2)
        scroll(0, GLFW_MOD_SHIFT, x=-2)
        ac(['right'] * 2, 2)
        scroll(0, GLFW_MOD_SHIFT, HIGHRES, x=60)
        ac([], 2)
        scroll(0, GLFW_MOD_SHIFT, HIGHRES, x=40)
        ac(['left'], 2)
        # A diagonal event fires the mappings of both axes
        scroll(1, GLFW_MOD_CONTROL, x=1)
        ac(['+', 'left'], 2)
        # Horizontal jitter, without horizontal mappings, continues a mapped
        # vertical gesture, so its momentum is still swallowed
        scroll(100, GLFW_MOD_ALT, HIGHRES)
        scroll(0, GLFW_MOD_ALT, HIGHRES, x=10)
        scroll(-200, GLFW_MOD_ALT, HIGHRES, MOMENTUM_BEGAN)
        ac([], 2)
        # But horizontal scrolling in an unmapped direction, with horizontal
        # mappings, ends the gesture, so its momentum scrolls
        scroll(100, GLFW_MOD_CONTROL, HIGHRES)
        scroll(0, GLFW_MOD_CONTROL, HIGHRES, x=-10)
        scroll(-20, GLFW_MOD_CONTROL, HIGHRES, MOMENTUM_BEGAN)
        ac(['+'], 1)
        # Spent momentum ends the gesture, so a later unmapped event in the same
        # window with the same modifiers scrolls instead of being swallowed.
        # shift is mapped horizontally only, so vertical scrolling is unmapped.
        scroll(0, GLFW_MOD_SHIFT, HIGHRES, x=100)
        scroll(0, GLFW_MOD_SHIFT, HIGHRES, MOMENTUM_BEGAN, x=-200)
        scroll(0, GLFW_MOD_SHIFT, HIGHRES, MOMENTUM_ENDED, x=-100)
        ac(['left'], 1)
        scroll(1, GLFW_MOD_SHIFT)
        ac([], 2)

        # A classic wheel has no end-of-gesture event, so a gesture is also
        # bounded by the time between its events and by the mouse mode, which
        # changes the set of mapped wheel buttons. Without that, an unmapped
        # direction would stay swallowed indefinitely. Reload the mappings so
        # that ctrl is mapped horizontally only, as in the mouse_map docs.
        opts = load_config(
            overrides=(
                'pixel_scroll no',
                'wheel_scroll_multiplier 1',
                'mouse_map ctrl+wheel_left press ungrabbed,grabbed previous_tab',
                'mouse_map ctrl+wheel_right press ungrabbed,grabbed next_tab',
                'mouse_map alt+wheel_up press ungrabbed change_font_size all +1',
            ),
            accumulate_bad_lines=errors,
        )
        self.ae(errors, [])
        set_options(opts)
        # Vertical is unmapped for ctrl now, so it scrolls
        scroll(1, GLFW_MOD_CONTROL)
        ac([], 3)
        # A mapped horizontal event starts a gesture, during which off-axis
        # jitter is still swallowed
        scroll(0, GLFW_MOD_CONTROL, x=1)
        ac(['left'], 3)
        scroll(1, GLFW_MOD_CONTROL)
        ac([], 3)
        # But once the gesture times out, vertical scrolling works again
        sleep(0.3)
        scroll(1, GLFW_MOD_CONTROL)
        ac([], 4)
        # Changing the mouse mode ends the gesture too. alt+wheel_up is mapped
        # only when ungrabbed, so once grabbed the wheel goes to the program
        # instead of being swallowed as a continuation of the mapped gesture.
        scroll(1, GLFW_MOD_ALT)
        ac(['+'], 4)
        parse_bytes(s, b'\x1b[?1000h')
        s.callbacks.wtcbuf = b''
        scroll(1, GLFW_MOD_ALT)
        ac([], 4)
        self.assertTrue(s.callbacks.wtcbuf, 'the wheel event was not reported to the program')
        parse_bytes(s, b'\x1b[?1000l')
