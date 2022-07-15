try:
    from typing import TypedDict, NamedTuple
except ImportError:
    TypedDict = dict
from enum import Enum, auto


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


class ModificationType(Enum):
    underline_position = auto()
    underline_thickness = auto()
    strikethrough_position = auto()
    strikethrough_thickness = auto()
    size = auto()


class ModificationUnit(Enum):
    pt = auto()
    percent = auto()


class ModificationValue(NamedTuple):
    val: float
    unit: ModificationUnit


class FontModification(NamedTuple):
    mod_type: ModificationType
    mod_value: ModificationValue
    font_name: str = ''
