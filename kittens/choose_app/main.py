#!/usr/bin/env python
# License: GPLv3 Copyright: 2026, Kovid Goyal <kovid at kovidgoyal.net>

import sys

from kitty.conf.types import Definition
from kitty.constants import appname
from kitty.simple_cli_definitions import CONFIG_HELP, CompletionSpec

definition = Definition(
    '!kittens.choose_app',
)

agr = definition.add_group
egr = definition.end_group
opt = definition.add_option
map = definition.add_map
mma = definition.add_mouse_map

agr('opening', 'Opening files and URLs')  # {{{

opt(
    '+open_with',
    '',
    add_to_default=False,
    long_text="""
Specify the program to open files or URLs with, based on their type. The syntax is::

    criterion program arguments...

The first :code:`open_with` whose criterion matches is used. The criterion can be
one of:

:code:`mime:image/*,application/pdf`
    Matches files and URLs with the specified MIME types. Patterns
    use shell glob syntax. A MIME type also matches the types it is a sub-class
    of, for example, :code:`mime:text/plain` matches Python files, whose MIME
    type is :code:`text/x-python`. URLs have MIME types of the form
    :code:`x-scheme-handler/https`.

:code:`ext:pdf,tar.*`
    Matches files whose name has one of the specified extensions, ignoring case.
    Patterns use shell glob syntax and can match multiple extensions, such as
    :code:`tar.gz`.

:code:`glob:*.part[0-9]`
    Matches files whose name matches the specified shell glob pattern. If the pattern
    contains a :code:`/` it is matched against the full path of the file instead, in which case
    :code:`**` matches any number of directories and :code:`~` at the start is
    the home directory. For example: :code:`glob:~/notes/**`.

:code:`scheme:https,http`
    Matches URLs with the specified schemes. Files have the scheme :code:`file`.

The program and its arguments use the same syntax as the :code:`Exec` key in
:file:`.desktop` files, with :code:`%f` replaced by the path to a single file, :code:`%F` by
the paths to one or more files, :code:`%u` by a single URL and :code:`%U` by one or more URLs.
If none of these are present, the path to the file is added to the end. Use :code:`%%` for a
literal :code:`%`. Programs that accept
only a single file are run once for every file. Prefix the program with :code:`terminal:` to run it in a
terminal, useful for terminal programs such as editors. Alternately, use :code:`desktop:application-id` to open
with an installed application, for example: :code:`desktop:org.kde.okular`. Examples::

    open_with mime:image/* imv %F
    open_with ext:pdf,epub zathura %f
    open_with glob:~/notes/** terminal:nvim %F
    open_with scheme:https,http desktop:firefox
""",
)

opt(
    'use_system_defaults',
    'yes',
    option_type='to_bool',
    long_text="""
Whether to open files with the default application configured for the desktop in :file:`mimeapps.list`, without asking,
when no :opt:`open_with <kitten-choose_app.open_with>` rule matches and no
application has been remembered for the type of file.
""",
)
opt(
    'remember_choice',
    'no',
    option_type='to_bool',
    long_text="""
Whether the application chosen for a type of file is remembered and used to open that type of file in future
without asking. Can be toggled in the chooser with :sc:`kitten-choose_app.toggle_remember`.
""",
)
opt(
    'terminal',
    'kitty',
    long_text="""
The terminal used to run terminal programs, such as applications whose :file:`.desktop` file
specifies :code:`Terminal=true` or commands marked to run in a terminal. The command line of the
program is appended to this. The default of :code:`kitty` runs them in a new kitty OS window.
For example, to use a new tab in an existing kitty instance::

    terminal kitty --single-instance --instance-group=choose-app
""",
)
egr()  # }}}

agr('appearance', 'Appearance')  # {{{
opt(
    'icon_theme',
    '',
    long_text="""
The icon theme to use for application icons. By default, the icon theme configured for the desktop is used.
The dark or light variant of the theme is used automatically, based on the background color of the terminal,
if it is installed, for example, :code:`breeze-dark` instead of :code:`breeze`.
""",
)
egr()  # }}}

agr('shortcuts', 'Keyboard shortcuts')  # {{{
map('Quit', 'quit esc quit')
map('Quit', 'quit ctrl+c quit')

