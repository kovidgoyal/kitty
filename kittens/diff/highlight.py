#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2018, Kovid Goyal <kovid at kovidgoyal.net>

from pygments import highlight
from pygments.formatter import Formatter
from pygments.lexers import get_lexer_for_filename
from pygments.util import ClassNotFound

from kitty.rgb import color_as_sgr, parse_sharp


class DiffFormatter(Formatter):

    def __init__(self, style='default'):
        Formatter.__init__(self, style=style)
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
            if value != '\n':
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


def highlight_data(code, filename):
    try:
        lexer = get_lexer_for_filename(filename, stripnl=False)
    except ClassNotFound:
        pass
    else:
        return highlight(code, lexer, formatter)


def main():
    # kitty +runpy "from kittens.diff.highlight import main; main()" file
    import sys
    initialize_highlighter()
    with open(sys.argv[-1]) as f:
        highlighted = highlight_data(f.read(), f.name)
    if highlighted is None:
        raise SystemExit('Unknown filetype: {}'.format(sys.argv[-1]))
    print(highlighted)
