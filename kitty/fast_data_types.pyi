from ctypes import Array
from typing import (
    Any, AnyStr, Callable, Dict, List, NewType, Optional, Tuple, TypedDict,
    Union
)

from kitty.boss import Boss
from kitty.fonts.render import FontObject
from kitty.options_stub import Options

# Constants {{{
KITTY_VCS_REV: str
ERROR_PREFIX: str
GLSL_VERSION: int
GLFW_IBEAM_CURSOR: int
GLFW_KEY_UNKNOWN: int
GLFW_KEY_SPACE: int
GLFW_KEY_EXCLAM: int
GLFW_KEY_DOUBLE_QUOTE: int
GLFW_KEY_NUMBER_SIGN: int
GLFW_KEY_DOLLAR: int
GLFW_KEY_AMPERSAND: int
GLFW_KEY_APOSTROPHE: int
GLFW_KEY_PARENTHESIS_LEFT: int
GLFW_KEY_PARENTHESIS_RIGHT: int
GLFW_KEY_PLUS: int
GLFW_KEY_COMMA: int
GLFW_KEY_MINUS: int
GLFW_KEY_PERIOD: int
GLFW_KEY_SLASH: int
GLFW_KEY_0: int
GLFW_KEY_1: int
GLFW_KEY_2: int
GLFW_KEY_3: int
GLFW_KEY_4: int
GLFW_KEY_5: int
GLFW_KEY_6: int
GLFW_KEY_7: int
GLFW_KEY_8: int
GLFW_KEY_9: int
GLFW_KEY_COLON: int
GLFW_KEY_SEMICOLON: int
GLFW_KEY_LESS: int
GLFW_KEY_EQUAL: int
GLFW_KEY_GREATER: int
GLFW_KEY_AT: int
GLFW_KEY_A: int
GLFW_KEY_B: int
GLFW_KEY_C: int
GLFW_KEY_D: int
GLFW_KEY_E: int
GLFW_KEY_F: int
GLFW_KEY_G: int
GLFW_KEY_H: int
GLFW_KEY_I: int
GLFW_KEY_J: int
GLFW_KEY_K: int
GLFW_KEY_L: int
GLFW_KEY_M: int
GLFW_KEY_N: int
GLFW_KEY_O: int
GLFW_KEY_P: int
GLFW_KEY_Q: int
GLFW_KEY_R: int
GLFW_KEY_S: int
GLFW_KEY_T: int
GLFW_KEY_U: int
GLFW_KEY_V: int
GLFW_KEY_W: int
GLFW_KEY_X: int
GLFW_KEY_Y: int
GLFW_KEY_Z: int
GLFW_KEY_LEFT_BRACKET: int
GLFW_KEY_BACKSLASH: int
GLFW_KEY_RIGHT_BRACKET: int
GLFW_KEY_CIRCUMFLEX: int
GLFW_KEY_UNDERSCORE: int
GLFW_KEY_GRAVE_ACCENT: int
GLFW_KEY_WORLD_1: int
GLFW_KEY_WORLD_2: int
GLFW_KEY_PARAGRAPH: int
GLFW_KEY_MASCULINE: int
GLFW_KEY_A_GRAVE: int
GLFW_KEY_A_DIAERESIS: int
GLFW_KEY_A_RING: int
GLFW_KEY_AE: int
GLFW_KEY_C_CEDILLA: int
GLFW_KEY_E_GRAVE: int
GLFW_KEY_E_ACUTE: int
GLFW_KEY_I_GRAVE: int
GLFW_KEY_N_TILDE: int
GLFW_KEY_O_GRAVE: int
GLFW_KEY_O_DIAERESIS: int
GLFW_KEY_O_SLASH: int
GLFW_KEY_U_GRAVE: int
GLFW_KEY_U_DIAERESIS: int
GLFW_KEY_S_SHARP: int
GLFW_KEY_CYRILLIC_A: int
GLFW_KEY_CYRILLIC_BE: int
GLFW_KEY_CYRILLIC_VE: int
GLFW_KEY_CYRILLIC_GHE: int
GLFW_KEY_CYRILLIC_DE: int
GLFW_KEY_CYRILLIC_IE: int
GLFW_KEY_CYRILLIC_ZHE: int
GLFW_KEY_CYRILLIC_ZE: int
GLFW_KEY_CYRILLIC_I: int
GLFW_KEY_CYRILLIC_SHORT_I: int
GLFW_KEY_CYRILLIC_KA: int
GLFW_KEY_CYRILLIC_EL: int
GLFW_KEY_CYRILLIC_EM: int
GLFW_KEY_CYRILLIC_EN: int
GLFW_KEY_CYRILLIC_O: int
GLFW_KEY_CYRILLIC_PE: int
GLFW_KEY_CYRILLIC_ER: int
GLFW_KEY_CYRILLIC_ES: int
GLFW_KEY_CYRILLIC_TE: int
GLFW_KEY_CYRILLIC_U: int
GLFW_KEY_CYRILLIC_EF: int
GLFW_KEY_CYRILLIC_HA: int
GLFW_KEY_CYRILLIC_TSE: int
GLFW_KEY_CYRILLIC_CHE: int
GLFW_KEY_CYRILLIC_SHA: int
GLFW_KEY_CYRILLIC_SHCHA: int
GLFW_KEY_CYRILLIC_HARD_SIGN: int
GLFW_KEY_CYRILLIC_YERU: int
GLFW_KEY_CYRILLIC_SOFT_SIGN: int
GLFW_KEY_CYRILLIC_E: int
GLFW_KEY_CYRILLIC_YU: int
GLFW_KEY_CYRILLIC_YA: int
GLFW_KEY_CYRILLIC_IO: int
GLFW_KEY_LAST_PRINTABLE: int
GLFW_KEY_ESCAPE: int
GLFW_KEY_ENTER: int
GLFW_KEY_TAB: int
GLFW_KEY_BACKSPACE: int
GLFW_KEY_INSERT: int
GLFW_KEY_DELETE: int
GLFW_KEY_RIGHT: int
GLFW_KEY_LEFT: int
GLFW_KEY_DOWN: int
GLFW_KEY_UP: int
GLFW_KEY_PAGE_UP: int
GLFW_KEY_PAGE_DOWN: int
GLFW_KEY_HOME: int
GLFW_KEY_END: int
GLFW_KEY_CAPS_LOCK: int
GLFW_KEY_SCROLL_LOCK: int
GLFW_KEY_NUM_LOCK: int
GLFW_KEY_PRINT_SCREEN: int
GLFW_KEY_PAUSE: int
GLFW_KEY_F1: int
GLFW_KEY_F2: int
GLFW_KEY_F3: int
GLFW_KEY_F4: int
GLFW_KEY_F5: int
GLFW_KEY_F6: int
GLFW_KEY_F7: int
GLFW_KEY_F8: int
GLFW_KEY_F9: int
GLFW_KEY_F10: int
GLFW_KEY_F11: int
GLFW_KEY_F12: int
GLFW_KEY_F13: int
GLFW_KEY_F14: int
GLFW_KEY_F15: int
GLFW_KEY_F16: int
GLFW_KEY_F17: int
GLFW_KEY_F18: int
GLFW_KEY_F19: int
GLFW_KEY_F20: int
GLFW_KEY_F21: int
GLFW_KEY_F22: int
GLFW_KEY_F23: int
GLFW_KEY_F24: int
GLFW_KEY_F25: int
GLFW_KEY_KP_0: int
GLFW_KEY_KP_1: int
GLFW_KEY_KP_2: int
GLFW_KEY_KP_3: int
GLFW_KEY_KP_4: int
GLFW_KEY_KP_5: int
GLFW_KEY_KP_6: int
GLFW_KEY_KP_7: int
GLFW_KEY_KP_8: int
GLFW_KEY_KP_9: int
GLFW_KEY_KP_DECIMAL: int
GLFW_KEY_KP_DIVIDE: int
GLFW_KEY_KP_MULTIPLY: int
GLFW_KEY_KP_SUBTRACT: int
GLFW_KEY_KP_ADD: int
GLFW_KEY_KP_ENTER: int
GLFW_KEY_KP_EQUAL: int
GLFW_KEY_LEFT_SHIFT: int
GLFW_KEY_LEFT_CONTROL: int
GLFW_KEY_LEFT_ALT: int
GLFW_KEY_LEFT_SUPER: int
GLFW_KEY_RIGHT_SHIFT: int
GLFW_KEY_RIGHT_CONTROL: int
GLFW_KEY_RIGHT_ALT: int
GLFW_KEY_RIGHT_SUPER: int
GLFW_KEY_MENU: int
GLFW_KEY_LAST: int
GLFW_MOD_SHIFT: int
GLFW_MOD_CONTROL: int
GLFW_MOD_ALT: int
GLFW_MOD_SUPER: int
GLFW_MOD_KITTY: int
GLFW_MOUSE_BUTTON_1: int
GLFW_MOUSE_BUTTON_2: int
GLFW_MOUSE_BUTTON_3: int
GLFW_MOUSE_BUTTON_4: int
GLFW_MOUSE_BUTTON_5: int
GLFW_MOUSE_BUTTON_6: int
GLFW_MOUSE_BUTTON_7: int
GLFW_MOUSE_BUTTON_8: int
GLFW_MOUSE_BUTTON_LAST: int
GLFW_MOUSE_BUTTON_LEFT: int
GLFW_MOUSE_BUTTON_RIGHT: int
GLFW_MOUSE_BUTTON_MIDDLE: int
GLFW_JOYSTICK_1: int
GLFW_JOYSTICK_2: int
GLFW_JOYSTICK_3: int
GLFW_JOYSTICK_4: int
GLFW_JOYSTICK_5: int
GLFW_JOYSTICK_6: int
GLFW_JOYSTICK_7: int
GLFW_JOYSTICK_8: int
GLFW_JOYSTICK_9: int
GLFW_JOYSTICK_10: int
GLFW_JOYSTICK_11: int
GLFW_JOYSTICK_12: int
GLFW_JOYSTICK_13: int
GLFW_JOYSTICK_14: int
GLFW_JOYSTICK_15: int
GLFW_JOYSTICK_16: int
GLFW_JOYSTICK_LAST: int
GLFW_NOT_INITIALIZED: int
GLFW_NO_CURRENT_CONTEXT: int
GLFW_INVALID_ENUM: int
GLFW_INVALID_VALUE: int
GLFW_OUT_OF_MEMORY: int
GLFW_API_UNAVAILABLE: int
GLFW_VERSION_UNAVAILABLE: int
GLFW_PLATFORM_ERROR: int
GLFW_FORMAT_UNAVAILABLE: int
GLFW_FOCUSED: int
GLFW_ICONIFIED: int
GLFW_RESIZABLE: int
GLFW_VISIBLE: int
GLFW_DECORATED: int
GLFW_AUTO_ICONIFY: int
GLFW_FLOATING: int
GLFW_RED_BITS: int
GLFW_GREEN_BITS: int
GLFW_BLUE_BITS: int
GLFW_ALPHA_BITS: int
GLFW_DEPTH_BITS: int
GLFW_STENCIL_BITS: int
GLFW_ACCUM_RED_BITS: int
GLFW_ACCUM_GREEN_BITS: int
GLFW_ACCUM_BLUE_BITS: int
GLFW_ACCUM_ALPHA_BITS: int
GLFW_AUX_BUFFERS: int
GLFW_STEREO: int
GLFW_SAMPLES: int
GLFW_SRGB_CAPABLE: int
GLFW_REFRESH_RATE: int
GLFW_DOUBLEBUFFER: int
GLFW_CLIENT_API: int
GLFW_CONTEXT_VERSION_MAJOR: int
GLFW_CONTEXT_VERSION_MINOR: int
GLFW_CONTEXT_REVISION: int
GLFW_CONTEXT_ROBUSTNESS: int
GLFW_OPENGL_FORWARD_COMPAT: int
GLFW_OPENGL_DEBUG_CONTEXT: int
GLFW_OPENGL_PROFILE: int
GLFW_OPENGL_API: int
GLFW_OPENGL_ES_API: int
GLFW_NO_ROBUSTNESS: int
GLFW_NO_RESET_NOTIFICATION: int
GLFW_LOSE_CONTEXT_ON_RESET: int
GLFW_OPENGL_ANY_PROFILE: int
GLFW_OPENGL_CORE_PROFILE: int
GLFW_OPENGL_COMPAT_PROFILE: int
GLFW_CURSOR: int
GLFW_STICKY_KEYS: int
GLFW_STICKY_MOUSE_BUTTONS: int
GLFW_CURSOR_NORMAL: int
GLFW_CURSOR_HIDDEN: int
GLFW_CURSOR_DISABLED: int
GLFW_CONNECTED: int
GLFW_DISCONNECTED: int
GLFW_PRESS: int
GLFW_RELEASE: int
GLFW_REPEAT: int
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
FC_WIDTH_NORMAL: int
FC_SLANT_ROMAN: int
FC_SLANT_ITALIC: int
BORDERS_PROGRAM: int
# }}}


