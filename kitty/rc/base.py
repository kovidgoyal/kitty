#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPLv3 Copyright: 2020, Kovid Goyal <kovid at kovidgoyal.net>

from contextlib import suppress
from typing import (
    TYPE_CHECKING, Any, Callable, Dict, FrozenSet, Generator, Iterable, List,
    NoReturn, Optional, Tuple, Type, Union, cast
)

from kitty.cli import get_defaults_from_seq, parse_args, parse_option_spec
from kitty.cli_stub import RCOptions as R
from kitty.constants import appname, running_in_kitty

if TYPE_CHECKING:
    from kitty.boss import Boss as B
    from kitty.tabs import Tab
    from kitty.window import Window as W
    Window = W
    Boss = B
    Tab
else:
    Boss = Window = Tab = None
RCOptions = R


class NoResponse:
    pass


class RemoteControlError(Exception):
    pass


class MatchError(ValueError):

    hide_traceback = True

    def __init__(self, expression: str, target: str = 'windows'):
        ValueError.__init__(self, 'No matching {} for expression: {}'.format(target, expression))


class OpacityError(ValueError):

    hide_traceback = True


class UnknownLayout(ValueError):

    hide_traceback = True


class PayloadGetter:

    def __init__(self, cmd: 'RemoteCommand', payload: Dict[str, Any]):
        self.payload = payload
        self.cmd = cmd

    def __call__(self, key: str, opt_name: Optional[str] = None, missing: Any = None) -> Any:
        ans = self.payload.get(key, payload_get)
        if ans is not payload_get:
            return ans
        return self.cmd.get_default(opt_name or key, missing=missing)


no_response = NoResponse()
payload_get = object()
ResponseType = Optional[Union[bool, str]]
CmdReturnType = Union[Dict[str, Any], List, Tuple, str, int, float, bool]
CmdGenerator = Generator[CmdReturnType, None, None]
PayloadType = Optional[Union[CmdReturnType, CmdGenerator]]
PayloadGetType = PayloadGetter
ArgsType = List[str]


MATCH_WINDOW_OPTION = '''\
--match -m
The window to match. Match specifications are of the form:
:italic:`field:regexp`. Where field can be one of: id, title, pid, cwd, cmdline, num, env.
You can use the :italic:`ls` command to get a list of windows. Note that for
numeric fields such as id, pid and num the expression is interpreted as a number,
not a regular expression. The field num refers to the window position in the current tab,
starting from zero and counting clockwise (this is the same as the order in which the
windows are reported by the :italic:`ls` command). The window id of the current window
is available as the KITTY_WINDOW_ID environment variable. When using the :italic:`env` field
to match on environment variables you can specify only the environment variable name or a name
and value, for example, :italic:`env:MY_ENV_VAR=2`
'''
MATCH_TAB_OPTION = '''\
--match -m
The tab to match. Match specifications are of the form:
:italic:`field:regexp`. Where field can be one of:
id, title, window_id, window_title, pid, cwd, env, cmdline.
You can use the :italic:`ls` command to get a list of tabs. Note that for
numeric fields such as id and pid the expression is interpreted as a number,
not a regular expression. When using title or id, first a matching tab is
looked for and if not found a matching window is looked for, and the tab
for that window is used. You can also use window_id and window_title to match
the tab that contains the window with the specified id or title.
'''


