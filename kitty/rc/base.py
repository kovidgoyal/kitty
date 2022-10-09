#!/usr/bin/env python
# License: GPLv3 Copyright: 2020, Kovid Goyal <kovid at kovidgoyal.net>

from contextlib import suppress
from dataclasses import dataclass
from typing import (
    TYPE_CHECKING, Any, Callable, Dict, FrozenSet, Iterable, Iterator, List,
    NoReturn, Optional, Set, Tuple, Type, Union, cast
)

from kitty.cli import get_defaults_from_seq, parse_args, parse_option_spec
from kitty.cli_stub import RCOptions as R
from kitty.constants import appname, list_kitty_resources, running_in_kitty
from kitty.types import AsyncResponse

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
        ValueError.__init__(self, f'No matching {target} for expression: {expression}')


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
ResponseType = Union[bool, str, None, NoResponse, AsyncResponse]
CmdReturnType = Union[Dict[str, Any], List[Any], Tuple[Any, ...], str, int, float, bool]
CmdGenerator = Iterator[CmdReturnType]
PayloadType = Optional[Union[CmdReturnType, CmdGenerator]]
PayloadGetType = PayloadGetter
ArgsType = List[str]


MATCH_WINDOW_OPTION = '''\
--match -m
The window to match. Match specifications are of the form: :italic:`field:query`.
Where :italic:`field` can be one of: :code:`id`, :code:`title`, :code:`pid`, :code:`cwd`, :code:`cmdline`, :code:`num`,
:code:`env`, :code:`state` and :code:`recent`.
:italic:`query` is the expression to match. Expressions can be either a number or a regular expression, and can be
:ref:`combined using Boolean operators <search_syntax>`.

The special value :code:`all` matches all windows.

For numeric fields: :code:`id`, :code:`pid`, :code:`num` and :code:`recent`, the expression is interpreted as
a number, not a regular expression.

The field :code:`num` refers to the window position in the current tab, starting from zero and counting clockwise (this
is the same as the order in which the windows are reported by the :ref:`kitty @ ls <at-ls>` command).

The window id of the current window is available as the :envvar:`KITTY_WINDOW_ID` environment variable.

The field :code:`recent` refers to recently active windows in the currently active tab, with zero being the currently
active window, one being the previously active window and so on.

When using the :code:`env` field to match on environment variables, you can specify only the environment variable name
or a name and value, for example, :code:`env:MY_ENV_VAR=2`.

The field :code:`state` matches on the state of the window. Supported states are:
:code:`active`, :code:`focused`, :code:`needs_attention`, :code:`parent_active` and :code:`parent_focused`.
Active windows are the windows that are active in their parent tab. There is only one focused window and it is the
window to which keyboard events are delivered.

Note that you can use the :ref:`kitty @ ls <at-ls>` command to get a list of windows.
'''
MATCH_TAB_OPTION = '''\
--match -m
The tab to match. Match specifications are of the form: :italic:`field:query`.
Where :italic:`field` can be one of: :code:`id`, :code:`index`, :code:`title`, :code:`window_id`, :code:`window_title`,
:code:`pid`, :code:`cwd`, :code:`cmdline` :code:`env`, :code:`state` and :code:`recent`.
:italic:`query` is the expression to match. Expressions can be either a number or a regular expression, and can be
:ref:`combined using Boolean operators <search_syntax>`.

The special value :code:`all` matches all tabs.

For numeric fields: :code:`id`, :code:`index`, :code:`window_id`, :code:`pid` and :code:`recent`, the
expression is interpreted as a number, not a regular expression.

When using :code:`title` or :code:`id`, first a matching tab is looked for, and if not found a matching window is looked
for, and the tab for that window is used.

You can also use :code:`window_id` and :code:`window_title` to match the tab that contains the window with the specified
id or title.

The :code:`index` number is used to match the nth tab in the currently active OS window.
The :code:`recent` number matches recently active tabs in the currently active OS window, with zero being the currently
active tab, one the previously active tab and so on.

When using the :code:`env` field to match on environment variables, you can specify only the environment variable name
or a name and value, for example, :code:`env:MY_ENV_VAR=2`. Tabs containing any window with the specified environment
variables are matched.

The field :code:`state` matches on the state of the tab. Supported states are:
:code:`active`, :code:`focused`, :code:`needs_attention`, :code:`parent_active` and :code:`parent_focused`.
Active tabs are the tabs that are active in their parent OS window. There is only one focused tab
and it is the tab to which keyboard events are delivered.

Note that you can use the :ref:`kitty @ ls <at-ls>` command to get a list of tabs.
'''


class ParsingOfArgsFailed(ValueError):
    pass


class AsyncResponder:

    def __init__(self, payload_get: PayloadGetType, window: Optional[Window]) -> None:
        self.async_id: str = payload_get('async_id', missing='')
        self.peer_id: int = payload_get('peer_id', missing=0)
        self.window_id: int = getattr(window, 'id', 0)

    def send_data(self, data: Any) -> None:
        from kitty.remote_control import send_response_to_client
        send_response_to_client(data=data, peer_id=self.peer_id, window_id=self.window_id, async_id=self.async_id)

    def send_error(self, error: str) -> None:
        from kitty.remote_control import send_response_to_client
        send_response_to_client(error=error, peer_id=self.peer_id, window_id=self.window_id, async_id=self.async_id)


