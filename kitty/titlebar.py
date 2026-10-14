#!/usr/bin/env python
# License: GPLv3 Copyright: 2026, Kovid Goyal <kovid at kovidgoyal.net>

# The titlebar of OS windows on Wayland, drawn here as an image and handed to
# the client side decorations code in glfw, which takes care of the mouse,
# dragging and the window buttons using the clickable regions returned below.

import math
import os
import subprocess
import threading
import time
from collections.abc import Callable
from functools import lru_cache
from typing import TYPE_CHECKING, Any, NamedTuple

if TYPE_CHECKING:
    from PIL import Image, ImageDraw, ImageFont

    from .boss import Boss

# Region ids. The ones below 1000 arrive in Boss.on_csd_toolbar_button(), the
# order of the first seven matches GLFWCSDToolbarButton in glfw3.h
SIDEBAR, NEW_TAB, SPLIT_RIGHT, SPLIT_DOWN, SAVE, WORKSPACES, SETTINGS, GIT, CLAUDE = range(9)
CLOSE, MINIMIZE, MAXIMIZE = 1000, 1001, 1002
FLAG_FOCUSED, FLAG_MAXIMIZED, FLAG_CAN_MAXIMIZE, FLAG_CAN_MINIMIZE = 1, 2, 4, 8


# Palette {{{
class Palette(NamedTuple):
    bg: str = '#121319'
    border: str = '#1f2129'
    control: str = '#171820'
    control_border: str = '#262833'
    hover: str = '#22242e'
    pressed: str = '#2b2d38'
    text: str = '#f2f3f5'
    text2: str = '#c3c6cf'
    muted: str = '#7c8190'
    accent: str = '#ff4fa3'
    accent_bg: str = '#2a1322'
    cyan: str = '#2de2e6'
    cyan_text: str = '#7ffcff'
    cyan_bg: str = '#10262a'
    cyan_border: str = '#1f4a4c'
    green: str = '#5af78e'
    yellow: str = '#f9e05c'


PALETTE = Palette()
CLAUDE_STATES = {  # state -> (label, color)
    'working': ('Claude думает', PALETTE.cyan_text),
    'waiting': ('Claude ждёт ответа', PALETTE.yellow),
    'done': ('Claude готово', PALETTE.green),
    '': ('Claude', PALETTE.cyan_text),
}
# }}}


# Fonts {{{
def font_path(*names: str) -> str:
    for d in (os.path.expanduser('~/.local/share/fonts'), '/usr/share/fonts', '/usr/local/share/fonts'):
        for root, _, files in os.walk(d):
            for name in names:
                if name in files:
                    return os.path.join(root, name)
    return ''


@lru_cache(maxsize=64)
def ui_font(size: int, weight: str = 'Regular') -> 'ImageFont.FreeTypeFont':
    from PIL import ImageFont
    path = font_path(f'Geist-{weight}.ttf', f'AdwaitaSans-{weight}.ttf', 'AdwaitaSans-Regular.ttf', 'Cantarell-VF.otf')
    try:
        return ImageFont.truetype(path, size) if path else ImageFont.load_default(size)
    except OSError:
        return ImageFont.load_default(size)
# }}}


# Git status, refreshed in the background {{{
class GitInfo(NamedTuple):
    branch: str = ''
    changes: int = 0
    ahead: int = 0
    behind: int = 0
    is_repo: bool = False


git_cache: dict[str, tuple[float, GitInfo]] = {}
git_refreshing: set[str] = set()
git_lock = threading.Lock()
GIT_TTL = 3.0


