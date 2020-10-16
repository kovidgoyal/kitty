from asyncio import AbstractEventLoop as AbstractEventLoop  # noqa
from socket import AddressFamily as AddressFamily, socket as Socket  # noqa
from typing import (  # noqa
    Literal, Protocol as Protocol, TypedDict as TypedDict
)

from kittens.hints.main import Mark as MarkType  # noqa
from kittens.tui.handler import Handler as HandlerType  # noqa
from kittens.tui.images import (  # noqa
    GraphicsCommand as GraphicsCommandType, ImageManager as ImageManagerType
)
from kittens.tui.loop import (  # noqa
    Debug as Debug, Loop as LoopType, MouseEvent as MouseEvent,
    TermManager as TermManagerType
)
from kitty.conf.utils import KittensKeyAction as KittensKeyActionType  # noqa

from .boss import Boss as BossType  # noqa
from .child import Child as ChildType  # noqa
from .conf.utils import BadLine as BadLineType  # noqa
from .fast_data_types import (  # noqa
    CoreTextFont as CoreTextFont, FontConfigPattern as FontConfigPattern,
    Screen as ScreenType, StartupCtx as StartupCtx
)
from .key_encoding import KeyEvent as KeyEventType  # noqa
from .layout.base import Layout as LayoutType  # noqa
from .rc.base import RemoteCommand as RemoteCommandType  # noqa
from .session import Session as SessionType, Tab as SessionTab  # noqa
from .tabs import (  # noqa
    SpecialWindowInstance as SpecialWindowInstance, Tab as TabType
)
from .utils import ScreenSize as ScreenSize  # noqa
from .window import Window as WindowType  # noqa

from subprocess import (  # noqa; noqa
    CompletedProcess as CompletedProcess, Popen as PopenType
)


from .config import (  # noqa; noqa
    KeyAction as KeyActionType, KeyMap as KeyMap, KeySpec as KeySpec,
    KittyCommonOpts as KittyCommonOpts, SequenceMap as SequenceMap
)

EdgeLiteral = Literal['left', 'top', 'right', 'bottom']
MatchType = Literal['mime', 'ext', 'protocol', 'file', 'path', 'url', 'fragment_matches']
GRT_a = Literal['t', 'T', 'q', 'p', 'd']
GRT_f = Literal[24, 32, 100]
GRT_t = Literal['d', 'f', 't', 's']
GRT_o = Literal['z']
GRT_m = Literal[0, 1]
GRT_d = Literal['a', 'A', 'c', 'C', 'i', 'I', 'p', 'P', 'q', 'Q', 'x', 'X', 'y', 'Y', 'z', 'Z']
