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
        if 'is_multicell' in assertions:
            if assertions['is_multicell']:
                assert cell['mcd'] is not None, msg
            else:
                assert cell['mcd'] is None, msg
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
            assert assertions[key] == val, f'{msg}{assertions[key]!r} != {val!r}'

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

    s = self.create_screen(cols=5, lines=5)
    ac(0, 0, is_multicell=False)
    multicell(s, 'a')
    ac(0, 0, is_multicell=True, width=1, scale=1, subscale=0, x=0, y=0, text='a', explicitly_set=True, cursor=(1, 0))
    ac(0, 1, is_multicell=False), ac(1, 0, is_multicell=False), ac(1, 1, is_multicell=False)
    s.draw('莊')
    ac(0, 0, is_multicell=True, width=1, scale=1, subscale=0, x=0, y=0, text='a', explicitly_set=True)
    ac(1, 0, is_multicell=True, width=2, scale=1, subscale=0, x=0, y=0, text='莊', explicitly_set=False, cursor=(3, 0))
    ac(2, 0, is_multicell=True, width=2, scale=1, subscale=0, x=1, y=0, text='', explicitly_set=False)
    ac(1, 0, is_multicell=False), ac(1, 1, is_multicell=False)
