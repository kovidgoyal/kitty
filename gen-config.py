#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPLv3 Copyright: 2021, Kovid Goyal <kovid at kovidgoyal.net>


from kitty.conf.generate import write_output


def main() -> None:
    from kitty.options.definition import definition
    write_output('kitty', definition)
    from kittens.diff.options.definition import definition as kd
    write_output('kittens.diff', kd)


if __name__ == '__main__':
    main()
