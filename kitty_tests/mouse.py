#!/usr/bin/env python
# License: GPL v3 Copyright: 2016, Kovid Goyal <kovid at kovidgoyal.net>

from functools import partial
from time import sleep

from kitty.fast_data_types import (
    GLFW_MOD_ALT,
    GLFW_MOD_CONTROL,
    GLFW_MOD_SHIFT,
    GLFW_MOUSE_BUTTON_LEFT,
    GLFW_MOUSE_BUTTON_RIGHT,
    MOUSE_SELECTION_WORD_AND_LINE_FROM_POINT,
    create_mock_window,
    mock_mouse_selection,
    send_mock_mouse_event_to_window,
    send_mock_scroll_event_to_window,
    set_options,
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
    send_mock_mouse_event_to_window(window, button, modifiers, is_release, ix, y, clear_click_queue, in_left_half_of_cell, pixel_x, pixel_y)


class TestMouse(BaseTest):
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
