try:
    from typing import TypedDict
except ImportError:
    TypedDict = dict


class ListedFont(TypedDict):
    family: str
    full_name: str
    postscript_name: str
    is_monospace: bool


class FontFeature(str):

    def __new__(cls, name: str, parsed: bytes) -> 'FontFeature':
        ans: FontFeature = str.__new__(cls, name)
        ans.parsed = parsed  # type: ignore
        return ans