map('Open with the current application', 'accept enter accept')
map(
    'Type a command',
    'use_command ctrl+enter use_command',
    long_text="""
Type a command line to open with, instead of using an installed application. Any text typed into the search
box is used as the start of the command. The command uses the same syntax as the
:opt:`open_with <kitten-choose_app.open_with>` setting, and can be run in a terminal. When typing the
command, this shortcut accepts it, the same as :kbd:`Enter`.
""",
)
map('Toggle remembering the choice', 'toggle_remember --allow-fallback=shifted,ascii alt+r toggle remember')
map(
    'Toggle running in a terminal',
    'toggle_terminal --allow-fallback=shifted,ascii alt+t toggle terminal',
    long_text='When typing a command, toggle whether the command is run in a terminal.',
)

map('Next application', 'next_app right next 1')
map('Previous application', 'prev_app left next -1')
map('Application below', 'down_app down next down')
map('Application above', 'up_app up next up')
map('Page down', 'page_down page_down next page_down')
map('Page up', 'page_up page_up next page_up')
map('First application', 'first_app home next first')
map('Last application', 'last_app end next last')
egr()  # }}}

OPTIONS = r"""
--open
type=bool-set
Open the specified files or URLs, instead of printing the chosen application. Files and URLs are opened
with the application specified by :opt:`open_with <kitten-choose_app.open_with>`, the application previously
remembered for their type or the default application for the desktop, in that order. If none of these exist,
the user is asked to choose. This makes this kitten a replacement for :program:`xdg-open`.


--ask
type=bool-set
When opening files, always ask which application to use, even if one is known.


--ask-in
choices=auto,terminal,panel
default=auto
Where to show the chooser when opening files. :code:`terminal` uses the terminal
this kitten is running in, :code:`panel` uses a kitty overlay panel and :code:`auto` uses the
terminal if there is one, otherwise a panel.


--list
type=bool-set
Instead of asking the user to choose, print the applications that can open
each of the specified files or URLs as JSON. The applications are listed in
order of preference, the system default application, if any, first. Also
shows how each file or URL would be opened without asking, if possible.


--forget
type=bool-set
Forget the remembered applications for the types of the specified files or URLs.


--clear-cache
type=bool-set
Clear the caches used by this kitten, this includes the remembered applications
and the rendered icons.


--content-type
The MIME type to choose an application for. Useful when no files are specified.


--display-name
The name of the file or URL to display, instead of the names of the specified files.


--recommend
type=list
The id of an application to recommend, can be specified multiple times. The applications
are shown after the ones recently chosen for the type of file and before the other applications
that can open it.


--preselect
The id of the application to select initially.


--commands-as-desktop-files
type=bool-set
When the user chooses to open with a command, rather than an installed application, create a
hidden :file:`.desktop` file for the command and output its id. Useful for programs that can only
launch installed applications.


--write-pid-to
Path to a file to which to write the process ID (PID) of this process to.


--write-output-to
Path to a file to which the output is written in addition to STDOUT.


--output-format
choices=text,json
default=text
The format in which to write the output. The :code:`text` format is :code:`desktop:` followed
by the id of the chosen application, or the chosen command line. The :code:`json` format
is an object with the key :code:`choice` containing either :code:`desktop_id` or :code:`cmdline`
and the key :code:`remember` indicating if the user chose to remember the choice.
If the user cancels the :code:`json` output contains the key :code:`interrupted` and
if an error occurs the key :code:`error`.


--title
Window title to use for the chooser.


--override -o
type=list
Override individual configuration options, can be specified multiple times.
Syntax: :italic:`name=value`.


--config
type=list
completion=type:file ext:conf group:"Config files" kwds:none,NONE
{config_help}
""".format(config_help=CONFIG_HELP.format(conf_name='choose-app', appname=appname)).format

help_text = """\
Choose an application to open the specified files or URLs with. Applications
are found the same way as the KDE and GNOME desktops do, from the installed
:file:`.desktop` files and the :file:`mimeapps.list` files. Use the :option:`--open`
option to open the files with the chosen application, as a replacement for :program:`xdg-open`.
"""

usage = '[file or URL ...]'


def main(args: list[str]) -> None:
    raise SystemExit('This must be run as kitten choose-app')


if __name__ == '__main__':
    main(sys.argv)
elif __name__ == '__doc__':
    cd = sys.cli_docs  # type: ignore
    cd['usage'] = usage
    cd['options'] = OPTIONS
    cd['help_text'] = help_text
    cd['short_desc'] = 'Choose an application to open files and URLs with'
    cd['args_completion'] = CompletionSpec.from_string('type:file group:"Files"')
elif __name__ == '__conf__':
    sys.options_definition = definition  # type: ignore
