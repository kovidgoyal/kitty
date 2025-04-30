#!/usr/bin/env python
# License: GPLv3 Copyright: 2021, Kovid Goyal <kovid at kovidgoyal.net>

from collections.abc import Callable, Iterator, Mapping, Sequence
from enum import Enum
from functools import update_wrapper
from typing import TYPE_CHECKING, Any, Generic, NamedTuple, TypedDict, TypeVar, Union

if TYPE_CHECKING:
    from kitty.fast_data_types import SingleKey

_T = TypeVar('_T')


class SingleInstanceData(TypedDict):
    cmd: str
    args: Sequence[str]
    cmdline_args_for_open: Sequence[str]
    cwd: str
    session_data: str
    environ: Mapping[str, str]
    notify_on_os_window_death: str | None


class OverlayType(Enum):
    transient = 'transient'
    main = 'main'


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


class WindowGeometry(NamedTuple):
    left: int
    top: int
    right: int
    bottom: int
    xnum: int
    ynum: int
    spaces: Edges = Edges()


class SignalInfo(NamedTuple):
    si_signo: int
    si_code: int
    si_pid: int
    si_uid: int
    si_addr: int
    si_status: int
    sival_int: int
    sival_ptr: int


class LayerShellConfig(NamedTuple):
    type: int = 0
    edge: int = 0
    focus_policy: int = 0
    output_name: str = ''
    x_size_in_pixels: int = 0
    y_size_in_pixels: int = 0
    x_size_in_cells: int = 0
    y_size_in_cells: int = 0
    requested_top_margin: int = 0
    requested_left_margin: int = 0
    requested_bottom_margin: int = 0
    requested_right_margin: int = 0
    requested_exclusive_zone: int = -1
    override_exclusive_zone: bool = False
    hide_on_focus_loss: bool = False


def mod_to_names(mods: int, has_kitty_mod: bool = False, kitty_mod: int = 0) -> Iterator[str]:
    if has_kitty_mod:
        mods &= ~kitty_mod
        yield 'kitty_mod'
    for name, val in modmap().items():
        if mods & val:
            yield name


def human_repr_of_single_key(self: 'SingleKey', kitty_mod: int) -> str:
    from .fast_data_types import glfw_get_key_name
    names = []
    names = list(mod_to_names(self.mods, self.defined_with_kitty_mod, kitty_mod))
    if self.key > 0:
        kname = (glfw_get_key_name(0, self.key) if self.is_native else glfw_get_key_name(self.key, 0)) or f'{self.key}'
        kname = {' ': 'space'}.get(kname, kname)
        names.append(kname)
    return '+'.join(names)


class Shortcut(NamedTuple):
    keys: tuple['SingleKey', ...]

    def human_repr(self, kitty_mod: int = 0) -> str:
        return ' > '.join(human_repr_of_single_key(k, kitty_mod) for k in self.keys)


class MouseEvent(NamedTuple):
    button: int = 0
    mods: int = 0
    repeat_count: int = 1
    grabbed: bool = False

    def human_repr(self, kitty_mod: int = 0) -> str:
        from .options.utils import mouse_button_map, mouse_trigger_count_map

        def mouse_button_num_to_name(num: int) -> str:
            button_map = {v: k for k, v in mouse_button_map.items()}
            name = f'b{num+1}'
            return button_map.get(name, name)

        def mouse_trigger_count_to_name(count: int) -> str:
            trigger_count_map = {str(v): k for k, v in mouse_trigger_count_map.items()}
            k = str(count)
            return trigger_count_map.get(k, k)

        names = list(mod_to_names(self.mods)) + [mouse_button_num_to_name(self.button)]
        when = mouse_trigger_count_to_name(self.repeat_count)
        grabbed = 'grabbed' if self.grabbed else 'ungrabbed'
        return ' '.join(('+'.join(names), when, grabbed))


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


@run_once
def modmap() -> dict[str, int]:
    from .constants import is_macos
    from .fast_data_types import (
        GLFW_MOD_ALT,
        GLFW_MOD_CAPS_LOCK,
        GLFW_MOD_CONTROL,
        GLFW_MOD_HYPER,
        GLFW_MOD_META,
        GLFW_MOD_NUM_LOCK,
        GLFW_MOD_SHIFT,
        GLFW_MOD_SUPER,
    )

    return {'ctrl': GLFW_MOD_CONTROL, 'shift': GLFW_MOD_SHIFT, ('opt' if is_macos else 'alt'): GLFW_MOD_ALT,
            ('cmd' if is_macos else 'super'): GLFW_MOD_SUPER, 'hyper': GLFW_MOD_HYPER, 'meta': GLFW_MOD_META,
            'caps_lock': GLFW_MOD_CAPS_LOCK, 'num_lock': GLFW_MOD_NUM_LOCK}


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
