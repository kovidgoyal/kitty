#!/usr/bin/env python
# License: GPL v3 Copyright: 2026, Kovid Goyal <kovid at kovidgoyal.net>

# Panels with a real GUI look (popovers, menus, sheets) drawn as images with
# PIL and shown in an overlay window using the kitty graphics protocol. The
# mouse is reported in pixels, so the panels respond to hovering and clicks
# like ordinary GUI widgets. The overlay shows a blurred snapshot of the
# window it covers behind the panel.

import json
import os
import sys
import tempfile
import time
from base64 import standard_b64encode
from collections.abc import Callable
from typing import TYPE_CHECKING, Any, NamedTuple

from kitty.key_encoding import KeyEvent
from kitty.titlebar import PALETTE, Canvas, icon_plus, icon_save
from kitty.typing_compat import BossType

from ..tui.handler import Handler, result_handler
from ..tui.loop import EventType, Loop, MouseButton, MouseEvent
from ..tui.operations import MouseTracking, clear_screen, set_cursor_visible, set_window_title

if TYPE_CHECKING:
    from PIL import Image

P = PALETTE
BG_IMAGE_ID, PANEL_IMAGE_ID = 1, 2


class Rect(NamedTuple):
    x: float
    y: float
    w: float
    h: float

    def contains(self, x: float, y: float) -> bool:
        return self.x <= x < self.x + self.w and self.y <= y < self.y + self.h


Hit = tuple[Rect, Any]  # a clickable area and the action it triggers


def icon_close(c: Canvas, x: float, y: float, color: str) -> None:
    c.line([(x + 4.5, y + 4.5), (x + 11.5, y + 11.5)], color, 1.6)
    c.line([(x + 4.5, y + 11.5), (x + 11.5, y + 4.5)], color, 1.6)


def icon_trash(c: Canvas, x: float, y: float, color: str) -> None:
    c.line([(x + 3, y + 4.5), (x + 13, y + 4.5)], color, 1.4)
    c.line([(x + 6.5, y + 4.5), (x + 6.5, y + 2.8), (x + 9.5, y + 2.8), (x + 9.5, y + 4.5)], color, 1.4)
    c.line([(x + 4.5, y + 4.5), (x + 5.3, y + 13.2), (x + 10.7, y + 13.2), (x + 11.5, y + 4.5)], color, 1.4)


def icon_search(c: Canvas, x: float, y: float, color: str) -> None:
    c.draw.ellipse((c.p(x + 2.5), c.p(y + 2.5), c.p(x + 10.5), c.p(y + 10.5)), outline=color, width=max(1, c.p(1.5)))
    c.line([(x + 9.5, y + 9.5), (x + 13.5, y + 13.5)], color, 1.6)


def icon_check(c: Canvas, x: float, y: float, color: str) -> None:
    c.line([(x + 3, y + 8.5), (x + 6.5, y + 12), (x + 13, y + 4.5)], color, 1.8)


# Views {{{
class View:
    ' A panel. Coordinates are in logical pixels relative to the panel. '
    width: float = 460
    title: str = ''

    def height(self) -> float:
        raise NotImplementedError()

    def draw(self, c: Canvas, hover: Any) -> list[Hit]:
        raise NotImplementedError()

    def on_click(self, action: Any) -> dict[str, Any] | None:
        ' Return a result to close the panel with it, None to redraw '
        return None

    def on_text(self, text: str) -> dict[str, Any] | None:
        return None

    def on_key(self, key: KeyEvent) -> dict[str, Any] | None:
        return None

    def on_escape(self) -> bool:
        return False


