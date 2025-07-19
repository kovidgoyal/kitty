#!./kitty/launcher/kitty +launch
# License: GPL v3 Copyright: 2016, Kovid Goyal <kovid at kovidgoyal.net>

import importlib  # me: importlit will let me assign the import to m
import inspect


def main() -> None:
    m = importlib.import_module("kitty_tests.main")  # me: assigning test import to m
    tests = [
        name
        for name, obj in m.__dict__.items()
        if inspect.isfunction(obj)
    ]  # me: getting the tests helpers names

    print("TESTS NAMES:", tests) # printing the test helpers names
    getattr(m, "main")()  # me: run all tests imported


if __name__ == "__main__":
    main()
