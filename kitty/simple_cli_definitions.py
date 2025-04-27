#!/usr/bin/env python
# License: GPLv3 Copyright: 2025, Kovid Goyal <kovid at kovidgoyal.net>

# This module must be runnable by a vanilla python interperter
# as it is used to generate C code when building kitty

import os
import sys
from dataclasses import dataclass
from enum import Enum, auto
from typing import Iterator, TypedDict

try:
    from kitty.constants import appname, is_macos
except ImportError:
    is_macos = 'darwin' in sys.platform.lower()
    try:
        appname
    except NameError:
        appname = os.environ['KITTY_APPNAME']
try:
    from kitty.utils import shlex_split as ksplit
    def shlex_split(text: str) -> Iterator[str]:
        yield from ksplit(text)
except ImportError:
    from shlex import split as psplit

    def shlex_split(text: str) -> Iterator[str]:
        yield from psplit(text)


def serialize_as_go_string(x: str) -> str:
    return x.replace('\\', '\\\\').replace('\n', '\\n').replace('"', '\\"')


class CompletionType(Enum):
    file = auto()
    directory = auto()
    keyword = auto()
    special = auto()
    none = auto()


class CompletionRelativeTo(Enum):
    cwd = auto()
    config_dir = auto()


@dataclass
class CompletionSpec:

    type: CompletionType = CompletionType.none
    kwds: tuple[str,...] = ()
    extensions: tuple[str,...] = ()
    mime_patterns: tuple[str,...] = ()
    group: str = ''
    relative_to: CompletionRelativeTo = CompletionRelativeTo.cwd

    @staticmethod
    def from_string(raw: str) -> 'CompletionSpec':
        self = CompletionSpec()
        for x in shlex_split(raw):
            ck, vv = x.split(':', 1)
            if ck == 'type':
                self.type = getattr(CompletionType, vv)
            elif ck == 'kwds':
                self.kwds += tuple(vv.split(','))
            elif ck == 'ext':
                self.extensions += tuple(vv.split(','))
            elif ck == 'group':
                self.group = vv
            elif ck == 'mime':
                self.mime_patterns += tuple(vv.split(','))
            elif ck == 'relative':
                if vv == 'conf':
                    self.relative_to = CompletionRelativeTo.config_dir
                else:
                    raise ValueError(f'Unknown completion relative to value: {vv}')
            else:
                raise KeyError(f'Unknown completion property: {ck}')
        return self

    def as_go_code(self, go_name: str, sep: str = ': ') -> Iterator[str]:
        completers = []
        if self.kwds:
            kwds = (f'"{serialize_as_go_string(x)}"' for x in self.kwds)
            g = (self.group if self.type is CompletionType.keyword else '') or "Keywords"
            completers.append(f'cli.NamesCompleter("{serialize_as_go_string(g)}", ' + ', '.join(kwds) + ')')
        relative_to = 'CONFIG' if self.relative_to is CompletionRelativeTo.config_dir else 'CWD'
        if self.type is CompletionType.file:
            g = serialize_as_go_string(self.group or 'Files')
            added = False
            if self.extensions:
                added = True
                pats = (f'"*.{ext}"' for ext in self.extensions)
                completers.append(f'cli.FnmatchCompleter("{g}", cli.{relative_to}, ' + ', '.join(pats) + ')')
            if self.mime_patterns:
                added = True
                completers.append(f'cli.MimepatCompleter("{g}", cli.{relative_to}, ' + ', '.join(f'"{p}"' for p in self.mime_patterns) + ')')
            if not added:
                completers.append(f'cli.FnmatchCompleter("{g}", cli.{relative_to}, "*")')
        if self.type is CompletionType.directory:
            g = serialize_as_go_string(self.group or 'Directories')
            completers.append(f'cli.DirectoryCompleter("{g}", cli.{relative_to})')
        if self.type is CompletionType.special:
            completers.append(self.group)
        if len(completers) > 1:
            yield f'{go_name}{sep}cli.ChainCompleters(' + ', '.join(completers) + ')'
        elif completers:
            yield f'{go_name}{sep}{completers[0]}'


class OptionDict(TypedDict):
    dest: str
    name: str
    aliases: tuple[str, ...]
    help: str
    choices: tuple[str, ...]
    type: str
    default: str | None
    condition: bool
    completion: CompletionSpec




listen_on_defn = f'''\
--listen-on
completion=type:special group:complete_kitty_listen_on
Listen on the specified socket address for control messages. For example,
:option:`{appname} --listen-on`=unix:/tmp/mykitty or :option:`{appname}
--listen-on`=tcp:localhost:12345. On Linux systems, you can also use abstract
UNIX sockets, not associated with a file, like this: :option:`{appname}
--listen-on`=unix:@mykitty. Environment variables are expanded and relative
paths are resolved with respect to the temporary directory. To control kitty,
you can send commands to it with :italic:`kitten @` using the
:option:`kitten @ --to` option to specify this address. Note that if you run
:italic:`kitten @` within a kitty window, there is no need to specify the
:option:`kitten @ --to` option as it will automatically read from the
environment. Note that this will be ignored unless :opt:`allow_remote_control`
is set to either: :code:`yes`, :code:`socket` or :code:`socket-only`. This can
also be specified in :file:`kitty.conf`.
'''


