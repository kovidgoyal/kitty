from collections import namedtuple
from typing import (
    Any, Callable, List, Mapping, NewType, Optional, Tuple, Union
)

from kitty.cli import Namespace

GLFW_IBEAM_CURSOR: int
CURSOR_BEAM: int
CURSOR_BLOCK: int
CURSOR_UNDERLINE: int
DECAWM: int
BGIMAGE_PROGRAM: int
BLIT_PROGRAM: int
CELL_BG_PROGRAM: int
CELL_FG_PROGRAM: int
CELL_PROGRAM: int
CELL_SPECIAL_PROGRAM: int
CSI: int
DCS: int
DECORATION: int
DIM: int
GRAPHICS_ALPHA_MASK_PROGRAM: int
GRAPHICS_PREMULT_PROGRAM: int
GRAPHICS_PROGRAM: int
MARK: int
MARK_MASK: int
OSC: int
REVERSE: int
SCROLL_FULL: int
SCROLL_LINE: int
SCROLL_PAGE: int
STRIKETHROUGH: int
TINT_PROGRAM: int
FC_MONO: int = 100
FC_DUAL: int
FC_WEIGHT_REGULAR: int
FC_WEIGHT_BOLD: int
FC_SLANT_ROMAN: int
FC_SLANT_ITALIC: int
BORDERS_PROGRAM: int


def default_color_table() -> Tuple[int, ...]:
    pass


FontConfigPattern = Mapping[str, Union[str, int, bool, float]]


def fc_list(spacing: int = -1, allow_bitmapped_fonts: bool = False) -> Tuple[FontConfigPattern, ...]:
    pass


def fc_match(
    family: Optional[str] = None,
    bold: bool = False,
    italic: bool = False,
    spacing: int = FC_MONO,
    allow_bitmapped_fonts: bool = False,
    size_in_pts: float = 0.,
    dpi: float = 0.
) -> FontConfigPattern:
    pass


def coretext_all_fonts() -> Tuple[Mapping[str, Any], ...]:
    pass


def add_timer(callback: Callable[[int], None], interval: float, repeats: bool = True) -> int:
    pass


def monitor_pid(pid: int) -> None:
    pass


def add_window(os_window_id: int, tab_id: int, title: str) -> int:
    pass


def compile_program(which: int, vertex_shader: str, fragment_shader: str) -> int:
    pass


def init_cell_program() -> None:
    pass


def set_titlebar_color(os_window_id: int, color: int) -> bool:
    pass


def add_borders_rect(os_window_id: int, tab_id: int, left: int, top: int, right: int, bottom: int, color: int) -> None:
    pass


def init_borders_program() -> None:
    pass


def os_window_has_background_image(os_window_id: int) -> bool:
    pass


def dbus_send_notification(app_name: str, icon: str, summary: str, body: str, action_name: str, timeout: int = -1) -> int:
    pass


def cocoa_send_notification(identifier: Optional[str], title: str, informative_text: str, path_to_img: Optional[str], subtitle: Optional[str] = None) -> None:
    pass


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


def update_window_title(os_window_id: int, tab_id: int, window_id: int, title: str) -> None:
    pass


def update_window_visibility(os_window_id: int, tab_id: int, window_id: int, window_idx: int, visible: bool) -> None:
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


def read_command_response(fd: int, timeout: float, list: List) -> None:
    pass


def wcswidth(string: str) -> int:
    pass


def is_emoji_presentation_base(code: int) -> bool:
    pass


def x11_window_id(os_window_id: int) -> int:
    pass


def swap_tabs(os_window_id: int, a: int, b: int) -> None:
    pass


def set_active_tab(os_window_id: int, a: int) -> None:
    pass


def ring_bell() -> None:
    pass


def remove_window(os_window_id: int, tab_id: int, window_id: int) -> None:
    pass


def remove_tab(os_window_id: int, tab_id: int) -> None:
    pass


def pt_to_px(pt: float, os_window_id: int = 0) -> float:
    pass


def next_window_id() -> int:
    pass


def mark_tab_bar_dirty(os_window_id: int) -> None:
    pass


def detach_window(os_window_id: int, tab_id: int, window_id: int) -> None:
    pass


def attach_window(os_window_id: int, tab_id: int, window_id: int) -> None:
    pass


def add_tab(os_window_id: int) -> int:
    pass


def cell_size_for_window(os_window_id: int) -> Tuple[int, int]:
    pass


Region = namedtuple('Region', 'left top right bottom width height')


def viewport_for_window(os_window_id: int) -> Tuple[Region, Region, int, int, int, int]:
    pass


TermiosPtr = NewType('TermiosPtr', int)


def raw_tty(fd: int, termios_ptr: TermiosPtr) -> None:
    pass


def close_tty(fd: int, termios_ptr: TermiosPtr) -> None:
    pass


def normal_tty(fd: int, termios_ptr: TermiosPtr) -> None:
    pass


def open_tty(read_with_timeout: bool = False) -> Tuple[int, TermiosPtr]:
    pass


def parse_input_from_terminal(
    text_callback: Callable[[str], None],
    dcs_callback: Callable[[str], None],
    csi_callback: Callable[[str], None],
    osc_callback: Callable[[str], None],
    pm_callback: Callable[[str], None],
    apc_callback: Callable[[str], None],
    data: str,
    in_bracketed_paste: bool
):
    pass


class Line:
    pass


def test_shape(line: Line, path: Optional[str] = None, index: int = 0) -> List[Tuple[int, int, int, Tuple[int, ...]]]:
    pass


def test_render_line(line: Line) -> None:
    pass


def sprite_map_set_limits(w: int, h: int) -> None:
    pass


def set_send_sprite_to_gpu(func: Callable[[int, int, int, bytes], None]) -> None:
    pass


def set_font_data(
    box_drawing_func: Callable[[int, int, int, float], Tuple[int, Union[bytearray, bytes]]],
    prerender_func: Callable[[int, int, int, int, int, float, float, float, float], Tuple[int, ...]],
    descriptor_for_idx: Callable[[int], Tuple[dict, bool, bool]],
    bold: int, italic: int, bold_italic: int, num_symbol_fonts: int,
    symbol_maps: Tuple[Tuple[int, int, int], ...],
    font_sz_in_pts: float,
    font_feature_settings: Mapping[str, Tuple[bytes, ...]]
):
    pass


def get_fallback_font(text: str, bold: bool, italic: bool):
    pass


def create_test_font_group(sz: float, dpix: float, dpiy: float) -> Tuple[int, int]:
    pass


class Screen:
    pass


def set_tab_bar_render_data(os_window_id: int, xstart: float, ystart: float, dx: float, dy: float, screen: Screen) -> None:
    pass


def set_window_render_data(
        os_window_id: int, tab_id: int, window_id: int, window_idx: int,
        xstart: float, ystart: float, dx: float, dy: float,
        screen: Screen,
        left: int, top: int, right: int, bottom: int
):
    pass


class ChildMonitor:

    def __init__(
            self,
            death_notify: Callable[[int], None],
            dump_callback: Optional[callable],
            talk_fd: int = -1, listen_fd: int = -1
    ):
        pass