class WorkspacesView(View):
    title = 'Воркспейсы'
    row_h = 54
    max_rows = 7

    def __init__(self, data: dict[str, Any]):
        self.workspaces: list[dict[str, Any]] = data.get('workspaces', [])
        self.on_close_policy: str = data.get('on_close', 'ask')
        self.policies: dict[str, str] = data.get('policies', {})
        self.query = ''
        self.selected = 0
        self.confirm_delete = ''
        self.last_caret_toggle = time.monotonic()

    def matches(self) -> list[dict[str, Any]]:
        q = self.query.strip().lower()
        return [w for w in self.workspaces if q in w['name'].lower()] if q else list(self.workspaces)

    def can_create(self) -> bool:
        q = self.query.strip()
        return bool(q) and all(w['name'].lower() != q.lower() for w in self.workspaces)

    def rows(self) -> list[tuple[str, Any]]:
        ans: list[tuple[str, Any]] = [('workspace', w) for w in self.matches()[:self.max_rows]]
        if self.can_create():
            ans.append(('create', self.query.strip()))
        return ans

    def height(self) -> float:
        n = max(1, len(self.rows()))
        return 16 + 32 + 10 + 38 + 12 + n * self.row_h + 12 + 1 + 56

    def draw(self, c: Canvas, hover: Any) -> list[Hit]:
        hits: list[Hit] = []
        W = self.width
        # header
        c.text(18, 32, self.title, 15, '#ffffff', 'SemiBold')
        close = Rect(W - 16 - 28, 18, 28, 28)
        c.circle(close.x + 14, close.y + 14, 14, P.pressed if hover == 'close' else '#262833')
        icon_close(c, close.x + 6, close.y + 6, P.text2)
        hits.append((close, 'close'))
        # search field
        y = 58
        c.rounded(16, y, W - 32, 38, 10, '#121319', '#2c2e3a')
        icon_search(c, 28, y + 11, P.muted)
        if self.query:
            tw = c.text(52, y + 19, c.fit_text(self.query, 13.5, W - 32 - 52), 13.5, P.text)
            c.line([(52 + tw + 2, y + 10), (52 + tw + 2, y + 28)], P.cyan, 1.5)
        else:
            c.line([(52, y + 10), (52, y + 28)], P.cyan, 1.5)
            c.text(58, y + 19, 'Найти или создать воркспейс…', 13.5, P.muted)
        # rows
        y += 38 + 12
        rows = self.rows()
        if not rows:
            c.text(W / 2, y + self.row_h / 2, 'Пока нет сохранённых воркспейсов', 13, P.muted, anchor='mm')
            y += self.row_h
        for i, (kind, item) in enumerate(rows):
            r = Rect(10, y, W - 20, self.row_h - 4)
            is_hover = hover == ('row', i) or (hover is None and i == self.selected)
            if kind == 'create':
                if is_hover:
                    c.rounded(r.x, r.y, r.w, r.h, 11, P.hover)
                icon_plus(c, 22, r.y + r.h / 2 - 8, P.accent)
                c.text(48, r.y + r.h / 2, c.fit_text(f'Создать «{item}»', 14, r.w - 60, 'Medium'), 14, P.accent, 'Medium')
                hits.append((r, ('create', item)))
                y += self.row_h
                continue
            name = item['name']
            if self.confirm_delete == name:
                c.rounded(r.x, r.y, r.w, r.h, 11, '#2e1417')
                c.text(22, r.y + r.h / 2, c.fit_text(f'Удалить «{name}»?', 13.5, r.w - 190, 'Medium'), 13.5, '#ffb3ba', 'Medium')
                cancel = Rect(r.x + r.w - 10 - 80, r.y + 10, 80, r.h - 20)
                delete = Rect(cancel.x - 8 - 84, r.y + 10, 84, r.h - 20)
                c.rounded(delete.x, delete.y, delete.w, delete.h, 8, '#ff7a85' if hover == ('delete', name) else '#ff4d5e')
                c.text(delete.x + delete.w / 2, delete.y + delete.h / 2, 'Удалить', 13, '#1a0b0d', 'SemiBold', anchor='mm')
                c.rounded(cancel.x, cancel.y, cancel.w, cancel.h, 8, P.pressed if hover == 'cancel_delete' else '#2b2d38')
                c.text(cancel.x + cancel.w / 2, cancel.y + cancel.h / 2, 'Отмена', 13, P.text, 'Medium', anchor='mm')
                hits += [(delete, ('delete', name)), (cancel, 'cancel_delete')]
                y += self.row_h
                continue
            if item.get('current'):
                c.rounded(r.x, r.y, r.w, r.h, 11, '#3a1a2e' if is_hover else P.accent_bg)
            elif is_hover:
                c.rounded(r.x, r.y, r.w, r.h, 11, P.hover)
            dot = P.accent if item.get('current') else (P.cyan if item.get('loaded') else '#4a4f5c')
            c.circle(28, r.y + 18, 4, dot)
            name_color = '#ffffff' if item.get('current') or item.get('loaded') else P.text2
            right_w = 150
            c.text(44, r.y + 18, c.fit_text(name, 14, r.w - 44 - right_w, 'SemiBold' if item.get('current') else 'Medium'), 14, name_color,
                   'SemiBold' if item.get('current') else 'Medium')
            if detail := item.get('detail', ''):
                c.text(44, r.y + 36, c.fit_text(detail, 12, r.w - 44 - 20), 12, P.muted)
            trash = Rect(r.x + r.w - 10 - 30, r.y + 4, 30, 30)
            if is_hover and hover is not None:
                c.rounded(trash.x, trash.y, trash.w, trash.h, 8, '#3a2026' if hover == ('ask_delete', name) else None)
                icon_trash(c, trash.x + 7, trash.y + 7, '#ff7a85' if hover == ('ask_delete', name) else P.muted)
                hits.append((trash, ('ask_delete', name)))
            else:
                status = item.get('status', '')
                if item.get('current'):
                    icon_check(c, r.x + r.w - 10 - 16, r.y + 10, P.accent)
                    status_x = r.x + r.w - 10 - 16 - 8
                else:
                    status_x = r.x + r.w - 12
                c.text(status_x, r.y + 18, status, 12, P.muted, anchor='rm')
            hits.append((r, ('row', i)))
            y += self.row_h
        # footer
        y += 12
        c.line([(16, y), (W - 16, y)], '#262833', 1)
        y += 12
        save = Rect(16, y, 196, 32)
        c.rounded(save.x, save.y, save.w, save.h, 9, P.pressed if hover == 'save_current' else '#20222b', '#2c2e3a')
        icon_save(c, save.x + 10, save.y + 8, P.text2)
        c.text(save.x + 34, save.y + 16, 'Сохранить текущий', 13, P.text, 'Medium')
        hits.append((save, 'save_current'))
        label = 'При закрытии: ' + self.policies.get(self.on_close_policy, self.on_close_policy)
        lw = c.text_width(label, 12.5) + 24
        policy = Rect(W - 16 - lw, y, lw, 32)
        if hover == 'policy':
            c.rounded(policy.x, policy.y, policy.w, policy.h, 9, P.hover)
        c.text(policy.x + policy.w - 12, policy.y + 16, label, 12.5, P.text2 if hover == 'policy' else P.muted, anchor='rm')
        hits.append((policy, 'policy'))
        return hits

    def activate_row(self, i: int) -> dict[str, Any] | None:
        rows = self.rows()
        if not 0 <= i < len(rows):
            return None
        kind, item = rows[i]
        if kind == 'create':
            return {'action': 'new', 'name': item}
        return {'action': 'open', 'name': item['name']}

    def on_click(self, action: Any) -> dict[str, Any] | None:
        self.confirm_delete = '' if action not in ('cancel_delete',) and not (isinstance(action, tuple) and action[0] == 'delete') else self.confirm_delete
        if action == 'close':
            return {'action': 'cancel'}
        if action == 'save_current':
            return {'action': 'save_current'}
        if action == 'policy':
            keys = list(self.policies) or ['ask']
            self.on_close_policy = keys[(keys.index(self.on_close_policy) + 1) % len(keys)] if self.on_close_policy in keys else keys[0]
            from kitty.workspaces import read_state, write_state
            write_state({**read_state(), 'on_close': self.on_close_policy})
            return None
        if action == 'cancel_delete':
            self.confirm_delete = ''
            return None
        if isinstance(action, tuple):
            kind, val = action
            if kind == 'row':
                return self.activate_row(val)
            if kind == 'create':
                return {'action': 'new', 'name': val}
            if kind == 'ask_delete':
                self.confirm_delete = val
                return None
            if kind == 'delete':
                return {'action': 'delete', 'name': val}
        return None

    def on_text(self, text: str) -> dict[str, Any] | None:
        self.query += text
        self.selected = 0
        self.confirm_delete = ''
        return None

    def on_escape(self) -> bool:
        ' Return True if the escape key was used up by the view '
        if self.confirm_delete:
            self.confirm_delete = ''
            return True
        return False

    def on_key(self, key: KeyEvent) -> dict[str, Any] | None:
        n = len(self.rows())
        if self.confirm_delete and key.matches('enter'):
            return {'action': 'delete', 'name': self.confirm_delete}
        if key.matches('backspace'):
            self.query = self.query[:-1]
            self.selected = 0
        elif key.matches('ctrl+backspace') or key.matches('ctrl+u'):
            self.query = ''
            self.selected = 0
        elif key.matches('down') or key.matches('tab'):
            self.selected = (self.selected + 1) % max(1, n)
        elif key.matches('up') or key.matches('shift+tab'):
            self.selected = (self.selected - 1) % max(1, n)
        elif key.matches('enter'):
            return self.activate_row(self.selected)
        elif key.matches('delete'):
            rows = self.rows()
            if 0 <= self.selected < len(rows) and rows[self.selected][0] == 'workspace':
                self.confirm_delete = rows[self.selected][1]['name']
        return None


