#!/usr/bin/env python
# License: GPLv3 Copyright: 2022, Kovid Goyal <kovid at kovidgoyal.net>
import re
from collections.abc import Callable, Iterator, Sequence
from enum import Enum
from functools import lru_cache
from gettext import gettext as _
from typing import NamedTuple, TypeVar

from .types import run_once


class ParseException(Exception):

    hide_traceback = True

    @property
    def msg(self) -> str:
        if len(self.args) > 0:
            return str(self.args[0])
        return ""


class ExpressionType(Enum):
    OR = 1
    AND = 2
    NOT = 3
    TOKEN = 4


class TokenType(Enum):
    OPCODE = 1
    WORD = 2
    QUOTED_WORD = 3
    EOF = 4


T = TypeVar('T')
GetMatches = Callable[[str, str, set[T]], set[T]]


class SearchTreeNode:
    type = ExpressionType.OR

    def __init__(self, type: ExpressionType) -> None:
        self.type = type

    def search(self, universal_set: set[T], get_matches: GetMatches[T]) -> set[T]:
        return self(universal_set, get_matches)

    def __call__(self, candidates: set[T], get_matches: GetMatches[T]) -> set[T]:
        return set()

    def iter_token_nodes(self) -> Iterator['TokenNode']:
        return iter(())


class OrNode(SearchTreeNode):

    def __init__(self, lhs: SearchTreeNode, rhs: SearchTreeNode) -> None:
        self.lhs = lhs
        self.rhs = rhs

    def __call__(self, candidates: set[T], get_matches: GetMatches[T]) -> set[T]:
        lhs = self.lhs(candidates, get_matches)
        return lhs.union(self.rhs(candidates.difference(lhs), get_matches))

    def iter_token_nodes(self) -> Iterator['TokenNode']:
        yield from self.lhs.iter_token_nodes()
        yield from self.rhs.iter_token_nodes()


class AndNode(SearchTreeNode):
    type = ExpressionType.AND

    def __init__(self, lhs: SearchTreeNode, rhs: SearchTreeNode) -> None:
        self.lhs = lhs
        self.rhs = rhs

    def __call__(self, candidates: set[T], get_matches: GetMatches[T]) -> set[T]:
        lhs = self.lhs(candidates, get_matches)
        return self.rhs(lhs, get_matches)

    def iter_token_nodes(self) -> Iterator['TokenNode']:
        yield from self.lhs.iter_token_nodes()
        yield from self.rhs.iter_token_nodes()


class NotNode(SearchTreeNode):
    type = ExpressionType.NOT

    def __init__(self, rhs: SearchTreeNode) -> None:
        self.rhs = rhs

    def __call__(self, candidates: set[T], get_matches: GetMatches[T]) -> set[T]:
        return candidates.difference(self.rhs(candidates, get_matches))

    def iter_token_nodes(self) -> Iterator['TokenNode']:
        yield from self.rhs.iter_token_nodes()


class TokenNode(SearchTreeNode):
    type = ExpressionType.TOKEN

    def __init__(self, location: str, query: str) -> None:
        self.location = location
        self.query = query

    def __call__(self, candidates: set[T], get_matches: GetMatches[T]) -> set[T]:
        return get_matches(self.location, self.query, candidates)

    def iter_token_nodes(self) -> Iterator['TokenNode']:
        yield self


class Token(NamedTuple):
    type: TokenType
    val: str


@run_once
def lex_scanner() -> Callable[[str], tuple[list[Token], str]]:
    return getattr(re, 'Scanner')([  # type: ignore
            (r'[()]', lambda x, t: Token(TokenType.OPCODE, t)),
            (r'@.+?:[^")\s]+', lambda x, t: Token(TokenType.WORD, str(t))),
            (r'[^"()\s]+', lambda x, t: Token(TokenType.WORD, str(t))),
            (r'".*?((?<!\\)")', lambda x, t: Token(TokenType.QUOTED_WORD, t[1:-1])),
            (r'\s+',              None)
    ], flags=re.DOTALL).scan


@run_once
def replacements() -> tuple[tuple[str, str], ...]:
    return tuple(('\\' + x, chr(i + 1)) for i, x in enumerate('\\"()'))


class NoLocation(ParseException):

    def __init__(self, tt: str):
        a, sep, b = tt.partition(':')
        if sep == ':':
            super().__init__(f'{a} is not a recognized location in {tt}')
        else:
            super().__init__(f'No location specified before {tt}')


