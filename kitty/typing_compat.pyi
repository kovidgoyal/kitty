import array
import mmap
from asyncio import AbstractEventLoop as AbstractEventLoop
from socket import AddressFamily as AddressFamily
from socket import socket as Socket
from subprocess import CompletedProcess as CompletedProcess
from subprocess import Popen as PopenType
from typing import Literal
from typing import NotRequired as NotRequired
from typing import Protocol as Protocol
from typing import TypedDict as TypedDict

from kittens.hints.main import Mark as MarkType
from kittens.tui.handler import Handler as HandlerType
from kittens.tui.images import GraphicsCommand as GraphicsCommandType
from kittens.tui.images import ImageManager as ImageManagerType
from kittens.tui.loop import Debug as Debug
from kittens.tui.loop import Loop as LoopType
from kittens.tui.loop import MouseButton as MouseButton
from kittens.tui.loop import MouseEvent as MouseEvent
from kittens.tui.loop import TermManager as TermManagerType

from .boss import Boss as BossType
from .child import Child as ChildType
from .conf.utils import BadLine as BadLineType
from .conf.utils import KeyAction as KeyActionType
from .config import KittyCommonOpts
from .fast_data_types import CoreTextFont as CoreTextFont
from .fast_data_types import FontConfigPattern as FontConfigPattern
from .fast_data_types import Screen as ScreenType
from .fast_data_types import StartupCtx as StartupCtx
from .key_encoding import KeyEvent as KeyEventType
from .layout.base import Layout as LayoutType
from .options.utils import AliasMap as AliasMap
from .options.utils import KeyMap as KeyMap
from .rc.base import RemoteCommand as RemoteCommandType
from .session import Session as SessionType
from .session import Tab as SessionTab
from .tabs import SpecialWindowInstance as SpecialWindowInstance
from .tabs import Tab as TabType
from .utils import ScreenSize as ScreenSize
from .window import Window as WindowType

EdgeLiteral = Literal['left', 'top', 'right', 'bottom']
UnderlineLiteral = Literal['straight', 'double', 'curly', 'dotted', 'dashed']
MatchType = Literal['mime', 'ext', 'protocol', 'file', 'path', 'url', 'fragment_matches']
PowerlineStyle = Literal['angled', 'slanted', 'round']
GRT_a = Literal['t', 'T', 'q', 'p', 'd', 'f', 'a', 'c']
GRT_f = Literal[24, 32, 100]
GRT_t = Literal['d', 'f', 't', 's']
GRT_o = Literal['z', 'z']  # two z's to workaround a bug in ruff
GRT_m = Literal[0, 1]
GRT_C = Literal[0, 1]
GRT_d = Literal['a', 'A', 'c', 'C', 'i', 'I', 'p', 'P', 'q', 'Q', 'x', 'X', 'y', 'Y', 'z', 'Z', 'f', 'F']
ReadableBuffer = bytes | bytearray | memoryview | array.array[int] | mmap.mmap
WriteableBuffer = bytearray | memoryview | array.array[int] | mmap.mmap



class WindowSystemMouseEvent(TypedDict):
    button: int
    count: int
    mods: int


__all__ = (
    'EdgeLiteral', 'MatchType', 'GRT_a', 'GRT_f', 'GRT_t', 'GRT_o', 'GRT_m', 'GRT_d',
    'GraphicsCommandType', 'HandlerType', 'AbstractEventLoop', 'AddressFamily', 'Socket', 'CompletedProcess',
    'PopenType', 'Protocol', 'TypedDict', 'MarkType', 'ImageManagerType', 'Debug', 'LoopType', 'MouseEvent',
    'TermManagerType', 'BossType', 'ChildType', 'BadLineType', 'MouseButton', 'NotRequired',
    'KeyActionType', 'KeyMap', 'KittyCommonOpts', 'AliasMap', 'CoreTextFont', 'WindowSystemMouseEvent',
    'FontConfigPattern', 'ScreenType', 'StartupCtx', 'KeyEventType', 'LayoutType', 'PowerlineStyle',
    'RemoteCommandType', 'SessionType', 'SessionTab', 'SpecialWindowInstance', 'TabType', 'ScreenSize', 'WindowType',
    'ReadableBuffer', 'WriteableBuffer',
)
