#!/usr/bin/env python
# License: GPL v3 Copyright: 2016, Kovid Goyal <kovid at kovidgoyal.net>

import json
import os
import re
import sys
import weakref
from collections import deque
from collections.abc import Callable, Generator, Iterable, Sequence
from contextlib import contextmanager, suppress
from enum import Enum, IntEnum, auto
from functools import lru_cache, partial
from gettext import gettext as _
from itertools import chain
from re import Pattern
from time import time_ns
from typing import (
    TYPE_CHECKING,
    Any,
    Deque,
    Literal,
    NamedTuple,
    Optional,
    Union,
)

from .child import ProcessDesc
from .cli_stub import CLIOptions
from .clipboard import ClipboardRequestManager, set_clipboard_string
from .constants import (
    appname,
    clear_handled_signals,
    config_dir,
    kitten_exe,
    wakeup_io_loop,
)
from .fast_data_types import (
    CURSOR_BEAM,
    CURSOR_BLOCK,
    CURSOR_UNDERLINE,
    ESC_CSI,
    ESC_DCS,
    ESC_OSC,
    GLFW_MOD_CONTROL,
    GLFW_PRESS,
    GLFW_RELEASE,
    GLFW_REPEAT,
    NO_CURSOR_SHAPE,
    SCROLL_FULL,
    SCROLL_LINE,
    SCROLL_PAGE,
    Color,
    ColorProfile,
    KeyEvent,
    Screen,
    add_timer,
    add_window,
    base64_decode,
    buffer_keys_in_window,
    cell_size_for_window,
    click_mouse_cmd_output,
    click_mouse_url,
    current_focused_os_window_id,
    encode_key_for_tty,
    get_boss,
    get_click_interval,
    get_mouse_data_for_window,
    get_options,
    is_css_pointer_name_valid,
    is_modifier_key,
    last_focused_os_window_id,
    mark_os_window_dirty,
    monotonic,
    mouse_selection,
    move_cursor_to_mouse_if_in_prompt,
    pointer_name_to_css_name,
    pt_to_px,
    replace_c0_codes_except_nl_space_tab,
    set_redirect_keys_to_overlay,
    set_window_logo,
    set_window_padding,
    set_window_render_data,
    update_ime_position_for_window,
    update_pointer_shape,
    update_window_title,
    update_window_visibility,
    wakeup_main_loop,
)
from .keys import keyboard_mode_name, mod_mask
from .options.types import Options
from .progress import Progress
from .rgb import to_color
from .terminfo import get_capabilities
from .types import MouseEvent, OverlayType, WindowGeometry, ac, run_once
from .typing_compat import BossType, ChildType, EdgeLiteral, TabType, TypedDict
from .utils import (
    color_as_int,
    docs_url,
    key_val_matcher,
    kitty_ansi_sanitizer_pat,
    log_error,
    open_cmd,
    open_url,
    path_from_osc7_url,
    resolve_custom_file,
    resolved_shell,
    sanitize_control_codes,
    sanitize_for_bracketed_paste,
    sanitize_title,
    sanitize_url_for_dispay_to_user,
    shlex_split,
)

MatchPatternType = Union[Pattern[str], tuple[Pattern[str], Optional[Pattern[str]]]]


if TYPE_CHECKING:
    from kittens.tui.handler import OpenUrlHandler

    from .fast_data_types import MousePosition
    from .file_transmission import FileTransmission
    from .notifications import OnlyWhen


class CwdRequestType(Enum):
    current = auto()
    last_reported = auto()
    oldest = auto()
    root = auto()


class CwdRequest:

    def __init__(self, window: Optional['Window'] = None, request_type: CwdRequestType = CwdRequestType.current) -> None:
        self.window_id = -1 if window is None else window.id
        self.request_type = request_type

    def __bool__(self) -> bool:
        return self.window_id > -1

    @property
    def window(self) -> Optional['Window']:
        return get_boss().window_id_map.get(self.window_id)

    @property
    def cwd_of_child(self) -> str:
        window = self.window
        if not window:
            return ''
        reported_cwd = path_from_osc7_url(window.screen.last_reported_cwd) if window.screen.last_reported_cwd else ''
        if reported_cwd and not window.child_is_remote and (self.request_type is CwdRequestType.last_reported or window.at_prompt):
            return reported_cwd
        if self.request_type is CwdRequestType.root:
            return window.get_cwd_of_root_child() or ''
        return window.get_cwd_of_child(oldest=self.request_type is CwdRequestType.oldest) or ''

    def modify_argv_for_launch_with_cwd(self, argv: list[str], env: dict[str, str] | None=None, hold_after_ssh: bool = False) -> str:
        window = self.window
        if not window:
            return ''
        reported_cwd = path_from_osc7_url(window.screen.last_reported_cwd) if window.screen.last_reported_cwd else ''
        if reported_cwd and (self.request_type is not CwdRequestType.root or window.root_in_foreground_processes):
            ssh_kitten_cmdline = window.ssh_kitten_cmdline()
            if ssh_kitten_cmdline:
                run_shell = argv[0] == resolved_shell(get_options())[0]
                server_args = [] if run_shell else list(argv)
                from kittens.ssh.utils import set_cwd_in_cmdline, set_env_in_cmdline, set_server_args_in_cmdline
                if ssh_kitten_cmdline and ssh_kitten_cmdline[0] == 'kitten':
                    ssh_kitten_cmdline[0] = kitten_exe()
                argv[:] = ssh_kitten_cmdline
                set_cwd_in_cmdline(reported_cwd, argv)
                set_server_args_in_cmdline(server_args, argv, allocate_tty=not run_shell)
                if hold_after_ssh:
                    argv[:0] = [kitten_exe(), "run-shell"]
                if env is not None:
                    # Assume env is coming from a local process so drop env
                    # vars that can cause issues when set on the remote host
                    if env.get('KITTY_KITTEN_RUN_MODULE') == 'ssh_askpass':
                        for k in ('KITTY_KITTEN_RUN_MODULE', 'SSH_ASKPASS', 'SSH_ASKPASS_REQUIRE'):
                            env.pop(k, None)
                    for k in (
                        'HOME', 'USER', 'TEMP', 'TMP', 'TMPDIR', 'PATH', 'PWD', 'OLDPWD', 'KITTY_INSTALLATION_DIR',
                        'HOSTNAME', 'SSH_AUTH_SOCK', 'SSH_AGENT_PID', 'KITTY_STDIO_FORWARDED',
                        'KITTY_PUBLIC_KEY', 'TERMINFO', 'XDG_RUNTIME_DIR', 'XDG_VTNR',
                        'XDG_DATA_DIRS', 'XAUTHORITY', 'EDITOR', 'VISUAL',
                    ):
                        env.pop(k, None)
                    set_env_in_cmdline(env, argv, clone=False)
                return ''
            if not window.child_is_remote and (self.request_type is CwdRequestType.last_reported or window.at_prompt):
                return reported_cwd
        return window.get_cwd_of_child(oldest=self.request_type is CwdRequestType.oldest) or ''


def process_title_from_child(title: memoryview, is_base64: bool, default_title: str) -> str:
    if is_base64:
        try:
            stitle = base64_decode(title).decode('utf-8', 'replace')
        except Exception:
            stitle = 'undecodeable title'
    else:
        stitle = str(title, 'utf-8', 'replace')
    return sanitize_title(stitle or default_title)


@lru_cache(maxsize=64)
def compile_match_query(exp: str, is_simple: bool = True) -> MatchPatternType:
    if is_simple:
        pat: MatchPatternType = re.compile(exp)
    else:
        kp, vp = exp.partition('=')[::2]
        if vp:
            pat = re.compile(kp), re.compile(vp)
        else:
            pat = re.compile(kp), None
    return pat


def decode_cmdline(x: str) -> str:
    ctype, sep, val = x.partition('=')
    if ctype == 'cmdline':
        return next(shlex_split(val, True))
    elif ctype == 'cmdline_url':
        from urllib.parse import unquote
        return unquote(val)
    return ''


class WindowDict(TypedDict):
    id: int
    is_focused: bool
    is_active: bool
    title: str
    pid: int | None
    cwd: str
    cmdline: list[str]
    last_reported_cmdline: str
    last_cmd_exit_status: int
    env: dict[str, str]
    foreground_processes: list[ProcessDesc]
    is_self: bool
    lines: int
    columns: int
    user_vars: dict[str, str]
    at_prompt: bool
    created_at: int
    in_alternate_screen: bool


class PipeData(TypedDict):
    input_line_number: int
    scrolled_by: int
    cursor_x: int
    cursor_y: int
    lines: int
    columns: int
    text: str


class ClipboardPending(NamedTuple):
    where: str
    data: str
    truncated: bool = False


class DynamicColor(IntEnum):
    default_fg, default_bg, cursor_color, highlight_fg, highlight_bg = range(1, 6)


class CommandOutput(IntEnum):
    last_run, first_on_screen, last_visited, last_non_empty = 0, 1, 2, 3


DYNAMIC_COLOR_CODES = {
    10: DynamicColor.default_fg,
    11: DynamicColor.default_bg,
    12: DynamicColor.cursor_color,
    17: DynamicColor.highlight_bg,
    19: DynamicColor.highlight_fg,
}
DYNAMIC_COLOR_CODES.update({k+100: v for k, v in DYNAMIC_COLOR_CODES.items()})


class Watcher:

    def __call__(self, boss: BossType, window: 'Window', data: dict[str, Any]) -> None:
        pass