class Parser:

    def __init__(self, allow_no_location: bool = False) -> None:
        self.current_token = 0
        self.tokens: list[Token] = []
        self.allow_no_location = allow_no_location

    def token(self, advance: bool = False) -> str | None:
        if self.is_eof():
            return None
        res = self.tokens[self.current_token].val
        if advance:
            self.current_token += 1
        return res

    def lcase_token(self, advance: bool = False) -> str | None:
        if self.is_eof():
            return None
        res = self.tokens[self.current_token].val
        if advance:
            self.current_token += 1
        return res.lower()

    def token_type(self) -> TokenType:
        if self.is_eof():
            return TokenType.EOF
        return self.tokens[self.current_token].type

    def is_eof(self) -> bool:
        return self.current_token >= len(self.tokens)

    def advance(self) -> None:
        self.current_token += 1

    def tokenize(self, expr: str) -> list[Token]:
        # Strip out escaped backslashes, quotes and parens so that the
        # lex scanner doesn't get confused. We put them back later.
        for k, v in replacements():
            expr = expr.replace(k, v)
        tokens, leftover = lex_scanner()(expr)
        if leftover:
            raise ParseException(_('Extra characters at end of search'))

        def unescape(x: str) -> str:
            for k, v in replacements():
                x = x.replace(v, k[1:])
            return x

        return [
            Token(tt, unescape(tv) if tt in (TokenType.WORD, TokenType.QUOTED_WORD) else tv)
            for tt, tv in tokens
        ]

    def parse(self, expr: str, locations: Sequence[str]) -> SearchTreeNode:
        self.locations = locations
        self.tokens = self.tokenize(expr)
        self.current_token = 0
        prog = self.or_expression()
        if not self.is_eof():
            raise ParseException(_('Extra characters at end of search'))
        return prog

    def or_expression(self) -> SearchTreeNode:
        lhs = self.and_expression()
        if self.lcase_token() == 'or':
            self.advance()
            return OrNode(lhs, self.or_expression())
        return lhs

    def and_expression(self) -> SearchTreeNode:
        lhs = self.not_expression()
        if self.lcase_token() == 'and':
            self.advance()
            return AndNode(lhs, self.and_expression())

        # Account for the optional 'and'
        if ((self.token_type() in (TokenType.WORD, TokenType.QUOTED_WORD) or self.token() == '(') and self.lcase_token() != 'or'):
            return AndNode(lhs, self.and_expression())
        return lhs

    def not_expression(self) -> SearchTreeNode:
        if self.lcase_token() == 'not':
            self.advance()
            return NotNode(self.not_expression())
        return self.location_expression()

    def location_expression(self) -> SearchTreeNode:
        if self.token_type() == TokenType.OPCODE and self.token() == '(':
            self.advance()
            res = self.or_expression()
            if self.token_type() != TokenType.OPCODE or self.token(advance=True) != ')':
                raise ParseException(_('missing )'))
            return res
        if self.token_type() not in (TokenType.WORD, TokenType.QUOTED_WORD):
            raise ParseException(_('Invalid syntax. Expected a lookup name or a word'))

        return self.base_token()

    def base_token(self) -> SearchTreeNode:
        if self.token_type() is TokenType.QUOTED_WORD:
            tt = self.token(advance=True)
            assert tt is not None
            if self.allow_no_location:
                return TokenNode('all', tt)
            raise NoLocation(tt)

        tt = self.token(advance=True)
        assert tt is not None
        words = tt.split(':')
        # The complexity here comes from having colon-separated search
        # values. That forces us to check that the first "word" in a colon-
        # separated group is a valid location. If not, then the token must
        # be reconstructed. We also have the problem that locations can be
        # followed by quoted strings that appear as the next token. and that
        # tokens can be a sequence of colons.

        # We have a location if there is more than one word and the first
        # word is in locations. This check could produce a "wrong" answer if
        # the search string is something like 'author: "foo"' because it
        # will be interpreted as 'author:"foo"'. I am choosing to accept the
        # possible error. The expression should be written '"author:" foo'
        if len(words) > 1 and words[0].lower() in self.locations:
            loc = words[0].lower()
            words = words[1:]
            if len(words) == 1 and self.token_type() == TokenType.QUOTED_WORD:
                tt = self.token(advance=True)
                assert tt is not None
                return TokenNode(loc, tt)
            return TokenNode(loc.lower(), ':'.join(words))

        if self.allow_no_location:
            return TokenNode('all', ':'.join(words))
        raise NoLocation(tt)


@lru_cache(maxsize=64)
def build_tree(query: str, locations: str | tuple[str, ...], allow_no_location: bool = False) -> SearchTreeNode:
    if isinstance(locations, str):
        locations = tuple(locations.split())
    p = Parser(allow_no_location)
    try:
        return p.parse(query, locations)
    except RuntimeError as e:
        raise ParseException(f'Failed to parse {query!r}, too much recursion required') from e


def search(
    query: str, locations: str | tuple[str, ...], universal_set: set[T], get_matches: GetMatches[T],
    allow_no_location: bool = False,
) -> set[T]:
    return build_tree(query, locations, allow_no_location).search(universal_set, get_matches)