def log_error_string(s: str) -> None:
    pass


def set_primary_selection(x: Union[bytes, str]) -> None:
    pass


def get_primary_selection() -> Optional[bytes]:
    pass


def redirect_std_streams(devnull: str) -> None:
    pass


def glfw_get_key_name(key: int, native_key: int) -> Optional[str]:
    pass


StartupCtx = NewType('StartupCtx', int)
Display = NewType('Display', int)


def init_x11_startup_notification(
    display: Display,
    window_id: int,
    startup_id: Optional[str] = None
) -> StartupCtx:
    pass


def end_x11_startup_notification(ctx: StartupCtx) -> None:
    pass


def x11_display() -> Optional[Display]:
    pass


def user_cache_dir() -> str:
    pass


def process_group_map() -> Tuple[Tuple[int, int], ...]:
    pass


def environ_of_process(pid: int) -> str:
    pass


def cmdline_of_process(pid: int) -> List[str]:
    pass


def cwd_of_process(pid: int) -> str:
    pass


def default_color_table() -> Tuple[int, ...]:
    pass


class FontConfigPattern(TypedDict):
    path: str
    index: int
    family: str
    full_name: str
    postscript_name: str
    style: str
    spacing: str
    weight: int
    width: int
    slant: int
    hint_style: int
    subpixel: int
    lcdfilter: int
    hinting: bool
    scalable: bool
    outline: bool
    color: bool


