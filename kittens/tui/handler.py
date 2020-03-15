#!/usr/bin/env python3
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2018, Kovid Goyal <kovid at kovidgoyal.net>


from types import TracebackType
from typing import (
    Any, Callable, ContextManager, Dict, Optional, Sequence, Type, Union
)

from kitty.typing import (
    AbstractEventLoop, BossType, Debug, ImageManagerType, KeyEventType,
    KittensKeyActionType, LoopType, MouseEvent, ScreenSize, TermManagerType
)


class Handler:

    image_manager_class: Optional[Type[ImageManagerType]] = None

    def _initialize(
        self,
        screen_size: ScreenSize,
        term_manager: TermManagerType,
        schedule_write: Callable[[bytes], None],
        tui_loop: LoopType,
        debug: Debug,
        image_manager: Optional[ImageManagerType] = None
    ) -> None:
        from .operations import commander
        self.screen_size = screen_size
        self._term_manager = term_manager
        self._tui_loop = tui_loop
        self._schedule_write = schedule_write
        self.debug = debug
        self.cmd = commander(self)
        self._image_manager = image_manager

    @property
    def image_manager(self) -> ImageManagerType:
        assert self._image_manager is not None
        return self._image_manager

    @property
    def asyncio_loop(self) -> AbstractEventLoop:
        return self._tui_loop.asycio_loop

    def add_shortcut(self, action: KittensKeyActionType, key: str, mods: Optional[int] = None, is_text: Optional[bool] = False) -> None:
        if not hasattr(self, '_text_shortcuts'):
            self._text_shortcuts, self._key_shortcuts = {}, {}
        if is_text:
            self._text_shortcuts[key] = action
        else:
            self._key_shortcuts[(key, mods or 0)] = action

    def shortcut_action(self, key_event_or_text: Union[str, KeyEventType]) -> Optional[KittensKeyActionType]:
        if isinstance(key_event_or_text, str):
            return self._text_shortcuts.get(key_event_or_text)
        return self._key_shortcuts.get((key_event_or_text.key, key_event_or_text.mods))

    def __enter__(self) -> None:
        if self._image_manager is not None:
            self._image_manager.__enter__()
        self.debug.fobj = self
        self.initialize()

    def __exit__(self, etype: type, value: Exception, tb: TracebackType) -> None:
        del self.debug.fobj
        self.finalize()
        if self._image_manager is not None:
            self._image_manager.__exit__(etype, value, tb)

    def initialize(self) -> None:
        pass

    def finalize(self) -> None:
        pass

    def on_resize(self, screen_size: ScreenSize) -> None:
        self.screen_size = screen_size

    def quit_loop(self, return_code: Optional[int] = None) -> None:
        self._tui_loop.quit(return_code)

    def on_term(self) -> None:
        self._tui_loop.quit(1)

    def on_text(self, text: str, in_bracketed_paste: bool = False) -> None:
        pass

    def on_key(self, key_event: KeyEventType) -> None:
        pass

    def on_mouse(self, mouse_event: 'MouseEvent') -> None:
        pass

    def on_interrupt(self) -> None:
        pass

    def on_eot(self) -> None:
        pass

    def on_kitty_cmd_response(self, response: Dict) -> None:
        pass

    def on_clipboard_response(self, text: str, from_primary: bool = False) -> None:
        pass

    def on_capability_response(self, name: str, val: str) -> None:
        pass

    def write(self, data: Union[bytes, str]) -> None:
        if isinstance(data, str):
            data = data.encode('utf-8')
        self._schedule_write(data)

    def flush(self) -> None:
        pass

    def print(self, *args: object, sep: str = ' ', end: str = '\r\n') -> None:
        data = sep.join(map(str, args)) + end
        self.write(data)

    def suspend(self) -> ContextManager[TermManagerType]:
        return self._term_manager.suspend()


class HandleResult:

    type_of_input: Optional[str] = None
    no_ui: bool = False

    def __init__(self, impl: Callable, type_of_input: Optional[str], no_ui: bool):
        self.impl = impl
        self.no_ui = no_ui
        self.type_of_input = type_of_input

    def __call__(self, args: Sequence[str], data: Any, target_window_id: int, boss: BossType) -> Any:
        return self.impl(args, data, target_window_id, boss)


def result_handler(type_of_input: Optional[str] = None, no_ui: bool = False) -> Callable[[Callable], HandleResult]:

    def wrapper(impl: Callable) -> HandleResult:
        return HandleResult(impl, type_of_input, no_ui)

    return wrapper
