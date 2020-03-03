from typing import Callable, Optional, Tuple
from kitty.cli import Namespace

GLFW_IBEAM_CURSOR: int


def create_os_window(
    get_window_size: Callable[[int, int, int, int, float, float], Tuple[int, int]],
    pre_show_callback: Callable[[object], None],
    title: str,
    wm_class_name: str,
    wm_class_class: str,
    load_programs: Optional[Callable[[bool], None]] = None,
    x: int = -1,
    y: int = -1
) -> int:
    pass


def set_options(
    opts: Namespace,
    is_wayland: bool = False,
    debug_gl: bool = False,
    debug_font_fallback: bool = False
) -> None:
    pass


def set_default_window_icon(data: bytes, width: int, height: int) -> None:
    pass


def set_custom_cursor(cursor_type: int, images: Tuple[Tuple[bytes, int, int], ...], x: int = 0, y: int = 0) -> None:
    pass


def load_png_data(data: bytes) -> Tuple[bytes, int, int]:
    pass


def glfw_terminate() -> None:
    pass


def glfw_init(path: str, debug_keyboard: bool = False) -> bool:
    pass


def free_font_data() -> None:
    pass
