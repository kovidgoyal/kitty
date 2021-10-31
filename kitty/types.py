#!/usr/bin/env python
# License: GPLv3 Copyright: 2021, Kovid Goyal <kovid at kovidgoyal.net>

from functools import update_wrapper
from typing import (
    TYPE_CHECKING, Any, Callable, Generic, NamedTuple, TypeVar, Union
)

_T = TypeVar('_T')


class ParsedShortcut(NamedTuple):
    mods: int
    key_name: str


class Edges(NamedTuple):
    left: int = 0
    top: int = 0
    right: int = 0
    bottom: int = 0


class FloatEdges(NamedTuple):
    left: float = 0
    top: float = 0
    right: float = 0
    bottom: float = 0


class ScreenGeometry(NamedTuple):
    xstart: float
    ystart: float
    xnum: int
    ynum: int
    dx: float
    dy: float


class WindowGeometry(NamedTuple):
    left: int
    top: int
    right: int
    bottom: int
    xnum: int
    ynum: int
    spaces: Edges = Edges()


class SingleKey(NamedTuple):
    mods: int = 0
    is_native: bool = False
    key: int = -1


class MouseEvent(NamedTuple):
    button: int = 0
    mods: int = 0
    repeat_count: int = 1
    grabbed: bool = False


class WindowSystemMouseEvent(NamedTuple):
    in_tab_bar: bool
    window_id: int
    action: int
    modifiers: int
    button: int
    currently_pressed_button: int
    x: float
    y: float


ConvertibleToNumbers = Union[str, bytes, int, float]


class AsyncResponse:
    pass


if TYPE_CHECKING:
    class RunOnce(Generic[_T]):

        def __init__(self, func: Callable[[], _T]): ...
        def __call__(self) -> _T: ...
        def set_override(self, val: _T) -> None: ...
        def clear_override(self) -> None: ...
        def clear_cached(self) -> None: ...
else:
    class RunOnce:

        def __init__(self, f):
            self._override = RunOnce
            self._cached_result = RunOnce
            update_wrapper(self, f)

        def __call__(self):
            if self._override is not RunOnce:
                return self._override
            if self._cached_result is RunOnce:
                self._cached_result = self.__wrapped__()
            return self._cached_result

        def clear_cached(self):
            self._cached_result = RunOnce

        def set_override(self, val):
            self._override = val

        def clear_override(self):
            self._override = RunOnce


def run_once(f: Callable[[], _T]) -> 'RunOnce[_T]':
    return RunOnce(f)


if TYPE_CHECKING:
    from typing import Literal
    ActionGroup = Literal['cp', 'sc', 'win', 'tab', 'mouse', 'mk', 'lay', 'misc', 'debug']
else:
    ActionGroup = str


class ActionSpec(NamedTuple):
    group: str
    doc: str


def ac(group: ActionGroup, doc: str) -> Callable[[_T], _T]:
    def w(f: _T) -> _T:
        setattr(f, 'action_spec', ActionSpec(group, doc))
        return f
    return w


DecoratedFunc = TypeVar('DecoratedFunc', bound=Callable[..., Any])
