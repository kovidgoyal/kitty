try:
    from typing import TypedDict
except ImportError:
    TypedDict = dict


class ListedFont(TypedDict):
    family: str
    full_name: str
    postscript_name: str
    is_monospace: bool
