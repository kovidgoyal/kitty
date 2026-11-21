#!/usr/bin/env python
# License: GPLv3 Copyright: 2026, Kovid Goyal <kovid at kovidgoyal.net>

# Support for the user supplied launch_wrapper.py module in the kitty config
# directory, which can prefix the commands kitty runs in new windows with a
# wrapper command. See docs/launch-wrapper.rst

import os
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import TYPE_CHECKING, NamedTuple

from .constants import config_dir, config_dir_files_ignored
from .fast_data_types import get_boss, get_options
from .types import run_once
from .utils import cmdline_for_hold, is_same_executable, log_error, resolved_shell

if TYPE_CHECKING:
    from .window import CwdRequest

MODULE_NAME = 'launch_wrapper.py'
FUNCTION_NAME = 'prefix_for_launch'


class LaunchRequest(NamedTuple):
    """
    Marks a window launch as one requested by the user, rather than one
    kitty makes internally, such as for kittens or the scrollback pager. Only
    such launches are passed to the launch wrapper.
    """

    # The type of the new window, one of the values of launch --type that
    # create windows, such as: window, tab, os-window, overlay, overlay-main
    launch_type: str
    # The id of the window the new one is being opened from, if any
    source_window_id: int | None = None
    # The user variables from launch --var
    user_vars: tuple[tuple[str, str], ...] = ()


class LaunchContext(NamedTuple):
    # The command kitty will run, before kitty adds its own helpers, such as
    # the run-shell kitten or /usr/bin/login on macOS. These are inserted
    # between the prefix and this command. The program is as requested, for
    # example, a name to be looked up in PATH, unless it would not be found in
    # PATH from env, in which case it is the full path kitty found it at.
    argv: tuple[str, ...]
    # The working directory the command should run in
    cwd: str
    # The full environment the command will be run with, including the
    # variables kitty sets, such as for shell integration and remote control.
    env: Mapping[str, str]
    # True if argv is the shell configured via the shell option
    is_default_shell: bool
    # The id of the new window, the same as KITTY_WINDOW_ID in env
    window_id: int
    # See LaunchRequest.launch_type
    launch_type: str
    # The id of the window the new one is opened from, if any
    source_window_id: int | None
    # The pid of the foreground process in the source window, if any
    source_pid: int | None
    # User variables from launch --var
    user_vars: Mapping[str, str]
    # True if the window is held open after the command exits, as with launch
    # --hold. Unless the wrapper returns a LaunchPrefix with handles_hold set,
    # kitty holds the window by running the command via the run-shell kitten,
    # placed outside the prefix, so that the window is held even if the
    # wrapper fails. The shell the window is held at thus runs outside the
    # wrapper.
    hold: bool = False


@dataclass(frozen=True, kw_only=True)
class LaunchPrefix:
    """
    The full form of the value returned by the launch wrapper function. A plain
    list of strings is the same as LaunchPrefix(argv=the_list). Fields are
    keyword only, so that more can be added in the future.
    """

    # The prefix to run the command with
    argv: Sequence[str] = ()
    # If True and the window is held, as indicated by LaunchContext.hold,
    # kitty does not hold the window itself, the prefix is responsible for
    # doing so, for example, by using hold_prefix(). Ignored if argv is empty.
    handles_hold: bool = False


PrefixFunc = Callable[[LaunchContext], LaunchPrefix | Sequence[str] | None]


def hold_prefix() -> list[str]:
    """
    The prefix kitty uses to hold windows open: it runs the command and then
    the shell, with shell integration, once the command exits. For use in a
    LaunchPrefix with handles_hold set.
    """
    return cmdline_for_hold()