@dataclass(frozen=True)
class ArgsHandling:

    json_field: str = ''
    count: Optional[int] = None
    spec: str = ''
    completion: Optional[Dict[str, Tuple[str, Union[Callable[[], Iterable[str]], Tuple[str, ...]]]]] = None
    value_if_unspecified: Tuple[str, ...] = ()
    minimum_count: int = -1
    first_rest: Optional[Tuple[str, str]] = None
    special_parse: str = ''

    @property
    def args_count(self) -> Optional[int]:
        if not self.spec:
            return 0
        return self.count

    def as_go_code(self, cmd_name: str, field_types: Dict[str, str], handled_fields: Set[str]) -> Iterator[str]:
        c = self.args_count
        if c == 0:
            yield f'if len(args) != 0 {{ return fmt.Errorf("%s", "Unknown extra argument(s) supplied to {cmd_name}") }}'
            return
        if c is not None:
            yield f'if len(args) != {c} {{ return fmt.Errorf("%s", "Must specify exactly {c} argument(s) for {cmd_name}") }}'
        if self.value_if_unspecified:
            yield 'if len(args) == 0 {'
            for x in self.value_if_unspecified:
                yield f'args = append(args, "{x}")'
            yield '}'
        if self.minimum_count > -1:
            yield f'if len(args) < {self.minimum_count} {{ return fmt.Errorf("%s", Must specify at least {self.minimum_count} arguments to {cmd_name}) }}'
        if self.json_field:
            jf = self.json_field
            dest = f'payload.{jf.capitalize()}'
            jt = field_types[jf]
            if self.first_rest:
                yield f'payload.{self.first_rest[0].capitalize()} = args[0]'
                yield f'payload.{self.first_rest[1].capitalize()} = args[1:]'
                handled_fields.add(self.first_rest[0])
                handled_fields.add(self.first_rest[1])
                return
            handled_fields.add(self.json_field)
            if self.special_parse:
                if self.special_parse.startswith('!'):
                    yield f'io_data.multiple_payload_generator, err = {self.special_parse[1:]}'
                else:
                    yield f'{dest}, err = {self.special_parse}'
                yield 'if err != nil { return err }'
                return
            if jt == 'list.str':
                yield f'{dest} = args'
                return
            if jt == 'str':
                if c == 1:
                    yield f'{dest} = args[0]'
                else:
                    yield f'{dest} = strings.Join(args, " ")'
                return
            if jt.startswith('choices.'):
                yield f'if len(args) != 1 {{ return fmt.Errorf("%s", "Must specify exactly 1 argument for {cmd_name}") }}'
                choices = ", ".join((f'"{x}"' for x in jt.split('.')[1:]))
                yield 'switch(args[0]) {'
                yield f'case {choices}:\n\t{dest} = args[0]'
                yield f'default: return fmt.Errorf("%s is not a valid choice. Allowed values: %s", args[0], `{choices}`)'
                yield '}'
                return
            if jt == 'dict.str':
                yield f'{dest} = parse_key_val_args(args)'
        raise TypeError(f'Unknown args handling for cmd: {cmd_name}')


class RemoteCommand:
    Args = ArgsHandling

    name: str = ''
    short_desc: str = ''
    desc: str = ''
    args: ArgsHandling = ArgsHandling()
    options_spec: Optional[str] = None
    no_response: bool = False
    response_timeout: float = 10.  # seconds
    string_return_is_error: bool = False
    defaults: Optional[Dict[str, Any]] = None
    is_asynchronous: bool = False
    options_class: Type[RCOptions] = RCOptions
    protocol_spec: str = ''
    argspec = args_count = args_completion = ArgsHandling()

    def __init__(self) -> None:
        self.desc = self.desc or self.short_desc
        self.name = self.__class__.__module__.split('.')[-1].replace('_', '-')

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

    def create_async_responder(self, payload_get: PayloadGetType, window: Optional[Window]) -> AsyncResponder:
        return AsyncResponder(payload_get, window)

    def message_to_kitty(self, global_opts: RCOptions, opts: Any, args: ArgsType) -> PayloadType:
        raise NotImplementedError()

    def response_from_kitty(self, boss: 'Boss', window: Optional['Window'], payload_get: PayloadGetType) -> ResponseType:
        raise NotImplementedError()

    def cancel_async_request(self, boss: 'Boss', window: Optional['Window'], payload_get: PayloadGetType) -> None:
        pass


def cli_params_for(command: RemoteCommand) -> Tuple[Callable[[], str], str, str, str]:
    return (command.options_spec or '\n').format, command.args.spec, command.desc, f'{appname} @ {command.name}'


def parse_subcommand_cli(command: RemoteCommand, args: ArgsType) -> Tuple[Any, ArgsType]:
    opts, items = parse_args(args[1:], *cli_params_for(command), result_class=command.options_class)
    if command.args.args_count is not None and command.args.args_count != len(items):
        if command.args.args_count == 0:
            raise SystemExit(f'Unknown extra argument(s) supplied to {command.name}')
        raise SystemExit(f'Must specify exactly {command.args.args_count} argument(s) for {command.name}')
    return opts, items


def display_subcommand_help(func: RemoteCommand) -> None:
    with suppress(SystemExit):
        parse_args(['--help'], (func.options_spec or '\n').format, func.args.spec, func.desc, func.name)


def command_for_name(cmd_name: str) -> RemoteCommand:
    from importlib import import_module
    cmd_name = cmd_name.replace('-', '_')
    try:
        m = import_module(f'kitty.rc.{cmd_name}')
    except ImportError:
        raise KeyError(f'Unknown kitty remote control command: {cmd_name}')
    return cast(RemoteCommand, getattr(m, cmd_name))


def all_command_names() -> FrozenSet[str]:

    def ok(name: str) -> bool:
        root, _, ext = name.rpartition('.')
        return bool(ext in ('py', 'pyc', 'pyo') and root and root not in ('base', '__init__'))

    return frozenset({x.rpartition('.')[0] for x in filter(ok, list_kitty_resources('kitty.rc'))})
