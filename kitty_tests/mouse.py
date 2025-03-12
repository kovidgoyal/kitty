#!/usr/bin/env python
# License: GPL v3 Copyright: 2016, Kovid Goyal <kovid at kovidgoyal.net>

from functools import partial

from kitty.fast_data_types import (
    GLFW_MOD_ALT,
    GLFW_MOD_CONTROL,
    GLFW_MOUSE_BUTTON_LEFT,
    GLFW_MOUSE_BUTTON_RIGHT,
    create_mock_window,
    mock_mouse_selection,
    send_mock_mouse_event_to_window,
)

from . import BaseTest


def send_mouse_event(
    window,
    button=-1,
    modifiers=0,
    is_release=False,
    x=0.0,
    y=0,
    clear_click_queue=False,
):
    ix = int(x)
    in_left_half_of_cell = x - ix < 0.5
    send_mock_mouse_event_to_window(
        window, button, modifiers, is_release, ix, y, clear_click_queue, in_left_half_of_cell
    )


class TestMouse(BaseTest):

    def test_mouse_selection(self):
        s = self.create_screen(
            options=dict(
                rectangle_select_modifiers=GLFW_MOD_ALT | GLFW_MOD_CONTROL
            )
        )
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
            ev(
                button,
                x=x,
                y=y,
                is_release=True,
                clear_click_queue=True
            )

        def move(x=0, y=0, button=-1, q=None):
            ev(x=x, y=y, button=button)
            if q is not None:
                sl = sel()
                from kitty.window import as_text
                self.ae(sl, q, f'{sl!r} != {q!r} after movement to x={x} y={y}. Screen contents: {as_text(s)!r}')

        def multi_click(x=0, y=0, count=2):
            clear_click_queue = True
            while count > 0:
                count -= 1
                ev(GLFW_MOUSE_BUTTON_LEFT, x=x, y=y, clear_click_queue=clear_click_queue)
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