CONFIG_HELP = '''\
Specify a path to the configuration file(s) to use. All configuration files are
merged onto the builtin :file:`{conf_name}.conf`, overriding the builtin values.
This option can be specified multiple times to read multiple configuration files
in sequence, which are merged. Use the special value :code:`NONE` to not load
any config file.

If this option is not specified, config files are searched for in the order:
:file:`$XDG_CONFIG_HOME/{appname}/{conf_name}.conf`,
:file:`~/.config/{appname}/{conf_name}.conf`,{macos_confpath}
:file:`$XDG_CONFIG_DIRS/{appname}/{conf_name}.conf`. The first one that exists
is used as the config file.

If the environment variable :envvar:`KITTY_CONFIG_DIRECTORY` is specified, that
directory is always used and the above searching does not happen.

If :file:`/etc/xdg/{appname}/{conf_name}.conf` exists, it is merged before (i.e.
with lower priority) than any user config files. It can be used to specify
system-wide defaults for all users. You can use either :code:`-` or
:file:`/dev/stdin` to read the config from STDIN.
'''.replace(
    '{macos_confpath}',
    (' :file:`~/Library/Preferences/{appname}/{conf_name}.conf`,' if is_macos else ''), 1
)


def kitty_options_spec() -> str:
    if not hasattr(kitty_options_spec, 'ans'):
        OPTIONS = '''
--class --app-id
dest=cls
default={appname}
condition=not is_macos
Set the class part of the :italic:`WM_CLASS` window property. On Wayland, it
sets the app id.


--name
condition=not is_macos
Set the name part of the :italic:`WM_CLASS` property. Defaults to using the
value from :option:`{appname} --class`.


--title -T
Set the OS window title. This will override any title set by the program running
inside kitty, permanently fixing the OS window's title. So only use this if you
are running a program that does not set titles.


--config -c
type=list
completion=type:file ext:conf group:"Config files" kwds:none,NONE
{config_help}


--override -o
type=list
completion=type:special group:complete_kitty_override
Override individual configuration options, can be specified multiple times.
Syntax: :italic:`name=value`. For example: :option:`{appname} -o` font_size=20


--directory --working-directory -d
default=.
completion=type:directory
Change to the specified directory when launching.


--detach
type=bool-set
Detach from the controlling terminal, if any. On macOS
use :code:`open -a kitty.app -n` instead.


--detached-log
Path to a log file to store STDOUT/STDERR when using :option:`--detach`


--session
completion=type:file ext:session relative:conf group:"Session files"
Path to a file containing the startup :italic:`session` (tabs, windows, layout,
programs). Use - to read from STDIN. See :ref:`sessions` for details and
an example. Environment variables in the file name are expanded,
relative paths are resolved relative to the kitty configuration directory.
The special value :code:`none` means no session will be used, even if
the :opt:`startup_session` option has been specified in kitty.conf.
Note that using this option means the command line arguments to kitty specifying
a program to run are ignored.


--hold
type=bool-set
Remain open, at a shell prompt, after child process exits. Note that this only
affects the first window. You can quit by either using the close window
shortcut or running the exit command.


--single-instance -1
type=bool-set
If specified only a single instance of :italic:`{appname}` will run. New
invocations will instead create a new top-level window in the existing
:italic:`{appname}` instance. This allows :italic:`{appname}` to share a single
sprite cache on the GPU and also reduces startup time. You can also have
separate groups of :italic:`{appname}` instances by using the :option:`{appname}
--instance-group` option.


--instance-group
Used in combination with the :option:`{appname} --single-instance` option. All
:italic:`{appname}` invocations with the same :option:`{appname}
--instance-group` will result in new windows being created in the first
:italic:`{appname}` instance within that group.


--wait-for-single-instance-window-close
type=bool-set
Normally, when using :option:`{appname} --single-instance`, :italic:`{appname}`
will open a new window in an existing instance and quit immediately. With this
option, it will not quit till the newly opened window is closed. Note that if no
previous instance is found, then :italic:`{appname}` will wait anyway,
regardless of this option.


{listen_on_defn} To start in headless mode,
without an actual window, use :option:`{appname} --start-as`=hidden.


--start-as
type=choices
default=normal
choices=normal,fullscreen,maximized,minimized,hidden
Control how the initial kitty window is created.


# Debugging options

--version -v
type=bool-set
The current {appname} version.


--dump-commands
type=bool-set
Output commands received from child process to STDOUT.


--replay-commands
Replay previously dumped commands. Specify the path to a dump file previously
created by :option:`{appname} --dump-commands`. You
can open a new kitty window to replay the commands with::

    {appname} sh -c "{appname} --replay-commands /path/to/dump/file; read"


--dump-bytes
Path to file in which to store the raw bytes received from the child process.


--debug-rendering --debug-gl
type=bool-set
Debug rendering commands. This will cause all OpenGL calls to check for errors
instead of ignoring them. Also prints out miscellaneous debug information.
Useful when debugging rendering problems.


--debug-input --debug-keyboard
dest=debug_keyboard
type=bool-set
Print out key and mouse events as they are received.


--debug-font-fallback
type=bool-set
Print out information about the selection of fallback fonts for characters not
present in the main font.


--watcher
completion=type:file ext:py relative:conf group:"Watcher files"
This option is deprecated in favor of the :opt:`watcher` option in
:file:`{conf_name}.conf` and should not be used.


--execute -e
type=bool-set
!
'''
        setattr(kitty_options_spec, 'ans', OPTIONS.format(
            appname=appname, conf_name=appname, listen_on_defn=listen_on_defn,
            config_help=CONFIG_HELP.format(appname=appname, conf_name=appname),
        ))
    ans: str = getattr(kitty_options_spec, 'ans')
    return ans


if __name__ == '__main__':
    print(111111111, appname)
