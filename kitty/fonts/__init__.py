from collections.abc import Sequence
from enum import Enum, IntEnum, auto
from typing import TYPE_CHECKING, Literal, NamedTuple, TypedDict, TypeVar, Union

from kitty.fast_data_types import ParsedFontFeature
from kitty.types import run_once
from kitty.typing_compat import CoreTextFont, FontConfigPattern
from kitty.utils import shlex_split

if TYPE_CHECKING:
    import re


class ListedFont(TypedDict):
    family: str
    style: str
    full_name: str
    postscript_name: str
    is_monospace: bool
    is_variable: bool
    descriptor: FontConfigPattern | CoreTextFont


class VariableAxis(TypedDict):
    minimum: float
    maximum: float
    default: float
    hidden: bool
    tag: str
    strid: str  # Can be empty string when not present


class NamedStyle(TypedDict):
    axis_values: dict[str, float]
    name: str
    psname: str  # can be empty string when not present


class DesignValue1(TypedDict):
    format: Literal[1]
    flags: int
    name: str
    value: float


class DesignValue2(TypedDict):
    format: Literal[2]
    flags: int
    name: str
    value: float
    minimum: float
    maximum: float


class DesignValue3(TypedDict):
    format: Literal[3]
    flags: int
    name: str
    value: float
    linked_value: float


DesignValue = Union[DesignValue1, DesignValue2, DesignValue3]


class DesignAxis(TypedDict):
    name: str
    ordering: int
    tag: str
    values: list[DesignValue]


class AxisValue(TypedDict):
    design_index: int
    value: float


class MultiAxisStyle(TypedDict):
    flags: int
    name: str
    values: tuple[AxisValue, ...]


class VariableData(TypedDict):
    axes: tuple[VariableAxis, ...]
    named_styles: tuple[NamedStyle, ...]
    variations_postscript_name_prefix: str
    elided_fallback_name: str
    design_axes: tuple[DesignAxis, ...]
    multi_axis_styles: tuple[MultiAxisStyle, ...]


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


class FontSpec(NamedTuple):
    family: str | None = None
    style: str | None = None
    postscript_name: str | None = None
    full_name: str | None = None
    system: str | None = None
    axes: tuple[tuple[str, float], ...] = ()
    variable_name: str | None = None
    features: tuple[ParsedFontFeature, ...] = ()
    created_from_string: str = ''

    @classmethod
    def from_setting(cls, spec: str) -> 'FontSpec':
        if spec == 'auto':
            return FontSpec(system='auto', created_from_string=spec)
        items = tuple(shlex_split(spec))
        if '=' not in items[0]:
            return FontSpec(system=spec, created_from_string=spec)
        axes = {}
        defined = {}
        features: tuple[ParsedFontFeature, ...] = ()
        for item in items:
            k, sep, v = item.partition('=')
            if sep != '=':
                raise ValueError(f'The font specification: {spec} is not valid as {item} does not contain an =')
            if k in ('family', 'style', 'full_name', 'postscript_name', 'variable_name'):
                defined[k] = v
            elif k == 'features':
                features += tuple(ParsedFontFeature(x) for x in v.split())
            else:
                try:
                    axes[k] = float(v)
                except Exception:
                    raise ValueError(f'The font specification: {spec} is not valid as {v} is not a number')
        return FontSpec(axes=tuple(axes.items()), created_from_string=spec, features=features, **defined)

    @property
    def is_system(self) -> bool:
        return bool(self.system)

    @property
    def is_auto(self) -> bool:
        return self.system == 'auto'

    @property
    def as_setting(self) -> str:
        if self.created_from_string:
            return self.created_from_string
        if self.system:
            return self.system
        ans = []
        from shlex import quote
        def a(key: str, val: str) -> None:
            ans.append(f'{key}={quote(val)}')

        if self.family is not None:
            a('family', self.family)
        if self.postscript_name is not None:
            a('postscript_name', self.postscript_name)
        if self.full_name is not None:
            a('full_name', self.full_name)
        if self.variable_name is not None:
            a('variable_name', self.variable_name)
        if self.style is not None:
            a('style', self.style)
        if self.features:
            a('features', ' '.join(str(f) for f in self.features))
        if self.axes:
            for (key, val) in self.axes:
                a(key, f'{val:g}')
        return ' '.join(ans)

    def __str__(self) -> str:
        return self.as_setting

    # Cannot change __repr__ as it will break config generation


Descriptor = Union[FontConfigPattern, CoreTextFont]
DescriptorVar = TypeVar('DescriptorVar', FontConfigPattern, CoreTextFont, Descriptor)


class Score(NamedTuple):
    variable_score: int
    style_score: float
    monospace_score: int
    width_score: int


class Scorer:

    def __init__(self, bold: bool = False, italic: bool = False, monospaced: bool = True, prefer_variable: bool = False) -> None:
        self.bold = bold
        self.italic = italic
        self.monospaced = monospaced
        self.prefer_variable = prefer_variable

    def sorted_candidates(self, candidates: Sequence[DescriptorVar], dump: bool = False) -> list[DescriptorVar]:
        raise NotImplementedError()

    def __repr__(self) -> str:
        return f'{self.__class__.__name__}(bold={self.bold}, italic={self.italic}, monospaced={self.monospaced}, prefer_variable={self.prefer_variable})'
    __str__ = __repr__


@run_once
def fnname_pat() -> 're.Pattern[str]':
    import re
    return re.compile(r'\s+')


def family_name_to_key(family: str) -> str:
    return fnname_pat().sub(' ', family).strip().lower()
