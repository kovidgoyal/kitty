#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2018, Kovid Goyal <kovid at kovidgoyal.net>

from gettext import gettext as _
from itertools import repeat

from kitty.fast_data_types import truncate_point_for_length, wcswidth

from .collect import data_for_path, lines_for_path, path_name_map, sanitize
from .config import formats


class HunkRef:

    __slots__ = ('hunk_num', 'line_num', 'chunk_num')

    def __init__(self, hunk_num, chunk_num=None, line_num=None):
        self.hunk_num = hunk_num
        self.chunk_num = chunk_num
        self.line_num = line_num


class LineRef:

    __slots__ = ('src_line_number', 'wrapped_line_idx')

    def __init__(self, sln, wli):
        self.src_line_number = sln
        self.wrapped_line_idx = wli


class Reference:

    __slots__ = ('path', 'extra')

    def __init__(self, path, extra=None):
        self.path = path
        self.extra = extra


class Line:

    __slots__ = ('text', 'ref')

    def __init__(self, text, ref):
        self.text = text
        self.ref = ref


def yield_lines_from(iterator, reference):
    for text in iterator:
        yield Line(text, reference)


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


def title_lines(left_path, args, columns, margin_size):
    name = fit_in(sanitize(path_name_map[left_path]), columns - 2 * margin_size)
    yield title_format(place_in(' ' + name, columns))
    yield title_format('━' * columns)


