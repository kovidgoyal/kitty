#!/usr/bin/env python
# License: GPLv3 Copyright: 2022, Kovid Goyal <kovid at kovidgoyal.net>


from .base import BaseTest


class TestSQP(BaseTest):
    def test_search_query_parser(self):
        from kitty.search_query_parser import ParseException, search

        locations = 'id'
        universal_set = {1, 2, 3, 4, 5}

        def get_matches(location, query, candidates):
            return {x for x in candidates if query == str(x)}

        def t(q, expected=set()):
            actual = search(q, locations, universal_set, get_matches)
            self.ae(actual, expected)

        t('id:1', {1})
        t('id:"1"', {1})
        t('id:1 and id:1', {1})
        t('id:1 or id:2', {1, 2})
        t('id:1 and id:2')
        t('not id:1', universal_set - {1})
        t('(id:1 or id:2) and id:1', {1})
        self.assertRaises(ParseException, t, '1')
        self.assertRaises(ParseException, t, '"id:1"')

    def test_search_query_lexing(self):
        import re

        from kitty.search_query_parser import ParseException, Parser, Token, TokenType, build_tree, lex_scanner

        # Capturing groups in a re.Scanner lexicon break the mapping from
        # matched group to lexicon entry and are rejected outright by
        # Python 3.15, see https://github.com/python/cpython/issues/140797
        for pattern, _action in lex_scanner().__self__.lexicon:
            self.ae(re.compile(pattern).groups, 0, f'The lexicon pattern {pattern!r} uses a capturing group')

        # A backslash escaped quote must not terminate a quoted word. The
        # parser escapes these before lexing, so test the lexer directly too.
        self.ae(lex_scanner()(r'"a\"b" c'), ([Token(TokenType.QUOTED_WORD, r'a\"b'), Token(TokenType.WORD, 'c')], ''))

        p = Parser(allow_no_location=True)

        def t(q, *expected):
            self.ae(tuple(p.tokenize(q)), expected)

        opcode, word, quoted = TokenType.OPCODE, TokenType.WORD, TokenType.QUOTED_WORD
        t('id:1', (word, 'id:1'))
        t('id:"1"', (word, 'id:'), (quoted, '1'))
        t('""', (quoted, ''))
        t('"a b"', (quoted, 'a b'))
        t('"a\nb"', (quoted, 'a\nb'))
        t('"a(b)"', (quoted, 'a(b)'))
        t(r'"a\"b"', (quoted, 'a"b'))
        t(r'"a\\b"', (quoted, 'a\\b'))
        t(r'\"a\"', (word, '"a"'))
        t('(a or "b c")', (opcode, '('), (word, 'a'), (word, 'or'), (quoted, 'b c'), (opcode, ')'))
        self.assertRaises(ParseException, p.tokenize, '"unterminated')

        tree = build_tree(r'id:"a\"b" and id:"c d"', 'id')
        self.ae([(n.location, n.query) for n in tree.iter_token_nodes()], [('id', 'a"b'), ('id', 'c d')])
