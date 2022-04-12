#!/usr/bin/env python
# License: GPLv3 Copyright: 2022, Kovid Goyal <kovid at kovidgoyal.net>


from . import BaseTest


class TestSQP(BaseTest):

    def test_search_query_parser(self):
        from kitty.search_query_parser import search
        locations = 'id'
        universal_set = {1, 2, 3, 4, 5}

        def get_matches(location, query, candidates):
            return {x for x in candidates if query == str(x)}

        def t(q, expected):
            actual = search(q, locations, universal_set, get_matches)
            self.ae(actual, expected)

        t('id:1', {1})
        t('id:1 and id:1', {1})
        t('id:1 or id:2', {1, 2})
        t('id:1 and id:2', set())
        t('not id:1', universal_set - {1})
        t('(id:1 or id:2) and id:1', {1})