def parse_git_status(output: str) -> GitInfo:
    branch, ahead, behind, changes = '', 0, 0, 0
    for line in output.splitlines():
        if line.startswith('## '):
            head = line[3:]
            branch = head.split('...')[0].split(' ')[0]
            if branch.startswith('No commits yet on '):
                branch = branch[len('No commits yet on '):]
            if '[' in head:
                for part in head[head.index('[') + 1:].rstrip(']').split(', '):
                    kind, _, num = part.partition(' ')
                    if kind == 'ahead' and num.isdigit():
                        ahead = int(num)
                    elif kind == 'behind' and num.isdigit():
                        behind = int(num)
        elif line.strip():
            changes += 1
    return GitInfo(branch, changes, ahead, behind, True)


def refresh_git(cwd: str) -> None:
    try:
        cp = subprocess.run(
            ['git', '-C', cwd, 'status', '--porcelain=v1', '--branch'], capture_output=True, text=True, timeout=3,
            env={**os.environ, 'GIT_OPTIONAL_LOCKS': '0'})
        info = parse_git_status(cp.stdout) if cp.returncode == 0 else GitInfo()
    except Exception:
        info = GitInfo()
    with git_lock:
        git_cache[cwd] = (time.monotonic(), info)
        git_refreshing.discard(cwd)


def git_info(cwd: str) -> GitInfo:
    ' Cached git status of cwd, refreshed in a background thread when stale '
    if not cwd:
        return GitInfo()
    with git_lock:
        ts, info = git_cache.get(cwd, (0., GitInfo()))
        stale = time.monotonic() - ts > GIT_TTL and cwd not in git_refreshing
        if stale:
            git_refreshing.add(cwd)
    if stale:
        threading.Thread(target=refresh_git, args=(cwd,), daemon=True, name='GitStatus').start()
    return info
# }}}


# Toasts: a short message shown in the middle of the titlebar {{{
toasts: dict[int, tuple[str, float]] = {}


def show_toast(os_window_id: int, msg: str, duration: float = 2.5) -> None:
    from .fast_data_types import add_timer, redraw_titlebar
    toasts[os_window_id] = (msg, time.monotonic() + duration)
    redraw_titlebar(os_window_id)
    add_timer(lambda timer_id: redraw_titlebar(os_window_id), duration + 0.05, False)
# }}}


# State of the window that the titlebar shows {{{
class TitlebarState(NamedTuple):
    sidebar_visible: bool = True
    workspace: str = ''
    is_workspace: bool = False
    folder: str = ''
    git: GitInfo = GitInfo()
    claude: str | None = None  # None when no claude runs in the active window, else its state
    toast: str = ''


def state_for_os_window(boss: 'Boss', os_window_id: int) -> TitlebarState:
    from .tab_bar import TabAccessor
    from .workspaces import is_workspace
    tm = boss.os_window_map.get(os_window_id)
    if tm is None:
        return TitlebarState()
    tab = tm.active_tab
    w = tm.active_window
    workspace = (w.created_in_session_name if w else '') or (tab.created_in_session_name if tab else '')
    cwd = (tab.get_cwd_of_active_window() if tab else '') or ''
    folder = TabAccessor(tab.id).active_wd_name if tab else ''
    claude: str | None = None
    if tab is not None and os.path.basename(tab.get_exe_of_active_window() or '') == 'claude':
        from .claude_status import status_for_window
        claude = status_for_window(w.id) if w is not None else ''
    toast = ''
    if (t := toasts.get(os_window_id)) and t[1] > time.monotonic():
        toast = t[0]
    return TitlebarState(
        sidebar_visible=not tm.sidebar_collapsed, workspace=workspace, is_workspace=is_workspace(workspace),
        folder=folder, git=git_info(cwd), claude=claude, toast=toast)
# }}}


