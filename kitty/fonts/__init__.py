try:
    from typing import TypedDict
except ImportError:
    TypedDict = dict


class ListedFont(TypedDict):
    family: str
    full_name: str
    postscript_name: str
    is_monospace: bool


class FontFeature:

    __slots__ = 'name', 'parsed'

    def __init__(self, name: str, parsed: bytes):
        self.name = name
        self.parsed = parsed

    def __repr__(self) -> str:
        return repr(self.name)
