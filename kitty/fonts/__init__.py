from enum import Enum, IntEnum, auto
from typing import Dict, NamedTuple, Optional, Tuple, TypedDict, Union

from kitty.typing import CoreTextFont, FontConfigPattern


class ListedFont(TypedDict):
    family: str
    full_name: str
    postscript_name: str
    is_monospace: bool
    is_variable: bool
    descriptor: Union[FontConfigPattern, CoreTextFont]


class VariableAxis(TypedDict):
    minimum: float
    maximum: float
    default: float
    hidden: bool
    tag: str
    strid: str  # Can be empty string when not present


class NamedStyle(TypedDict):
    axis_values: Dict[str, float]
    name: Optional[str]
    psname: Optional[str]


class VariableData(TypedDict):
    axes: Tuple[VariableAxis, ...]
    named_styles: Tuple[NamedStyle, ...]
    variations_postscript_name_prefix: str


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
    cell_width = auto()
    cell_height = auto()
    baseline = auto()
    size = auto()


class ModificationUnit(IntEnum):
    pt = 0
    percent = 1
    pixel = 2


class ModificationValue(NamedTuple):
    val: float
    unit: ModificationUnit

    def __repr__(self) -> str:
        u = '%' if self.unit is ModificationUnit.percent else ''
        return f'{self.val:g}{u}'


class FontModification(NamedTuple):
    mod_type: ModificationType
    mod_value: ModificationValue
    font_name: str = ''

    def __repr__(self) -> str:
        fn = f' {self.font_name}' if self.font_name else ''
        return f'{self.mod_type.name}{fn} {self.mod_value}'
