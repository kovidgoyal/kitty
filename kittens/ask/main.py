#!/usr/bin/env python
# License: GPL v3 Copyright: 2018, Kovid Goyal <kovid at kovidgoyal.net>

import sys

from kitty.typing_compat import BossType, TypedDict

from ..tui.handler import result_handler


def option_text() -> str:
    return '''\
--type -t
choices=line,yesno,choices,password
default=line
Type of input. Defaults to asking for a line of text.


--message -m
The message to display to the user. If not specified a default
message is shown.


--name -n
The name for this question. Used to store history of previous answers which can
be used for completions and via the browse history readline bindings.


--title --window-title
The title for the window in which the question is displayed. Only implemented
for yesno and choices types.


--choice -c
type=list
dest=choices
A choice for the choices type. Can be specified multiple times. Every choice has
the syntax: ``letter[;color]:text``, where :italic:`text` is the choice
text and :italic:`letter` is the selection key. :italic:`letter` is a single letter
belonging to :italic:`text`. This letter is highlighted within the choice text.
There can be an optional color specification after the letter
to indicate what color it should be.
For example: :code:`y:Yes` and :code:`n;red:No`


--default -d
A default choice or text. If unspecified, it is :code:`y` for the type
:code:`yesno`, the first choice for :code:`choices` and empty for others types.
The default choice is selected when the user presses the :kbd:`Enter` key.


--prompt -p
default="> "
The prompt to use when inputting a line of text or a password.


--unhide-key
default=u
The key to be pressed to unhide hidden text


--hidden-text-placeholder
The text in the message to be replaced by hidden text. The hidden text is read via STDIN.
'''


class Response(TypedDict):
    items: list[str]
    response: str | None

def main(args: list[str]) -> Response:
    raise SystemExit('This must be run as kitten ask')


@result_handler()
def handle_result(args: list[str], data: Response, target_window_id: int, boss: BossType) -> None:
    if data['response'] is not None:
        func, *args = data['items']
        getattr(boss, func)(data['response'], *args)


if __name__ == '__main__':
    main(sys.argv)
elif __name__ == '__doc__':
    cd = sys.cli_docs  # type: ignore
    cd['usage'] = ''
    cd['options'] = option_text
    cd['help_text'] = 'Ask the user for input'
    cd['short_desc'] = 'Ask the user for input'
