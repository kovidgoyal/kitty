#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPLv3 Copyright: 2020, Kovid Goyal <kovid at kovidgoyal.net>


class CMD:
    pass


def generate_stub() -> None:
    from kittens.tui.operations import as_type_stub
    from kitty.conf.definition import save_type_stub
    text = as_type_stub()
    save_type_stub(text, __file__)