def fc_list(
    spacing: int = -1,
    allow_bitmapped_fonts: bool = False
) -> Tuple[FontConfigPattern, ...]:
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


class CoreTextFont(TypedDict):
    path: str
    postscript_name: str
    family: str
    style: str
    bold: bool
    italic: bool
    expanded: bool
    condensed: bool
    color_glyphs: bool
    monospace: bool
    weight: float
    width: float
    traits: int


def coretext_all_fonts() -> Tuple[CoreTextFont, ...]:
    pass


def add_timer(
    callback: Callable[[Optional[int]], bool],
    interval: float,
    repeats: bool = True
) -> int:
    pass


def monitor_pid(pid: int) -> None:
    pass


def add_window(os_window_id: int, tab_id: int, title: str) -> int:
    pass


def compile_program(
    which: int, vertex_shader: str, fragment_shader: str
) -> int:
    pass


def init_cell_program() -> None:
    pass


def set_titlebar_color(os_window_id: int, color: int) -> bool:
    pass


def add_borders_rect(
    os_window_id: int, tab_id: int, left: int, top: int, right: int,
    bottom: int, color: int
) -> None:
    pass


def init_borders_program() -> None:
    pass


def os_window_has_background_image(os_window_id: int) -> bool:
    pass


def dbus_send_notification(
    app_name: str,
    icon: str,
    summary: str,
    body: str,
    action_name: str,
    timeout: int = -1
) -> int:
    pass


