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
If none of these are present, the path to the file is added to the end. Programs that accept
only a single file are run once for every file. Alternately, use :code:`desktop:application-id` to open
with an installed application, for example: :code:`desktop:org.kde.okular`. Examples::

    open_with mime:image/* imv %F
    open_with ext:pdf,epub zathura %f
    open_with glob:~/notes/** kitty --hold nvim %F
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

OPTIONS = r"""
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
:file:`.desktop` files and the :file:`mimeapps.list` files.
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