class Watchers:

    on_resize: list[Watcher]
    on_close: list[Watcher]
    on_focus_change: list[Watcher]
    on_set_user_var: list[Watcher]
    on_title_change: list[Watcher]
    on_cmd_startstop: list[Watcher]
    on_color_scheme_preference_change: list[Watcher]
    on_tab_bar_dirty: list[Watcher]

    def __init__(self) -> None:
        self.on_resize = []
        self.on_close = []
        self.on_focus_change = []
        self.on_set_user_var = []
        self.on_title_change = []
        self.on_cmd_startstop = []
        self.on_color_scheme_preference_change = []
        self.on_tab_bar_dirty = []

    def add(self, others: 'Watchers') -> None:
        def merge(base: list[Watcher], other: list[Watcher]) -> None:
            for x in other:
                if x not in base:
                    base.append(x)
        merge(self.on_resize, others.on_resize)
        merge(self.on_close, others.on_close)
        merge(self.on_focus_change, others.on_focus_change)
        merge(self.on_set_user_var, others.on_set_user_var)
        merge(self.on_title_change, others.on_title_change)
        merge(self.on_cmd_startstop, others.on_cmd_startstop)
        merge(self.on_color_scheme_preference_change, others.on_color_scheme_preference_change)
        merge(self.on_tab_bar_dirty, others.on_tab_bar_dirty)

    def clear(self) -> None:
        del self.on_close[:], self.on_resize[:], self.on_focus_change[:]
        del self.on_set_user_var[:], self.on_title_change[:], self.on_cmd_startstop[:]
        del self.on_color_scheme_preference_change[:]
        del self.on_tab_bar_dirty[:]

    def copy(self) -> 'Watchers':
        ans = Watchers()
        ans.on_close = self.on_close[:]
        ans.on_resize = self.on_resize[:]
        ans.on_focus_change = self.on_focus_change[:]
        ans.on_set_user_var = self.on_set_user_var[:]
        ans.on_title_change = self.on_title_change[:]
        ans.on_cmd_startstop = self.on_cmd_startstop[:]
        ans.on_color_scheme_preference_change = self.on_color_scheme_preference_change[:]
        ans.on_tab_bar_dirty = self.on_tab_bar_dirty[:]
        return ans

    @property
    def has_watchers(self) -> bool:
        return bool(self.on_close or self.on_resize or self.on_focus_change or self.on_color_scheme_preference_change
                    or self.on_set_user_var or self.on_title_change or self.on_cmd_startstop or self.on_tab_bar_dirty)


def call_watchers(windowref: Callable[[], Optional['Window']], which: str, data: dict[str, Any]) -> None:

    def callback(timer_id: int | None) -> None:
        w = windowref()
        if w is not None:
            watchers: list[Watcher] = getattr(w.watchers, which)
            w.call_watchers(watchers, data)

    add_timer(callback, 0, False)


def pagerhist(screen: Screen, as_ansi: bool = False, add_wrap_markers: bool = True, upto_output_start: bool = False) -> str:
    pht = screen.historybuf.pagerhist_as_text(upto_output_start)
    if pht and (not as_ansi or not add_wrap_markers):
        sanitizer = text_sanitizer(as_ansi, add_wrap_markers)
        pht = sanitizer(pht)
    return pht


def as_text(
    screen: Screen,
    as_ansi: bool = False,
    add_history: bool = False,
    add_wrap_markers: bool = False,
    alternate_screen: bool = False,
    add_cursor: bool = False
) -> str:
    lines: list[str] = []
    add_history = add_history and not (screen.is_using_alternate_linebuf() ^ alternate_screen)
    if alternate_screen:
        f = screen.as_text_alternate
    else:
        f = screen.as_text_non_visual if add_history else screen.as_text
    f(lines.append, as_ansi, add_wrap_markers)
    ctext = ''
    if add_cursor:
        ctext += '\x1b[?25' + ('h' if screen.cursor_visible else 'l')
        ctext += f'\x1b[{screen.cursor.y + 1};{screen.cursor.x + 1}H'
        shape = screen.cursor.shape
        if shape == NO_CURSOR_SHAPE:
            ctext += '\x1b[?12' + ('h' if screen.cursor.blink else 'l')
        else:
            code = {CURSOR_BLOCK: 1, CURSOR_UNDERLINE: 3, CURSOR_BEAM: 5}[shape]
            if not screen.cursor.blink:
                code += 1
            ctext += f'\x1b[{code} q'

    if add_history:
        pht = pagerhist(screen, as_ansi, add_wrap_markers)
        h: list[str] = [pht] if pht else []
        screen.as_text_for_history_buf(h.append, as_ansi, add_wrap_markers)
        if h:
            if as_ansi:
                h[-1] += '\x1b[m'
        ans = ''.join(chain(h, lines))
        if ctext:
            ans += ctext
        return ans
    ans = ''.join(lines)
    if ctext:
        ans += ctext
    return ans



@run_once
def load_paste_filter() -> Callable[[str], str]:
    import runpy
    import traceback
    try:
        m = runpy.run_path(os.path.join(config_dir, 'paste-actions.py'))
        func: Callable[[str], str] = m['filter_paste']
    except Exception as e:
        if not isinstance(e, FileNotFoundError):
            traceback.print_exc()
            log_error(f'Failed to load paste filter function with error: {e}')

        def func(text: str) -> str:
            return text
    return func


def text_sanitizer(as_ansi: bool, add_wrap_markers: bool) -> Callable[[str], str]:
    pat = kitty_ansi_sanitizer_pat()
    ansi, wrap_markers = not as_ansi, not add_wrap_markers

    def remove_wrap_markers(line: str) -> str:
        return line.replace('\r', '')

    def remove_sgr(line: str) -> str:
        return str(pat.sub('', line))

    def remove_both(line: str) -> str:
        return str(pat.sub('', line.replace('\r', '')))

    if ansi:
        return remove_both if wrap_markers else remove_sgr
    return remove_wrap_markers


def cmd_output(screen: Screen, which: CommandOutput = CommandOutput.last_run, as_ansi: bool = False, add_wrap_markers: bool = False) -> str:
    lines: list[str] = []
    search_in_pager_hist = screen.cmd_output(which, lines.append, as_ansi, add_wrap_markers)
    if search_in_pager_hist:
        pht = pagerhist(screen, as_ansi, add_wrap_markers, True)
        if pht:
            lines.insert(0, pht)
    for i in range(min(len(lines), 3)):
        x = lines[i]
        if x.startswith('\x1b]133;C'):
            lines[i] = x.partition('\\')[-1]
    return ''.join(lines)


def process_remote_print(msg: memoryview) -> str:
    return replace_c0_codes_except_nl_space_tab(base64_decode(msg)).decode('utf-8', 'replace')


def transparent_background_color_control(cp: ColorProfile, responses: dict[str, str], index: int, key: str, sep: str, val: str) -> None:
    if sep == '=':
        if val == '?':
            if index > 8:
                responses[key] = '?'
            else:
                c = cp.get_transparent_background_color(index - 1)
                if c is None:
                    responses[key] = ''
                else:
                    opacity = max(0, min(c.alpha / 255.0, 1))
                    responses[key] = f'rgb:{c.red:02x}/{c.green:02x}/{c.blue:02x}@{opacity:.4f}'
        elif index <= 8:
            col, _, o = val.partition('@')
            try:
                opacity = float(o)
            except Exception:
                opacity = -1.0
            c = to_color(col)
            if c is not None:
                cp.set_transparent_background_color(index - 1, c, opacity)
    elif index <= 8:
        cp.set_transparent_background_color(index - 1)


def color_control(cp: ColorProfile, code: int, value: str | bytes | memoryview = '') -> str:
    if isinstance(value, (bytes, memoryview)):
        value = str(value, 'utf-8', 'replace')
    responses: dict[str, str] = {}
    for rec in value.split(';'):
        key, sep, val = rec.partition('=')
        if key.startswith('transparent_background_color'):
            index = int(key[len('transparent_background_color'):])
            transparent_background_color_control(cp, responses, index, key, sep, val)
            continue
        attr = {
            'foreground': 'default_fg', 'background': 'default_bg',
            'selection_background': 'highlight_bg', 'selection_foreground': 'highlight_fg',
            'cursor': 'cursor_color', 'cursor_text': 'cursor_text_color',
            'visual_bell': 'visual_bell_color',
        }.get(key, '')
        colnum = -1
        with suppress(Exception):
            colnum = int(key)

        def serialize_color(c: Color | None) -> str:
            return '' if c is None else f'rgb:{c.red:02x}/{c.green:02x}/{c.blue:02x}'

        if sep == '=':
            if val == '?':
                if attr:
                    c = getattr(cp, attr)
                    responses[key] = serialize_color(c)
                else:
                    if 0 <= colnum <= 255:
                        c = cp.as_color((colnum << 8) | 1)
                        responses[key] = serialize_color(c)
                    else:
                        responses[key] = '?'
            else:
                if attr:
                    if val:
                        val = val.partition('@')[0]
                        col = to_color(val)
                        if col is not None:
                            setattr(cp, attr, col)
                    else:
                        with suppress(TypeError):
                            setattr(cp, attr, None)
                else:
                    if 0 <= colnum <= 255:
                        val = val.partition('@')[0]
                        col = to_color(val)
                        if col is not None:
                            cp.set_color(colnum, color_as_int(col))
        else:
            if attr:
                delattr(cp, attr)
            else:
                if 0 <= colnum <= 255:
                    cp.set_color(colnum, get_options().color_table[colnum])
    if responses:
        payload = ';'.join(f'{k}={v}' for k, v in responses.items())
        return f'{code};{payload}'
    return ''


def da1(opts: Options) -> str:
    ans = '?62;'
    if 'write-clipboard' in opts.clipboard_control:
        # see https://github.com/contour-terminal/vt-extensions/blob/master/clipboard-extension.md
        ans += '52;'
    return ans + 'c'


class EdgeWidths:
    left: float | None
    top: float | None
    right: float | None
    bottom: float | None

    def __init__(self, serialized: dict[str, float | None] | None = None):
        if serialized is not None:
            self.left = serialized['left']
            self.right = serialized['right']
            self.top = serialized['top']
            self.bottom = serialized['bottom']
        else:
            self.left = self.top = self.right = self.bottom = None

    def serialize(self) -> dict[str, float | None]:
        return {'left': self.left, 'right': self.right, 'top': self.top, 'bottom': self.bottom}

    def copy(self) -> 'EdgeWidths':
        return EdgeWidths(self.serialize())


class GlobalWatchers:

    def __init__(self) -> None:
        self.options_spec: dict[str, str] | None = None
        self.ans = Watchers()
        self.extra = ''

    def __call__(self) -> Watchers:
        spec = get_options().watcher
        if spec == self.options_spec:
            return self.ans
        from .launch import load_watch_modules
        if self.extra:
            spec = spec.copy()
            spec[self.extra] = self.extra
        self.ans = load_watch_modules(spec.keys()) or self.ans
        self.options_spec = spec.copy()
        return self.ans

    def set_extra(self, extra: str) -> None:
        self.extra = extra


global_watchers = GlobalWatchers()