# Drawing {{{
class Canvas:
    ' Draws in logical pixels on a supersampled image, so that shapes come out antialiased '

    def __init__(self, width: int, height: int, scale: float, bg: str | tuple[int, int, int, int] = PALETTE.bg, mode: str = 'RGBA'):
        from PIL import Image, ImageDraw
        self.scale = scale
        self.ss = 3 if scale < 1.5 else 2
        self.factor = scale * self.ss
        self.out_size = (width, height)
        # RGB is much faster to downsample than RGBA, use it for anything opaque
        self.img: Image.Image = Image.new(mode, (width * self.ss, height * self.ss), bg)
        self.draw: ImageDraw.ImageDraw = ImageDraw.Draw(self.img)
        self.width = width / scale  # in logical pixels
        self.height = height / scale
        # Text is drawn after downsampling, at the final size: FreeType antialiases it anyway and
        # rendering glyphs at the supersampled size is by far the slowest part of drawing
        self.texts: list[tuple[float, float, str, float, str, str, str]] = []

    def p(self, v: float) -> int:
        return round(v * self.factor)

    def box(self, x: float, y: float, w: float, h: float) -> tuple[int, int, int, int]:
        return self.p(x), self.p(y), self.p(x + w) - 1, self.p(y + h) - 1

    def rounded(self, x: float, y: float, w: float, h: float, r: float, fill: str | None, outline: str | None = None) -> None:
        self.draw.rounded_rectangle(self.box(x, y, w, h), radius=self.p(r), fill=fill, outline=outline, width=max(1, self.p(1)) if outline else 0)

    def circle(self, cx: float, cy: float, r: float, fill: str) -> None:
        self.draw.ellipse((self.p(cx - r), self.p(cy - r), self.p(cx + r), self.p(cy + r)), fill=fill)

    def line(self, points: list[tuple[float, float]], color: str, width: float = 1.5) -> None:
        self.draw.line([(self.p(x), self.p(y)) for x, y in points], fill=color, width=max(1, self.p(width)), joint='curve')

    def font(self, size: float, weight: str = 'Regular') -> 'ImageFont.FreeTypeFont':
        ' The font at the final, not supersampled, size '
        return ui_font(max(1, round(size * self.scale)), weight)

    def text_width(self, text: str, size: float, weight: str = 'Regular') -> float:
        return self.font(size, weight).getlength(text) / self.scale

    def text(self, x: float, cy: float, text: str, size: float, color: str, weight: str = 'Regular', anchor: str = 'lm') -> float:
        self.texts.append((x, cy, text, size, color, weight, anchor))
        return self.text_width(text, size, weight)

    def fit_text(self, text: str, size: float, max_width: float, weight: str = 'Regular') -> str:
        ' Shorten text with an ellipsis so that it fits in max_width '
        if self.text_width(text, size, weight) <= max_width:
            return text
        while text and self.text_width(text + '…', size, weight) > max_width:
            text = text[:-1]
        return text + '…'

    def finish(self) -> 'Image.Image':
        from PIL import Image, ImageDraw
        if self.img.width == self.out_size[0] * self.ss:
            img = self.img.reduce(self.ss)
        else:
            img = self.img.resize(self.out_size, Image.Resampling.BOX)
        if self.texts:
            draw = ImageDraw.Draw(img)
            for x, cy, text, size, color, weight, anchor in self.texts:
                draw.text((round(x * self.scale), round(cy * self.scale)), text, font=self.font(size, weight), fill=color, anchor=anchor)
        return img


# Icons, drawn in a 16x16 box whose top left corner is at x, y
def icon_sidebar(c: Canvas, x: float, y: float, color: str) -> None:
    c.rounded(x + 2, y + 3, 12, 10, 2, None, color)
    c.line([(x + 6.5, y + 3), (x + 6.5, y + 13)], color)


def icon_plus(c: Canvas, x: float, y: float, color: str) -> None:
    c.line([(x + 8, y + 3), (x + 8, y + 13)], color, 1.6)
    c.line([(x + 3, y + 8), (x + 13, y + 8)], color, 1.6)


def icon_split_right(c: Canvas, x: float, y: float, color: str) -> None:
    c.rounded(x + 2, y + 3, 12, 10, 2, None, color)
    c.line([(x + 8, y + 3), (x + 8, y + 13)], color)