class RemoteCommand:

    name: str = ''
    short_desc: str = ''
    desc: str = ''
    argspec: str = '...'
    options_spec: Optional[str] = None
    no_response: bool = False
    string_return_is_error: bool = False
    args_count: Optional[int] = None
    args_completion: Optional[Dict[str, Tuple[str, Union[Callable[[], Iterable[str]], Tuple[str, ...]]]]] = None
    defaults: Optional[Dict[str, Any]] = None
    options_class: Type = RCOptions

    def __init__(self) -> None:
        self.desc = self.desc or self.short_desc
        self.name = self.__class__.__module__.split('.')[-1].replace('_', '-')
        self.args_count = 0 if not self.argspec else self.args_count

    def fatal(self, msg: str) -> NoReturn:
        if running_in_kitty():
            raise RemoteControlError(msg)
        raise SystemExit(msg)

    def get_default(self, name: str, missing: Any = None) -> Any:
        if self.options_spec:
            if self.defaults is None:
                self.defaults = get_defaults_from_seq(parse_option_spec(self.options_spec)[0])
            return self.defaults.get(name, missing)
        return missing

    def windows_for_match_payload(self, boss: 'Boss', window: Optional['Window'], payload_get: PayloadGetType) -> List['Window']:
        if payload_get('all'):
            windows = list(boss.all_windows)
        else:
            if payload_get('self') in (None, True):
                window = window or boss.active_window
            else:
                window = boss.active_window or window
            windows = [window] if window else []
            if payload_get('match'):
                windows = list(boss.match_windows(payload_get('match')))
                if not windows:
                    raise MatchError(payload_get('match'))
        return windows

    def tabs_for_match_payload(self, boss: 'Boss', window: Optional['Window'], payload_get: PayloadGetType) -> List['Tab']:
        if payload_get('all'):
            return list(boss.all_tabs)
        match = payload_get('match')
        if match:
            tabs = list(boss.match_tabs(match))
            if not tabs:
                raise MatchError(match, 'tabs')
            return tabs
        if window and payload_get('self') in (None, True):
            q = boss.tab_for_window(window)
            if q:
                return [q]
        t = boss.active_tab
        if t:
            return [t]
        return []

    def windows_for_payload(self, boss: 'Boss', window: Optional['Window'], payload_get: PayloadGetType) -> List['Window']:
        if payload_get('all'):
            windows = list(boss.all_windows)
        else:
            window = window or boss.active_window
            windows = [window] if window else []
            if payload_get('match_window'):
                windows = list(boss.match_windows(payload_get('match_window')))
                if not windows:
                    raise MatchError(payload_get('match_window'))
            if payload_get('match_tab'):
                tabs = tuple(boss.match_tabs(payload_get('match_tab')))
                if not tabs:
                    raise MatchError(payload_get('match_tab'), 'tabs')
                for tab in tabs:
                    windows += list(tab)
        return windows

    def message_to_kitty(self, global_opts: RCOptions, opts: Any, args: ArgsType) -> PayloadType:
        raise NotImplementedError()

    def response_from_kitty(self, boss: 'Boss', window: Optional['Window'], payload_get: PayloadGetType) -> ResponseType:
        raise NotImplementedError()


def cli_params_for(command: RemoteCommand) -> Tuple[Callable[[], str], str, str, str]:
    return (command.options_spec or '\n').format, command.argspec, command.desc, '{} @ {}'.format(appname, command.name)


def parse_subcommand_cli(command: RemoteCommand, args: ArgsType) -> Tuple[Any, ArgsType]:
    opts, items = parse_args(args[1:], *cli_params_for(command), result_class=command.options_class)
    if command.args_count is not None and command.args_count != len(items):
        if command.args_count == 0:
            raise SystemExit('Unknown extra argument(s) supplied to {}'.format(command.name))
        raise SystemExit('Must specify exactly {} argument(s) for {}'.format(command.args_count, command.name))
    return opts, items


def display_subcommand_help(func: RemoteCommand) -> None:
    with suppress(SystemExit):
        parse_args(['--help'], (func.options_spec or '\n').format, func.argspec, func.desc, func.name)


def command_for_name(cmd_name: str) -> RemoteCommand:
    from importlib import import_module
    cmd_name = cmd_name.replace('-', '_')
    try:
        m = import_module(f'kitty.rc.{cmd_name}')
    except ImportError:
        raise KeyError(f'{cmd_name} is not a known kitty remote control command')
    return cast(RemoteCommand, getattr(m, cmd_name))


def all_command_names() -> FrozenSet[str]:
    try:
        from importlib.resources import contents
    except ImportError:
        from importlib_resources import contents  # type:ignore

    def ok(name: str) -> bool:
        root, _, ext = name.rpartition('.')
        return bool(ext in ('py', 'pyc', 'pyo') and root and root not in ('base', '__init__'))

    return frozenset({x.rpartition('.')[0] for x in filter(ok, contents('kitty.rc'))})