def binary_lines(path, other_path, columns, margin_size):
    template = _('Binary file: {}')

    def fl(path):
        text = template.format(human_readable(len(data_for_path(path))))
        text = place_in(text, columns // 2 - margin_size)
        return margin_format(' ' * margin_size) + text_format(text)

    return fl(path) + fl(other_path)


def split_to_size(line, width):
    if not line:
        yield line
    while line:
        p = truncate_point_for_length(line, width)
        yield line[:p]
        line = line[p:]


def split_to_size_with_center(line, width, prefix_count, suffix_count, start, stop):
    sz = len(line)
    if prefix_count + suffix_count == sz:
        yield from split_to_size(line, width)
        return
    suffix_pos = sz - suffix_count
    pos = state = 0
    while line:
        p = truncate_point_for_length(line, width)
        if state is 0:
            if pos + p > prefix_count:
                state = 1
                a, line = line[:p], line[p:]
                if pos + p > suffix_pos:
                    a = a[:suffix_pos - pos] + stop + a[suffix_pos - pos:]
                    state = 2
                yield a[:prefix_count - pos] + start + a[prefix_count - pos:]
            else:
                yield line[:p]
                line = line[p:]
        elif state is 1:
            if pos + p > suffix_pos:
                state = 2
                a, line = line[:p], line[p:]
                yield start + a[:suffix_pos - pos] + stop + a[suffix_pos - pos:]
            else:
                yield start + line[:p]
                line = line[p:]
        elif state is 2:
            yield line[:p]
            line = line[p:]
        pos += p


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


def render_half_line(line_number, src, ltype, margin_size, available_cols, changed_center=None):
    if changed_center is not None and changed_center[0]:
        start, stop = highlight_boundaries(ltype)
        lines = split_to_size_with_center(src[line_number], available_cols, changed_center[0], changed_center[1], start, stop)
    else:
        lines = split_to_size(src[line_number], available_cols)
    line_number = str(line_number + 1)
    for line in lines:
        yield render_diff_line(line_number, line, ltype, margin_size, available_cols)
        line_number = ''


def lines_for_chunk(data, hunk_num, chunk, chunk_num):
    if chunk.is_context:
        for i in range(chunk.left_count):
            left_line_number = chunk.left_start + i
            right_line_number = chunk.right_start + i
            lines = split_to_size(data.left_lines[left_line_number], data.available_cols)
            ref = Reference(data.left_path, HunkRef(hunk_num, chunk_num, i))
            left_line_number = str(left_line_number + 1)
            right_line_number = str(right_line_number + 1)
            for text in lines:
                line = render_diff_line(left_line_number, text, 'context', data.margin_size, data.available_cols)
                if right_line_number == left_line_number:
                    r = line
                else:
                    r = render_diff_line(right_line_number, text, 'context', data.margin_size, data.available_cols)
                yield Line(line + r, ref)
                left_line_number = right_line_number = ''
    else:
        common = min(chunk.left_count, chunk.right_count)
        for i in range(max(chunk.left_count, chunk.right_count)):
            ref = Reference(data.left_path, HunkRef(hunk_num, chunk_num, i))
            ll, rl = [], []
            if i < chunk.left_count:
                ll.extend(render_half_line(
                    chunk.left_start + i, data.left_lines, 'remove', data.margin_size,
                    data.available_cols, None if chunk.centers is None else chunk.centers[i]))
            if i < chunk.right_count:
                rl.extend(render_half_line(
                    chunk.right_start + i, data.right_lines, 'add', data.margin_size,
                    data.available_cols, None if chunk.centers is None else chunk.centers[i]))
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
            for left_line, right_line in zip(ll, rl):
                yield Line(left_line + right_line, ref)


def lines_for_diff(left_path, right_path, hunks, args, columns, margin_size):
    available_cols = columns // 2 - margin_size
    data = DiffData(left_path, right_path, available_cols, margin_size)

    for hunk_num, hunk in enumerate(hunks):
        yield Line(hunk_title(hunk_num, hunk, margin_size, columns - margin_size), Reference(left_path, HunkRef(hunk_num)))
        for cnum, chunk in enumerate(hunk.chunks):
            yield from lines_for_chunk(data, hunk_num, chunk, cnum)


def all_lines(path, args, columns, margin_size, is_add=True):
    available_cols = columns // 2 - margin_size
    ltype = 'add' if is_add else 'remove'
    lines = lines_for_path(path)
    filler = render_diff_line('', '', 'filler', margin_size, available_cols)
    for line_number in range(len(lines)):
        h = render_half_line(line_number, lines, ltype, margin_size, available_cols)
        for i, hl in enumerate(h):
            ref = Reference(path, LineRef(line_number, i))
            text = (filler + h) if is_add else (h + filler)
            yield Line(text, ref)


def rename_lines(path, other_path, args, columns, margin_size):
    m = ' ' * margin_size
    for line in split_to_size(margin_size + _('The file {0} was renamed to {1}').format(
            sanitize(path_name_map[path]), sanitize(path_name_map[other_path])), columns - margin_size):
        yield m + line


def render_diff(collection, diff_map, args, columns):
    largest_line_number = 0
    for path, item_type, other_path in collection:
        if item_type == 'diff':
            patch = diff_map.get(path)
            if patch is not None:
                largest_line_number = max(largest_line_number, patch.largest_line_number)

    margin_size = max(3, len(str(largest_line_number)) + 1)

    for path, item_type, other_path in collection:
        item_ref = Reference(path)
        if item_type == 'diff':
            yield from yield_lines_from(title_lines(path, args, columns, margin_size), item_ref)
            is_binary = isinstance(data_for_path(path), bytes)
            if is_binary:
                yield from yield_lines_from(binary_lines(path, other_path, columns, margin_size), item_ref)
            else:
                yield from lines_for_diff(path, other_path, diff_map[path], args, columns, margin_size)
        elif item_type == 'add':
            yield from yield_lines_from(title_lines(other_path, args, columns, margin_size), item_ref)
            yield from all_lines(other_path, args, columns, margin_size, is_add=True)
        elif item_type == 'removal':
            yield from yield_lines_from(title_lines(path, args, columns, margin_size), item_ref)
            yield from all_lines(path, args, columns, margin_size, is_add=False)
        elif item_type == 'rename':
            yield from yield_lines_from(title_lines(path, args, columns, margin_size), item_ref)
            yield from yield_lines_from(rename_lines(path, other_path, args, columns, margin_size))