def icon_split_down(c: Canvas, x: float, y: float, color: str) -> None:
    c.rounded(x + 2, y + 3, 12, 10, 2, None, color)
    c.line([(x + 2, y + 8), (x + 14, y + 8)], color)


def icon_git(c: Canvas, x: float, y: float, color: str) -> None:
    for cx, cy in ((5, 4), (5, 12), (11, 6)):
        c.draw.ellipse((c.p(x + cx - 1.6), c.p(y + cy - 1.6), c.p(x + cx + 1.6), c.p(y + cy + 1.6)), outline=color, width=max(1, c.p(1.4)))
    c.line([(x + 5, y + 5.6), (x + 5, y + 10.4)], color)
    c.line([(x + 11, y + 7.6), (x + 10.4, y + 9.2), (x + 8.6, y + 10.2), (x + 6.4, y + 11)], color)


def icon_sparkle(c: Canvas, x: float, y: float, color: str) -> None:
    for (x1, y1), (x2, y2) in (((8, 2), (8, 5)), ((8, 11), (8, 14)), ((2, 8), (5, 8)), ((11, 8), (14, 8)),
                               ((3.8, 3.8), (5.8, 5.8)), ((10.2, 10.2), (12.2, 12.2)), ((12.2, 3.8), (10.2, 5.8)), ((5.8, 10.2), (3.8, 12.2))):
        c.line([(x + x1, y + y1), (x + x2, y + y2)], color)


def icon_save(c: Canvas, x: float, y: float, color: str) -> None:
    c.line([(x + 8, y + 2.5), (x + 8, y + 9.5)], color, 1.6)
    c.line([(x + 5, y + 6.8), (x + 8, y + 9.8), (x + 11, y + 6.8)], color, 1.6)
    c.line([(x + 3, y + 10.5), (x + 3, y + 13), (x + 13, y + 13), (x + 13, y + 10.5)], color, 1.6)


def icon_gear(c: Canvas, x: float, y: float, color: str) -> None:
    c.draw.ellipse((c.p(x + 5.6), c.p(y + 5.6), c.p(x + 10.4), c.p(y + 10.4)), outline=color, width=max(1, c.p(1.5)))
    for (x1, y1), (x2, y2) in (((8, 1.8), (8, 3.8)), ((8, 12.2), (8, 14.2)), ((1.8, 8), (3.8, 8)), ((12.2, 8), (14.2, 8)),
                               ((3.6, 3.6), (5, 5)), ((11, 11), (12.4, 12.4)), ((12.4, 3.6), (11, 5)), ((5, 11), (3.6, 12.4))):
        c.line([(x + x1, y + y1), (x + x2, y + y2)], color)


def icon_chevron(c: Canvas, x: float, y: float, color: str) -> None:
    c.line([(x + 3, y + 4.5), (x + 6, y + 7.5), (x + 9, y + 4.5)], color, 1.6)


Regions = list[tuple[int, int, int]]


class Layout(NamedTuple):
    ' Where the groups of controls are, in output pixels, used to recompose the titlebar at a new width '
    left_end: int
    right_start: int
    pill_x: int = -1
    pill_w: int = 0
    margin: int = 0
    dropped_detail: bool = False
    pill_logical_w: float = 0
    scale: float = 1


def pill_position(window_width: float, pill_w: float, scale: float) -> float:
    ' Centered, snapped to whole output pixels so that recomposing gives identical results '
    return math.floor((window_width - pill_w) / 2 * scale) / scale


class Rendered(NamedTuple):
    img: 'Image.Image'
    regions: Regions
    layout: Layout


# The last full render of each OS window, and the last result handed to glfw
base_cache: dict[int, tuple[Any, Rendered]] = {}
output_cache: dict[int, tuple[Any, tuple[bytes, Regions]]] = {}
render_count = 0


