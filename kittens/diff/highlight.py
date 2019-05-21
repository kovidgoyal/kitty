#!/usr/bin/env python3
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2018, Kovid Goyal <kovid at kovidgoyal.net>

import concurrent
import os
import re

from pygments import highlight
from pygments.formatter import Formatter
from pygments.lexers import get_lexer_for_filename
from pygments.util import ClassNotFound

from kitty.rgb import color_as_sgr, parse_sharp

from .collect import Segment, data_for_path, lines_for_path


class StyleNotFound(Exception):
    pass


class DiffFormatter(Formatter):

    def __init__(self, style='default'):
        try:
            Formatter.__init__(self, style=style)
            initialized = True
        except ClassNotFound:
            initialized = False
        if not initialized:
            raise StyleNotFound('pygments style "{}" not found'.format(style))

        self.styles = {}
        for token, style in self.style:
            start = []
            end = []
            # a style item is a tuple in the following form:
            # colors are readily specified in hex: 'RRGGBB'
            if style['color']:
                start.append('38' + color_as_sgr(parse_sharp(style['color'])))
                end.append('39')
            if style['bold']:
                start.append('1')
                end.append('22')
            if style['italic']:
                start.append('3')
                end.append('23')
            if style['underline']:
                start.append('4')
                end.append('24')
            if start:
                start = '\033[{}m'.format(';'.join(start))
                end = '\033[{}m'.format(';'.join(end))
            self.styles[token] = start or '', end or ''

    def format(self, tokensource, outfile):
        for ttype, value in tokensource:
            not_found = True
            if value.rstrip('\n'):
                while ttype and not_found:
                    tok = self.styles.get(ttype)
                    if tok is None:
                        ttype = ttype[:-1]
                    else:
                        on, off = tok
                        lines = value.split('\n')
                        for line in lines:
                            if line:
                                outfile.write(on + line + off)
                            if line is not lines[-1]:
                                outfile.write('\n')
                        not_found = False

            if not_found:
                outfile.write(value)


formatter = None


def initialize_highlighter(style='default'):
    global formatter
    formatter = DiffFormatter(style)


def highlight_data(code, filename, aliases=None):
    if aliases:
        base, ext = os.path.splitext(filename)
        alias = aliases.get(ext[1:])
        if alias is not None:
            filename = base + '.' + alias
    try:
        lexer = get_lexer_for_filename(filename, stripnl=False)
    except ClassNotFound:
        pass
    else:
        return highlight(code, lexer, formatter)


split_pat = re.compile(r'(\033\[.*?m)')


def highlight_line(line):
    ans = []
    current = None
    pos = 0
    for x in split_pat.split(line):
        if x.startswith('\033'):
            if current is None:
                current = Segment(pos, x)
            else:
                current.end = pos
                current.end_code = x
                ans.append(current)
                current = None
        else:
            pos += len(x)
    return ans


def highlight_for_diff(path, aliases):
    ans = []
    lines = lines_for_path(path)
    hd = highlight_data('\n'.join(lines), path, aliases)
    if hd is not None:
        for line in hd.splitlines():
            ans.append(highlight_line(line))
    return ans


def highlight_collection(collection, aliases=None):
    jobs = {}
    ans = {}
    with concurrent.futures.ProcessPoolExecutor(max_workers=os.cpu_count()) as executor:
        highlight_collection.processes = executor._processes
        for path, item_type, other_path in collection:
            if item_type != 'rename':
                for p in (path, other_path):
                    if p:
                        is_binary = isinstance(data_for_path(p), bytes)
                        if not is_binary:
                            jobs[executor.submit(highlight_for_diff, p, aliases)] = p
        for future in concurrent.futures.as_completed(jobs):
            path = jobs[future]
            try:
                highlights = future.result()
            except Exception as e:
                return 'Running syntax highlighting for {} generated an exception: {}'.format(path, e)
            ans[path] = highlights
    return ans


def main():
    from .config import defaults
    # kitty +runpy "from kittens.diff.highlight import main; main()" file
    import sys
    initialize_highlighter()
    with open(sys.argv[-1]) as f:
        highlighted = highlight_data(f.read(), f.name, defaults.syntax_aliases)
    if highlighted is None:
        raise SystemExit('Unknown filetype: {}'.format(sys.argv[-1]))
    print(highlighted)