@run_once
def load_prefix_func() -> PrefixFunc | None:
    if config_dir_files_ignored():
        return None
    path = os.path.join(config_dir, MODULE_NAME)
    import runpy

    try:
        m = runpy.run_path(path)
    except FileNotFoundError:
        return None
    except Exception as e:
        import traceback

        traceback.print_exc()
        log_error(f'Failed to load {path} with error: {e}')
        return None
    func = m.get(FUNCTION_NAME)
    if not callable(func):
        log_error(f'{path} does not define a {FUNCTION_NAME}() function, ignoring it')
        return None
    ans: PrefixFunc = func
    return ans


def clear_caches() -> None:
    load_prefix_func.clear_cached()


def source_pid_for(window_id: int | None) -> int | None:
    if window_id is None:
        return None
    w = get_boss().window_id_map.get(window_id)
    if w is None:
        return None
    try:
        return w.child.pid_for_cwd
    except Exception as e:
        log_error(f'Failed to get the foreground process of window {window_id} with error: {e}')
        return None


def is_same_command(a: Sequence[str], b: Sequence[str]) -> bool:
    # Commands are the same if their arguments are and they run the same
    # executable, whether or not it is given as a full path
    a, b = list(a), list(b)
    if a == b:
        return True
    if not a or len(a) != len(b) or a[1:] != b[1:]:
        return False
    return is_same_executable(a[0], b[0])


def prefix_for_launch(
    req: LaunchRequest, argv: Sequence[str], cwd: str, env: Mapping[str, str], *, unmodified_argv: Sequence[str], hold: bool = False
) -> LaunchPrefix:
    """
    Return the prefix to run argv with, from the user's launch wrapper, with
    argv as a tuple. Any failure is reported and results in no prefix, so that
    a broken wrapper does not prevent new windows from being opened.
    """
    func = load_prefix_func()
    if func is None:
        return LaunchPrefix()
    try:
        window_id = int(env.get('KITTY_WINDOW_ID', '0'))
    except ValueError:
        window_id = 0
    ctx = LaunchContext(
        argv=tuple(argv),
        cwd=cwd,
        env=MappingProxyType(dict(env)),
        is_default_shell=is_same_command(unmodified_argv, resolved_shell(get_options())),
        window_id=window_id,
        launch_type=req.launch_type,
        source_window_id=req.source_window_id,
        source_pid=source_pid_for(req.source_window_id),
        user_vars=MappingProxyType(dict(req.user_vars)),
        hold=hold,
    )
    try:
        ans = func(ctx)
    except Exception as e:
        import traceback

        traceback.print_exc()
        log_error(f'The {FUNCTION_NAME}() function in {MODULE_NAME} failed with error: {e}, running the command without a wrapper')
        return LaunchPrefix()
    if ans is None:
        return LaunchPrefix()
    if isinstance(ans, LaunchPrefix):
        argv, handles_hold = ans.argv, ans.handles_hold
        if not isinstance(handles_hold, bool):
            log_error(f'The {FUNCTION_NAME}() function in {MODULE_NAME} returned a LaunchPrefix with a non-boolean handles_hold: {handles_hold!r}, ignoring it')
            return LaunchPrefix()
    else:
        argv, handles_hold = ans, False
    if isinstance(argv, str) or not isinstance(argv, Sequence) or not all(isinstance(x, str) for x in argv):
        log_error(f'The {FUNCTION_NAME}() function in {MODULE_NAME} must return a LaunchPrefix, a list of strings or None, got: {ans!r}, ignoring it')
        return LaunchPrefix()
    argv = tuple(argv)
    return LaunchPrefix(argv=argv, handles_hold=handles_hold and bool(argv))


def user_launch_request(launch_type: str, cwd_from: 'CwdRequest | None' = None) -> LaunchRequest:
    """
    A request for a window the user asked for via a kitty action, such as
    new_window or new_tab. The window it is opened from is the one the working
    directory is taken from, if any, otherwise the active window.
    """
    if cwd_from:
        return LaunchRequest(launch_type, cwd_from.window_id)
    boss = get_boss()
    w = None if boss is None else boss.active_window_for_cwd
    return LaunchRequest(launch_type, None if w is None else w.id)