def recompose(base: Rendered, width: int) -> tuple['Image.Image', Regions] | None:
    '''
    Build the titlebar for a new width from a full render at another width, by moving its groups
    of controls. This is what happens on every step of an interactive resize, so it must be fast.
    Returns None when the controls do not fit the same way at the new width.
    '''
    img, regions, lo = base
    w0, h = img.size
    if width == w0:
        return img, regions
    if lo.dropped_detail and width > w0:
        return None
    right_w = w0 - lo.right_start
    dx_right = width - w0
    if lo.pill_x > -1:
        # Only recompose while the pill is freely centered, near the other controls it is clamped and is placed differently
        px = round(pill_position(width / lo.scale, lo.pill_logical_w, lo.scale) * lo.scale)
        if px < lo.left_end + 2 * lo.margin or px + lo.pill_w > width - right_w - 2 * lo.margin:
            return None
    elif lo.left_end + right_w > width:
        return None
    # The column just after the left group is plain background (and the bottom border)
    ans = img.crop((lo.left_end, 0, lo.left_end + 1, h)).resize((width, h))
    ans.paste(img.crop((0, 0, lo.left_end, h)), (0, 0))
    ans.paste(img.crop((lo.right_start, 0, w0, h)), (width - right_w, 0))
    new_regions = []
    for left, right, rid in regions:
        dx = 0
        if left >= lo.right_start:
            dx = dx_right
        elif lo.pill_x > -1 and left >= lo.pill_x and right <= lo.pill_x + lo.pill_w:
            dx = px - lo.pill_x
        new_regions.append((left + dx, right + dx, rid))
    if lo.pill_x > -1:
        ans.paste(img.crop((lo.pill_x, 0, lo.pill_x + lo.pill_w, h)), (px, 0))
    return ans, new_regions


def render(boss: 'Boss', os_window_id: int, width: int, height: int, scale: float, hover: int, pressed: int, flags: int) -> tuple[bytes, Regions]:
    ' Render the titlebar, re-using the previous render when only the width changed. '
    st = state_for_os_window(boss, os_window_id)
    key = (st, height, scale, hover, pressed, flags)
    out = output_cache.get(os_window_id)
    if out is not None and out[0] == (key, width):
        return out[1]  # glfw renders both buffers of the titlebar
    global render_count
    start = time.perf_counter()
    composed = None
    base = base_cache.get(os_window_id)
    if base is not None and base[0] == key:
        composed = recompose(base[1], width)
    if composed is None:
        render_count += 1
        rendered = render_uncached(st, width, height, scale, hover, pressed, flags)
        base_cache[os_window_id] = key, rendered
        composed = rendered.img, rendered.regions
    img, regions = composed
    pixels = img.tobytes('raw', 'BGRA')
    if dump := os.environ.get('KITTY_FORK_TITLEBAR_DUMP'):  # for debugging, the titlebar is not part of screenshots
        img.save(dump)
        print(f'titlebar #{render_count} {width}x{height} took {(time.perf_counter() - start) * 1000:.1f}ms', flush=True)
    ans = pixels, regions
    output_cache[os_window_id] = (key, width), ans
    return ans