def cocoa_send_notification(
    identifier: Optional[str],
    title: str,
    informative_text: str,
    path_to_img: Optional[str],
    subtitle: Optional[str] = None
) -> None:
    pass


def create_os_window(
    get_window_size: Callable[[int, int, int, int, float, float], Tuple[int,
                                                                        int]],
    pre_show_callback: Callable[[int], None],
    title: str,
    wm_class_name: str,
    wm_class_class: str,
    load_programs: Optional[Callable[[bool], None]] = None,
    x: int = -1,
    y: int = -1
) -> int:
    pass


def update_window_title(
    os_window_id: int, tab_id: int, window_id: int, title: str
) -> None:
    pass


def update_window_visibility(
    os_window_id: int, tab_id: int, window_id: int, window_idx: int,
    visible: bool
) -> None:
    pass


def set_options(
    opts: Options,
    is_wayland: bool = False,
    debug_gl: bool = False,
    debug_font_fallback: bool = False
) -> None:
    pass


def resolve_key_mods(kitty_mod: int, mods: int) -> int:
    pass


def parse_font_feature(ff: str) -> bytes:
    pass


def glfw_primary_monitor_size() -> Tuple[int, int]:
    pass


def set_smallest_allowed_resize(width: int, height: int) -> None:
    pass


