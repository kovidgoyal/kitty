from typing import Callable, Mapping, Optional, Tuple

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


def toggle_maximized() -> bool:
    pass


def toggle_fullscreen() -> bool:
    pass


def thread_write(fd: int, data: bytes) -> None:
    pass


def set_in_sequence_mode(yes: bool) -> None:
    pass


def set_clipboard_string(data: bytes) -> None:
    pass


def set_background_image(
        path: Optional[str], os_window_ids: Tuple[int, ...],
        configured: bool = True, layout_name: Optional[str] = None
) -> None:
    pass


def safe_pipe(nonblock: bool = True) -> Tuple[int, int]:
    pass


def patch_global_colors(spec: Mapping[str, int], configured: bool) -> None:
    pass


def os_window_font_size(os_window_id: int, new_sz: float = -1., force: bool = False) -> float:
    pass


def mark_os_window_for_close(os_window_id: int, yes: bool = True) -> bool:
    pass


def global_font_size(val: float = -1.) -> float:
    pass


def get_clipboard_string() -> str:
    pass


def focus_os_window(os_window_id: int, also_raise: bool = True) -> bool:
    pass


def destroy_global_data() -> None:
    pass


def current_os_window() -> Optional[int]:
    pass


def cocoa_set_menubar_title(title: str) -> None:
    pass


def change_os_window_state(state: str) -> None:
    pass


def change_background_opacity(os_window_id: int, opacity: float) -> bool:
    pass


def background_opacity_of(os_window_id: int) -> Optional[float]:
    pass


def read_command_response(fd: int, timeout: float, list) -> None:
    pass


def wcswidth(string: str) -> int:
    pass


def is_emoji_presentation_base(code: int) -> bool:
    pass


class ChildMonitor:

    def __init__(
            self,
            death_notify: Callable[[int], None],
            dump_callback: Optional[callable],
            talk_fd: int = -1, listen_fd: int = -1
    ):
        pass
