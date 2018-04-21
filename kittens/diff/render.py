#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2018, Kovid Goyal <kovid at kovidgoyal.net>

import re
from gettext import gettext as _
from functools import partial

from kitty.fast_data_types import wcswidth

from .collect import data_for_path, path_name_map
from .config import formats

sanitize_pat = re.compile('[\x00-\x1f\x7f\x80-\x9f]')


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


def sanitize_sub(m):
    return '<{:x}>'.format(ord(m.group()[0]))


def sanitize(text):
    return sanitize_pat.sub(sanitize_sub, text)


def fit_in(text, count):
    w = wcswidth(text)
    if w <= count:
        return text
    text = text[:count-1]
    while wcswidth(text) > count - 1:
        text = text[:-1]
    return text + '…'


def formatted(fmt, text):
    return '\x1b[' + fmt + 'm' + text + '\x1b[0m'


title_format = partial(formatted, formats['title'])
margin_format = partial(formatted, formats['margin'])
text_format = partial(formatted, formats['text'])
del formatted


def place_in(text, sz):
    return fit_in(text, sz).ljust(sz)


def title_lines(left_path, right_path, args, columns, margin_size):
    name = fit_in(sanitize(path_name_map[left_path]), columns - 2 * margin_size)
    yield title_format((' ' + name).ljust(columns))
    yield title_format('━' * columns)
    yield title_format(' ' * columns)


def binary_lines(path, other_path, columns, margin_size):
    template = _('Binary file: {}')

    def fl(path):
        text = template.format(human_readable(len(data_for_path(path))))
        text = place_in(text, columns // 2 - margin_size)
        return margin_format(' ' * margin_size) + text_format(text)

    return fl(path) + fl(other_path)


def lines_for_diff(left_path, right_path, hunks, args, columns, margin_size):
    return iter(())


def render_diff(collection, diff_map, args, columns):
    largest_line_number = 0
    for path, item_type, other_path in collection:
        if item_type == 'diff':
            patch = diff_map.get(path)
            if patch is not None:
                largest_line_number = max(largest_line_number, patch.largest_line_number)

    margin_size = max(3, len(str(largest_line_number)) + 1)

    for path, item_type, other_path in collection:
        if item_type == 'diff':
            yield from title_lines(path, other_path, args, columns, margin_size)
            is_binary = isinstance(data_for_path(path), bytes)
            if is_binary:
                yield from binary_lines(path, other_path, columns, margin_size)
            else:
                yield from lines_for_diff(path, other_path, diff_map[path], args, columns, margin_size)