class Window:

    window_custom_type: str = ''
    overlay_type = OverlayType.transient
    initial_ignore_focus_changes: bool = False
    initial_ignore_focus_changes_context_manager_in_operation: bool = False

    @classmethod
    @contextmanager
    def set_ignore_focus_changes_for_new_windows(cls, value: bool = True) -> Generator[None, None, None]:
        if cls.initial_ignore_focus_changes_context_manager_in_operation:
            yield
        else:
            orig, cls.initial_ignore_focus_changes = cls.initial_ignore_focus_changes, value
            cls.initial_ignore_focus_changes_context_manager_in_operation = True
            try:
                yield
            finally:
                cls.initial_ignore_focus_changes = orig
                cls.initial_ignore_focus_changes_context_manager_in_operation = False

    def __init__(
        self,
        tab: TabType,
        child: ChildType,
        args: CLIOptions,
        override_title: str | None = None,
        copy_colors_from: Optional['Window'] = None,
        watchers: Watchers | None = None,
        allow_remote_control: bool = False,
        remote_control_passwords: dict[str, Sequence[str]] | None = None,
    ):
        if watchers:
            self.watchers = watchers
            self.watchers.add(global_watchers())
        else:
            self.watchers = global_watchers().copy()
        self.keys_redirected_till_ready_from: int = 0
        self.last_focused_at = 0.
        self.is_focused: bool = False
        self.progress = Progress()
        self.last_resized_at = 0.
        self.started_at = monotonic()
        self.created_at = time_ns()
        self.clear_progress_timer: int = 0
        self.current_remote_data: list[str] = []
        self.current_mouse_event_button = 0
        self.current_clipboard_read_ask: bool | None = None
        self.last_cmd_output_start_time = 0.
        self.last_cmd_end_notification: tuple[int, 'OnlyWhen'] | None = None
        self.open_url_handler: 'OpenUrlHandler' = None
        self.last_cmd_cmdline = ''
        self.last_cmd_exit_status = 0
        self.actions_on_close: list[Callable[['Window'], None]] = []
        self.actions_on_focus_change: list[Callable[['Window', bool], None]] = []
        self.actions_on_removal: list[Callable[['Window'], None]] = []
        self.current_marker_spec: tuple[str, str | tuple[tuple[int, str], ...]] | None = None
        self.kitten_result_processors: list[Callable[['Window', Any], None]] = []
        self.child_is_launched = False
        self.last_reported_pty_size = (-1, -1, -1, -1)
        self.needs_attention = False
        self.ignore_focus_changes = self.initial_ignore_focus_changes
        self.override_title = override_title
        self.default_title = os.path.basename(child.argv[0] or appname)
        self.child_title = self.default_title
        self.title_stack: Deque[str] = deque(maxlen=10)
        self.user_vars: dict[str, str] = {}
        self.id: int = add_window(tab.os_window_id, tab.id, self.title)
        self.clipboard_request_manager = ClipboardRequestManager(self.id)
        self.margin = EdgeWidths()
        self.padding = EdgeWidths()
        self.kitten_result: dict[str, Any] | None = None
        if not self.id:
            raise Exception(f'No tab with id: {tab.id} in OS Window: {tab.os_window_id} was found, or the window counter wrapped')
        self.tab_id = tab.id
        self.os_window_id = tab.os_window_id
        self.tabref: Callable[[], TabType | None] = weakref.ref(tab)
        self.destroyed = False
        self.geometry: WindowGeometry = WindowGeometry(0, 0, 0, 0, 0, 0)
        self.needs_layout = True
        self.is_visible_in_layout: bool = True
        self.child = child
        cell_width, cell_height = cell_size_for_window(self.os_window_id)
        opts = get_options()
        self.screen: Screen = Screen(self, 24, 80, opts.scrollback_lines, cell_width, cell_height, self.id)
        if copy_colors_from is not None:
            self.screen.copy_colors_from(copy_colors_from.screen)
        self.remote_control_passwords = remote_control_passwords
        self.allow_remote_control = allow_remote_control

    def remote_control_allowed(self, pcmd: dict[str, Any], extra_data: dict[str, Any]) -> bool:
        if not self.allow_remote_control:
            return False
        from .remote_control import remote_control_allowed
        return remote_control_allowed(pcmd, self.remote_control_passwords, self, extra_data)

    @property
    def file_transmission_control(self) -> 'FileTransmission':
        ans: Optional['FileTransmission'] = getattr(self, '_file_transmission', None)
        if ans is None:
            from .file_transmission import FileTransmission
            ans = self._file_transmission = FileTransmission(self.id)
        return ans

    def on_dpi_change(self, font_sz: float) -> None:
        self.update_effective_padding()

    def change_tab(self, tab: TabType) -> None:
        self.tab_id = tab.id
        self.os_window_id = tab.os_window_id
        self.tabref = weakref.ref(tab)

    def effective_margin(self, edge: EdgeLiteral) -> int:
        q = getattr(self.margin, edge)
        if q is not None:
            return pt_to_px(q, self.os_window_id)
        opts = get_options()
        tab = self.tabref()
        is_single_window = tab is not None and tab.has_single_window_visible()
        if is_single_window:
            q = getattr(opts.single_window_margin_width, edge)
            if q > -0.1:
                return pt_to_px(q, self.os_window_id)
        q = getattr(opts.window_margin_width, edge)
        return pt_to_px(q, self.os_window_id)

    def effective_padding(self, edge: EdgeLiteral) -> int:
        q = getattr(self.padding, edge)
        if q is not None:
            return pt_to_px(q, self.os_window_id)
        opts = get_options()
        tab = self.tabref()
        is_single_window = tab is not None and tab.has_single_window_visible()
        if is_single_window:
            q = getattr(opts.single_window_padding_width, edge)
            if q > -0.1:
                return pt_to_px(q, self.os_window_id)
        q = getattr(opts.window_padding_width, edge)
        return pt_to_px(q, self.os_window_id)

    def update_effective_padding(self) -> None:
        set_window_padding(
            self.os_window_id, self.tab_id, self.id,
            self.effective_padding('left'), self.effective_padding('top'),
            self.effective_padding('right'), self.effective_padding('bottom'))

    def patch_edge_width(self, which: str, edge: EdgeLiteral, val: float | None) -> None:
        q = self.padding if which == 'padding' else self.margin
        setattr(q, edge, val)
        if q is self.padding:
            self.update_effective_padding()

    def effective_border(self) -> int:
        val, unit = get_options().window_border_width
        if unit == 'pt':
            val = max(1 if val > 0 else 0, pt_to_px(val, self.os_window_id))
        else:
            val = round(val)
        return int(val)

    def apply_options(self, is_active: bool) -> None:
        self.update_effective_padding()
        self.screen.color_profile.reload_from_opts()

    @property
    def title(self) -> str:
        return self.override_title or self.child_title

    def __repr__(self) -> str:
        return f'Window(title={self.title}, id={self.id})'

    def as_dict(self, is_focused: bool = False, is_self: bool = False, is_active: bool = False) -> WindowDict:
        return {
            'id': self.id,
            'is_focused': is_focused,
            'is_active': is_active,
            'title': self.title,
            'pid': self.child.pid,
            'cwd': self.child.current_cwd or self.child.cwd,
            'cmdline': self.child.cmdline,
            'last_reported_cmdline': self.last_cmd_cmdline,
            'last_cmd_exit_status': self.last_cmd_exit_status,
            'env': self.child.environ or self.child.final_env,
            'foreground_processes': self.child.foreground_processes,
            'is_self': is_self,
            'at_prompt': self.at_prompt,
            'lines': self.screen.lines,
            'columns': self.screen.columns,
            'user_vars': self.user_vars,
            'created_at': self.created_at,
            'in_alternate_screen': self.screen.is_using_alternate_linebuf(),
        }

    def serialize_state(self) -> dict[str, Any]:
        ans = {
            'version': 1,
            'id': self.id,
            'child_title': self.child_title,
            'override_title': self.override_title,
            'default_title': self.default_title,
            'title_stack': list(self.title_stack),
            'allow_remote_control': self.allow_remote_control,
            'remote_control_passwords': self.remote_control_passwords,
            'cwd': self.child.current_cwd or self.child.cwd,
            'env': self.child.environ,
            'cmdline': self.child.cmdline,
            'last_reported_cmdline': self.last_cmd_cmdline,
            'last_cmd_exit_status': self.last_cmd_exit_status,
            'margin': self.margin.serialize(),
            'user_vars': self.user_vars,
            'padding': self.padding.serialize(),
        }
        if self.window_custom_type:
            ans['window_custom_type'] = self.window_custom_type
        if self.overlay_type is not OverlayType.transient:
            ans['overlay_type'] = self.overlay_type.value
        if self.user_vars:
            ans['user_vars'] = self.user_vars
        return ans

    @property
    def overlay_parent(self) -> Optional['Window']:
        tab = self.tabref()
        if tab is None:
            return None
        return tab.overlay_parent(self)

    @property
    def current_colors(self) -> dict[str, int | None | tuple[tuple[Color, float], ...]]:
        return self.screen.color_profile.as_dict()

    @property
    def at_prompt(self) -> bool:
        return self.screen.cursor_at_prompt()

    @property
    def has_running_program(self) -> bool:
        return not self.at_prompt

    def matches(self, field: str, pat: MatchPatternType) -> bool:
        if isinstance(pat, tuple):
            if field == 'env':
                return key_val_matcher(self.child.environ.items(), *pat)
            if field == 'var':
                return key_val_matcher(self.user_vars.items(), *pat)
            return False

        if field in ('id', 'window_id'):
            return pat.pattern == str(self.id)
        if field == 'pid':
            return pat.pattern == str(self.child.pid)
        if field == 'title':
            return pat.search(self.override_title or self.title) is not None
        if field in 'cwd':
            return pat.search(self.child.current_cwd or self.child.cwd) is not None
        if field == 'cmdline':
            for x in self.child.cmdline:
                if pat.search(x) is not None:
                    return True
            return False
        return False

    def matches_query(self, field: str, query: str, active_tab: TabType | None = None, self_window: Optional['Window'] = None) -> bool:
        if field in ('num', 'recent'):
            if active_tab is not None:
                try:
                    q = int(query)
                except Exception:
                    return False
                with suppress(Exception):
                    if field == 'num':
                        return active_tab.get_nth_window(q) is self
                    return active_tab.nth_active_window_id(q) == self.id
            return False
        if field == 'state':
            if query == 'active':
                tab = self.tabref()
                return tab is not None and tab.active_window is self
            if query == 'focused':
                return active_tab is not None and self is active_tab.active_window and last_focused_os_window_id() == self.os_window_id
            if query == 'needs_attention':
                return self.needs_attention
            if query == 'parent_active':
                tab = self.tabref()
                if tab is not None:
                    tm = tab.tab_manager_ref()
                    return tm is not None and tm.active_tab is tab
                return False
            if query == 'parent_focused':
                return active_tab is not None and self.tabref() is active_tab and last_focused_os_window_id() == self.os_window_id
            if query == 'self':
                return self is self_window
            if query == 'overlay_parent':
                return self_window is not None and self is self_window.overlay_parent
            return False
        if field == 'neighbor':
            t = get_boss().active_tab
            if t is None:
                return False
            gid: int | None = None
            if query == 'left':
                gid = t.neighboring_group_id("left")
            elif query == 'right':
                gid = t.neighboring_group_id("right")
            elif query == 'top':
                gid = t.neighboring_group_id("top")
            elif query == 'bottom':
                gid = t.neighboring_group_id("bottom")
            return gid is not None and t.windows.active_window_in_group_id(gid) is self

        pat = compile_match_query(query, field not in ('env', 'var'))
        return self.matches(field, pat)

    def set_visible_in_layout(self, val: bool) -> None:
        val = bool(val)
        if val is not self.is_visible_in_layout:
            self.is_visible_in_layout = val
            update_window_visibility(self.os_window_id, self.tab_id, self.id, val)
            if val:
                self.refresh()

    def refresh(self, reload_all_gpu_data: bool = False) -> None:
        self.screen.mark_as_dirty()
        if reload_all_gpu_data:
            self.screen.reload_all_gpu_data()
        wakeup_io_loop()
        wakeup_main_loop()

    def set_geometry(self, new_geometry: WindowGeometry) -> None:
        if self.destroyed:
            return
        if self.needs_layout or new_geometry.xnum != self.screen.columns or new_geometry.ynum != self.screen.lines:
            self.screen.resize(max(0, new_geometry.ynum), max(0, new_geometry.xnum))
            self.needs_layout = False
            call_watchers(weakref.ref(self), 'on_resize', {'old_geometry': self.geometry, 'new_geometry': new_geometry})
        current_pty_size = (
            self.screen.lines, self.screen.columns,
            max(0, new_geometry.right - new_geometry.left), max(0, new_geometry.bottom - new_geometry.top))
        update_ime_position = False
        if current_pty_size != self.last_reported_pty_size:
            boss = get_boss()
            boss.child_monitor.resize_pty(self.id, *current_pty_size)
            self.last_resized_at = monotonic()
            self.last_reported_pty_size = current_pty_size
            self.notify_child_of_resize()
            if not self.child_is_launched:
                self.child.mark_terminal_ready()
                self.child_is_launched = True
                update_ime_position = True
                if boss.args.debug_rendering:
                    now = monotonic()
                    print(f'[{now:.3f}] Child launched', file=sys.stderr)
            elif boss.args.debug_rendering:
                print(f'[{monotonic():.3f}] SIGWINCH sent to child in window: {self.id} with size: {current_pty_size}', file=sys.stderr)
        else:
            mark_os_window_dirty(self.os_window_id)

        self.geometry = g = new_geometry
        set_window_render_data(self.os_window_id, self.tab_id, self.id, self.screen, *g[:4])
        self.update_effective_padding()
        if update_ime_position:
            update_ime_position_for_window(self.id, True)

    def contains(self, x: int, y: int) -> bool:
        g = self.geometry
        return g.left <= x <= g.right and g.top <= y <= g.bottom

    def close(self) -> None:
        get_boss().mark_window_for_close(self)

    @ac('misc', '''
        Send the specified text to the active window

        See :sc:`send_text <send_text>` for details.
        ''')
    def send_text(self, *args: str) -> bool:
        mode = keyboard_mode_name(self.screen)
        required_mode_, text = args[-2:]
        required_mode = frozenset(required_mode_.split(','))
        if not required_mode & {mode, 'all'}:
            return True
        if not text:
            return True
        self.write_to_child(text)
        return False

    @ac(
        'misc', '''
        Send the specified keys to the active window.
        Note that the key will be sent only if the current keyboard mode of the program running in the terminal supports it.
        Both key press and key release are sent. First presses for all specified keys and then releases in reverse order.
        To send a pattern of press and release for multiple keys use the :ac:`combine` action. For example::

            map f1 send_key ctrl+x alt+y
            map f1 combine : send_key ctrl+x : send_key alt+y
    ''')
    def send_key(self, *args: str) -> bool:
        from .options.utils import parse_shortcut
        km = get_options().kitty_mod
        passthrough = True
        events = []
        prev = ''
        for human_key in args:
            sk = parse_shortcut(human_key)
            if sk.is_native:
                raise ValueError(f'Native key codes not allowed in send_key: {human_key}')
            sk = sk.resolve_kitty_mod(km)
            events.append(KeyEvent(key=sk.key, mods=sk.mods, action=GLFW_REPEAT if human_key == prev else GLFW_PRESS))
            prev = human_key
        scroll_needed = False
        for ev in events + [KeyEvent(key=x.key, mods=x.mods, action=GLFW_RELEASE) for x in reversed(events)]:
            enc = self.encoded_key(ev)
            if enc:
                self.write_to_child(enc)
                if ev.action != GLFW_RELEASE and not is_modifier_key(ev.key):
                    scroll_needed = True
                passthrough = False
        if scroll_needed:
            self.scroll_end()
        return passthrough

    def send_key_sequence(self, *keys: KeyEvent, synthesize_release_events: bool = True) -> None:
        for key in keys:
            enc = self.encoded_key(key)
            if enc:
                self.write_to_child(enc)
            if synthesize_release_events and key.action != GLFW_RELEASE:
                rkey = KeyEvent(key=key.key, mods=key.mods, action=GLFW_RELEASE)
                enc = self.encoded_key(rkey)
                if enc:
                    self.write_to_child(enc)

    @ac('debug', 'Show a dump of the current lines in the scrollback + screen with their line attributes')
    def dump_lines_with_attrs(self, which_screen: Literal['main', 'alternate', 'current'] = 'current') -> None:
        strings: list[str] = []
        ws = 0 if which_screen == 'main' else (1 if which_screen == 'alternate' else -1)
        self.screen.dump_lines_with_attrs(strings.append, ws)
        text = ''.join(strings)
        get_boss().display_scrollback(self, text, title='Dump of lines', report_cursor=False)

    def write_to_child(self, data: str | bytes | memoryview) -> None:
        if data:
            if isinstance(data, str):
                data = data.encode('utf-8')
            if get_boss().child_monitor.needs_write(self.id, data) is not True:
                log_error(f'Failed to write to child {self.id} as it does not exist')

    def title_updated(self) -> None:
        update_window_title(self.os_window_id, self.tab_id, self.id, self.title)
        t = self.tabref()
        if t is not None:
            t.title_changed(self)

    def set_title(self, title: str | None) -> None:
        if title:
            title = sanitize_title(title)
        self.override_title = title or None
        self.call_watchers(self.watchers.on_title_change, {'title': self.title, 'from_child': False})
        self.title_updated()

    @ac(
        'win', '''
        Change the title of the active window interactively, by typing in the new title.
        If you specify an argument to this action then that is used as the title instead of asking for it.
        Use the empty string ("") to reset the title to default. Use a space (" ") to indicate that the
        prompt should not be pre-filled. For example::

            # interactive usage
            map f1 set_window_title
            # set a specific title
            map f2 set_window_title some title
            # reset to default
            map f3 set_window_title ""
            # interactive usage without prefilled prompt
            map f3 set_window_title " "
        '''
    )
    def set_window_title(self, title: str | None = None) -> None:
        if title is not None and title not in ('" "', "' '"):
            if title in ('""', "''"):
                title = ''
            self.set_title(title)
            return
        prefilled = self.title
        if title in ('" "', "' '"):
            prefilled = ''
        get_boss().get_line(
            _('Enter the new title for this window below. An empty title will cause the default title to be used.'),
            self.set_title, window=self, initial_value=prefilled)

    def set_user_var(self, key: str, val: str | bytes | None) -> None:
        key = sanitize_control_codes(key).replace('\n', ' ')
        self.user_vars.pop(key, None)  # ensure key will be newest in user_vars even if already present
        if len(self.user_vars) > 64:  # dont store too many user vars
            oldest_key = next(iter(self.user_vars))
            self.user_vars.pop(oldest_key)
        if val is not None:
            if isinstance(val, bytes):
                val = val.decode('utf-8', 'replace')
            self.user_vars[key] = val = sanitize_control_codes(val).replace('\n', ' ')
            self.call_watchers(self.watchers.on_set_user_var, {'key': key, 'value': val})
        else:
            self.call_watchers(self.watchers.on_set_user_var, {'key': key, 'value': None})

    # screen callbacks {{{

    def osc_1337(self, raw_data: str) -> None:
        for record in raw_data.split(';'):
            key, _, val = record.partition('=')
            if key == 'SetUserVar':
                ukey, has_equal, uval = val.partition('=')
                self.set_user_var(ukey, (base64_decode(uval) if uval else b'') if has_equal == '=' else None)

    def desktop_notify(self, osc_code: int, raw_datab: memoryview) -> None:
        raw_data = str(raw_datab, 'utf-8', 'replace')
        if osc_code == 1337:
            self.osc_1337(raw_data)
        if osc_code == 777:
            if not raw_data.startswith('notify;'):
                log_error(f'Ignoring unknown OSC 777: {raw_data}')
                return  # unknown OSC 777
            raw_data = raw_data[len('notify;'):]
        if osc_code == 9 and raw_data.startswith('4;'):
            # This is probably the ConEmu "progress reporting" conflicting
            # implementation which sadly some thoughtless people have
            # implemented in unix CLI programs.
            # See for example: https://github.com/kovidgoyal/kitty/issues/8011
            try:
                parts = tuple(map(int, raw_data.split(';')))[1:]
            except Exception:
                log_error(f'Ignoring malmormed OSC 9;4 progress report: {raw_data!r}')
                return
            self.progress.update(*parts[:2])
            if (tab := self.tabref()) is not None:
                tab.update_progress()
            self.clear_progress_if_needed()
            return
        get_boss().notification_manager.handle_notification_cmd(self.id, osc_code, raw_data)

    def clear_progress_if_needed(self, timer_id: int | None = None) -> None:
        # Clear stuck or completed progress
        if timer_id is not None:  # this is a timer callback
            self.clear_progress_timer = 0
        if self.progress.clear_progress():
            if (tab := self.tabref()) is not None:
                tab.update_progress()
        else:
            if not self.clear_progress_timer:
                self.clear_progress_timer = add_timer(self.clear_progress_if_needed, 1.0, False)

    def on_mouse_event(self, event: dict[str, Any]) -> bool:
        event['mods'] = event.get('mods', 0) & mod_mask
        ev = MouseEvent(**event)
        self.current_mouse_event_button = ev.button
        action = get_options().mousemap.get(ev)
        if action is None:
            return False
        return get_boss().combine(action, window_for_dispatch=self, dispatch_type='MouseEvent')

    def open_url(self, url: str, hyperlink_id: int, cwd: str | None = None) -> None:
        boss = get_boss()
        try:
            if self.open_url_handler and self.open_url_handler(boss, self, url, hyperlink_id, cwd or ''):
                return
        except Exception:
            import traceback
            traceback.print_exc()
        opts = get_options()
        if hyperlink_id:
            if not opts.allow_hyperlinks:
                return
            from urllib.parse import unquote, urlparse, urlunparse
            try:
                purl = urlparse(url)
            except Exception:
                return
            if (not purl.scheme or purl.scheme == 'file'):
                if purl.netloc:
                    from .utils import get_hostname
                    hostname = get_hostname()
                    remote_hostname = purl.netloc.partition(':')[0]
                    if remote_hostname and remote_hostname != hostname and remote_hostname != 'localhost':
                        self.handle_remote_file(purl.netloc, unquote(purl.path))
                        return
                    url = urlunparse(purl._replace(netloc=''))
            if opts.allow_hyperlinks & 0b10:
                from kittens.tui.operations import styled
                boss.choose(
                    'What would you like to do with this URL:\n' + styled(sanitize_url_for_dispay_to_user(url), fg='yellow'),
                    partial(self.hyperlink_open_confirmed, url, cwd),
                    'o:Open', 'c:Copy to clipboard', 'n;red:Nothing', default='o',
                    window=self, title=_('Hyperlink activated'),
                )
                return
        boss.open_url(url, cwd=cwd)

    def hyperlink_open_confirmed(self, url: str, cwd: str | None, q: str) -> None:
        if q == 'o':
            get_boss().open_url(url, cwd=cwd)
        elif q == 'c':
            set_clipboard_string(url)

    def handle_remote_file(self, netloc: str, remote_path: str) -> None:
        from kittens.remote_file.main import is_ssh_kitten_sentinel
        from kittens.ssh.utils import get_connection_data

        from .utils import SSHConnectionData
        args = self.ssh_kitten_cmdline()
        conn_data: None | list[str] | SSHConnectionData = None
        if args:
            ssh_cmdline = sorted(self.child.foreground_processes, key=lambda p: p['pid'])[-1]['cmdline'] or ['']
            if 'ControlPath=' in ' '.join(ssh_cmdline):
                idx = ssh_cmdline.index('--')
                conn_data = [is_ssh_kitten_sentinel] + list(ssh_cmdline[:idx + 2])
        if conn_data is None:
            args = self.child.foreground_cmdline
            conn_data = get_connection_data(args, self.child.foreground_cwd or self.child.current_cwd or '')
            if conn_data is None:
                get_boss().show_error('Could not handle remote file', f'No SSH connection data found in: {args}')
                return
        get_boss().run_kitten(
            'remote_file', '--hostname', netloc.partition(':')[0], '--path', remote_path,
            '--ssh-connection-data', json.dumps(conn_data)
        )

    def send_signal_for_key(self, key_num: bytes) -> bool:
        try:
            return self.child.send_signal_for_key(key_num)
        except OSError as err:
            log_error(f'Failed to send signal for key to child with err: {err}')
            return False

    def focus_changed(self, focused: bool) -> None:
        if self.destroyed or self.ignore_focus_changes or self.is_focused == focused:
            return
        self.is_focused = focused
        call_watchers(weakref.ref(self), 'on_focus_change', {'focused': focused})
        for c in self.actions_on_focus_change:
            try:
                c(self, focused)
            except Exception:
                import traceback
                traceback.print_exc()
        self.screen.focus_changed(focused)
        if focused:
            self.last_focused_at = monotonic()
            update_ime_position_for_window(self.id, False, 1)
            changed = self.needs_attention
            self.needs_attention = False
            if changed:
                tab = self.tabref()
                if tab is not None:
                    tab.relayout_borders()
            if self.last_cmd_end_notification is not None:
                from .notifications import OnlyWhen
                opts = get_options()
                if self.last_cmd_end_notification[1] in (OnlyWhen.unfocused, OnlyWhen.invisible) and 'focus' in opts.notify_on_cmd_finish.clear_on:
                    get_boss().notification_manager.close_notification(self.last_cmd_end_notification[0])
                    self.last_cmd_end_notification = None
        elif self.os_window_id == current_focused_os_window_id():
            # Cancel IME composition after loses focus
            update_ime_position_for_window(self.id, False, -1)

    def title_changed(self, new_title: memoryview | None, is_base64: bool = False) -> None:
        self.child_title = process_title_from_child(new_title or memoryview(b''), is_base64, self.default_title)
        self.call_watchers(self.watchers.on_title_change, {'title': self.child_title, 'from_child': True})
        if self.override_title is None:
            self.title_updated()

    def icon_changed(self, new_icon: memoryview) -> None:
        pass  # TODO: Implement this

    @property
    def is_active(self) -> bool:
        return get_boss().active_window is self

    @property
    def has_activity_since_last_focus(self) -> bool:
        return self.screen.has_activity_since_last_focus()

    def on_activity_since_last_focus(self) -> bool:
        if get_options().tab_activity_symbol and (monotonic() - self.last_resized_at) > 0.5:
            # Ignore activity soon after a resize as the child program is probably redrawing the screen
            get_boss().on_activity_since_last_focus(self)
            return True
        return False

    def on_da1(self) -> None:
        self.screen.send_escape_code_to_child(ESC_CSI, da1(get_options()))

    def on_bell(self) -> None:
        cb = get_options().command_on_bell
        if cb and cb != ['none']:
            import shlex
            import subprocess
            env = self.child.foreground_environ
            env['KITTY_CHILD_CMDLINE'] = ' '.join(map(shlex.quote, self.child.cmdline))
            subprocess.Popen(cb, env=env, cwd=self.child.foreground_cwd, preexec_fn=clear_handled_signals)
        if not self.is_active:
            changed = not self.needs_attention
            self.needs_attention = True
            tab = self.tabref()
            if tab is not None:
                if changed:
                    tab.relayout_borders()
                tab.on_bell(self)

    def color_profile_popped(self, bg_changed: bool) -> None:
        if bg_changed:
            get_boss().default_bg_changed_for(self.id, via_escape_code=True)

    def report_color(self, code: str, col: Color) -> None:
        r, g, b = col.red, col.green, col.blue
        r |= r << 8
        g |= g << 8
        b |= b << 8
        self.screen.send_escape_code_to_child(ESC_OSC, f'{code};rgb:{r:04x}/{g:04x}/{b:04x}')

    def notify_child_of_resize(self) -> None:
        pty_size = self.last_reported_pty_size
        if pty_size[0] > -1 and self.screen.in_band_resize_notification:
            self.screen.send_escape_code_to_child(ESC_CSI, f'48;{pty_size[0]};{pty_size[1]};{pty_size[3]};{pty_size[2]}t')

    def color_control(self, code: int, value: str | bytes | memoryview = '') -> None:
        response = color_control(self.screen.color_profile, code, value)
        if response:
            self.screen.send_escape_code_to_child(ESC_OSC, response)

    def set_dynamic_color(self, code: int, value: str | bytes | memoryview = '') -> None:
        if isinstance(value, (bytes, memoryview)):
            value = str(value, 'utf-8', 'replace')
        if code == 22:
            ret = set_pointer_shape(self.screen, value, self.os_window_id)
            if ret:
                self.screen.send_escape_code_to_child(ESC_OSC, '22;' + ret)
            return

        dirtied = default_bg_changed = False
        def change(which: DynamicColor, val: str) -> None:
            nonlocal dirtied, default_bg_changed
            dirtied = True
            if which.name == 'default_bg':
                default_bg_changed = True
            v = to_color(val) if val else None
            if v is None:
                delattr(self.screen.color_profile, which.name)
            else:
                setattr(self.screen.color_profile, which.name, v)

        for val in value.split(';'):
            w = DYNAMIC_COLOR_CODES.get(code)
            if w is not None:
                if val == '?':
                    col = getattr(self.screen.color_profile, w.name) or Color()
                    self.report_color(str(code), col)
                else:
                    q = '' if code >= 100 else val
                    change(w, q)
            code += 1
        if dirtied:
            self.screen.mark_as_dirty()
        if default_bg_changed:
            get_boss().default_bg_changed_for(self.id, via_escape_code=True)

    @property
    def is_dark(self) -> bool:
        return self.screen.color_profile.default_bg.is_dark

    def on_color_scheme_preference_change(self, via_escape_code: bool = False) -> None:
        if self.screen.color_preference_notification and not via_escape_code:
            self.report_color_scheme_preference()
        self.call_watchers(self.watchers.on_color_scheme_preference_change, {
            'is_dark': self.is_dark, 'via_escape_code': via_escape_code
        })

    def report_color_scheme_preference(self) -> None:
        n = 1 if self.is_dark else 2
        self.screen.send_escape_code_to_child(ESC_CSI, f'?997;{n}n')

    def set_color_table_color(self, code: int, bvalue: memoryview | None = None) -> None:
        value = str(bvalue or b'', 'utf-8', 'replace')
        cp = self.screen.color_profile

        def parse_color_set(raw: str) -> Generator[tuple[int, int | None], None, None]:
            parts = raw.split(';')
            lp = len(parts)
            if lp % 2 != 0:
                return
            for c_, spec in [parts[i:i + 2] for i in range(0, len(parts), 2)]:
                try:
                    c = int(c_)
                    if c < 0 or c > 255:
                        continue
                    if spec == '?':
                        yield c, None
                    else:
                        q = to_color(spec)
                        if q is not None:
                            yield c, color_as_int(q)
                except Exception:
                    continue

        if code == 4:
            changed = False
            for c, val in parse_color_set(value):
                if val is None:  # color query
                    qc = self.screen.color_profile.as_color((c << 8) | 1)
                    assert qc is not None
                    self.report_color(f'4;{c}', qc)
                else:
                    changed = True
                    cp.set_color(c, val)
            if changed:
                self.refresh()
        elif code == 104:
            if not value.strip():
                cp.reset_color_table()
            else:
                for x in value.split(';'):
                    try:
                        y = int(x)
                    except Exception:
                        continue
                    if 0 <= y <= 255:
                        cp.reset_color(y)
            self.refresh()

    def request_capabilities(self, q: str) -> None:
        for result in get_capabilities(q, get_options(), self.id, self.os_window_id):
            self.screen.send_escape_code_to_child(ESC_DCS, result)

    def handle_remote_cmd(self, cmd: memoryview) -> None:
        get_boss().handle_remote_cmd(cmd, self)

    def handle_remote_echo(self, msg: memoryview) -> None:
        data = base64_decode(msg)
        # ensure we are not writing any control char back as this can lead to command injection on shell prompts
        # Any bytes outside the printable ASCII range are removed.
        data = re.sub(rb'[^ -~]', b'', data)
        self.write_to_child(data)

    def handle_remote_ssh(self, msg: memoryview) -> None:
        from kittens.ssh.utils import get_ssh_data
        for line in get_ssh_data(msg, f'{os.getpid()}-{self.id}'):
            self.write_to_child(line)

    def handle_kitten_result(self, msg: memoryview) -> None:
        import base64
        self.kitten_result = json.loads(base64.b85decode(msg))
        for processor in self.kitten_result_processors:
            try:
                processor(self, self.kitten_result)
            except Exception:
                import traceback
                traceback.print_exc()

    def add_kitten_result_processor(self, callback: Callable[['Window', Any], None]) -> None:
        self.kitten_result_processors.append(callback)

    def handle_overlay_ready(self, msg: memoryview) -> None:
        boss = get_boss()
        tab = boss.tab_for_window(self)
        if tab is not None:
            tab.move_window_to_top_of_group(self)
        if self.keys_redirected_till_ready_from:
            set_redirect_keys_to_overlay(self.os_window_id, self.tab_id, self.keys_redirected_till_ready_from, 0)
            buffer_keys_in_window(self.os_window_id, self.tab_id, self.id, False)
            self.keys_redirected_till_ready_from = 0

    def append_remote_data(self, msgb: memoryview) -> str:
        if not msgb:
            cdata = ''.join(self.current_remote_data)
            self.current_remote_data = []
            return cdata
        msg = str(msgb, 'utf-8', 'replace')
        num, rest = msg.split(':', 1)
        max_size = get_options().clipboard_max_size * 1024 * 1024
        if num == '0' or sum(map(len, self.current_remote_data)) > max_size:
            self.current_remote_data = []
        self.current_remote_data.append(rest)
        return ''

    def handle_remote_edit(self, msg: memoryview) -> None:
        cdata = self.append_remote_data(msg)
        if cdata:
            from .launch import remote_edit
            remote_edit(cdata, self)

    def handle_remote_clone(self, msg: memoryview) -> None:
        cdata = self.append_remote_data(msg)
        if cdata:
            ac = get_options().allow_cloning
            if ac == 'ask':
                get_boss().confirm(_(
                    'A program running in this window wants to clone it into another window.'
                    ' Allow it do so, once?'),
                    partial(self.handle_remote_clone_confirmation, cdata), window=self,
                    title=_('Allow cloning of window?'),
                )
            elif ac in ('yes', 'y', 'true'):
                self.handle_remote_clone_confirmation(cdata, True)

    def handle_remote_clone_confirmation(self, cdata: str, confirmed: bool) -> None:
        if confirmed:
            from .launch import clone_and_launch
            clone_and_launch(cdata, self)

    def handle_remote_askpass(self, msgb: memoryview) -> None:
        from .shm import SharedMemory
        msg = str(msgb, 'utf-8')
        with SharedMemory(name=msg, readonly=True) as shm:
            shm.seek(1)
            data = json.loads(shm.read_data_with_size())

        def callback(ans: Any) -> None:
            data = json.dumps(ans)
            with SharedMemory(name=msg) as shm:
                shm.seek(1)
                shm.write_data_with_size(data)
                shm.flush()
                shm.seek(0)
                shm.write(b'\x01')

        message: str = data['message']
        if data['type'] == 'confirm':
            get_boss().confirm(
                message, callback, window=self, confirm_on_cancel=bool(data.get('confirm_on_cancel')),
                confirm_on_accept=bool(data.get('confirm_on_accept', True)))
        elif data['type'] == 'choose':
            get_boss().choose(
                message, callback, *data['choices'], window=self, default=data.get('default', ''))
        elif data['type'] == 'get_line':
            get_boss().get_line(
                message, callback, window=self, is_password=bool(data.get('is_password')), prompt=data.get('prompt', '> '))
        else:
            log_error(f'Ignoring ask request with unknown type: {data["type"]}')

    def handle_remote_print(self, msg: memoryview) -> None:
        text = process_remote_print(msg)
        print(text, end='', flush=True)

    def handle_restore_cursor_appearance(self, msg: memoryview | None = None) -> None:
        opts = get_options()
        self.screen.cursor.blink = opts.cursor_blink_interval[0] != 0
        self.screen.cursor.shape = opts.cursor_shape
        self.screen.cursor_visible = True
        delattr(self.screen.color_profile, 'cursor_color')

    def send_cmd_response(self, response: Any) -> None:
        self.screen.send_escape_code_to_child(ESC_DCS, '@kitty-cmd' + json.dumps(response))

    def file_transmission(self, data: memoryview) -> None:
        self.file_transmission_control.handle_serialized_command(data)

    def clipboard_control(self, data: memoryview, is_partial: bool | None = False) -> None:
        if is_partial is None:
            self.clipboard_request_manager.parse_osc_5522(data)
        else:
            self.clipboard_request_manager.parse_osc_52(data, is_partial)

    def manipulate_title_stack(self, pop: bool, title: str, icon: Any) -> None:
        if title:
            if pop:
                if self.title_stack:
                    self.child_title = self.title_stack.pop()
                    self.call_watchers(self.watchers.on_title_change, {'title': self.child_title, 'from_child': True})
                    self.title_updated()
            else:
                if self.child_title:
                    self.title_stack.append(self.child_title)

    def handle_cmd_end(self, exit_status: str = '') -> None:
        if self.last_cmd_output_start_time == 0.:
            return
        try:
            self.last_cmd_exit_status = int(exit_status)
        except Exception:
            self.last_cmd_exit_status = 0
        end_time = monotonic()
        last_cmd_output_duration = end_time - self.last_cmd_output_start_time
        self.last_cmd_output_start_time = 0.

        self.call_watchers(self.watchers.on_cmd_startstop, {
            "is_start": False, "time": end_time, 'cmdline': self.last_cmd_cmdline, 'exit_status': self.last_cmd_exit_status})

        opts = get_options()
        when, duration, action, notify_cmdline, _ = opts.notify_on_cmd_finish

        if last_cmd_output_duration >= duration and when != 'never':
            from .notifications import OnlyWhen
            nm = get_boss().notification_manager
            cmd = nm.create_notification_cmd()
            cmd.title = 'kitty'
            s = self.last_cmd_cmdline.replace('\\\n', ' ')
            cmd.body = f'Command {s} finished with status: {exit_status}.\nClick to focus.'
            cmd.only_when = OnlyWhen(when)
            if not nm.is_notification_allowed(cmd, self.id):
                return
            if action == 'notify':
                if self.last_cmd_end_notification is not None:
                    if 'next' in opts.notify_on_cmd_finish.clear_on:
                        nm.close_notification(self.last_cmd_end_notification[0])
                    self.last_cmd_end_notification = None
                notification_id = nm.notify_with_command(cmd, self.id)
                if notification_id is not None:
                    self.last_cmd_end_notification = notification_id, cmd.only_when
            elif action == 'bell':
                self.screen.bell()
            elif action == 'command':
                open_cmd([x.replace('%c', self.last_cmd_cmdline).replace('%s', exit_status) for x in notify_cmdline])
            else:
                raise ValueError(f'Unknown action in option `notify_on_cmd_finish`: {action}')

    def cmd_output_marking(self, is_start: bool | None, cmdline: str = '') -> None:
        if is_start:
            start_time = monotonic()
            self.last_cmd_output_start_time = start_time
            cmdline = decode_cmdline(cmdline) if cmdline else ''
            self.last_cmd_cmdline = cmdline
            self.call_watchers(self.watchers.on_cmd_startstop, {"is_start": True, "time": start_time, 'cmdline': cmdline, 'exit_status': 0})
        else:
            self.handle_cmd_end(cmdline)
    # }}}

    # mouse actions {{{
    @ac('mouse', '''
        Handle a mouse click

        Try to perform the specified actions one after the other till one of them is successful.
        Supported actions are::

            selection - check for a selection and if one exists abort processing
            link - if a link exists under the mouse, click it
            prompt - if the mouse click happens at a shell prompt move the cursor to the mouse location

        For examples, see :ref:`conf-kitty-mouse.mousemap`
        ''')
    def mouse_handle_click(self, *actions: str) -> None:
        for a in actions:
            if a == 'selection':
                if self.screen.has_selection():
                    break
            if a == 'link':
                if click_mouse_url(self.os_window_id, self.tab_id, self.id):
                    break
            if a == 'prompt':
                # Do not send move cursor events too soon after the window is
                # focused, this is because there are people that click on
                # windows and start typing immediately and the cursor event
                # can interfere with that. See https://github.com/kovidgoyal/kitty/issues/4128
                if monotonic() - self.last_focused_at < 1.5 * get_click_interval():
                    return
                if move_cursor_to_mouse_if_in_prompt(self.os_window_id, self.tab_id, self.id):
                    self.screen.ignore_bells_for(1)
                    break

    @ac('mouse', 'Click the URL under the mouse')
    def mouse_click_url(self) -> None:
        self.mouse_handle_click('link')

    @ac('mouse', 'Click the URL under the mouse only if the screen has no selection')
    def mouse_click_url_or_select(self) -> None:
        self.mouse_handle_click('selection', 'link')

    @ac('mouse', '''
        Manipulate the selection based on the current mouse position

        For examples, see :ref:`conf-kitty-mouse.mousemap`
        ''')
    def mouse_selection(self, code: int) -> None:
        mouse_selection(self.os_window_id, self.tab_id, self.id, code, self.current_mouse_event_button)

    @ac('mouse', 'Paste the current primary selection')
    def paste_selection(self) -> None:
        txt = get_boss().current_primary_selection()
        if txt:
            self.paste_with_actions(txt)

    @ac('mouse', 'Paste the current primary selection or the clipboard if no selection is present')
    def paste_selection_or_clipboard(self) -> None:
        txt = get_boss().current_primary_selection_or_clipboard()
        if txt:
            self.paste_with_actions(txt)

    @ac('mouse', '''
        Select clicked command output

        Requires :ref:`shell_integration` to work
        ''')
    def mouse_select_command_output(self) -> None:
        click_mouse_cmd_output(self.os_window_id, self.tab_id, self.id, True)

    @ac('mouse', '''
        Show clicked command output in a pager like less

        Requires :ref:`shell_integration` to work
        ''')
    def mouse_show_command_output(self) -> None:
        if click_mouse_cmd_output(self.os_window_id, self.tab_id, self.id, False):
            self.show_cmd_output(CommandOutput.last_visited, 'Clicked command output')
    # }}}

    def text_for_selection(self, as_ansi: bool = False) -> str:
        sts = get_options().strip_trailing_spaces
        strip_trailing_spaces = sts == 'always' or (sts == 'smart' and not self.screen.is_rectangle_select())
        lines = self.screen.text_for_selection(as_ansi, strip_trailing_spaces)
        return ''.join(lines)

    def has_selection(self) -> bool:
        return self.screen.has_selection()

    def call_watchers(self, which: Iterable[Watcher], data: dict[str, Any]) -> None:
        boss = get_boss()
        for w in which:
            try:
                w(boss, self, data)
            except Exception:
                import traceback
                traceback.print_exc()

    def destroy(self) -> None:
        self.call_watchers(self.watchers.on_close, {})
        self.destroyed = True
        self.clipboard_request_manager.close()
        del self.kitten_result_processors
        if hasattr(self, 'screen'):
            if self.is_active and self.os_window_id == current_focused_os_window_id():
                # Cancel IME composition when window is destroyed
                update_ime_position_for_window(self.id, False, -1)
            # Remove cycles so that screen is de-allocated immediately
            self.screen.reset_callbacks()
            del self.screen

    def as_text(
        self,
        as_ansi: bool = False,
        add_history: bool = False,
        add_wrap_markers: bool = False,
        alternate_screen: bool = False,
        add_cursor: bool = False
    ) -> str:
        return as_text(self.screen, as_ansi, add_history, add_wrap_markers, alternate_screen, add_cursor)

    def cmd_output(self, which: CommandOutput = CommandOutput.last_run, as_ansi: bool = False, add_wrap_markers: bool = False) -> str:
        return cmd_output(self.screen, which, as_ansi, add_wrap_markers)

    def get_cwd_of_child(self, oldest: bool = False) -> str | None:
        return self.child.get_foreground_cwd(oldest) or self.child.current_cwd

    def get_cwd_of_root_child(self) -> str | None:
        return self.child.current_cwd

    def get_exe_of_child(self, oldest: bool = False) -> str:
        return self.child.get_foreground_exe(oldest) or self.child.argv[0]

    @property
    def cwd_of_child(self) -> str | None:
        return self.get_cwd_of_child()

    @property
    def root_in_foreground_processes(self) -> bool:
        q = self.child.pid
        for p in self.child.foreground_processes:
            if p['pid'] == q:
                return True
        return False

    @property
    def child_is_remote(self) -> bool:
        for p in self.child.foreground_processes:
            q = list(p['cmdline'] or ())
            if q and q[0].lower() == 'ssh':
                return True
        return False

    def ssh_kitten_cmdline(self) -> list[str]:
        from kittens.ssh.utils import is_kitten_cmdline
        for p in self.child.foreground_processes:
            q = list(p['cmdline'] or ())
            if len(q) > 3 and os.path.basename(q[0]) == 'kitten' and q[1] == 'run-shell':
                q = q[2:]  # --hold-after-ssh causes kitten run-shell wrapper to be added
            if is_kitten_cmdline(q):
                return q
        return []

    def pipe_data(self, text: str, has_wrap_markers: bool = False) -> PipeData:
        text = text or ''
        if has_wrap_markers:
            text = text.replace('\r\n', '\n').replace('\r', '\n')
        lines = text.count('\n')
        input_line_number = (lines - (self.screen.lines - 1) - self.screen.scrolled_by)
        return {
            'input_line_number': input_line_number,
            'scrolled_by': self.screen.scrolled_by,
            'cursor_x': self.screen.cursor.x + 1,
            'cursor_y': self.screen.cursor.y + 1,
            'lines': self.screen.lines,
            'columns': self.screen.columns,
            'text': text
        }

    def set_logo(self, path: str, position: str = '', alpha: float = -1, png_data: bytes = b'') -> None:
        path = resolve_custom_file(path) if path else ''
        set_window_logo(self.os_window_id, self.tab_id, self.id, path, position or '', alpha, png_data)

    def paste_with_actions(self, text: str) -> None:
        if self.destroyed or not text:
            return
        opts = get_options()
        if 'filter' in opts.paste_actions:
            text = load_paste_filter()(text)
            if not text:
                return
        if 'quote-urls-at-prompt' in opts.paste_actions and self.at_prompt:
            prefixes = '|'.join(opts.url_prefixes)
            m = re.match(f'({prefixes}):(.+)', text)
            if m is not None:
                scheme, rest = m.group(1), m.group(2)
                if rest.startswith('//') or scheme in ('mailto', 'irc'):
                    import shlex
                    text = shlex.quote(text)
        if 'replace-dangerous-control-codes' in opts.paste_actions:
            text = replace_c0_codes_except_nl_space_tab(text)
        if 'replace-newline' in opts.paste_actions and 'confirm' not in opts.paste_actions:
            text = text.replace('\n', '\x1bE')
        btext = text.encode('utf-8')
        if 'confirm' in opts.paste_actions:
            sanitized = replace_c0_codes_except_nl_space_tab(btext)
            replaced_c0_control_codes = sanitized != btext
            if 'replace-newline' in opts.paste_actions:
                sanitized = sanitized.replace(b'\n', b'\x1bE')
            replaced_newlines = False
            if not self.screen.in_bracketed_paste_mode:
                # \n is converted to \r and \r is interpreted as the enter key
                # by legacy programs that dont support the full kitty keyboard protocol,
                # which in the case of shells can lead to command execution, so
                # replace with <ESC>E (NEL) which has the newline visual effect \r\n but
                # isnt interpreted as Enter.
                t = sanitized.replace(b'\n', b'\x1bE')
                replaced_newlines = t != sanitized
                sanitized = t
            if replaced_c0_control_codes or replaced_newlines:
                msg = _('The text to be pasted contains terminal control codes.\n\nIf the terminal program you are pasting into does not properly'
                        ' sanitize pasted text, this can lead to \x1b[31mcode execution vulnerabilities\x1b[39m.\n\nHow would you like to proceed?')
                get_boss().choose(
                    msg, partial(self.handle_dangerous_paste_confirmation, btext, sanitized),
                    's;green:Sanitize and paste', 'p;red:Paste anyway', 'c;yellow:Cancel',
                    window=self, default='s', title=_('Allow paste?'),
                )
                return
        if 'confirm-if-large' in opts.paste_actions:
            msg = ''
            if len(btext) > 16 * 1024:
                msg = _('Pasting very large amounts of text ({} bytes) can be slow.').format(len(btext))
                get_boss().confirm(msg + _(' Are you sure?'), partial(self.handle_large_paste_confirmation, btext), window=self, title=_(
                'Allow large paste?'))
                return
        self.paste_text(btext)

    def handle_dangerous_paste_confirmation(self, unsanitized: bytes, sanitized: bytes, choice: str) -> None:
        if choice == 's':
            self.paste_text(sanitized)
        elif choice == 'p':
            self.paste_text(unsanitized)

    def handle_large_paste_confirmation(self, btext: bytes, confirmed: bool) -> None:
        if confirmed:
            self.paste_text(btext)

    def paste_bytes(self, text: str | bytes) -> None:
        # paste raw bytes without any processing
        if isinstance(text, str):
            text = text.encode('utf-8')
        self.screen.paste_bytes(text)

    def paste_text(self, text: str | bytes) -> None:
        if text and not self.destroyed:
            if isinstance(text, str):
                text = text.encode('utf-8')
            if self.screen.in_bracketed_paste_mode:
                text = sanitize_for_bracketed_paste(text)
            else:
                # Workaround for broken editors like nano that cannot handle
                # newlines in pasted text see https://github.com/kovidgoyal/kitty/issues/994
                text = text.replace(b'\r\n', b'\n').replace(b'\n', b'\r')
            self.screen.paste(text)

    def clear_screen(self, reset: bool = False, scrollback: bool = False) -> None:
        self.screen.cursor.x = self.screen.cursor.y = 0
        if reset:
            self.screen.reset()
        else:
            self.screen.erase_in_display(3 if scrollback else 2, False)

    def current_mouse_position(self) -> Optional['MousePosition']:
        ' Return the last position at which a mouse event was received by this window '
        return get_mouse_data_for_window(self.os_window_id, self.tab_id, self.id)

    # actions {{{

    @ac('cp', 'Show scrollback in a pager like less')
    def show_scrollback(self) -> None:
        text = self.as_text(as_ansi=True, add_history=True, add_wrap_markers=True)
        data = self.pipe_data(text, has_wrap_markers=True)
        cursor_on_screen = self.screen.scrolled_by < self.screen.lines - self.screen.cursor.y
        get_boss().display_scrollback(self, data['text'], data['input_line_number'], report_cursor=cursor_on_screen)

    def show_cmd_output(self, which: CommandOutput, title: str = 'Command output', as_ansi: bool = True, add_wrap_markers: bool = True) -> None:
        text = self.cmd_output(which, as_ansi=as_ansi, add_wrap_markers=add_wrap_markers)
        text = text.replace('\r\n', '\n').replace('\r', '\n')
        get_boss().display_scrollback(self, text, title=title, report_cursor=False)

    @ac('cp', '''
        Show output from the first shell command on screen in a pager like less

        Requires :ref:`shell_integration` to work
        ''')
    def show_first_command_output_on_screen(self) -> None:
        self.show_cmd_output(CommandOutput.first_on_screen, 'First command output on screen')

    @ac('cp', '''
        Show output from the last shell command in a pager like less

        Requires :ref:`shell_integration` to work
        ''')
    def show_last_command_output(self) -> None:
        self.show_cmd_output(CommandOutput.last_run, 'Last command output')

    @ac('cp', '''
        Show the first command output below the last scrolled position via scroll_to_prompt
        or the last mouse clicked command output in a pager like less

        Requires :ref:`shell_integration` to work
        ''')
    def show_last_visited_command_output(self) -> None:
        self.show_cmd_output(CommandOutput.last_visited, 'Last visited command output')

    @ac('cp', '''
        Show the last non-empty output from a shell command in a pager like less

        Requires :ref:`shell_integration` to work
        ''')
    def show_last_non_empty_command_output(self) -> None:
        self.show_cmd_output(CommandOutput.last_non_empty, 'Last non-empty command output')

    @ac('cp', 'Paste the specified text into the current window. ANSI C escapes are decoded.')
    def paste(self, text: str) -> None:
        self.paste_with_actions(text)

    @ac('cp', 'Copy the selected text from the active window to the clipboard')
    def copy_to_clipboard(self) -> None:
        text = self.text_for_selection()
        if text:
            set_clipboard_string(text)

    @ac('cp', 'Copy the selected text from the active window to the clipboard with ANSI formatting codes')
    def copy_ansi_to_clipboard(self) -> None:
        text = self.text_for_selection(as_ansi=True)
        if text:
            set_clipboard_string(text)

    def encoded_key(self, key_event: KeyEvent) -> bytes:
        return encode_key_for_tty(
            key=key_event.key, shifted_key=key_event.shifted_key, alternate_key=key_event.alternate_key,
            mods=key_event.mods, action=key_event.action, text=key_event.text,
            key_encoding_flags=self.screen.current_key_encoding_flags(),
            cursor_key_mode=self.screen.cursor_key_mode,
        ).encode('ascii')

    @ac('cp', 'Copy the selected text from the active window to the clipboard, if no selection, send SIGINT (aka :kbd:`ctrl+c`)')
    def copy_or_interrupt(self) -> None:
        text = self.text_for_selection()
        if text:
            set_clipboard_string(text)
        else:
            self.scroll_end()
            self.write_to_child(self.encoded_key(KeyEvent(key=ord('c'), mods=GLFW_MOD_CONTROL)))

    @ac('cp', 'Copy the selected text from the active window to the clipboard and clear selection, if no selection, send SIGINT (aka :kbd:`ctrl+c`)')
    def copy_and_clear_or_interrupt(self) -> None:
        self.copy_or_interrupt()
        self.screen.clear_selection()

    @ac('cp', 'Pass the selected text from the active window to the specified program')
    def pass_selection_to_program(self, *args: str) -> None:
        cwd = self.cwd_of_child
        text = self.text_for_selection()
        if text:
            if args:
                open_cmd(args, text, cwd=cwd)
            else:
                open_url(text, cwd=cwd)

    @ac('cp', 'Clear the current selection')
    def clear_selection(self) -> None:
        self.screen.clear_selection()

    @ac('sc', 'Scroll up by one line when in main screen. To scroll by different amounts, you can map the remote_control scroll-window action.')
    def scroll_line_up(self) -> bool | None:
        if self.screen.is_main_linebuf():
            self.screen.scroll(SCROLL_LINE, True)
            return None
        return True

    @ac('sc', 'Scroll down by one line when in main screen. To scroll by different amounts, you can map the remote_control scroll-window action.')
    def scroll_line_down(self) -> bool | None:
        if self.screen.is_main_linebuf():
            self.screen.scroll(SCROLL_LINE, False)
            return None
        return True

    @ac('sc', 'Scroll up by one page when in main screen. To scroll by different amounts, you can map the remote_control scroll-window action.')
    def scroll_page_up(self) -> bool | None:
        if self.screen.is_main_linebuf():
            self.screen.scroll(SCROLL_PAGE, True)
            return None
        return True

    @ac('sc', 'Scroll down by one page when in main screen. To scroll by different amounts, you can map the remote_control scroll-window action.')
    def scroll_page_down(self) -> bool | None:
        if self.screen.is_main_linebuf():
            self.screen.scroll(SCROLL_PAGE, False)
            return None
        return True

    @ac('sc', 'Scroll to the top of the scrollback buffer when in main screen')
    def scroll_home(self) -> bool | None:
        if self.screen.is_main_linebuf():
            self.screen.scroll(SCROLL_FULL, True)
            return None
        return True

    @ac('sc', 'Scroll to the bottom of the scrollback buffer when in main screen')
    def scroll_end(self) -> bool | None:
        if self.screen.is_main_linebuf():
            self.screen.scroll(SCROLL_FULL, False)
            return None
        return True

    @ac('sc', '''
        Scroll to the previous/next shell command prompt
        Allows easy jumping from one command to the next. Requires working
        :ref:`shell_integration`. Takes two optional numbers as arguments:

        The first is the number of prompts to jump; negative values jump up and
        positive values jump down. A value of zero will jump to the last prompt
        visited by this action. Defaults to -1

        The second is the number of lines to show above the prompt that was
        jumped to. This is somewhat like `less`'s `--jump-target` option or
        vim's `scrolloff` setting. Defaults to 0.

        For example::

            map ctrl+p scroll_to_prompt -1 3  # jump to previous, showing 3 lines prior
            map ctrl+n scroll_to_prompt 1     # jump to next
            map ctrl+o scroll_to_prompt 0     # jump to last visited
        ''')
    def scroll_to_prompt(self, num_of_prompts: int = -1, scroll_offset: int = 0) -> bool | None:
        if self.screen.is_main_linebuf():
            self.screen.scroll_to_prompt(num_of_prompts, scroll_offset)
            return None
        return True

    @ac('sc', 'Scroll prompt to the top of the screen, filling screen with empty lines, when in main screen.'
        ' To avoid putting the lines above the prompt into the scrollback use scroll_prompt_to_top y')
    def scroll_prompt_to_top(self, clear_scrollback: bool = False) -> bool | None:
        if self.screen.is_main_linebuf():
            self.screen.scroll_until_cursor_prompt(not clear_scrollback)
            if self.screen.scrolled_by > 0:
                self.scroll_end()
            return None
        return True

    @ac('sc', 'Scroll prompt to the bottom of the screen, filling in extra lines from the scrollback buffer, when in main screen')
    def scroll_prompt_to_bottom(self) -> bool | None:
        if self.screen.is_main_linebuf():
            self.screen.scroll_prompt_to_bottom()
            return None
        return True

    @ac('mk', 'Toggle the current marker on/off')
    def toggle_marker(self, ftype: str, spec: str | tuple[tuple[int, str], ...], flags: int) -> None:
        from .marks import marker_from_spec
        key = ftype, spec
        if key == self.current_marker_spec:
            self.remove_marker()
            return
        self.screen.set_marker(marker_from_spec(ftype, spec, flags))
        self.current_marker_spec = key

    def set_marker(self, spec: str | Sequence[str]) -> None:
        from .marks import marker_from_spec
        from .options.utils import parse_marker_spec, toggle_marker
        if isinstance(spec, str):
            func, (ftype, spec_, flags) = toggle_marker('toggle_marker', spec)
        else:
            ftype, spec_, flags = parse_marker_spec(spec[0], spec[1:])
        key = ftype, spec_
        self.screen.set_marker(marker_from_spec(ftype, spec_, flags))
        self.current_marker_spec = key

    @ac('mk', 'Remove a previously created marker')
    def remove_marker(self) -> None:
        if self.current_marker_spec is not None:
            self.screen.set_marker()
            self.current_marker_spec = None

    @ac('mk', 'Scroll to the next or previous mark of the specified type')
    def scroll_to_mark(self, prev: bool = True, mark: int = 0) -> None:
        self.screen.scroll_to_next_mark(mark, prev)

    @ac('misc', '''
        Send the specified SIGNAL to the foreground process in the active window

        For example::

            map f1 signal_child SIGTERM
        ''')
    def signal_child(self, *signals: int) -> None:
        pid = self.child.pid_for_cwd
        if pid is not None:
            for sig in signals:
                os.kill(pid, sig)

    @ac('misc', '''
    Display the specified kitty documentation, preferring a local copy, if found.

    For example::

        # show the config docs
        map f1 show_kitty_doc conf
        # show the ssh kitten docs
        map f1 show_kitty_doc kittens/ssh
    ''')
    def show_kitty_doc(self, which: str = '') -> None:
        url = docs_url(which)
        get_boss().open_url(url)
    # }}}


def set_pointer_shape(screen: Screen, value: str, os_window_id: int = 0) -> str:
    op, ret = '=', ''
    if value and value[0] in '><=?':
        op = value[0]
        value = value[1:]
    if op in '=>':
        for v in value.split(','):
            if v or op == '=':
                screen.change_pointer_shape(op, v)
        if os_window_id and current_focused_os_window_id() == os_window_id:
            update_pointer_shape(os_window_id)
    elif op == '<':
        screen.change_pointer_shape('<', '')
        if os_window_id and current_focused_os_window_id() == os_window_id:
            update_pointer_shape(os_window_id)
    elif op == '?':
        ans = []
        for q in value.split(','):
            if is_css_pointer_name_valid(q):
                ans.append('1')
            else:
                if q == '__default__':
                    ans.append(pointer_name_to_css_name(get_options().default_pointer_shape))
                elif q == '__grabbed__':
                    ans.append(pointer_name_to_css_name(get_options().pointer_shape_when_grabbed))
                elif q == '__current__':
                    ans.append(screen.current_pointer_shape())
                else:
                    ans.append('0')
        ret = ','.join(ans)
    return ret
