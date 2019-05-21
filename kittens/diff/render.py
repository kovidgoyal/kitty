#!/usr/bin/env python3
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2018, Kovid Goyal <kovid at kovidgoyal.net>

import warnings
from gettext import gettext as _
from itertools import repeat, zip_longest
from math import ceil

from kitty.fast_data_types import truncate_point_for_length, wcswidth

from ..tui.images import can_display_images
from .collect import (
    Segment, data_for_path, highlights_for_path, is_image, lines_for_path,
    path_name_map, sanitize
)
from .config import formats
from .diff_speedup import split_with_highlights as _split_with_highlights


class ImageSupportWarning(Warning):
    pass


def images_supported():
    ans = getattr(images_supported, 'ans', None)
    if ans is None:
        images_supported.ans = ans = can_display_images()
        if not ans:
            warnings.warn('ImageMagick not found images cannot be displayed', ImageSupportWarning)
    return ans


class Ref:

    def __setattr__(self, name, value):
        raise AttributeError("can't set attribute")

    def __repr__(self):
        return '{}({})'.format(self.__class__.__name__, ', '.join(
            '{}={}'.format(n, getattr(self, n)) for n in self.__slots__ if n != '_hash'))


class LineRef(Ref):

    __slots__ = ('src_line_number', 'wrapped_line_idx')

    def __init__(self, sln, wli=0):
        object.__setattr__(self, 'src_line_number', sln)
        object.__setattr__(self, 'wrapped_line_idx', wli)


class Reference(Ref):

    __slots__ = ('path', 'extra')

    def __init__(self, path, extra=None):
        object.__setattr__(self, 'path', path)
        object.__setattr__(self, 'extra', extra)


class Line:

    __slots__ = ('text', 'ref', 'is_change_start', 'image_data')

    def __init__(self, text, ref, change_start=False, image_data=None):
        self.text = text
        self.ref = ref
        self.is_change_start = change_start
        self.image_data = image_data


def yield_lines_from(iterator, reference, is_change_start=True):
    for text in iterator:
        yield Line(text, reference, is_change_start)
        is_change_start = False


def human_readable(size, sep=' '):
    """ Convert a size in bytes into a human readable form """
    divisor, suffix = 1, "B"
    for i, candidate in enumerate(('B', 'KB', 'MB', 'GB', 'TB', 'PB', 'EB')):
        if size < (1 << ((i + 1) * 10)):
            divisor, suffix = (1 << (i * 10)), candidate
            break
    size = str(float(size)/divisor)
    if size.find(".") > -1:
        size = size[:size.find(".")+2]
    if size.endswith('.0'):
        size = size[:-2]
    return size + sep + suffix


def fit_in(text, count):
    p = truncate_point_for_length(text, count)
    if p >= len(text):
        return text
    if count > 1:
        p = truncate_point_for_length(text, count - 1)
    return text[:p] + '…'


def fill_in(text, sz):
    w = wcswidth(text)
    if w < sz:
        text += ' ' * (sz - w)
    return text


def place_in(text, sz):
    return fill_in(fit_in(text, sz), sz)


def format_func(which):
    def formatted(text):
        fmt = formats[which]
        return '\x1b[' + fmt + 'm' + text + '\x1b[0m'
    formatted.__name__ = which + '_format'
    return formatted


text_format = format_func('text')
title_format = format_func('title')
margin_format = format_func('margin')
added_format = format_func('added')
removed_format = format_func('removed')
removed_margin_format = format_func('removed_margin')
added_margin_format = format_func('added_margin')
filler_format = format_func('filler')
hunk_margin_format = format_func('hunk_margin')
hunk_format = format_func('hunk')
highlight_map = {'remove': ('removed_highlight', 'removed'), 'add': ('added_highlight', 'added')}


def highlight_boundaries(ltype):
    s, e = highlight_map[ltype]
    start = '\x1b[' + formats[s] + 'm'
    stop = '\x1b[' + formats[e] + 'm'
    return start, stop