def render_uncached(st: TitlebarState, width: int, height: int, scale: float, hover: int, pressed: int, flags: int) -> Rendered:
    c = Canvas(width, height, scale)
    P = PALETTE
    focused = bool(flags & FLAG_FOCUSED)
    H = c.height
    cy = H / 2
    regions: list[tuple[int, int, int]] = []

    def region(x: float, w: float, rid: int) -> None:
        regions.append((round(x * scale), round((x + w) * scale), rid))

    def button_bg(rid: int, base: str | None = None) -> str | None:
        if pressed == rid:
            return P.pressed
        if hover == rid:
            return P.hover
        return base

    c.line([(0, H - 0.5), (c.width, H - 0.5)], P.border, 1)

    # Window buttons, macOS style
    x = 16
    group_hovered = hover in (CLOSE, MINIMIZE, MAXIMIZE)
    buttons = [(CLOSE, '#ff5f57', '#4d0000')]
    if flags & FLAG_CAN_MINIMIZE:
        buttons.append((MINIMIZE, '#febc2e', '#5a3c00'))
    if flags & FLAG_CAN_MAXIMIZE:
        buttons.append((MAXIMIZE, '#28c840', '#004d00'))
    for rid, color, glyph in buttons:
        bcx = x + 6.5
        c.circle(bcx, cy, 6.5, color if focused or group_hovered else '#3a3c46')
        if group_hovered:
            if rid == CLOSE:
                c.line([(bcx - 2.6, cy - 2.6), (bcx + 2.6, cy + 2.6)], glyph, 1.3)
                c.line([(bcx - 2.6, cy + 2.6), (bcx + 2.6, cy - 2.6)], glyph, 1.3)
            elif rid == MINIMIZE:
                c.line([(bcx - 3, cy), (bcx + 3, cy)], glyph, 1.4)
            else:
                c.line([(bcx - 3, cy), (bcx + 3, cy)], glyph, 1.3)
                c.line([(bcx, cy - 3), (bcx, cy + 3)], glyph, 1.3)
        region(x - 3, 19, rid)
        x += 21

    def icon_button(x: float, rid: int, draw_icon: Callable[[Canvas, float, float, str], None], active: bool = False, color: str = '') -> float:
        bg = button_bg(rid, P.control if active else None)
        if bg:
            c.rounded(x, cy - 15, 30, 30, 8, bg)
        draw_icon(c, x + 7, cy - 8, color or (P.text if active else P.text2))
        region(x, 30, rid)
        return x + 30

    x += 12
    x = icon_button(x, SIDEBAR, icon_sidebar, active=st.sidebar_visible) + 4
    x = icon_button(x, NEW_TAB, icon_plus)
    left_end = x

    # Right hand side, laid out from the right edge
    right = c.width - 12
    right = icon_button(right - 30, SETTINGS, icon_gear) - 30 - 4
    right = icon_button(right - 30, SAVE, icon_save) - 30 - 10

    def pill(right: float, rid: int, label: str, draw_icon: Callable[[Canvas, float, float, str], None], fg: str, bg: str, border: str,
             badge: str = '', weight: str = 'Medium') -> float:
        tw = c.text_width(label, 13, weight)
        bw = (c.text_width(badge, 11, 'SemiBold') + 10) if badge else 0
        w = 9 + 16 + 7 + tw + (7 + max(18, bw) if badge else 0) + 11
        x = right - w
        if hover == rid or pressed == rid:
            bg = P.pressed if pressed == rid else P.hover
        c.rounded(x, cy - 15, w, 30, 9, bg, border)
        draw_icon(c, x + 9, cy - 8, fg)
        c.text(x + 9 + 16 + 7, cy, label, 13, fg, weight)
        if badge:
            bx = x + 9 + 16 + 7 + tw + 7
            bwidth = max(18, bw)
            c.rounded(bx, cy - 9, bwidth, 18, 9, P.accent)
            c.text(bx + bwidth / 2, cy, badge, 11, '#0b0c10', 'SemiBold', anchor='mm')
        region(x, w, rid)
        return x

    if st.claude is not None:
        label, color = CLAUDE_STATES.get(st.claude, CLAUDE_STATES[''])
        right = pill(right, CLAUDE, label, icon_sparkle, color, P.cyan_bg, P.cyan_border) - 8
    if st.git.is_repo:
        right = pill(right, GIT, 'Git', icon_git, '#e4e6ea', P.control, P.control_border,
                     badge=str(st.git.changes) if st.git.changes else '') - 8

    # Split segmented control
    seg_w = 2 + 30 + 30 + 2
    sx = right - seg_w
    c.rounded(sx, cy - 15, seg_w, 30, 9, P.control, P.control_border)
    for i, (rid, draw_icon) in enumerate(((SPLIT_RIGHT, icon_split_right), (SPLIT_DOWN, icon_split_down))):
        bx = sx + 2 + i * 30
        if bg := button_bg(rid):
            c.rounded(bx, cy - 13, 30, 26, 7, bg)
        draw_icon(c, bx + 7, cy - 8, P.text2)
        region(bx, 30, rid)
    right_start = sx

    # The workspace switcher in the middle
    if st.toast:
        name, detail, dot = st.toast, '', P.green
    else:
        name = st.workspace if st.is_workspace else (st.folder or 'kitty')
        detail = st.git.branch
        dot = P.cyan if st.is_workspace else P.muted
        if st.is_workspace and st.claude in CLAUDE_STATES and st.claude:
            dot = CLAUDE_STATES[st.claude][1]
    name_w = c.text_width(name, 13, 'SemiBold')
    detail_w = c.text_width(detail, 13) if detail else 0
    pw = 12 + 8 + 8 + name_w + (8 + detail_w if detail else 0) + (8 + 12 if not st.toast else 0) + 12
    available = right_start - left_end - 24
    dropped_detail = False
    if pw > available and detail:  # not enough room, drop the branch
        pw -= 8 + detail_w
        detail = ''
        dropped_detail = True
    pill = None
    if pw <= available:
        px = max(left_end + 12, min(pill_position(c.width, pw, scale), right_start - 12 - pw))
        bg = P.pressed if pressed == WORKSPACES else (P.hover if hover == WORKSPACES else P.control)
        c.rounded(px, cy - 15, pw, 30, 9, bg, P.control_border)
        c.circle(px + 16, cy, 4, dot)
        tx = px + 28 + c.text(px + 28, cy, name, 13, P.text, 'SemiBold')
        if detail:
            tx += 8 + c.text(tx + 8, cy, detail, 13, P.muted)
        if not st.toast:
            icon_chevron(c, tx + 8, cy - 6, P.muted)
        if not st.toast:
            region(px, pw, WORKSPACES)
        pill = px, pw

    if not focused:  # dim everything a little, like macOS does for inactive windows
        from PIL import Image
        overlay = Image.new('RGBA', c.img.size, (18, 19, 25, 90))
        c.img.alpha_composite(overlay)
    # the pill moves on resize, so its slice must not touch the groups on either side
    layout = Layout(
        left_end=math.ceil(left_end * scale) + 1, right_start=math.floor(right_start * scale) - 1,
        pill_x=math.floor(pill[0] * scale) if pill else -1, pill_w=math.ceil(pill[1] * scale) + 1 if pill else 0,
        margin=math.ceil(12 * scale) + 1, dropped_detail=dropped_detail, pill_logical_w=pill[1] if pill else 0, scale=scale)
    return Rendered(c.finish(), regions, layout)
# }}}


# Redrawing {{{
pending_redraws: set[int] = set()


def schedule_redraw(os_window_id: int) -> None:
    ' Coalesce redraw requests, the titlebar is redrawn at most once per event loop tick per OS window '
    from .fast_data_types import add_timer, redraw_titlebar
    if os_window_id in pending_redraws:
        return
    pending_redraws.add(os_window_id)

    def do(timer_id: int | None) -> None:
        pending_redraws.discard(os_window_id)
        redraw_titlebar(os_window_id)

    add_timer(do, 0.03, False)


last_rendered: dict[int, Any] = {}


def refresh_all(boss: 'Boss') -> None:
    ' Called periodically: redraws titlebars whose git or claude state changed '
    for os_window_id in boss.os_window_map:
        st = state_for_os_window(boss, os_window_id)
        key = st._replace(toast='')
        if last_rendered.get(os_window_id) != key:
            last_rendered[os_window_id] = key
            schedule_redraw(os_window_id)


def start_refresh_timer(boss: 'Boss') -> None:
    from .fast_data_types import add_timer
    add_timer(lambda timer_id: refresh_all(boss), 1.0, True)
# }}}
