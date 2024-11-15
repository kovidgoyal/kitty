#!/usr/bin/env python
# License: GPLv3 Copyright: 2024, Kovid Goyal <kovid at kovidgoyal.net>


from kitty.fast_data_types import TEXT_SIZE_CODE, Screen

from . import BaseTest, parse_bytes


class TestMulticell(BaseTest):

    def test_multicell(self):
        test_multicell(self)


def multicell(screen: Screen, text: str, width: int = 0, scale: int = 1, subscale: int = 0) -> None:
    cmd = f'\x1b]{TEXT_SIZE_CODE};w={width}:s={scale}:f={subscale};{text}\a'
    parse_bytes(screen, cmd.encode())


def test_multicell(self: TestMulticell) -> None:

    def ac(x_, y_, **assertions):  # assert cell
        cell = s.cpu_cells(y_, x_)
        msg = f'Assertion failed for cell at ({x_}, {y_})\n{cell}\n'
        def ae(key):
            if key not in assertions:
                return
            if key in cell:
                val = cell[key]
            else:
                mcd = cell['mcd']
                if mcd is None:
                    raise AssertionError(f'{msg}Unexpectedly not a multicell')
                val = mcd[key]
            if assertions[key] != val:
                raise AssertionError(f'{msg}{assertions[key]!r} != {val!r}')

        ae('x')
        ae('y')
        ae('width')
        ae('scale')
        ae('subscale')
        ae('vertical_align')
        ae('text')
        ae('explicitly_set')

        if 'cursor' in assertions:
            self.ae(assertions['cursor'], (s.cursor.x, s.cursor.y), msg)

        if 'is_multicell' in assertions:
            q = cell['mcd']
            if assertions['is_multicell']:
                if q is None:
                    raise AssertionError(f'{msg}Unexpectedly not a multicell')
            else:
                if q is not None:
                    raise AssertionError(f'{msg}Unexpectedly is a multicell')

    def count_multicells(with_text=''):
        ans = 0
        for y in range(s.lines):
            for x in range(s.columns):
                c = s.cpu_cells(y, x)
                if c['mcd'] is not None and (not with_text or c['text'] == with_text):
                    ans += 1
        return ans

    # Test basic multicell drawing
    s = self.create_screen(cols=6, lines=6)
    ac(0, 0, is_multicell=False)
    multicell(s, 'a')
    ac(0, 0, is_multicell=True, width=1, scale=1, subscale=0, x=0, y=0, text='a', explicitly_set=True, cursor=(1, 0))
    ac(0, 1, is_multicell=False), ac(1, 0, is_multicell=False), ac(1, 1, is_multicell=False)
    s.draw('莊')
    ac(0, 0, is_multicell=True, width=1, scale=1, subscale=0, x=0, y=0, text='a', explicitly_set=True)
    ac(1, 0, is_multicell=True, width=2, scale=1, subscale=0, x=0, y=0, text='莊', explicitly_set=False, cursor=(3, 0))
    ac(2, 0, is_multicell=True, width=2, scale=1, subscale=0, x=1, y=0, text='', explicitly_set=False)
    for x in range(s.columns):
        ac(x, 1, is_multicell=False)
    s.cursor.x = 0
    multicell(s, 'a', width=2, scale=2, subscale=3)
    ac(0, 0, is_multicell=True, width=2, scale=2, subscale=3, x=0, y=0, text='a', explicitly_set=True, cursor=(4, 0))
    for x in range(1, 4):
        ac(x, 0, is_multicell=True, width=2, scale=2, subscale=3, x=x, y=0, text='', explicitly_set=True)
    for x in range(0, 4):
        ac(x, 1, is_multicell=True, width=2, scale=2, subscale=3, x=x, y=1, text='', explicitly_set=True)

    # Test draw with cursor in a multicell
    s.reset()
    s.draw('莊')
    s.cursor.x -= 1
    s.draw('a'), ac(0, 0, is_multicell=False), ac(1, 0, is_multicell=False)
    s.reset()
    s.draw('莊')
    s.cursor.x = 0
    s.draw('a'), ac(0, 0, is_multicell=False), ac(1, 0, is_multicell=False)
    s.reset()
    multicell(s, 'a', width=2, scale=2, subscale=3)
    s.cursor.x, s.cursor.y = 1, 1
    s.draw('b')
    self.ae(0, count_multicells())
    s.reset()
    s.cursor.x = 1
    s.draw('莊')
    s.cursor.x = 0
    s.draw('莊')
    ac(2, 0, is_multicell=False, text=' ')

    # Test multicell with cursor in a multicell
    def big_a(x, y):
        s.reset()
        s.cursor.x, s.cursor.y = 1, 1
        multicell(s, 'a', scale=4)
        s.cursor.x, s.cursor.y = x, y
        multicell(s, 'b', scale=2)
        self.ae(4, count_multicells())
        for x in range(1, 5):
            ac(x, 4, text=' ')
    big_a(0, 0), big_a(1, 1), big_a(2, 2), big_a(5, 1)