def set_default_window_icon(data: bytes, width: int, height: int) -> None:
    pass


def set_custom_cursor(
    cursor_type: int,
    images: Tuple[Tuple[bytes, int, int], ...],
    x: int = 0,
    y: int = 0
) -> None:
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


def set_clipboard_string(data: AnyStr) -> None:
    pass


def set_background_image(
    path: Optional[str],
    os_window_ids: Tuple[int, ...],
    configured: bool = True,
    layout_name: Optional[str] = None
) -> None:
    pass


def set_boss(boss: Boss) -> None:
    pass


def get_boss() -> Boss:  # this can return None but we ignore that for convenience
    pass


def safe_pipe(nonblock: bool = True) -> Tuple[int, int]:
    pass


def patch_global_colors(spec: Dict[str, int], configured: bool) -> None:
    pass


class ColorProfile:

    default_bg: int

    def as_dict(self) -> Dict:
        pass

    def as_color(self, val: int) -> Tuple[int, int, int]:
        pass

    def set_color(self, num: int, val: int) -> None:
        pass

    def reset_color_table(self) -> None:
        pass

    def reset_color(self, num: int) -> None:
        pass

    def update_ansi_color_table(self, val: List[int]) -> None:
        pass

    def set_configured_colors(
        self, fg: int, bg: int, cursor: int = 0, cursor_text: int = 0, cursor_text_uses_bg: int = 0, highlight_fg: int = 0, highlight_bg: int = 0
    ) -> None:
        pass


def patch_color_profiles(
    spec: Dict[str, int], cursor_text_color: Optional[Union[bool, int]],
    profiles: Tuple[ColorProfile, ...], change_configured: bool
) -> None:
    pass


def os_window_font_size(
    os_window_id: int, new_sz: float = -1., force: bool = False
) -> float:
    pass


def cocoa_set_notification_activated_callback(identifier: Callable[[str], None]) -> None:
    pass


def cocoa_set_new_window_trigger(mods: int, key: int) -> bool:
    pass


def cocoa_get_lang() -> Optional[str]:
    pass


