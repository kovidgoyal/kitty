#!/usr/bin/env python
# License: GPL v3

from functools import partial
from types import SimpleNamespace
from unittest.mock import patch

from kitty.config import load_config
from kitty.fast_data_types import (
    GLFW_DRAG_OPERATION_COPY,
    GLFW_MOD_SHIFT,
    GLFW_MOUSE_BUTTON_LEFT,
    GLFW_MOUSE_BUTTON_RIGHT,
    MOUSE_SELECTION_DRAG_OR_NORMAL_SELECT,
    create_mock_window,
    mock_mouse_selection,
    set_options,
)
from kitty.window import Window

from .base import BaseTest, draw_multicell
from .mouse import send_mouse_event

LEFT = GLFW_MOUSE_BUTTON_LEFT


class TestSelectionDrag(BaseTest):
    def drag_screen(self, *config, cols=40, lines=6):
        s = self.create_screen(cols=cols, lines=lines, scrollback=20)
        errors = []
        opts = load_config(
            overrides=(
                'pixel_scroll no',
                'click_interval 0.5',
                'drag_threshold 5',
                'mouse_map left press ungrabbed mouse_selection drag_or_normal_select',
                *config,
            ),
            accumulate_bad_lines=errors,
        )
        self.ae(errors, [])
        set_options(opts)
        w = create_mock_window(s)
        s.callbacks.mouse_selection = lambda code: mock_mouse_selection(w, s.callbacks.current_mouse_button, code)
        drags = []
        s.callbacks.drag_selection = lambda: drags.append(''.join(s.text_for_selection()))
        return s, partial(send_mouse_event, w), drags

    @staticmethod
    def select(s, start=(0, 0), end=(5, 0), rectangle=False):
        s.start_selection(*start, rectangle, 0, True)
        s.update_selection(*end, True)

    def test_selection_drag_gesture(self):
        s, ev, drags = self.drag_screen()
        s.draw('alpha beta gamma')
        self.select(s)
        ev(LEFT, x=1, pixel_x=12, clear_click_queue=True)
        self.ae(''.join(s.text_for_selection()), 'alpha')
        ev(x=1, pixel_x=16)
        ev(x=1, pixel_x=17)  # Exactly the threshold is not a drag.
        self.ae(drags, [])
        self.ae(''.join(s.text_for_selection()), 'alpha')
        ev(x=1, pixel_x=18)  # A drag can start without leaving the cell.
        ev(x=2)
        self.ae(drags, ['alpha'])
        self.ae(''.join(s.text_for_selection()), 'alpha')

        # Native drag-and-drop consumes mouse-up, even if the drop is canceled.
        # The next gesture must work without delivering the previous release.
        ev(LEFT, x=6, clear_click_queue=True)
        ev(x=10)
        ev(LEFT, x=10, is_release=True)
        self.ae(''.join(s.text_for_selection()), 'beta')
        self.ae(drags, ['alpha'])
        ev(x=20)
        self.ae(drags, ['alpha'])

    def test_selection_drag_clicks(self):
        s, ev, drags = self.drag_screen()
        s.draw('alpha beta gamma')
        self.select(s)
        ev(LEFT, x=1, clear_click_queue=True)
        ev(x=1, pixel_x=13)
        ev(LEFT, x=1, is_release=True)
        self.assertFalse(s.has_selection())
        ev(x=20)
        self.ae(drags, [])

        for count, expected in ((2, 'alpha'), (3, 'alpha beta gamma')):
            with self.subTest(clicks=count):
                self.select(s)
                for i in range(count):
                    ev(LEFT, x=1, clear_click_queue=i == 0)
                    if i != count - 1:
                        ev(LEFT, x=1, is_release=True)
                self.ae(''.join(s.text_for_selection()), expected)
                ev(x=12)
                ev(LEFT, x=12, is_release=True)
                self.assertTrue(s.has_selection())
                self.ae(drags, [])

    def test_selection_drag_configuration(self):
        for config, button in (
            (('drag_threshold 0',), LEFT),
            (('mouse_map left press ungrabbed mouse_selection normal',), LEFT),
            (('mouse_map right press ungrabbed mouse_selection drag_or_normal_select',), GLFW_MOUSE_BUTTON_RIGHT),
        ):
            with self.subTest(config=config):
                s, ev, drags = self.drag_screen(*config)
                s.draw('alpha beta gamma')
                self.select(s)
                ev(button, x=1, clear_click_queue=True)
                ev(x=4)
                ev(button, x=4, is_release=True)
                self.ae(drags, [])
                self.ae(''.join(s.text_for_selection()), 'lph')

        s, ev, drags = self.drag_screen('mouse_map shift+left press grabbed mouse_selection drag_or_normal_select')
        s.draw('alpha beta gamma')
        self.select(s)
        s.set_mode(1002, True)  # The terminal program owns unmodified mouse events.
        ev(LEFT, x=1, clear_click_queue=True)
        ev(x=4)
        ev(LEFT, x=4, is_release=True)
        self.ae(drags, [])
        self.ae(''.join(s.text_for_selection()), 'alpha')
        ev(LEFT, x=1, modifiers=GLFW_MOD_SHIFT, clear_click_queue=True)
        ev(x=4, modifiers=GLFW_MOD_SHIFT)
        self.ae(drags, ['alpha'])

    def test_selection_drag_links(self):
        s, ev, drags = self.drag_screen('mouse_map left click ungrabbed')
        s.draw('https://example.com')
        urls = []
        s.callbacks.drag_url = lambda url, hyperlink_id: urls.append(url)
        self.select(s, (8, 0), (15, 0))
        ev(x=10)
        ev(LEFT, x=10, clear_click_queue=True)
        ev(x=11)
        self.ae(drags, ['example'])
        self.ae(urls, [])
        s.clear_selection()
        ev(x=10)
        self.assertNotIn(2, s.current_selections())
        ev(LEFT, x=10, clear_click_queue=True)
        ev(x=11)
        self.ae(urls, ['https://example.com'])
        self.ae(drags, ['example'])

    def test_selection_drag_click_count(self):
        s, ev, drags = self.drag_screen()
        s.draw('https://example.com')
        urls = []
        s.callbacks.drag_url = lambda url, hyperlink_id: urls.append(url)
        codes = []
        dispatch = s.callbacks.mouse_selection

        def record(code):
            codes.append(code)
            dispatch(code)

        s.callbacks.mouse_selection = record
        # A native drag consumes mouse-up, so the press must not linger in the
        # click queue, otherwise the next press counts as a double press and
        # selects a word instead of starting a new gesture. This applies to
        # link drags just as much as to text drags.
        for i in range(1, 3):
            with self.subTest(gesture=i):
                ev(x=10)
                ev(LEFT, x=10, pixel_x=100)
                ev(x=10, pixel_x=106)  # exceed the threshold without leaving the cell
                self.ae(codes, [MOUSE_SELECTION_DRAG_OR_NORMAL_SELECT] * i)
                self.ae(urls, ['https://example.com'] * i)
                self.ae(drags, [])

    def test_selection_drag_hit_testing(self):
        for kind in ('forward', 'backward', 'rectangle', 'unicode', 'multicell', 'scrollback', 'alternate'):
            with self.subTest(kind=kind):
                s, ev, drags = self.drag_screen(cols=12, lines=4)
                if kind == 'alternate':
                    s.toggle_alt_screen()
                if kind == 'multicell':
                    s.draw('a')
                    draw_multicell(s, 'X', scale=2)
                    s.draw('bc')
                elif kind == 'unicode':
                    s.draw('a中文😀e\u0301b')
                else:
                    for i in range(8 if kind == 'scrollback' else 3):
                        s.draw(f'{i} abcdefghij\r\n')
                    if kind == 'scrollback':
                        s.scroll(2, True)
                start, end = (2, 0), (5, 2)
                if kind == 'backward':
                    start, end = end, start
                for y in range(s.lines):
                    for x in range(s.columns):
                        self.select(s, start, end, kind == 'rectangle')
                        selected = bool(s.current_selections()[y * s.columns + x] & 1)
                        text = ''.join(s.text_for_selection())
                        before = len(drags)
                        ev(LEFT, x=x, y=y, clear_click_queue=True)
                        ev(x=x, y=y, pixel_x=x * 10 + 6)
                        self.ae(len(drags) - before, int(selected), f'{kind}: cell {(x, y)}')
                        if selected:
                            self.ae(drags[-1], text)
                        ev(LEFT, x=x, y=y, is_release=True)

    def test_selection_drag_payload(self):
        s, _, _ = self.drag_screen()
        text = '中文 😀 e\u0301\t  value\n' * 100
        w = SimpleNamespace(
            text_for_selection=lambda: text,
            screen=s,
            geometry=SimpleNamespace(left=0, right=400),
            os_window_id=1,
        )
        w.drag_thumbnails = partial(Window.drag_thumbnails, w)
        with (
            patch('kitty.window.draw_single_line_of_text', return_value=(b'\0' * 4, 1)) as draw,
            patch('kitty.window.start_drag_with_data') as start,
            patch('kitty.window.set_clipboard_string') as clipboard,
        ):
            for macos in (True, False):
                with self.subTest(macos=macos), patch('kitty.window.is_macos', macos):
                    Window.drag_selection(w)
                    data = start.call_args.args[1]
                    self.ae(data['text/plain'], text.encode('utf-8'))
                    if macos:
                        self.ae(len(data), 1)  # Cocoa creates a separate drag item for each MIME type.
                    else:
                        self.ae(data['text/plain;charset=utf-8'], text.encode('utf-8'))
                    self.ae(start.call_args.args[2:], (((b'\0' * 4, 1, 1),), GLFW_DRAG_OPERATION_COPY))
            preview = draw.call_args.args[1]
            self.assertLess(len(preview), 260)
            self.assertNotIn('\n', preview)
            self.assertNotIn('\t', preview)
            start.side_effect = OSError('drag canceled')
            with patch('kitty.window.log_error') as log:
                Window.drag_selection(w)
                log.assert_called_once()
            text = ''
            start.reset_mock()
            Window.drag_selection(w)
            start.assert_not_called()
            clipboard.assert_not_called()

    def test_selection_drag_paste_policy(self):
        s, _, _ = self.drag_screen()
        for text, bracketed, confirm in (
            ('single line', False, False),
            ('first\nsecond', False, True),
            ('first\nsecond', True, False),
            ('text\x1b[31m', True, True),
        ):
            with self.subTest(text=text, bracketed=bracketed):
                (s.set_mode if bracketed else s.reset_mode)(2004, True)
                pasted = []
                w = SimpleNamespace(destroyed=False, at_prompt=False, screen=s, paste_text=pasted.append)
                w.handle_dangerous_paste_confirmation = partial(Window.handle_dangerous_paste_confirmation, w)
                with patch('kitty.window.get_boss') as boss:
                    Window.paste_with_actions(w, text, from_drop=True)
                    self.ae(boss.return_value.choose.called, confirm)
                    self.ae(pasted, [] if confirm else [text.encode('utf-8')])

    def test_selection_drag_clipped_multicell(self):
        s, ev, drags = self.drag_screen(cols=12, lines=4)
        draw_multicell(s, 'X', scale=3)
        s.cursor_position(4, 1)
        s.linefeed()
        s.scroll(1, True)
        self.select(s, (0, 0), (3, 0))
        s.scroll(1, False)
        # The selected row has left the viewport. The remaining rows of the
        # large character are not highlighted and must not start a text drag.
        self.assertFalse(any(c & 1 for c in s.current_selections()))
        ev(LEFT, x=1, clear_click_queue=True)
        ev(x=1, pixel_x=16)
        self.ae(drags, [])
        ev(LEFT, x=1, is_release=True)

    def test_selection_drag_resumes_rendering(self):
        s, ev, drags = self.drag_screen()
        s.draw('alpha beta gamma')
        self.select(s)
        self.assertTrue(s.pause_rendering(True, 5000))
        ev(LEFT, x=1, clear_click_queue=True)
        # Mouse selection ends synchronized output, including when preserving
        # an existing selection while waiting for the drag threshold.
        self.assertFalse(s.pause_rendering(False))
        ev(x=2)
        self.ae(drags, ['alpha'])
