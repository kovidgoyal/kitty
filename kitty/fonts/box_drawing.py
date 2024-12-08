#!/usr/bin/env python
# License: GPL v3 Copyright: 2017, Kovid Goyal <kovid at kovidgoyal.net>

#
# NOTE: to add a new glyph, add an entry to the `box_chars` dict, then update
# the functions `font_for_cell` and `box_glyph_id` in `kitty/fonts.c`.
#

import math
from collections.abc import Iterable, Iterator, MutableSequence, Sequence
from functools import lru_cache, wraps
from functools import partial as p
from itertools import repeat
from typing import Any, Callable, Literal, Optional

scale = (0.001, 1., 1.5, 2.)
_dpi = 96.0
BufType = MutableSequence[int]


def set_scale(new_scale: Sequence[float]) -> None:
    global scale
    scale = (new_scale[0], new_scale[1], new_scale[2], new_scale[3])


def thickness(level: int = 1, horizontal: bool = True) -> int:
    pts = scale[level]
    return int(math.ceil(pts * (_dpi / 72.0)))


def draw_hline(buf: BufType, width: int, height: int, x1: int, x2: int, y: int, level: int, supersample_factor: int = 1) -> None:
    ' Draw a horizontal line between [x1, x2) centered at y with the thickness given by level and supersample factor '
    sz = int(supersample_factor * thickness(level=level, horizontal=False))
    start = max(0, y - sz // 2)
    for y in range(start, min(start + sz, height)):
        offset = y * width
        for x in range(x1, x2):
            buf[offset + x] = 255


def draw_vline(buf: BufType, width: int, y1: int, y2: int, x: int, level: int, supersample_factor: float = 1.0) -> None:
    ' Draw a vertical line between [y1, y2) centered at x with the thickness given by level and supersample factor '
    sz = int(supersample_factor * thickness(level=level, horizontal=True))
    start = max(0, x - sz // 2)
    for x in range(start, min(start + sz, width)):
        for y in range(y1, y2):
            buf[x + y * width] = 255


def half_hline(buf: BufType, width: int, height: int, level: int = 1, which: str = 'left', extend_by: int = 0) -> None:
    x1, x2 = (0, extend_by + width // 2) if which == 'left' else (width // 2 - extend_by, width)
    draw_hline(buf, width, height, x1, x2, height // 2, level)


def half_vline(buf: BufType, width: int, height: int, level: int = 1, which: str = 'top', extend_by: int = 0) -> None:
    y1, y2 = (0, height // 2 + extend_by) if which == 'top' else (height // 2 - extend_by, height)
    draw_vline(buf, width, y1, y2, width // 2, level)


def get_holes(sz: int, hole_sz: int, num: int) -> list[tuple[int, ...]]:
    all_holes_use = (num + 1) * hole_sz
    individual_block_size = max(1, (sz - all_holes_use) // (num + 1))
    half_hole_sz = hole_sz // 2
    pos = - half_hole_sz
    holes = []
    while pos < sz:
        left = max(0, pos)
        right = min(sz, pos + hole_sz)
        if right > left:
            holes.append(tuple(range(left, right)))
        pos = right + individual_block_size
    return holes


hole_factor = 8


def add_hholes(buf: BufType, width: int, height: int, level: int = 1, num: int = 1) -> None:
    line_sz = thickness(level=level, horizontal=True)
    hole_sz = width // hole_factor
    start = height // 2 - line_sz // 2
    holes = get_holes(width, hole_sz, num)
    for y in range(start, start + line_sz):
        offset = y * width
        for hole in holes:
            for x in hole:
                buf[offset + x] = 0


def add_vholes(buf: BufType, width: int, height: int, level: int = 1, num: int = 1) -> None:
    line_sz = thickness(level=level, horizontal=False)
    hole_sz = height // hole_factor
    start = width // 2 - line_sz // 2
    holes = get_holes(height, hole_sz, num)
    for x in range(start, start + line_sz):
        for hole in holes:
            for y in hole:
                buf[x + width * y] = 0


def hline(buf: BufType, width: int, height: int, level: int = 1) -> None:
    half_hline(buf, width, height, level=level)
    half_hline(buf, width, height, level=level, which='right')


def vline(buf: BufType, width: int, height: int, level: int = 1) -> None:
    half_vline(buf, width, height, level=level)
    half_vline(buf, width, height, level=level, which='bottom')


def hholes(buf: BufType, width: int, height: int, level: int = 1, num: int = 1) -> None:
    hline(buf, width, height, level=level)
    add_hholes(buf, width, height, level=level, num=num)


def vholes(buf: BufType, width: int, height: int, level: int = 1, num: int = 1) -> None:
    vline(buf, width, height, level=level)
    add_vholes(buf, width, height, level=level, num=num)


def corner(buf: BufType, width: int, height: int, hlevel: int = 1, vlevel: int = 1, which: Optional[str] = None) -> None:
    wh = 'right' if which is not None and which in '┌└' else 'left'
    half_hline(buf, width, height, level=hlevel, which=wh, extend_by=thickness(vlevel, horizontal=True) // 2)
    wv = 'top' if which is not None and which in '└┘' else 'bottom'
    half_vline(buf, width, height, level=vlevel, which=wv)


def vert_t(buf: BufType, width: int, height: int, a: int = 1, b: int = 1, c: int = 1, which: Optional[str] = None) -> None:
    half_vline(buf, width, height, level=a, which='top')
    half_hline(buf, width, height, level=b, which='left' if which == '┤' else 'right')
    half_vline(buf, width, height, level=c, which='bottom')


def horz_t(buf: BufType, width: int, height: int, a: int = 1, b: int = 1, c: int = 1, which: Optional[str] = None) -> None:
    half_hline(buf, width, height, level=a, which='left')
    half_hline(buf, width, height, level=b, which='right')
    half_vline(buf, width, height, level=c, which='top' if which == '┴' else 'bottom')


def cross(buf: BufType, width: int, height: int, a: int = 1, b: int = 1, c: int = 1, d: int = 1) -> None:
    half_hline(buf, width, height, level=a)
    half_hline(buf, width, height, level=b, which='right')
    half_vline(buf, width, height, level=c)
    half_vline(buf, width, height, level=d, which='bottom')


def downsample(src: BufType, dest: BufType, dest_width: int, dest_height: int, factor: int = 4) -> None:
    src_width = factor * dest_width

    def average_intensity_in_src(dest_x: int, dest_y: int) -> int:
        src_y = dest_y * factor
        src_x = dest_x * factor
        total = 0
        for y in range(src_y, src_y + factor):
            offset = src_width * y
            for x in range(src_x, src_x + factor):
                total += src[offset + x]
        return total // (factor * factor)

    for y in range(dest_height):
        offset = dest_width * y
        for x in range(dest_width):
            dest[offset + x] = min(255, dest[offset + x] + average_intensity_in_src(x, y))


class SSByteArray(bytearray):
    supersample_factor = 1


def supersampled(supersample_factor: int = 4) -> Callable[[Callable[..., None]], Callable[..., None]]:
    # Anti-alias the drawing performed by the wrapped function by
    # using supersampling

    def create_wrapper(f: Callable[..., None]) -> Callable[..., None]:
        @wraps(f)
        def supersampled_wrapper(buf: BufType, width: int, height: int, *args: Any, **kw: Any) -> None:
            w, h = supersample_factor * width, supersample_factor * height
            ssbuf = SSByteArray(w * h)
            ssbuf.supersample_factor = supersample_factor
            f(ssbuf, w, h, *args, **kw)
            downsample(ssbuf, buf, width, height, factor=supersample_factor)
        return supersampled_wrapper
    return create_wrapper


def fill_region(buf: BufType, width: int, height: int, xlimits: Iterable[Iterable[float]], inverted: bool = False) -> None:
    full, empty = (0, 255) if inverted else (255, 0)
    for y in range(height):
        offset = y * width
        for x, (upper, lower) in enumerate(xlimits):
            buf[x + offset] = full if upper <= y <= lower else empty


def line_equation(x1: int, y1: int, x2: int, y2: int) -> Callable[[int], float]:
    m = (y2 - y1) / (x2 - x1)
    c = y1 - m * x1

    def y(x: int) -> float:
        return m * x + c

    return y


@supersampled()
def triangle(buf: SSByteArray, width: int, height: int, left: bool = True, inverted: bool = False) -> None:
    ay1, by1, y2 = 0, height - 1, height // 2
    if left:
        x1, x2 = 0, width - 1
    else:
        x1, x2 = width - 1, 0
    uppery = line_equation(x1, ay1, x2, y2)
    lowery = line_equation(x1, by1, x2, y2)
    xlimits = [(uppery(x), lowery(x)) for x in range(width)]
    fill_region(buf, width, height, xlimits, inverted)


@supersampled()
def corner_triangle(buf: SSByteArray, width: int, height: int, corner: str) -> None:
    if corner == 'top-right' or corner == 'bottom-left':
        diagonal_y = line_equation(0, 0, width - 1, height - 1)
        if corner == 'top-right':
            xlimits = [(0., diagonal_y(x)) for x in range(width)]
        elif corner == 'bottom-left':
            xlimits = [(diagonal_y(x), height - 1.) for x in range(width)]
    else:
        diagonal_y = line_equation(width - 1, 0, 0, height - 1)
        if corner == 'top-left':
            xlimits = [(0., diagonal_y(x)) for x in range(width)]
        elif corner == 'bottom-right':
            xlimits = [(diagonal_y(x), height - 1.) for x in range(width)]
    fill_region(buf, width, height, xlimits)


@supersampled()
def half_triangle(buf: SSByteArray, width: int, height: int, which: str = 'left', inverted: bool = False) -> None:
    mid_x, mid_y = width // 2, height // 2
    if which == 'left':
        upper_y = line_equation(0, 0, mid_x, mid_y)
        lower_y = line_equation(0, height - 1, mid_x, mid_y)
        limits = tuple((upper_y(x), lower_y(x)) for x in range(width))
    elif which == 'top':
        first_y = line_equation(0, 0, mid_x, mid_y)
        first = tuple((0, first_y(x)) for x in range(mid_x))
        second_y = line_equation(mid_x, mid_y, width - 1, 0)
        second = tuple((0, second_y(x)) for x in range(mid_x, width))
        limits = first + second
    elif which == 'right':
        upper_y = line_equation(mid_x, mid_y, width - 1, 0)
        lower_y = line_equation(mid_x, mid_y, width - 1, height - 1)
        limits = tuple((upper_y(x), lower_y(x)) for x in range(width))
    elif which == 'bottom':
        first_y = line_equation(0, height - 1, mid_x, mid_y)
        first_ = tuple((first_y(x), height - 1) for x in range(mid_x))
        second_y = line_equation(mid_x, mid_y, width - 1, height - 1)
        second_ = tuple((second_y(x), height - 1) for x in range(mid_x, width))
        limits = first_ + second_
    fill_region(buf, width, height, limits, inverted)


def thick_line(buf: BufType, width: int, height: int, thickness_in_pixels: int, p1: tuple[int, int], p2: tuple[int, int]) -> None:
    if p1[0] > p2[0]:
        p1, p2 = p2, p1
    leq = line_equation(*p1, *p2)
    delta, extra = divmod(thickness_in_pixels, 2)

    for x in range(p1[0], p2[0] + 1):
        if 0 <= x < width:
            y_p = leq(x)
            r = range(int(y_p) - delta, int(y_p) + delta + extra)
            for y in r:
                if 0 <= y < height:
                    buf[x + y * width] = 255


@supersampled()
def cross_line(buf: SSByteArray, width: int, height: int, left: bool = True, level: int = 1) -> None:
    if left:
        p1, p2 = (0, 0), (width - 1, height - 1)
    else:
        p1, p2 = (width - 1, 0), (0, height - 1)
    thick_line(buf, width, height, buf.supersample_factor * thickness(level), p1, p2)


@supersampled()
def cross_shade(buf: SSByteArray, width: int, height: int, rotate: bool = False, num_of_lines: int = 7) -> None:
    line_thickness = max(buf.supersample_factor, width // num_of_lines)
    delta = int(2 * line_thickness)
    y1, y2 = (height, 0) if rotate else (0, height)
    for x in range(0, width, delta):
        thick_line(buf, width, height, line_thickness, (0 + x, y1), (width + x, y2))
        thick_line(buf, width, height, line_thickness, (0 - x, y1), (width - x, y2))


@supersampled()
def half_cross_line(buf: SSByteArray, width: int, height: int, which: str = 'tl', level: int = 1) -> None:
    thickness_in_pixels = thickness(level) * buf.supersample_factor
    my = (height - 1) // 2
    if which == 'tl':
        p1 = 0, 0
        p2 = width - 1, my
    elif which == 'bl':
        p2 = 0, height - 1
        p1 = width - 1, my
    elif which == 'tr':
        p1 = width - 1, 0
        p2 = 0, my
    else:
        p2 = width - 1, height - 1
        p1 = 0, my
    thick_line(buf, width, height, thickness_in_pixels, p1, p2)


@supersampled()
def mid_lines(buf: SSByteArray, width: int, height: int, level: int = 1, pts: Iterable[str] = ('lt',)) -> None:
    mid_x, mid_y = width // 2, height // 2

    def pt_to_coords(p: str) -> tuple[int, int]:
        if p == 'l':
            return 0, mid_y
        if p == 't':
            return mid_x, 0
        if p == 'r':
            return width - 1, mid_y
        if p == 'b':
            return mid_x, height - 1
        raise KeyError(f'Unknown p: {p}')

    for x in pts:
        p1, p2 = map(pt_to_coords, x)
        thick_line(buf, width, height, buf.supersample_factor * thickness(level), p1, p2)


def get_fading_lines(total_length: int, num: int = 1, fade: str = 'right') -> Iterator[tuple[int, int]]:
    if fade == 'left' or fade == 'up':
        d1 = total_length
        dir = -1
    else:
        d1 = 0
        dir = 1

    step = total_length // num

    for i in range(num):
        sz = step * (num - i) // (num + 1)
        if sz >= step - 1 and step > 2:
            sz = step - 2
        d2 = d1 + dir * sz
        yield (d1, d2) if d1 <= d2 else (d2, d1)
        d1 += step * dir


@supersampled()
def fading_hline(buf: SSByteArray, width: int, height: int, level: int = 1, num: int = 1, fade: str = 'right') -> None:
    factor = buf.supersample_factor
    y = (height // 2 // factor) * factor
    for x1, x2 in get_fading_lines(width, num, fade):
        draw_hline(buf, width, height, x1, x2, y, level, supersample_factor = factor)


@supersampled()
def fading_vline(buf: SSByteArray, width: int, height: int, level: int = 1, num: int = 1, fade: str = 'down') -> None:
    factor = buf.supersample_factor
    x = (width // 2 // factor) * factor
    for y1, y2 in get_fading_lines(height, num, fade):
        draw_vline(buf, width, y1, y2, x, level, supersample_factor = factor)


ParameterizedFunc = Callable[[float], float]


def cubic_bezier(start: tuple[int, int], end: tuple[int, int], c1: tuple[int, int], c2: tuple[int, int]) -> tuple[ParameterizedFunc, ParameterizedFunc]:

    def bezier_eq(p0: int, p1: int, p2: int, p3: int) -> ParameterizedFunc:

        def f(t: float) -> float:
            tm1 = 1 - t
            tm1_3 = tm1 * tm1 * tm1
            t_3 = t * t * t
            return tm1_3 * p0 + 3 * t * tm1 * (tm1 * p1 + t * p2) + t_3 * p3
        return f

    bezier_x = bezier_eq(start[0], c1[0], c2[0], end[0])
    bezier_y = bezier_eq(start[1], c1[1], c2[1], end[1])
    return bezier_x, bezier_y


def find_bezier_for_D(width: int, height: int) -> int:
    cx = last_cx = width - 1
    start = (0, 0)
    end = (0, height - 1)
    while True:
        c1 = cx, start[1]
        c2 = cx, end[1]
        bezier_x, bezier_y = cubic_bezier(start, end, c1, c2)
        if bezier_x(0.5) > width - 1:
            return last_cx
        last_cx = cx
        cx += 1


def get_bezier_limits(bezier_x: ParameterizedFunc, bezier_y: ParameterizedFunc) -> Iterator[tuple[float, float]]:
    start_x = int(bezier_x(0))
    max_x = int(bezier_x(0.5))
    last_t, t_limit = 0., 0.5

    def find_t_for_x(x: int, start_t: float) -> float:
        if abs(bezier_x(start_t) - x) < 0.1:
            return start_t
        increment = t_limit - start_t
        if increment <= 0:
            return start_t
        while True:
            q = bezier_x(start_t + increment)
            if (abs(q - x) < 0.1):
                return start_t + increment
            if q > x:
                increment /= 2
                if increment < 1e-6:
                    raise ValueError(f'Failed to find t for x={x}')
            else:
                start_t += increment
                increment = t_limit - start_t
                if increment <= 0:
                    return start_t

    for x in range(start_x, max_x + 1):
        if x > start_x:
            last_t = find_t_for_x(x, last_t)
        upper, lower = bezier_y(last_t), bezier_y(1 - last_t)
        if abs(upper - lower) <= 2:  # avoid pip on end of D
            break
        yield upper, lower


@supersampled()
def D(buf: SSByteArray, width: int, height: int, left: bool = True) -> None:
    c1x = find_bezier_for_D(width, height)
    start = (0, 0)
    end = (0, height - 1)
    c1 = c1x, start[1]
    c2 = c1x, end[1]
    bezier_x, bezier_y = cubic_bezier(start, end, c1, c2)
    xlimits = list(get_bezier_limits(bezier_x, bezier_y))
    if left:
        fill_region(buf, width, height, xlimits)
    else:
        mbuf = bytearray(width * height)
        fill_region(mbuf, width, height, xlimits)
        for y in range(height):
            offset = y * width
            for src_x in range(width):
                dest_x = width - 1 - src_x
                buf[offset + dest_x] = mbuf[offset + src_x]


def draw_parametrized_curve(
    buf: SSByteArray, width: int, height: int, level: int,
    xfunc: ParameterizedFunc, yfunc: ParameterizedFunc
) -> None:
    supersample_factor = buf.supersample_factor
    num_samples = height * 8
    delta, extra = divmod(thickness(level), 2)
    delta *= supersample_factor
    extra *= supersample_factor
    seen = set()
    for i in range(num_samples + 1):
        t = i / num_samples
        p = int(xfunc(t)), int(yfunc(t))
        if p in seen:
            continue
        x_p, y_p = p
        seen.add(p)
        for y in range(y_p - delta, y_p + delta + extra):
            if 0 <= y < height:
                offset = y * width
                for x in range(x_p - delta, x_p + delta + extra):
                    if 0 <= x < width:
                        pos = offset + x
                        buf[pos] = min(255, buf[pos] + 255)


def circle_equations(
    origin_x: int = 0, origin_y: int = 0, radius: float = 10., # radius is in pixels as are origin co-ords
    start_at: float = 0., end_at: float = 360.
) -> tuple[ParameterizedFunc, ParameterizedFunc]:
    conv = math.pi / 180.
    start = start_at * conv
    end = end_at * conv
    amt = end - start

    def x(t: float) -> float:
        return origin_x + radius * math.cos(start + amt * t)

    def y(t: float) -> float:
        return origin_y + radius * math.sin(start + amt * t)

    return x, y


def rectircle_equations(
    cell_width: int, cell_height: int, supersample_factor: int,
    which: str = '╭'
) -> tuple[ParameterizedFunc, ParameterizedFunc]:
    '''
    Return two functions, x(t) and y(t) that map the parameter t which must be
    in the range [0, 1] to x and y coordinates in the cell. The rectircle equation
    we use is:

    (|x| / a) ^ (2a / r) + (|y| / a) ^ (2b / r) = 1

    where 2a = width, 2b = height and r is radius

    The entire rectircle fits in four cells, each cell being one quadrant
    of the full rectircle and the origin being the center of the rectircle.
    The functions we return do the mapping for the specified cell.
    ╭╮
    ╰╯
    See https://math.stackexchange.com/questions/1649714
    '''
    a = ((cell_width // supersample_factor) // 2) * supersample_factor
    b = ((cell_height // supersample_factor) // 2) * supersample_factor
    radius = cell_width / 2
    yexp = cell_height / radius
    xexp = radius / cell_width
    pow = math.pow
    left_quadrants, lower_quadrants = {'╭': (True, False), '╮': (False, False), '╰': (True, True), '╯': (False, True)}[which]
    cell_width_is_odd = (cell_width // supersample_factor) % 2
    adjust_x = cell_width_is_odd * supersample_factor

    if lower_quadrants:
        def y(t: float) -> float:  # 0 -> top of cell, 1 -> middle of cell
            return t * b
    else:
        def y(t: float) -> float:  # 0 -> bottom of cell, 1 -> middle of cell
            return (2 - t) * b

    # x(t). To get this we first need |y(t)|/b. This is just t since as t goes
    # from 0 to 1 y goes from either 0 to b or 0 to -b
    if left_quadrants:
        def x(t: float) -> float:
            xterm = 1 - pow(t, yexp)
            return math.floor(cell_width - abs(a * pow(xterm, xexp)) - adjust_x)
    else:
        def x(t: float) -> float:
            xterm = 1 - pow(t, yexp)
            return math.ceil(abs(a * pow(xterm, xexp)))

    return x, y


@supersampled()
def rounded_corner(buf: SSByteArray, width: int, height: int, level: int = 1, which: str = '╭') -> None:
    xfunc, yfunc = rectircle_equations(width, height, buf.supersample_factor, which)
    draw_parametrized_curve(buf, width, height, level, xfunc, yfunc)


@supersampled()
def rounded_separator(buf: SSByteArray, width: int, height: int, level: int = 1, left: bool = True) -> None:
    gap = thickness(level) * buf.supersample_factor
    c1x = find_bezier_for_D(width - gap, height)
    start = (0, 0)
    end = (0, height - 1)
    c1 = c1x, start[1]
    c2 = c1x, end[1]
    bezier_x, bezier_y = cubic_bezier(start, end, c1, c2)
    if left:
        draw_parametrized_curve(buf, width, height, level, bezier_x, bezier_y)
    else:
        mbuf = SSByteArray(width * height)
        mbuf.supersample_factor = buf.supersample_factor
        draw_parametrized_curve(mbuf, width, height, level, bezier_x, bezier_y)
        for y in range(height):
            offset = y * width
            for src_x in range(width):
                dest_x = width - 1 - src_x
                buf[offset + dest_x] = mbuf[offset + src_x]


@supersampled()
def spinner(buf: SSByteArray, width: int, height: int, level: int = 1, start: float = 0, end: float = 360) -> None:
    w, h = width // 2, height // 2
    radius = min(w, h) - int(thickness(level) * buf.supersample_factor) // 2
    arc_x, arc_y = circle_equations(w, h, radius, start_at=start, end_at=end)
    draw_parametrized_curve(buf, width, height, level, arc_x, arc_y)


def draw_circle(buf: SSByteArray, width: int, height: int, scale: float = 1.0, gap: int = 0, invert: bool = False) -> None:
    w, h = width // 2, height // 2
    radius = int(scale * min(w, h) - gap / 2)
    fill = 0 if invert else 255
    limit = radius * radius
    for y in range(height):
        for x in range(width):
            xw, yh = x - w, y - h
            if xw * xw + yh * yh <= limit:
                buf[y * width + x] = fill


@supersampled()
def draw_filled_circle(buf: SSByteArray, width: int, height: int, level: int = 1) -> None:
    draw_circle(buf, width, height)


@supersampled()
def draw_fish_eye(buf: SSByteArray, width: int, height: int, level: int = 0) -> None:
    w, h = width // 2, height // 2
    line_width = int(thickness(level) * buf.supersample_factor) // 2
    radius = min(w, h) - line_width
    arc_x, arc_y = circle_equations(w, h, radius, start_at=0, end_at=360)
    draw_parametrized_curve(buf, width, height, level, arc_x, arc_y)
    gap = radius - radius // 10
    draw_circle(buf, width, height, gap=gap)


@supersampled()
def commit(buf: SSByteArray, width: int, height: int, level: int = 1, scale: float = 0.9, lines: list[str] = [], solid: bool = True) -> None:
    ' Draw a circular commit with the given scale. Commits can either be solid or hollow and can have vertical, horizontal, up, down, left, or right line(s) '

    factor = buf.supersample_factor
    # Round half width/height to supersample factor to avoid misalignment with non-supersampled lines
    hwidth, hheight = factor * (width // 2 // factor), factor * (height // 2 // factor)

    for line in lines:
        if line == 'horizontal' or line == 'right':
            draw_hline(buf, width, height, hwidth, width, hheight, level, supersample_factor=factor)
        if line == 'horizontal' or line == 'left':
            draw_hline(buf, width, height, 0, hwidth, hheight, level, supersample_factor=factor)
        if line == 'vertical' or line == 'down':
            draw_vline(buf, width, hheight, height, hwidth, level, supersample_factor=factor)
        if line == 'vertical' or line == 'up':
            draw_vline(buf, width, 0, hheight, hwidth, level, supersample_factor=factor)

    draw_circle(buf, width, height, scale=scale)
    if not solid:
        draw_circle(buf, width, height, scale=scale, gap=thickness(level) * factor, invert=True)


def half_dhline(buf: BufType, width: int, height: int, level: int = 1, which: str = 'left', only: Optional[str] = None) -> tuple[int, int]:
    x1, x2 = (0, width // 2) if which == 'left' else (width // 2, width)
    gap = thickness(level + 1, horizontal=False)
    if only != 'bottom':
        draw_hline(buf, width, height, x1, x2, height // 2 - gap, level)
    if only != 'top':
        draw_hline(buf, width, height, x1, x2, height // 2 + gap, level)
    return height // 2 - gap, height // 2 + gap


def half_dvline(buf: BufType, width: int, height: int, level: int = 1, which: str = 'top', only: Optional[str] = None) -> tuple[int, int]:
    y1, y2 = (0, height // 2) if which == 'top' else (height // 2, height)
    gap = thickness(level + 1, horizontal=True)
    if only != 'right':
        draw_vline(buf, width, y1, y2, width // 2 - gap, level)
    if only != 'left':
        draw_vline(buf, width, y1, y2, width // 2 + gap, level)
    return width // 2 - gap, width // 2 + gap


def dvline(buf: BufType, width: int, height: int, only: Optional[str] = None, level: int = 1) -> tuple[int, int]:
    half_dvline(buf, width, height, only=only, level=level)
    return half_dvline(buf, width, height, only=only, which='bottom', level=level)


def dhline(buf: BufType, width: int, height: int, only: Optional[str] = None, level: int = 1) -> tuple[int, int]:
    half_dhline(buf, width, height, only=only, level=level)
    return half_dhline(buf, width, height, only=only, which='bottom', level=level)


def dvcorner(buf: BufType, width: int, height: int, level: int = 1, which: str = '╒') -> None:
    hw = 'right' if which in '╒╘' else 'left'
    half_dhline(buf, width, height, which=hw)
    vw = 'top' if which in '╘╛' else 'bottom'
    gap = thickness(level + 1, horizontal=False)
    half_vline(buf, width, height, which=vw, extend_by=gap // 2 + thickness(level, horizontal=False))


def dhcorner(buf: BufType, width: int, height: int, level: int = 1, which: str = '╓') -> None:
    vw = 'top' if which in '╙╜' else 'bottom'
    half_dvline(buf, width, height, which=vw)
    hw = 'right' if which in '╓╙' else 'left'
    gap = thickness(level + 1, horizontal=True)
    half_hline(buf, width, height, which=hw, extend_by=gap // 2 + thickness(level, horizontal=True))


def dcorner(buf: BufType, width: int, height: int, level: int = 1, which: str = '╔') -> None:
    hw = 'right' if which in '╔╚' else 'left'
    vw = 'top' if which in '╚╝' else 'bottom'
    hgap = thickness(level + 1, horizontal=False)
    vgap = thickness(level + 1, horizontal=True)
    x1, x2 = (0, width // 2) if hw == 'left' else (width // 2, width)
    ydelta = hgap if vw == 'top' else -hgap
    if hw == 'left':
        x2 += vgap
    else:
        x1 -= vgap
    draw_hline(buf, width, height, x1, x2, height // 2 + ydelta, level)
    if hw == 'left':
        x2 -= 2 * vgap
    else:
        x1 += 2 * vgap
    draw_hline(buf, width, height, x1, x2, height // 2 - ydelta, level)
    y1, y2 = (0, height // 2) if vw == 'top' else (height // 2, height)
    xdelta = vgap if hw == 'right' else -vgap
    yd = thickness(level, horizontal=True) // 2
    if vw == 'top':
        y2 += hgap + yd
    else:
        y1 -= hgap + yd
    draw_vline(buf, width, y1, y2, width // 2 - xdelta, level)
    if vw == 'top':
        y2 -= 2 * hgap
    else:
        y1 += 2 * hgap
    draw_vline(buf, width, y1, y2, width // 2 + xdelta, level)


def dpip(buf: BufType, width: int, height: int, level: int = 1, which: str = '╟') -> None:
    if which in '╟╢':
        left, right = dvline(buf, width, height)
        x1, x2 = (0, left) if which == '╢' else (right, width)
        draw_hline(buf, width, height, x1, x2, height // 2, level)
    else:
        top, bottom = dhline(buf, width, height)
        y1, y2 = (0, top) if which == '╧' else (bottom, height)
        draw_vline(buf, width, y1, y2, width // 2, level)


def inner_corner(buf: BufType, width: int, height: int, which: str = 'tl', level: int = 1) -> None:
    hgap = thickness(level + 1, horizontal=True)
    vgap = thickness(level + 1, horizontal=False)
    vthick = thickness(level, horizontal=True) // 2
    x1, x2 = (0, width // 2 - hgap + vthick + 1) if 'l' in which else (width // 2 + hgap - vthick, width)
    yd = -1 if 't' in which else 1
    draw_hline(buf, width, height, x1, x2, height // 2 + (yd * vgap), level)
    y1, y2 = (0, height // 2 - vgap) if 't' in which else (height // 2 + vgap, height)
    xd = -1 if 'l' in which else 1
    draw_vline(buf, width, y1, y2, width // 2 + (xd * hgap), level)


def shade(
    buf: BufType, width: int, height: int, light: bool = False, invert: bool = False, which_half: str = '', fill_blank: bool = False,
    xnum: int = 12, ynum: int = 0
) -> None:

    square_width = max(1, width // xnum)
    square_height = max(1, (height // ynum) if ynum else square_width)
    number_of_rows = height // square_height
    number_of_cols = width // square_width

    # Make sure the parity is correct
    # (except when that would cause division by zero)
    if number_of_cols > 1 and number_of_cols % 2 != xnum % 2:
        number_of_cols -= 1
    if number_of_rows > 1 and number_of_rows % 2 != ynum % 2:
        number_of_rows -= 1

    # Calculate how much space remains unused, and how frequently
    # to insert an extra column/row to fill all of it
    excess_cols = width - (square_width * number_of_cols)
    square_width_extension = excess_cols / number_of_cols

    excess_rows = height - (square_height * number_of_rows)
    square_height_extension = excess_rows / number_of_rows

    rows = range(number_of_rows)
    cols = range(number_of_cols)
    if which_half == 'top':
        rows = range(number_of_rows // 2)
        square_height_extension *= 2   # this is to remove gaps between half-filled characters
    elif which_half == 'bottom':
        rows = range(number_of_rows // 2, number_of_rows)
        square_height_extension *= 2
    elif which_half == 'left':
        cols = range(number_of_cols // 2)
        square_width_extension *= 2
    elif which_half == 'right':
        cols = range(number_of_cols // 2, number_of_cols)
        square_width_extension *= 2

    extra_row = False
    ey, old_ey, drawn_rows = 0, 0, 0

    for r in rows:
        # Keep track of how much extra height has accumulated,
        # and add an extra row at every passed integer, including 0
        old_ey = ey
        ey = math.ceil(drawn_rows * square_height_extension)
        extra_row = ey != old_ey

        drawn_rows += 1

        extra_col = False
        ex, old_ex, drawn_cols = 0, 0, 0

        for c in cols:
            old_ex = ex
            ex = math.ceil(drawn_cols * square_width_extension)
            extra_col = ex != old_ex

            drawn_cols += 1

            # Fill extra rows with semi-transparent pixels that match the pattern
            if extra_row:
                y = r * square_height + old_ey
                offset = width * y
                for xc in range(square_width):
                    x = c * square_width + xc + ex
                    if light:
                        if invert:
                            buf[offset + x] = 255 if c % 2 else 70
                        else:
                            buf[offset + x] = 0 if c % 2 else 70
                    else:
                        buf[offset + x] = 120 if c % 2 == invert else 30
            # Do the same for the extra columns
            if extra_col:
                x = c * square_width + old_ex
                for yr in range(square_height):
                    y = r * square_height + yr + ey
                    offset = width * y
                    if light:
                        if invert:
                            buf[offset + x] = 255 if r % 2 else 70
                        else:
                            buf[offset + x] = 0 if r % 2 else 70
                    else:
                        buf[offset + x] = 120 if r % 2 == invert else 30
            # And in case they intersect, set the corner pixel too
            if extra_row and extra_col:
                x = c * square_width + old_ex
                y = r * square_height + old_ey
                offset = width * y
                buf[offset + x] = 50

            # Blank space
            if invert ^ ((r % 2 != c % 2) or (light and r % 2 == 1)):
                continue

            # Fill the square
            for yr in range(square_height):
                y = r * square_height + yr + ey
                offset = width * y
                for xc in range(square_width):
                    x = c * square_width + xc + ex
                    buf[offset + x] = 255

    if not fill_blank:
        return
    if which_half == 'bottom':
        rows = range(height//2)
        cols = range(width)
    elif which_half == 'top':
        rows = range(height//2 - 1, height)
        cols = range(width)
    elif which_half == 'right':
        cols = range(width // 2)
        rows = range(height)
    elif which_half == 'left':
        cols = range(width // 2 - 1, width)
        rows = range(height)

    for r in rows:
        off = r * width
        for c in cols:
            buf[off + c] = 255


def mask(
    mask_func: Callable[[BufType, int, int], None], buf: BufType, width: int, height: int,
) -> None:
    m = bytearray(width * height)
    mask_func(m, width, height)
    for y in range(height):
        offset = y * width
        for x in range(width):
            p = offset + x
            buf[p] = int(255.0 * (buf[p] / 255.0 * m[p] / 255.0))


def quad(buf: BufType, width: int, height: int, x: int = 0, y: int = 0) -> None:
    num_cols = width // 2
    left = x * num_cols
    right = width if x else num_cols
    num_rows = height // 2
    top = y * num_rows
    bottom = height if y else num_rows
    for r in range(top, bottom):
        off = r * width
        for c in range(left, right):
            buf[off + c] = 255


def sextant(buf: BufType, width: int, height: int, level: int = 1, which: int = 0) -> None:

    def draw_sextant(row: int = 0, col: int = 0) -> None:
        if row == 0:
            y_start, y_end = 0, height // 3
        elif row == 1:
            y_start, y_end = height // 3, 2 * height // 3
        else:
            y_start, y_end = 2 * height // 3, height
        if col == 0:
            x_start, x_end = 0, width // 2
        else:
            x_start, x_end = width // 2, width
        for r in range(y_start, y_end):
            off = r * width
            for c in range(x_start, x_end):
                buf[c + off] = 255

    def add_row(q: int, r: int) -> None:
        if q & 1:
            draw_sextant(r)
        if q & 2:
            draw_sextant(r, col=1)

    add_row(which % 4, 0)
    add_row(which // 4, 1)
    add_row(which // 16, 2)


@supersampled()
def smooth_mosaic(
    buf: SSByteArray, width: int, height: int, level: int = 1,
    lower: bool = True, a: tuple[float, float] = (0, 0), b: tuple[float, float] = (0, 0)
) -> None:
    ax, ay = int(a[0] * (width - 1)), int(a[1] * (height - 1))
    bx, by = int(b[0] * (width - 1)), int(b[1] * (height - 1))
    line = line_equation(ax, ay, bx, by)

    def lower_condition(x: int, y: int) -> bool:
        return y >= line(x)

    def upper_condition(x: int, y: int) -> bool:
        return y <= line(x)

    condition = lower_condition if lower else upper_condition
    for y in range(height):
        offset = width * y
        for x in range(width):
            if condition(x, y):
                buf[offset + x] = 255


def eight_range(size: int, which: int) -> range:
    thickness = max(1, size // 8)
    block = thickness * 8
    if block == size:
        return range(thickness * which, thickness * (which + 1))
    if block > size:
        start = min(which * thickness, size - thickness)
        return range(start, start + thickness)
    extra = size - block
    thicknesses = list(repeat(thickness, 8))
    for i in (3, 4, 2, 5, 6, 1, 7, 0):  # ensures the thickness of first and last are least likely to be changed
        if not extra:
            break
        extra -= 1
        thicknesses[i] += 1
    pos = sum(thicknesses[:which])
    return range(pos, pos + thicknesses[which])


def eight_bar(buf: BufType, width: int, height: int, level: int = 1, which: int = 0, horizontal: bool = False) -> None:
    if horizontal:
        x_range = range(0, width)
        y_range = eight_range(height, which)
    else:
        y_range = range(0, height)
        x_range = eight_range(width, which)
    for y in y_range:
        offset = y * width
        for x in x_range:
            buf[offset + x] = 255


def eight_block(buf: BufType, width: int, height: int, level: int = 1, which: tuple[int, ...] = (0,), horizontal: bool = False) -> None:
    for x in which:
        eight_bar(buf, width, height, level, x, horizontal)


def frame(buf: BufType, width: int, height: int, edges: tuple[Literal['l', 'r', 't', 'b'], ...] = ('l', 'r', 't', 'b'), level: int = 0) -> None:
    h = thickness(level=level, horizontal=True)
    v = thickness(level=level, horizontal=False)

    def line(x1: int, x2: int, y1: int, y2: int) -> None:
        for y in range(y1, y2):
            offset = y * width
            for x in range(x1, x2):
                buf[x + offset] = 255

    def hline(y1: int, y2: int) -> None:
        line(0, width, y1, y2)

    def vline(x1: int, x2: int) -> None:
        line(x1, x2, 0, height)

    if 't' in edges:
        hline(0, h + 1)
    if 'b' in edges:
        hline(height - h - 1, height)
    if 'l' in edges:
        vline(0, v + 1)
    if 'r' in edges:
        vline(width - v - 1, width)


def progress_bar(buf: BufType, width: int, height: int, which: Literal['l', 'm', 'r'] = 'l', filled: bool = False, level: int = 1, gap_factor: int = 3) -> None:
    if which == 'l':
        frame(buf, width, height, edges=('l', 't', 'b'), level=level)
    elif which == 'm':
        frame(buf, width, height, edges=('t', 'b'), level=level)
    else:
        frame(buf, width, height, edges=('r', 't', 'b'), level=level)
    if not filled:
        return
    h = thickness(level=level, horizontal=True)
    v = thickness(level=level, horizontal=False)
    y1 = gap_factor * h
    y2 = height - gap_factor*h
    if which == 'l':
        x1, x2 = gap_factor * v, width
    elif which == 'm':
        x1, x2 = 0, width
    else:
        x1, x2 = 0, width - gap_factor*v
    for y in range(y1, y2):
        offset = y * width
        for x in range(x1, x2):
            buf[x + offset] = 255


@lru_cache(maxsize=64)
def distribute_dots(available_space: int, num_of_dots: int) -> tuple[tuple[int, ...], int]:
    dot_size = max(1, available_space // (2 * num_of_dots))
    extra = available_space - 2 * num_of_dots * dot_size
    gaps = list(repeat(dot_size, num_of_dots))
    if extra > 0:
        idx = 0
        while extra > 0:
            gaps[idx] += 1
            idx = (idx + 1) % len(gaps)
            extra -= 1
    gaps[0] //= 2
    summed_gaps = tuple(sum(gaps[:i + 1]) for i in range(len(gaps)))
    return summed_gaps, dot_size


def braille_dot(buf: BufType, width: int, height: int, col: int, row: int) -> None:
    x_gaps, dot_width = distribute_dots(width, 2)
    y_gaps, dot_height = distribute_dots(height, 4)
    x_start = x_gaps[col] + col * dot_width
    y_start = y_gaps[row] + row * dot_height
    if y_start < height and x_start < width:
        for y in range(y_start, min(height, y_start + dot_height)):
            offset = y * width
            for x in range(x_start, min(width, x_start + dot_width)):
                buf[offset + x] = 255


def braille(buf: BufType, width: int, height: int, which: int = 0) -> None:
    if not which:
        return
    for i, x in enumerate(reversed(bin(which)[2:])):
        if x == '1':
            q = i + 1
            col = 0 if q in (1, 2, 3, 7) else 1
            row = 0 if q in (1, 4) else 1 if q in (2, 5) else 2 if q in (3, 6) else 3
            braille_dot(buf, width, height, col, row)


box_chars: dict[str, list[Callable[[BufType, int, int], Any]]] = {
    '─': [hline],
    '━': [p(hline, level=3)],
    '│': [vline],
    '┃': [p(vline, level=3)],
    '╌': [hholes],
    '╍': [p(hholes, level=3)],
    '┄': [p(hholes, num=2)],
    '┅': [p(hholes, num=2, level=3)],
    '┈': [p(hholes, num=3)],
    '┉': [p(hholes, num=3, level=3)],
    '╎': [vholes],
    '╏': [p(vholes, level=3)],
    '┆': [p(vholes, num=2)],
    '┇': [p(vholes, num=2, level=3)],
    '┊': [p(vholes, num=3)],
    '┋': [p(vholes, num=3, level=3)],
    '╴': [half_hline],
    '╵': [half_vline],
    '╶': [p(half_hline, which='right')],
    '╷': [p(half_vline, which='bottom')],
    '╸': [p(half_hline, level=3)],
    '╹': [p(half_vline, level=3)],
    '╺': [p(half_hline, which='right', level=3)],
    '╻': [p(half_vline, which='bottom', level=3)],
    '╼': [half_hline, p(half_hline, level=3, which='right')],
    '╽': [half_vline, p(half_vline, level=3, which='bottom')],
    '╾': [p(half_hline, level=3), p(half_hline, which='right')],
    '╿': [p(half_vline, level=3), p(half_vline, which='bottom')],
    '': [triangle],
    '': [p(triangle, inverted=True)],
    '': [p(half_cross_line, which='tl'), p(half_cross_line, which='bl')],
    '': [p(triangle, left=False)],
    '': [p(triangle, left=False, inverted=True)],
    '': [p(half_cross_line, which='tr'), p(half_cross_line, which='br')],
    '': [D],
    '◗': [D],
    '': [rounded_separator],
    '': [p(D, left=False)],
    '◖': [p(D, left=False)],
    '': [p(rounded_separator, left=False)],
    '': [p(corner_triangle, corner='bottom-left')],
    '◣': [p(corner_triangle, corner='bottom-left')],
    '': [cross_line],
    '': [p(corner_triangle, corner='bottom-right')],
    '◢': [p(corner_triangle, corner='bottom-right')],
    '': [p(cross_line, left=False)],
    '': [p(corner_triangle, corner='top-left')],
    '◤': [p(corner_triangle, corner='top-left')],
    '': [p(cross_line, left=False)],
    '': [p(corner_triangle, corner='top-right')],
    '◥': [p(corner_triangle, corner='top-right')],
    '': [cross_line],
    '': [p(progress_bar, which='l')],
    '': [p(progress_bar, which='m')],
    '': [p(progress_bar, which='r')],
    '': [p(progress_bar, which='l', filled=True)],
    '': [p(progress_bar, which='m', filled=True)],
    '': [p(progress_bar, which='r', filled=True)],
    '': [p(spinner, start=235, end=305)],
    '': [p(spinner, start=270, end=390)],
    '': [p(spinner, start=315, end=470)],
    '': [p(spinner, start=360, end=540)],
    '': [p(spinner, start=80, end=220)],
    '': [p(spinner, start=170, end=270)],
    '○': [p(spinner, start=0, end=360, level=0)],    # circle
    '●': [draw_filled_circle],
    '◉': [draw_fish_eye],
    '◜': [p(spinner, start=180, end=270)],  # upper-left
    '◝': [p(spinner, start=270, end=360)],  # upper-right
    '◞': [p(spinner, start=360, end=450)],  # lower-right
    '◟': [p(spinner, start=450, end=540)],  # lower-left
    '◠': [p(spinner, start=180, end=360)],  # upper-half
    '◡': [p(spinner, start=0, end=180)],    # lower-half
    '═': [dhline],
    '║': [dvline],

    '╞': [vline, p(half_dhline, which='right')],

    '╡': [vline, half_dhline],

    '╥': [hline, p(half_dvline, which='bottom')],

    '╨': [hline, half_dvline],

    '╪': [vline, half_dhline, p(half_dhline, which='right')],

    '╫': [hline, half_dvline, p(half_dvline, which='bottom')],

    '╬': [p(inner_corner, which=x) for x in 'tl tr bl br'.split()],

    '╠': [p(inner_corner, which='tr'), p(inner_corner, which='br'), p(dvline, only='left')],

    '╣': [p(inner_corner, which='tl'), p(inner_corner, which='bl'), p(dvline, only='right')],

    '╦': [p(inner_corner, which='bl'), p(inner_corner, which='br'), p(dhline, only='top')],

    '╩': [p(inner_corner, which='tl'), p(inner_corner, which='tr'), p(dhline, only='bottom')],

    '╱': [p(cross_line, left=False)],
    '╲': [cross_line],
    '╳': [cross_line, p(cross_line, left=False)],
    '▀': [p(eight_block, horizontal=True, which=(0, 1, 2, 3))],
    '▁': [p(eight_bar, which=7, horizontal=True)],
    '▂': [p(eight_block, horizontal=True, which=(6, 7))],
    '▃': [p(eight_block, horizontal=True, which=(5, 6, 7))],
    '▄': [p(eight_block, horizontal=True, which=(4, 5, 6, 7))],
    '▅': [p(eight_block, horizontal=True, which=(3, 4, 5, 6, 7))],
    '▆': [p(eight_block, horizontal=True, which=(2, 3, 4, 5, 6, 7))],
    '▇': [p(eight_block, horizontal=True, which=(1, 2, 3, 4, 5, 6, 7))],
    '█': [p(eight_block, horizontal=True, which=(0, 1, 2, 3, 4, 5, 6, 7))],
    '▉': [p(eight_block, which=(0, 1, 2, 3, 4, 5, 6))],
    '▊': [p(eight_block, which=(0, 1, 2, 3, 4, 5))],
    '▋': [p(eight_block, which=(0, 1, 2, 3, 4))],
    '▌': [p(eight_block, which=(0, 1, 2, 3))],
    '▍': [p(eight_block, which=(0, 1, 2))],
    '▎': [p(eight_block, which=(0, 1))],
    '▏': [p(eight_bar)],
    '▐': [p(eight_block, which=(4, 5, 6, 7))],

    '░': [p(shade, light=True)],
    '▒': [shade],
    '▓': [p(shade, light=True, invert=True)],
    '🮌': [p(shade, which_half='left')],
    '🮍': [p(shade, which_half='right')],
    '🮎': [p(shade, which_half='top')],
    '🮏': [p(shade, which_half='bottom')],
    '🮐': [p(shade, invert=True)],
    '🮑': [p(shade, which_half='bottom', invert=True, fill_blank=True)],
    '🮒': [p(shade, which_half='top', invert=True, fill_blank=True)],
    '🮓': [p(shade, which_half='right', invert=True, fill_blank=True)],
    '🮔': [p(shade, which_half='left', invert=True, fill_blank=True)],
    '🮕': [p(shade, xnum=4, ynum=4)],
    '🮖': [p(shade, xnum=4, ynum=4, invert=True)],
    '🮗': [p(shade, xnum=1, ynum=4, invert=True)],
    '🮜': [shade, p(mask, p(corner_triangle, corner='top-left'))],
    '🮝': [shade, p(mask, p(corner_triangle, corner='top-right'))],
    '🮞': [shade, p(mask, p(corner_triangle, corner='bottom-right'))],
    '🮟': [shade, p(mask, p(corner_triangle, corner='bottom-left'))],
    '🮘': [cross_shade],
    '🮙': [p(cross_shade, rotate=True)],

    '▔': [p(eight_bar, horizontal=True)],
    '▕': [p(eight_bar, which=7)],
    '▖': [p(quad, y=1)],
    '▗': [p(quad, x=1, y=1)],
    '▘': [quad],
    '▙': [quad, p(quad, y=1), p(quad, x=1, y=1)],
    '▚': [quad, p(quad, x=1, y=1)],
    '▛': [quad, p(quad, x=1), p(quad, y=1)],
    '▜': [quad, p(quad, x=1, y=1), p(quad, x=1)],
    '▝': [p(quad, x=1)],
    '▞': [p(quad, x=1), p(quad, y=1)],
    '▟': [p(quad, x=1), p(quad, y=1), p(quad, x=1, y=1)],

    '🬼': [p(smooth_mosaic, a=(0, 2 / 3), b=(0.5, 1))],
    '🬽': [p(smooth_mosaic, a=(0, 2 / 3), b=(1, 1))],
    '🬾': [p(smooth_mosaic, a=(0, 1 / 3), b=(0.5, 1))],
    '🬿': [p(smooth_mosaic, a=(0, 1 / 3), b=(1, 1))],
    '🭀': [p(smooth_mosaic, a=(0, 0), b=(0.5, 1))],

    '🭁': [p(smooth_mosaic, a=(0, 1 / 3), b=(0.5, 0))],
    '🭂': [p(smooth_mosaic, a=(0, 1 / 3), b=(1, 0))],
    '🭃': [p(smooth_mosaic, a=(0, 2 / 3), b=(0.5, 0))],
    '🭄': [p(smooth_mosaic, a=(0, 2 / 3), b=(1, 0))],
    '🭅': [p(smooth_mosaic, a=(0, 1), b=(0.5, 0))],
    '🭆': [p(smooth_mosaic, a=(0, 2 / 3), b=(1, 1 / 3))],

    '🭇': [p(smooth_mosaic, a=(0.5, 1), b=(1, 2 / 3))],
    '🭈': [p(smooth_mosaic, a=(0, 1), b=(1, 2 / 3))],
    '🭉': [p(smooth_mosaic, a=(0.5, 1), b=(1, 1 / 3))],
    '🭊': [p(smooth_mosaic, a=(0, 1), b=(1, 1 / 3))],
    '🭋': [p(smooth_mosaic, a=(0.5, 1), b=(1, 0))],

    '🭌': [p(smooth_mosaic, a=(0.5, 0), b=(1, 1 / 3))],
    '🭍': [p(smooth_mosaic, a=(0, 0), b=(1, 1 / 3))],
    '🭎': [p(smooth_mosaic, a=(0.5, 0), b=(1, 2 / 3))],
    '🭏': [p(smooth_mosaic, a=(0, 0), b=(1, 2 / 3))],
    '🭐': [p(smooth_mosaic, a=(0.5, 0), b=(1, 1))],
    '🭑': [p(smooth_mosaic, a=(0, 1 / 3), b=(1, 2 / 3))],

    '🭒': [p(smooth_mosaic, lower=False, a=(0, 2 / 3), b=(0.5, 1))],
    '🭓': [p(smooth_mosaic, lower=False, a=(0, 2 / 3), b=(1, 1))],
    '🭔': [p(smooth_mosaic, lower=False, a=(0, 1 / 3), b=(0.5, 1))],
    '🭕': [p(smooth_mosaic, lower=False, a=(0, 1 / 3), b=(1, 1))],
    '🭖': [p(smooth_mosaic, lower=False, a=(0, 0), b=(0.5, 1))],

    '🭗': [p(smooth_mosaic, lower=False, a=(0, 1 / 3), b=(0.5, 0))],
    '🭘': [p(smooth_mosaic, lower=False, a=(0, 1 / 3), b=(1, 0))],
    '🭙': [p(smooth_mosaic, lower=False, a=(0, 2 / 3), b=(0.5, 0))],
    '🭚': [p(smooth_mosaic, lower=False, a=(0, 2 / 3), b=(1, 0))],
    '🭛': [p(smooth_mosaic, lower=False, a=(0, 1), b=(0.5, 0))],

    '🭜': [p(smooth_mosaic, lower=False, a=(0, 2 / 3), b=(1, 1 / 3))],
    '🭝': [p(smooth_mosaic, lower=False, a=(0.5, 1), b=(1, 2 / 3))],
    '🭞': [p(smooth_mosaic, lower=False, a=(0, 1), b=(1, 2 / 3))],
    '🭟': [p(smooth_mosaic, lower=False, a=(0.5, 1), b=(1, 1 / 3))],
    '🭠': [p(smooth_mosaic, lower=False, a=(0, 1), b=(1, 1 / 3))],
    '🭡': [p(smooth_mosaic, lower=False, a=(0.5, 1), b=(1, 0))],

    '🭢': [p(smooth_mosaic, lower=False, a=(0.5, 0), b=(1, 1 / 3))],
    '🭣': [p(smooth_mosaic, lower=False, a=(0, 0), b=(1, 1 / 3))],
    '🭤': [p(smooth_mosaic, lower=False, a=(0.5, 0), b=(1, 2 / 3))],
    '🭥': [p(smooth_mosaic, lower=False, a=(0, 0), b=(1, 2 / 3))],
    '🭦': [p(smooth_mosaic, lower=False, a=(0.5, 0), b=(1, 1))],
    '🭧': [p(smooth_mosaic, lower=False, a=(0, 1 / 3), b=(1, 2 / 3))],

    '🭨': [p(half_triangle, inverted=True)],
    '🭩': [p(half_triangle, which='top', inverted=True)],
    '🭪': [p(half_triangle, which='right', inverted=True)],
    '🭫': [p(half_triangle, which='bottom', inverted=True)],
    '🭬': [half_triangle],
    '🮛': [half_triangle, p(half_triangle, which='right')],
    '🭭': [p(half_triangle, which='top')],
    '🭮': [p(half_triangle, which='right')],
    '🭯': [p(half_triangle, which='bottom')],
    '🮚': [p(half_triangle, which='bottom'), p(half_triangle, which='top')],

    '🭼': [eight_bar, p(eight_bar, which=7, horizontal=True)],
    '🭽': [eight_bar, p(eight_bar, horizontal=True)],
    '🭾': [p(eight_bar, which=7), p(eight_bar, horizontal=True)],
    '🭿': [p(eight_bar, which=7), p(eight_bar, which=7, horizontal=True)],
    '🮀': [p(eight_bar, horizontal=True), p(eight_bar, which=7, horizontal=True)],
    '🮁': [
        p(eight_bar, horizontal=True), p(eight_bar, which=2, horizontal=True),
        p(eight_bar, which=4, horizontal=True), p(eight_bar, which=7, horizontal=True)],
    '🮂': [p(eight_block, horizontal=True, which=(0, 1))],
    '🮃': [p(eight_block, horizontal=True, which=(0, 1, 2))],
    '🮄': [p(eight_block, horizontal=True, which=(0, 1, 2, 3, 4))],
    '🮅': [p(eight_block, horizontal=True, which=(0, 1, 2, 3, 4, 5))],
    '🮆': [p(eight_block, horizontal=True, which=(0, 1, 2, 3, 4, 5, 6))],
    '🮇': [p(eight_block, which=(6, 7))],
    '🮈': [p(eight_block, which=(5, 6, 7))],
    '🮉': [p(eight_block, which=(3, 4, 5, 6, 7))],
    '🮊': [p(eight_block, which=(2, 3, 4, 5, 6, 7))],
    '🮋': [p(eight_block, which=(1, 2, 3, 4, 5, 6, 7))],

    '🮠': [mid_lines],
    '🮡': [p(mid_lines, pts=('tr',))],
    '🮢': [p(mid_lines, pts=('lb',))],
    '🮣': [p(mid_lines, pts=('br',))],
    '🮤': [p(mid_lines, pts=('lt', 'lb'))],
    '🮥': [p(mid_lines, pts=('rt', 'rb'))],
    '🮦': [p(mid_lines, pts=('rb', 'lb'))],
    '🮧': [p(mid_lines, pts=('rt', 'lt'))],
    '🮨': [p(mid_lines, pts=('rb', 'lt'))],
    '🮩': [p(mid_lines, pts=('lb', 'rt'))],
    '🮪': [p(mid_lines, pts=('lb', 'rt', 'rb'))],
    '🮫': [p(mid_lines, pts=('lb', 'lt', 'rb'))],
    '🮬': [p(mid_lines, pts=('rt', 'lt', 'rb'))],
    '🮭': [p(mid_lines, pts=('rt', 'lt', 'lb'))],
    '🮮': [p(mid_lines, pts=('rt', 'rb', 'lt', 'lb'))],

    '': [hline],
    '': [vline],
    '': [p(fading_hline, num=4, fade='right')],
    '': [p(fading_hline, num=4, fade='left')],
    '': [p(fading_vline, num=5, fade='down')],
    '': [p(fading_vline, num=5, fade='up')],
    '': [p(rounded_corner, which='╭')],
    '': [p(rounded_corner, which='╮')],
    '': [p(rounded_corner, which='╰')],
    '': [p(rounded_corner, which='╯')],
    '': [vline, p(rounded_corner, which='╰')],
    '': [vline, p(rounded_corner, which='╭')],
    '': [p(rounded_corner, which='╰'), p(rounded_corner, which='╭')],
    '': [vline, p(rounded_corner, which='╯')],
    '': [vline, p(rounded_corner, which='╮')],
    '': [p(rounded_corner, which='╮'), p(rounded_corner, which='╯')],
    '': [hline, p(rounded_corner, which='╮')],
    '': [hline, p(rounded_corner, which='╭')],
    '': [p(rounded_corner, which='╭'), p(rounded_corner, which='╮')],
    '': [hline, p(rounded_corner, which='╯')],
    '': [hline, p(rounded_corner, which='╰')],
    '': [p(rounded_corner, which='╰'), p(rounded_corner, which='╯')],
    '': [vline, p(rounded_corner, which='╰'), p(rounded_corner, which='╯')],
    '': [vline, p(rounded_corner, which='╭'), p(rounded_corner, which='╮')],
    '': [hline, p(rounded_corner, which='╮'), p(rounded_corner, which='╯')],
    '': [hline, p(rounded_corner, which='╰'), p(rounded_corner, which='╭')],
    '': [vline, p(rounded_corner, which='╭'), p(rounded_corner, which='╯')],
    '': [vline, p(rounded_corner, which='╮'), p(rounded_corner, which='╰')],
    '': [hline, p(rounded_corner, which='╭'), p(rounded_corner, which='╯')],
    '': [hline, p(rounded_corner, which='╮'), p(rounded_corner, which='╰')],
    '': [commit],
    '': [p(commit, solid=False)],
    '': [p(commit, lines=['right'])],
    '': [p(commit, solid=False, lines=['right'])],
    '': [p(commit, lines=['left'])],
    '': [p(commit, solid=False, lines=['left'])],
    '': [p(commit, lines=['horizontal'])],
    '': [p(commit, solid=False, lines=['horizontal'])],
    '': [p(commit, lines=['down'])],
    '': [p(commit, solid=False, lines=['down'])],
    '': [p(commit, lines=['up'])],
    '': [p(commit, solid=False, lines=['up'])],
    '': [p(commit, lines=['vertical'])],
    '': [p(commit, solid=False, lines=['vertical'])],
    '': [p(commit, lines=['right', 'down'])],
    '': [p(commit, solid=False, lines=['right', 'down'])],
    '': [p(commit, lines=['left', 'down'])],
    '': [p(commit, solid=False, lines=['left', 'down'])],
    '': [p(commit, lines=['right', 'up'])],
    '': [p(commit, solid=False, lines=['right', 'up'])],
    '': [p(commit, lines=['left', 'up'])],
    '': [p(commit, solid=False, lines=['left', 'up'])],
    '': [p(commit, lines=['vertical', 'right'])],
    '': [p(commit, solid=False, lines=['vertical', 'right'])],
    '': [p(commit, lines=['vertical', 'left'])],
    '': [p(commit, solid=False, lines=['vertical', 'left'])],
    '': [p(commit, lines=['horizontal', 'down'])],
    '': [p(commit, solid=False, lines=['horizontal', 'down'])],
    '': [p(commit, lines=['horizontal', 'up'])],
    '': [p(commit, solid=False, lines=['horizontal', 'up'])],
    '': [p(commit, lines=['horizontal', 'vertical'])],
    '': [p(commit, solid=False, lines=['horizontal', 'vertical'])],
}

t, f = 1, 3
for start in '┌┐└┘':
    for i, (hlevel, vlevel) in enumerate(((t, t), (f, t), (t, f), (f, f))):
        box_chars[chr(ord(start) + i)] = [p(corner, which=start, hlevel=hlevel, vlevel=vlevel)]
for ch in '╭╮╰╯':
    box_chars[ch] = [p(rounded_corner, which=ch)]

for i, (a_, b_, c_, d_) in enumerate((
        (t, t, t, t), (f, t, t, t), (t, f, t, t), (f, f, t, t), (t, t, f, t), (t, t, t, f), (t, t, f, f),
        (f, t, f, t), (t, f, f, t), (f, t, t, f), (t, f, t, f), (f, f, f, t), (f, f, t, f), (f, t, f, f),
        (t, f, f, f), (f, f, f, f)
)):
    box_chars[chr(ord('┼') + i)] = [p(cross, a=a_, b=b_, c=c_, d=d_)]

for starts, func, pattern in (
        ('├┤', vert_t, ((t, t, t), (t, f, t), (f, t, t), (t, t, f), (f, t, f), (f, f, t), (t, f, f), (f, f, f))),
        ('┬┴', horz_t, ((t, t, t), (f, t, t), (t, f, t), (f, f, t), (t, t, f), (f, t, f), (t, f, f), (f, f, f))),
):
    for start in starts:
        for i, (a_, b_, c_) in enumerate(pattern):
            box_chars[chr(ord(start) + i)] = [p(func, which=start, a=a_, b=b_, c=c_)]

for chars, func_ in (('╒╕╘╛', dvcorner), ('╓╖╙╜', dhcorner), ('╔╗╚╝', dcorner), ('╟╢╤╧', dpip)):
    for ch in chars:
        box_chars[ch] = [p(func_, which=ch)]

for i in range(256):
    box_chars[chr(0x2800 + i)] = [p(braille, which=i)]


c = 0x1fb00
for i in range(1, 63):
    if i not in (21, 42):
        box_chars[chr(c)] = [p(sextant, which=i)]
        c += 1

for i in range(1, 7):
    box_chars[chr(0x1fb6f + i)] = [p(eight_bar, which=i)]
    box_chars[chr(0x1fb75 + i)] = [p(eight_bar, which=i, horizontal=True)]


def render_box_char(ch: str, buf: BufType, width: int, height: int, dpi: float = 96.0) -> BufType:
    global _dpi
    _dpi = dpi
    for func in box_chars[ch]:
        func(buf, width, height)
    return buf


def render_missing_glyph(buf: BufType, width: int, height: int) -> None:
    frame(buf, width, height)


def test_char(ch: str, sz: int = 48) -> None:
    # kitty +runpy "from kitty.fonts.box_drawing import test_char; test_char('XXX')"
    from kitty.fast_data_types import concat_cells, set_send_sprite_to_gpu

    from .render import display_bitmap, setup_for_testing
    with setup_for_testing('monospace', sz) as (_, width, height):
        buf = bytearray(width * height)
        try:
            render_box_char(ch, buf, width, height)

            def join_cells(*cells: bytes) -> bytes:
                cells = tuple(bytes(x) for x in cells)
                return concat_cells(width, height, False, cells)

            rgb_data = join_cells(buf)
            display_bitmap(rgb_data, width, height)
            print()
        finally:
            set_send_sprite_to_gpu(None)


def test_drawing(sz: int = 48, family: str = 'monospace', start: int = 0x2500, num_rows: int = 10, num_cols: int = 16) -> None:
    from kitty.fast_data_types import concat_cells, set_send_sprite_to_gpu

    from .render import display_bitmap, setup_for_testing

    with setup_for_testing(family, sz) as (_, width, height):
        space = bytearray(width * height)

        def join_cells(cells: Iterable[bytes]) -> bytes:
            cells = tuple(bytes(x) for x in cells)
            return concat_cells(width, height, False, cells)

        def render_chr(ch: str) -> bytearray:
            if ch in box_chars:
                cell = bytearray(len(space))
                render_box_char(ch, cell, width, height)
                return cell
            return space

        pos = start
        rows = []
        space_row = join_cells(repeat(space, 32))

        try:
            for r in range(num_rows):
                row = []
                for i in range(num_cols):
                    row.append(render_chr(chr(pos)))
                    row.append(space)
                    pos += 1
                rows.append(join_cells(row))
                rows.append(space_row)
            rgb_data = b''.join(rows)
            width *= 32
            height *= len(rows)
            assert len(rgb_data) == width * height * 4, f'{len(rgb_data)} != {width * height * 4}'
            display_bitmap(rgb_data, width, height)
        finally:
            set_send_sprite_to_gpu(None)