def mark_os_window_for_close(os_window_id: int, yes: bool = True) -> bool:
    pass


def global_font_size(val: float = -1.) -> float:
    pass


def get_clipboard_string() -> str:
    pass


def focus_os_window(os_window_id: int, also_raise: bool = True) -> bool:
    pass


def start_profiler(path: str) -> None:
    pass


def stop_profiler() -> None:
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


def swap_windows(os_window_id: int, tab_id: int, a: int, b: int) -> None:
    pass


def set_active_tab(os_window_id: int, a: int) -> None:
    pass


def set_active_window(os_window_id: int, tab_id: int, window_idx: int) -> None:
    pass


def ring_bell() -> None:
    pass


def concat_cells(cell_width: int, cell_height: int, is_32_bit: bool, cells: Tuple[bytes, ...]) -> bytes:
    pass


def current_fonts() -> Dict[str, Any]:
    pass


def remove_window(os_window_id: int, tab_id: int, window_id: int) -> None:
    pass


def remove_tab(os_window_id: int, tab_id: int) -> None:
    pass


def pt_to_px(pt: float, os_window_id: int = 0) -> int:
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


class Region:
    left: int
    top: int
    right: int
    bottom: int
    width: int
    height: int

    def __init__(self, x: Tuple[int, int, int, int, int, int]):
        pass


def viewport_for_window(
    os_window_id: int
) -> Tuple[Region, Region, int, int, int, int]:
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
    text_callback: Callable[[str], None], dcs_callback: Callable[[str], None],
    csi_callback: Callable[[str], None], osc_callback: Callable[[str], None],
    pm_callback: Callable[[str], None], apc_callback: Callable[[str], None],
    data: str, in_bracketed_paste: bool
) -> str:
    pass


class Line:

    def sprite_at(self, cell: int) -> Tuple[int, int, int]:
        pass


def test_shape(line: Line,
               path: Optional[str] = None,
               index: int = 0) -> List[Tuple[int, int, int, Tuple[int, ...]]]:
    pass


def test_render_line(line: Line) -> None:
    pass


def sprite_map_set_limits(w: int, h: int) -> None:
    pass


def set_send_sprite_to_gpu(
    func: Optional[Callable[[int, int, int, bytes], None]]
) -> None:
    pass


def set_font_data(
    box_drawing_func: Callable[[int, int, int, float],
                               Tuple[int, Union[bytearray, bytes, Array]]],
    prerender_func: Callable[
        [int, int, int, int, int, int, int, float, float, float, float],
        Tuple[Union[Array, int], ...]],
    descriptor_for_idx: Callable[[int], Tuple[FontObject, bool, bool]],
    bold: int, italic: int, bold_italic: int, num_symbol_fonts: int,
    symbol_maps: Tuple[Tuple[int, int, int], ...], font_sz_in_pts: float,
    font_feature_settings: Dict[str, Tuple[str, ...]]
) -> None:
    pass


def get_fallback_font(text: str, bold: bool, italic: bool) -> Any:
    pass


def create_test_font_group(sz: float, dpix: float,
                           dpiy: float) -> Tuple[int, int]:
    pass


class HistoryBuf:

    def as_text(self, callback: Callable[[str], None], as_ansi: bool, insert_wrap_markers: bool) -> None:
        pass

    def pagerhist_as_text(self, callback: Callable[[str], None]) -> None:
        pass


class LineBuf:

    def is_continued(self, idx: int) -> bool:
        pass

    def line(self, num: int) -> Line:
        pass


class Cursor:
    x: int
    y: int
    bg: int
    fg: int
    bold: bool
    italic: bool