def title_lines(left_path, right_path, args, columns, margin_size):
    m = ' ' * margin_size
    left_name, right_name = map(path_name_map.get, (left_path, right_path))
    if right_name and right_name != left_name:
        n1 = fit_in(m + sanitize(left_name), columns // 2 - margin_size)
        n1 = place_in(n1, columns // 2)
        n2 = fit_in(m + sanitize(right_name), columns // 2 - margin_size)
        n2 = place_in(n2, columns // 2)
        name = n1 + n2
    else:
        name = place_in(m + sanitize(left_name), columns)
    yield title_format(place_in(name, columns))
    yield title_format('━' * columns)


def binary_lines(path, other_path, columns, margin_size):
    template = _('Binary file: {}')
    available_cols = columns // 2 - margin_size

    def fl(path, fmt):
        text = template.format(human_readable(len(data_for_path(path))))
        text = place_in(text, available_cols)
        return margin_format(' ' * margin_size) + fmt(text)

    if path is None:
        filler = render_diff_line('', '', 'filler', margin_size, available_cols)
        yield filler + fl(other_path, added_format)
    elif other_path is None:
        filler = render_diff_line('', '', 'filler', margin_size, available_cols)
        yield fl(path, removed_format) + filler
    else:
        yield fl(path, removed_format) + fl(other_path, added_format)


def split_to_size(line, width):
    if not line:
        yield line
    while line:
        p = truncate_point_for_length(line, width)
        yield line[:p]
        line = line[p:]


def truncate_points(line, width):
    pos = 0
    sz = len(line)
    while True:
        pos = truncate_point_for_length(line, width, pos)
        if pos < sz:
            yield pos
        else:
            break


def split_with_highlights(line, width, highlights, bg_highlight=None):
    truncate_pts = list(truncate_points(line, width))
    return _split_with_highlights(line, truncate_pts, highlights, bg_highlight)


margin_bg_map = {'filler': filler_format, 'remove': removed_margin_format, 'add': added_margin_format, 'context': margin_format}
text_bg_map = {'filler': filler_format, 'remove': removed_format, 'add': added_format, 'context': text_format}


class DiffData:

    def __init__(self, left_path, right_path, available_cols, margin_size):
        self.left_path, self.right_path = left_path, right_path
        self.available_cols = available_cols
        self.margin_size = margin_size
        self.left_lines, self.right_lines = map(lines_for_path, (left_path, right_path))
        self.filler_line = render_diff_line('', '', 'filler', margin_size, available_cols)
        self.left_filler_line = render_diff_line('', '', 'remove', margin_size, available_cols)
        self.right_filler_line = render_diff_line('', '', 'add', margin_size, available_cols)
        self.left_hdata = highlights_for_path(left_path)
        self.right_hdata = highlights_for_path(right_path)

    def left_highlights_for_line(self, line_num):
        if line_num < len(self.left_hdata):
            return self.left_hdata[line_num]
        return []

    def right_highlights_for_line(self, line_num):
        if line_num < len(self.right_hdata):
            return self.right_hdata[line_num]
        return []


def render_diff_line(number, text, ltype, margin_size, available_cols):
    margin = margin_bg_map[ltype](place_in(number, margin_size))
    content = text_bg_map[ltype](fill_in(text or '', available_cols))
    return margin + content


def render_diff_pair(left_line_number, left, left_is_change, right_line_number, right, right_is_change, is_first, margin_size, available_cols):
    ltype = 'filler' if left_line_number is None else ('remove' if left_is_change else 'context')
    rtype = 'filler' if right_line_number is None else ('add' if right_is_change else 'context')
    return (
            render_diff_line(left_line_number if is_first else None, left, ltype, margin_size, available_cols) +
            render_diff_line(right_line_number if is_first else None, right, rtype, margin_size, available_cols)
    )


def hunk_title(hunk_num, hunk, margin_size, available_cols):
    m = hunk_margin_format(' ' * margin_size)
    t = '@@ -{},{} +{},{} @@ {}'.format(hunk.left_start + 1, hunk.left_count, hunk.right_start + 1, hunk.right_count, hunk.title)
    return m + hunk_format(place_in(t, available_cols))


def render_half_line(line_number, line, highlights, ltype, margin_size, available_cols, changed_center=None):
    bg_highlight = None
    if changed_center is not None and changed_center[0]:
        prefix_count, suffix_count = changed_center
        line_sz = len(line)
        if prefix_count + suffix_count < line_sz:
            start, stop = highlight_boundaries(ltype)
            seg = Segment(prefix_count, start)
            seg.end = line_sz - suffix_count
            seg.end_code = stop
            bg_highlight = seg
    if highlights or bg_highlight:
        lines = split_with_highlights(line, available_cols, highlights, bg_highlight)
    else:
        lines = split_to_size(line, available_cols)
    line_number = str(line_number + 1)
    for line in lines:
        yield render_diff_line(line_number, line, ltype, margin_size, available_cols)
        line_number = ''


def lines_for_chunk(data, hunk_num, chunk, chunk_num):
    if chunk.is_context:
        for i in range(chunk.left_count):
            left_line_number = line_ref = chunk.left_start + i
            right_line_number = chunk.right_start + i
            highlights = data.left_highlights_for_line(left_line_number)
            if highlights:
                lines = split_with_highlights(data.left_lines[left_line_number], data.available_cols, highlights)
            else:
                lines = split_to_size(data.left_lines[left_line_number], data.available_cols)
            left_line_number = str(left_line_number + 1)
            right_line_number = str(right_line_number + 1)
            for wli, text in enumerate(lines):
                line = render_diff_line(left_line_number, text, 'context', data.margin_size, data.available_cols)
                if right_line_number == left_line_number:
                    r = line
                else:
                    r = render_diff_line(right_line_number, text, 'context', data.margin_size, data.available_cols)
                ref = Reference(data.left_path, LineRef(line_ref, wli))
                yield Line(line + r, ref)
                left_line_number = right_line_number = ''
    else:
        common = min(chunk.left_count, chunk.right_count)
        for i in range(max(chunk.left_count, chunk.right_count)):
            ll, rl = [], []
            if i < chunk.left_count:
                rln = ref_ln = chunk.left_start + i
                ll.extend(render_half_line(
                    rln, data.left_lines[rln], data.left_highlights_for_line(rln),
                    'remove', data.margin_size, data.available_cols,
                    None if chunk.centers is None else chunk.centers[i]))
                ref_path = data.left_path
            if i < chunk.right_count:
                rln = ref_ln = chunk.right_start + i
                rl.extend(render_half_line(
                    rln, data.right_lines[rln], data.right_highlights_for_line(rln),
                    'add', data.margin_size, data.available_cols,
                    None if chunk.centers is None else chunk.centers[i]))
                ref_path = data.right_path
            if i < common:
                extra = len(ll) - len(rl)
                if extra != 0:
                    if extra < 0:
                        x, fl = ll, data.left_filler_line
                        extra = -extra
                    else:
                        x, fl = rl, data.right_filler_line
                    x.extend(repeat(fl, extra))
            else:
                if ll:
                    x, count = rl, len(ll)
                else:
                    x, count = ll, len(rl)
                x.extend(repeat(data.filler_line, count))
            for wli, (left_line, right_line) in enumerate(zip(ll, rl)):
                ref = Reference(ref_path, LineRef(ref_ln, wli))
                yield Line(left_line + right_line, ref, i == 0 and wli == 0)


def lines_for_diff(left_path, right_path, hunks, args, columns, margin_size):
    available_cols = columns // 2 - margin_size
    data = DiffData(left_path, right_path, available_cols, margin_size)

    for hunk_num, hunk in enumerate(hunks):
        yield Line(hunk_title(hunk_num, hunk, margin_size, columns - margin_size), Reference(left_path, LineRef(hunk.left_start)))
        for cnum, chunk in enumerate(hunk.chunks):
            yield from lines_for_chunk(data, hunk_num, chunk, cnum)


def all_lines(path, args, columns, margin_size, is_add=True):
    available_cols = columns // 2 - margin_size
    ltype = 'add' if is_add else 'remove'
    lines = lines_for_path(path)
    filler = render_diff_line('', '', 'filler', margin_size, available_cols)
    msg_written = False
    hdata = highlights_for_path(path)

    def highlights(num):
        return hdata[num] if num < len(hdata) else []

    for line_number, line in enumerate(lines):
        h = render_half_line(line_number, line, highlights(line_number), ltype, margin_size, available_cols)
        for i, hl in enumerate(h):
            ref = Reference(path, LineRef(line_number, i))
            empty = filler
            if not msg_written:
                msg_written = True
                empty = render_diff_line(
                        '', _('This file was added') if is_add else _('This file was removed'),
                        'filler', margin_size, available_cols)
            text = (empty + hl) if is_add else (hl + empty)
            yield Line(text, ref, line_number == 0 and i == 0)


def rename_lines(path, other_path, args, columns, margin_size):
    m = ' ' * margin_size
    for line in split_to_size(_('The file {0} was renamed to {1}').format(
            sanitize(path_name_map[path]), sanitize(path_name_map[other_path])), columns - margin_size):
        yield m + line


class Image:

    def __init__(self, image_id, width, height, margin_size, screen_size):
        self.image_id = image_id
        self.width, self.height = width, height
        self.rows = int(ceil(self.height / screen_size.cell_height))
        self.columns = int(ceil(self.width / screen_size.cell_width))
        self.margin_size = margin_size


class ImagePlacement:

    def __init__(self, image, row):
        self.image = image
        self.row = row


def render_image(path, is_left, available_cols, margin_size, image_manager):
    lnum = 0
    margin_fmt = removed_margin_format if is_left else added_margin_format
    m = margin_fmt(' ' * margin_size)
    fmt = removed_format if is_left else added_format

    def yield_split(text):
        nonlocal lnum
        for i, line in enumerate(split_to_size(text, available_cols)):
            yield m + fmt(place_in(line, available_cols)), Reference(path, LineRef(lnum, i)), None
        lnum += 1

    try:
        image_id, width, height = image_manager.send_image(path, available_cols - margin_size, image_manager.screen_size.rows - 2)
    except Exception as e:
        yield from yield_split(_('Failed to render image, with error:'))
        yield from yield_split(' '.join(str(e).splitlines()))
        return
    meta = _('Dimensions: {0}x{1} pixels Size: {2}').format(
            width, height, human_readable(len(data_for_path(path))))
    yield from yield_split(meta)
    bg_line = m + fmt(' ' * available_cols)
    img = Image(image_id, width, height, margin_size, image_manager.screen_size)
    for r in range(img.rows):
        yield bg_line, Reference(path, LineRef(lnum)), ImagePlacement(img, r)
        lnum += 1


def image_lines(left_path, right_path, columns, margin_size, image_manager):
    available_cols = columns // 2 - margin_size
    left_lines, right_lines = iter(()), iter(())
    if left_path is not None:
        left_lines = render_image(left_path, True, available_cols, margin_size, image_manager)
    if right_path is not None:
        right_lines = render_image(right_path, False, available_cols, margin_size, image_manager)
    filler = ' ' * (available_cols + margin_size)
    is_change_start = True
    for left, right in zip_longest(left_lines, right_lines):
        left_placement = right_placement = None
        if left is None:
            left = filler
            right, ref, right_placement = right
        elif right is None:
            right = filler
            left, ref, left_placement = left
        else:
            right, ref, right_placement = right
            left, ref, left_placement = left
        image_data = (left_placement, right_placement) if left_placement or right_placement else None
        yield Line(left + right, ref, is_change_start, image_data)
        is_change_start = False


def render_diff(collection, diff_map, args, columns, image_manager):
    largest_line_number = 0
    for path, item_type, other_path in collection:
        if item_type == 'diff':
            patch = diff_map.get(path)
            if patch is not None:
                largest_line_number = max(largest_line_number, patch.largest_line_number)

    margin_size = render_diff.margin_size = max(3, len(str(largest_line_number)) + 1)
    last_item_num = len(collection) - 1

    for i, (path, item_type, other_path) in enumerate(collection):
        item_ref = Reference(path)
        is_binary = isinstance(data_for_path(path), bytes)
        if not is_binary and item_type == 'diff' and isinstance(data_for_path(other_path), bytes):
            is_binary = True
        is_img = is_binary and (is_image(path) or is_image(other_path)) and images_supported()
        yield from yield_lines_from(title_lines(path, other_path, args, columns, margin_size), item_ref, False)
        if item_type == 'diff':
            if is_binary:
                if is_img:
                    ans = image_lines(path, other_path, columns, margin_size, image_manager)
                else:
                    ans = yield_lines_from(binary_lines(path, other_path, columns, margin_size), item_ref)
            else:
                ans = lines_for_diff(path, other_path, diff_map[path], args, columns, margin_size)
        elif item_type == 'add':
            if is_binary:
                if is_img:
                    ans = image_lines(None, path, columns, margin_size, image_manager)
                else:
                    ans = yield_lines_from(binary_lines(None, path, columns, margin_size), item_ref)
            else:
                ans = all_lines(path, args, columns, margin_size, is_add=True)
        elif item_type == 'removal':
            if is_binary:
                if is_img:
                    ans = image_lines(path, None, columns, margin_size, image_manager)
                else:
                    ans = yield_lines_from(binary_lines(path, None, columns, margin_size), item_ref)
            else:
                ans = all_lines(path, args, columns, margin_size, is_add=False)
        elif item_type == 'rename':
            ans = yield_lines_from(rename_lines(path, other_path, args, columns, margin_size), item_ref)
        else:
            raise ValueError('Unsupported item type: {}'.format(item_type))
        yield from ans
        if i < last_item_num:
            yield Line('', item_ref)