VIEWS: dict[str, Callable[[dict[str, Any]], View]] = {'workspaces': WorkspacesView}
# }}}


class PixelUI(Handler):
    mouse_tracking = MouseTracking.full

    def __init__(self, view: View, background: str):
        self.view = view
        self.background_path = background
        self.result: dict[str, Any] = {'action': 'cancel'}
        self.hits: list[Hit] = []
        self.hover: Any = None
        self.panel_rect = (0, 0, 0, 0)  # x, y, w, h in pixels of the panel itself, without its shadow
        self.panel_origin = (0, 0)  # where the panel image (with its shadow margin) is placed, in pixels
        self.margin_px = 0
        self.scale = 1.

    # Graphics {{{
    def transmit(self, img: 'Image.Image', image_id: int, x: int, y: int, z: int) -> None:
        cw, ch = self.screen_size.cell_width, self.screen_size.cell_height
        x, y = max(0, x), max(0, y)
        with tempfile.NamedTemporaryFile(prefix='tty-graphics-protocol-', suffix='.rgba', dir='/dev/shm' if os.path.isdir('/dev/shm') else None, delete=False) as f:
            f.write(img.tobytes())
        path = standard_b64encode(f.name.encode()).decode()
        cmd = f'a=T,f=32,t=t,s={img.width},v={img.height},i={image_id},p=1,q=2,C=1,z={z},X={x % cw},Y={y % ch}'
        self.write(f'\x1b[{y // ch + 1};{x // cw + 1}H\x1b_G{cmd};{path}\x1b\\')

    def draw_background(self) -> None:
        from PIL import Image, ImageFilter
        W, H = self.screen_size.width, self.screen_size.height
        img: Image.Image | None = None
        if self.background_path:
            try:
                img = Image.open(self.background_path).convert('RGBA').resize((W, H))
                img = img.filter(ImageFilter.GaussianBlur(10 * self.scale))
            except Exception:
                img = None
            finally:
                try:
                    os.remove(self.background_path)
                except OSError:
                    pass
        if img is None:
            img = Image.new('RGBA', (W, H), (11, 12, 16, 255))
        img.alpha_composite(Image.new('RGBA', (W, H), (8, 9, 12, 140)))
        self.transmit(img, BG_IMAGE_ID, 0, 0, 0)

    def draw_panel(self) -> None:
        from PIL import Image, ImageDraw, ImageFilter
        s = self.scale
        view = self.view
        pw, ph = round(view.width * s), round(view.height() * s)
        m = self.margin_px = round(28 * s)
        W = self.screen_size.width
        x0 = max(0, (W - pw) // 2)
        y0 = round(10 * s)
        self.panel_rect = (x0, y0, pw, ph)
        self.panel_origin = (x0 - m, y0 - m)
        c = Canvas(pw, ph, s, (0, 0, 0, 0))
        c.rounded(0, 0, view.width, view.height(), 16, '#1a1b22', '#2c2e3a')
        self.hits = view.draw(c, self.hover)
        panel = c.finish()
        shadow = Image.new('RGBA', (pw + 2 * m, ph + 2 * m), (0, 0, 0, 0))
        ImageDraw.Draw(shadow).rounded_rectangle((m, m + round(8 * s), m + pw, m + ph + round(8 * s)), radius=round(16 * s), fill=(0, 0, 0, 170))
        shadow = shadow.filter(ImageFilter.GaussianBlur(14 * s))
        shadow.alpha_composite(panel, (m, m))
        self.transmit(shadow, PANEL_IMAGE_ID, x0 - m, y0 - m, 1)
    # }}}

    def initialize(self) -> None:
        self.cmd.set_cursor_visible(False)
        self.write(set_window_title(self.view.title))
        self.scale = max(1., min(3., round(self.screen_size.cell_height / 22 * 4) / 4))
        self.write(clear_screen())
        self.draw_background()
        self.draw_panel()

    def finalize(self) -> None:
        self.write('\x1b_Ga=d,d=A,q=2\x1b\\')
        self.write(set_cursor_visible(True))

    def on_resize(self, new_size: Any) -> None:
        super().on_resize(new_size)
        self.write(clear_screen())
        self.draw_panel()

    def finish(self, result: dict[str, Any] | None) -> None:
        if result is None:
            self.draw_panel()
            return
        self.result = result
        self.quit_loop(0)

    def hit_at(self, ev: MouseEvent) -> Any:
        x0, y0, pw, ph = self.panel_rect
        lx, ly = (ev.pixel_x - x0) / self.scale, (ev.pixel_y - y0) / self.scale
        for rect, action in reversed(self.hits):
            if rect.contains(lx, ly):
                return action
        return None

    def inside_panel(self, ev: MouseEvent) -> bool:
        x0, y0, pw, ph = self.panel_rect
        return x0 <= ev.pixel_x < x0 + pw and y0 <= ev.pixel_y < y0 + ph

    def on_mouse_event(self, ev: MouseEvent) -> None:
        if ev.type is EventType.MOVE:
            action = self.hit_at(ev)
            if action != self.hover:
                self.hover = action
                self.draw_panel()
            return
        if ev.type is EventType.RELEASE and ev.buttons & MouseButton.LEFT:
            if not self.inside_panel(ev):
                self.finish({'action': 'cancel'})
                return
            action = self.hit_at(ev)
            if action is not None:
                self.finish(self.view.on_click(action))

    def on_text(self, text: str, in_bracketed_paste: bool = False) -> None:
        self.finish(self.view.on_text(text))

    def on_key(self, key_event: KeyEvent) -> None:
        if key_event.matches('esc'):
            self.finish(None if self.view.on_escape() else {'action': 'cancel'})
            return
        self.hover = None
        self.finish(self.view.on_key(key_event))

    def on_interrupt(self) -> None:
        self.finish({'action': 'cancel'})

    on_eot = on_interrupt


def main(args: list[str]) -> dict[str, Any]:
    # args: [kitten name, path to a JSON spec: {"view": name, "data": {...}, "background": path to a PNG}]
    with open(args[1]) as f:
        spec = json.load(f)
    try:
        os.remove(args[1])
    except OSError:
        pass
    view = VIEWS[spec['view']](spec.get('data', {}))
    handler = PixelUI(view, spec.get('background', ''))
    Loop().loop(handler)
    return handler.result


@result_handler()
def handle_result(args: list[str], data: dict[str, Any], target_window_id: int, boss: BossType) -> None:
    pass


if __name__ == '__main__':
    print(main(sys.argv))