class Screen:

    color_profile: ColorProfile
    columns: int
    lines: int
    focus_tracking_enabled: bool
    historybuf: HistoryBuf
    linebuf: LineBuf
    in_bracketed_paste_mode: bool
    scrolled_by: int
    cursor: Cursor
    disable_ligatures: int
    extended_keyboard: bool
    cursor_key_mode: bool
    auto_repeat_enabled: bool

    def __init__(
            self,
            callbacks: Any = None,
            lines: int = 80, columns: int = 24, scrollback: int = 0,
            cell_width: int = 10, cell_height: int = 20,
            window_id: int = 0,
            test_child: Any = None
    ):
        pass

    def line(self, num: int) -> Line:
        pass

    def draw(self, text: str) -> None:
        pass

    def copy_colors_from(self, other: 'Screen') -> None:
        pass

    def mark_as_dirty(self) -> None:
        pass

    def resize(self, width: int, height: int) -> None:
        pass

    def send_escape_code_to_child(self, code: int, text: str) -> None:
        pass

    def reset_callbacks(self) -> None:
        pass

    def text_for_selection(self) -> Tuple[str, ...]:
        pass

    def is_rectangle_select(self) -> bool:
        pass

    def is_using_alternate_linebuf(self) -> bool:
        pass

    def is_main_linebuf(self) -> bool:
        pass

    def erase_in_line(self, mode: int = 0, private: bool = False) -> None:
        pass

    def scroll(self, amt: int, upwards: bool) -> bool:
        pass

    def scroll_to_next_mark(self, mark: int = 0, backwards: bool = True) -> bool:
        pass

    def clear_selection(self) -> None:
        pass

    def reset_mode(self, mode: int, private: bool = False) -> None:
        pass

    def refresh_sprite_positions(self) -> None:
        pass

    def set_marker(self, marker: Optional[Callable] = None) -> None:
        pass

    def paste_bytes(self, data: bytes) -> None:
        pass
    paste = paste_bytes

    def as_text(self, callback: Callable[[str], None], as_ansi: bool, insert_wrap_markers: bool) -> None:
        pass
    as_text_non_visual = as_text
    as_text_alternate = as_text

    def scroll_until_cursor(self) -> None:
        pass

    def reset(self) -> None:
        pass

    def erase_in_display(self, how: int = 0, private: bool = False) -> None:
        pass


def set_tab_bar_render_data(
    os_window_id: int, xstart: float, ystart: float, dx: float, dy: float,
    screen: Screen
) -> None:
    pass


def set_window_render_data(
    os_window_id: int, tab_id: int, window_id: int, window_idx: int,
    xstart: float, ystart: float, dx: float, dy: float, screen: Screen,
    left: int, top: int, right: int, bottom: int
) -> None:
    pass


def truncate_point_for_length(
    text: str, num_cells: int, start_pos: int = 0
) -> int:
    pass


class ChildMonitor:

    def __init__(
        self,
        death_notify: Callable[[int], None],
        dump_callback: Optional[Callable],
        talk_fd: int = -1,
        listen_fd: int = -1
    ):
        pass

    def wakeup(self) -> None:
        pass

    def main_loop(self) -> None:
        pass

    def resize_pty(self, window_id: int, rows: int, cols: int, x_pixels: int, y_pixels: int) -> None:
        pass

    def needs_write(self, child_id: int, data: Union[bytes, str]) -> bool:
        pass

    def set_iutf8_winid(self, win_id: int, on: bool) -> bool:
        pass

    def add_child(self, id: int, pid: int, fd: int, screen: Screen) -> None:
        pass

    def mark_for_close(self, window_id: int) -> None:
        pass

    def start(self) -> None:
        pass

    def shutdown_monitor(self) -> None:
        pass


def set_iutf8_fd(fd: int, on: bool) -> bool:
    pass


def spawn(
    exe: str,
    cwd: str,
    argv: Tuple[str, ...],
    env: Tuple[str, ...],
    master: int,
    slave: int,
    stdin_read_fd: int,
    stdin_write_fd: int,
    ready_read_fd: int,
    ready_write_fd: int
) -> int:
    pass


def key_to_bytes(glfw_key: int, smkx: bool, extended: bool, mods: int, action: int) -> bytes:
    pass
