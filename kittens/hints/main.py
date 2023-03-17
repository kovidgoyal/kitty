#!/usr/bin/env python3
# License: GPL v3 Copyright: 2018, Kovid Goyal <kovid at kovidgoyal.net>

import sys
from functools import lru_cache
from typing import Any, Dict, List, Optional, Sequence, Tuple

from kitty.cli_stub import HintsCLIOptions
from kitty.clipboard import set_clipboard_string, set_primary_selection
from kitty.constants import website_url
from kitty.fast_data_types import get_options
from kitty.typing import BossType
from kitty.utils import resolve_custom_file

from ..tui.handler import result_handler

DEFAULT_REGEX = r'(?m)^\s*(.+)\s*$'

def load_custom_processor(customize_processing: str) -> Any:
    if customize_processing.startswith('::import::'):
        import importlib
        m = importlib.import_module(customize_processing[len('::import::'):])
        return {k: getattr(m, k) for k in dir(m)}
    if customize_processing == '::linenum::':
        return {'handle_result': linenum_handle_result}
    custom_path = resolve_custom_file(customize_processing)
    import runpy
    return runpy.run_path(custom_path, run_name='__main__')

class Mark:

    __slots__ = ('index', 'start', 'end', 'text', 'is_hyperlink', 'group_id', 'groupdict')

    def __init__(
            self,
            index: int, start: int, end: int,
            text: str,
            groupdict: Any,
            is_hyperlink: bool = False,
            group_id: Optional[str] = None
    ):
        self.index, self.start, self.end = index, start, end
        self.text = text
        self.groupdict = groupdict
        self.is_hyperlink = is_hyperlink
        self.group_id = group_id

    def as_dict(self) -> Dict[str, Any]:
        return {
            'index': self.index, 'start': self.start, 'end': self.end,
            'text': self.text, 'groupdict': {str(k):v for k, v in (self.groupdict or {}).items()},
            'group_id': self.group_id or '', 'is_hyperlink': self.is_hyperlink
        }


def parse_hints_args(args: List[str]) -> Tuple[HintsCLIOptions, List[str]]:
    from kitty.cli import parse_args
    return parse_args(args, OPTIONS, usage, help_text, 'kitty +kitten hints', result_class=HintsCLIOptions)


def custom_marking() -> None:
    import json
    text = sys.stdin.read()
    sys.stdin.close()
    opts, extra_cli_args = parse_hints_args(sys.argv[1:])
    m = load_custom_processor(opts.customize_processing or '::impossible::')
    if 'mark' not in m:
        raise SystemExit(2)
    all_marks = tuple(x.as_dict() for x in m['mark'](text, opts, Mark, extra_cli_args))
    sys.stdout.write(json.dumps(all_marks))
    raise SystemExit(0)


OPTIONS = r'''
--program
type=list
What program to use to open matched text. Defaults to the default open program
for the operating system. Various special values are supported:

:code:`-`
    paste the match into the terminal window.

:code:`@`
    copy the match to the clipboard

:code:`*`
    copy the match to the primary selection (on systems that support primary selections)

:code:`@NAME`
    copy the match to the specified buffer, e.g. :code:`@a`

:code:`default`
    run the default open program.

:code:`launch`
    run :doc:`/launch` to open the program in a new kitty tab, window, overlay, etc.
    For example::

        --program "launch --type=tab vim"

Can be specified multiple times to run multiple programs.


--type
default=url
choices=url,regex,path,line,hash,word,linenum,hyperlink,ip
The type of text to search for. A value of :code:`linenum` is special, it looks
for error messages using the pattern specified with :option:`--regex`, which
must have the named groups: :code:`path` and :code:`line`. If not specified,
will look for :code:`path:line`. The :option:`--linenum-action` option
controls where to display the selected error message, other options are ignored.


--regex
default={default_regex}
The regular expression to use when option :option:`--type` is set to
:code:`regex`, in python syntax. If you specify a numbered group in the regular
expression, only the group will be matched. This allow you to match text
ignoring a prefix/suffix, as needed. The default expression matches lines. To
match text over multiple lines, you should prefix the regular expression with
:code:`(?ms)`, which turns on MULTILINE and DOTALL modes for the regex engine.
If you specify named groups and a :option:`--program`, then the program will be
passed arguments corresponding to each named group of the form
:code:`key=value`.


--linenum-action
default=self
type=choice
choices=self,window,tab,os_window,background
Where to perform the action on matched errors. :code:`self` means the current
window, :code:`window` a new kitty window, :code:`tab` a new tab,
:code:`os_window` a new OS window and :code:`background` run in the background.
The actual action is whatever arguments are provided to the kitten, for
example:
:code:`kitty +kitten hints --type=linenum --linenum-action=tab vim +{line} {path}`
will open the matched path at the matched line number in vim in
a new kitty tab. Note that in order to use :option:`--program` to copy or paste
the provided arguments, you need to use the special value :code:`self`.


--url-prefixes
default=default
Comma separated list of recognized URL prefixes. Defaults to the list of
prefixes defined by the :opt:`url_prefixes` option in :file:`kitty.conf`.


--word-characters
Characters to consider as part of a word. In addition, all characters marked as
alphanumeric in the Unicode database will be considered as word characters.
Defaults to the :opt:`select_by_word_characters` option from :file:`kitty.conf`.


--minimum-match-length
default=3
type=int
The minimum number of characters to consider a match.


--multiple
type=bool-set
Select multiple matches and perform the action on all of them together at the
end. In this mode, press :kbd:`Esc` to finish selecting.


--multiple-joiner
default=auto
String for joining multiple selections when copying to the clipboard or
inserting into the terminal. The special values are: :code:`space` - a space
character, :code:`newline` - a newline, :code:`empty` - an empty joiner,
:code:`json` - a JSON serialized list, :code:`auto` - an automatic choice, based
on the type of text being selected. In addition, integers are interpreted as
zero-based indices into the list of selections. You can use :code:`0` for the
first selection and :code:`-1` for the last.


--add-trailing-space
default=auto
choices=auto,always,never
Add trailing space after matched text. Defaults to :code:`auto`, which adds the
space when used together with :option:`--multiple`.


--hints-offset
default=1
type=int
The offset (from zero) at which to start hint numbering. Note that only numbers
greater than or equal to zero are respected.


--alphabet
The list of characters to use for hints. The default is to use numbers and
lowercase English alphabets. Specify your preference as a string of characters.
Note that you need to specify the :option:`--hints-offset` as zero to use the
first character to highlight the first match, otherwise it will start with the
second character by default.


--ascending
type=bool-set
Make the hints increase from top to bottom, instead of decreasing from top to
bottom.


--hints-foreground-color
default=black
type=str
The foreground color for hints.


--hints-background-color
default=green
type=str
The background color for hints.


--hints-text-color
default=gray
type=str
The foreground color for text pointed to by the hints.


--customize-processing
Name of a python file in the kitty config directory which will be imported to
provide custom implementations for pattern finding and performing actions
on selected matches. You can also specify absolute paths to load the script from
elsewhere. See {hints_url} for details.


--window-title
The title for the hints window, default title is based on the type of text being
hinted.
'''.format(
    default_regex=DEFAULT_REGEX,
    line='{{line}}', path='{{path}}',
    hints_url=website_url('kittens/hints'),
).format
help_text = 'Select text from the screen using the keyboard. Defaults to searching for URLs.'
usage = ''


def main(args: List[str]) -> Optional[Dict[str, Any]]:
    raise SystemExit('Should be run as kitten hints')


def linenum_process_result(data: Dict[str, Any]) -> Tuple[str, int]:
    for match, g in zip(data['match'], data['groupdicts']):
        path, line = g['path'], g['line']
        if path and line:
            return path, int(line)
    return '', -1


def linenum_handle_result(args: List[str], data: Dict[str, Any], target_window_id: int, boss: BossType, extra_cli_args: Sequence[str], *a: Any) -> None:
    path, line = linenum_process_result(data)
    if not path:
        return

    cmd = [x.format(path=path, line=line) for x in extra_cli_args or ('vim', '+{line}', '{path}')]
    w = boss.window_id_map.get(target_window_id)
    action = data['linenum_action']

    if action == 'self':
        if w is not None:
            def is_copy_action(s: str) -> bool:
                return s in ('-', '@', '*') or s.startswith('@')

            programs = list(filter(is_copy_action, data['programs'] or ()))
            # keep for backward compatibility, previously option `--program` does not need to be specified to perform copy actions
            if is_copy_action(cmd[0]):
                programs.append(cmd.pop(0))
            if programs:
                text = ' '.join(cmd)
                for program in programs:
                    if program == '-':
                        w.paste_bytes(text)
                    elif program == '@':
                        set_clipboard_string(text)
                    elif program == '*':
                        set_primary_selection(text)
                    elif program.startswith('@'):
                        boss.set_clipboard_buffer(program[1:], text)
            else:
                import shlex
                text = ' '.join(shlex.quote(arg) for arg in cmd)
                w.paste_bytes(f'{text}\r')
    elif action == 'background':
        import subprocess
        subprocess.Popen(cmd, cwd=data['cwd'])
    else:
        getattr(boss, {
            'window': 'new_window_with_cwd', 'tab': 'new_tab_with_cwd', 'os_window': 'new_os_window_with_cwd'
            }[action])(*cmd)


@result_handler(type_of_input='screen-ansi', has_ready_notification=True)
def handle_result(args: List[str], data: Dict[str, Any], target_window_id: int, boss: BossType) -> None:
    cp = data['customize_processing']
    if data['type'] == 'linenum':
        cp = '::linenum::'
    if cp:
        m = load_custom_processor(cp)
        if 'handle_result' in m:
            m['handle_result'](args, data, target_window_id, boss, data['extra_cli_args'])
            return None

    programs = data['programs'] or ('default',)
    matches: List[str] = []
    groupdicts = []
    for m, g in zip(data['match'], data['groupdicts']):
        if m:
            matches.append(m)
            groupdicts.append(g)
    joiner = data['multiple_joiner']
    try:
        is_int: Optional[int] = int(joiner)
    except Exception:
        is_int = None
    text_type = data['type']

    @lru_cache()
    def joined_text() -> str:
        if is_int is not None:
            try:
                return matches[is_int]
            except IndexError:
                return matches[-1]
        if joiner == 'json':
            import json
            return json.dumps(matches, ensure_ascii=False, indent='\t')
        if joiner == 'auto':
            q = '\n\r' if text_type in ('line', 'url') else ' '
        else:
            q = {'newline': '\n\r', 'space': ' '}.get(joiner, '')
        return q.join(matches)

    for program in programs:
        if program == '-':
            w = boss.window_id_map.get(target_window_id)
            if w is not None:
                w.paste_text(joined_text())
        elif program == '*':
            set_primary_selection(joined_text())
        elif program.startswith('@'):
            if program == '@':
                set_clipboard_string(joined_text())
            else:
                boss.set_clipboard_buffer(program[1:], joined_text())
        else:
            from kitty.conf.utils import to_cmdline
            cwd = data['cwd']
            program = get_options().open_url_with if program == 'default' else program
            if text_type == 'hyperlink':
                w = boss.window_id_map.get(target_window_id)
                for m in matches:
                    if w is not None:
                        w.open_url(m, hyperlink_id=1, cwd=cwd)
            else:
                launch_args = []
                if isinstance(program, str) and program.startswith('launch '):
                    launch_args = to_cmdline(program)
                    launch_args.insert(1, '--cwd=' + cwd)
                for m, groupdict in zip(matches, groupdicts):
                    if groupdict:
                        m = []
                        for k, v in groupdict.items():
                            m.append('{}={}'.format(k, v or ''))
                    if launch_args:
                        w = boss.window_id_map.get(target_window_id)
                        boss.call_remote_control(active_window=w, args=tuple(launch_args + ([m] if isinstance(m, str) else m)))
                    else:
                        boss.open_url(m, program, cwd=cwd)


if __name__ == '__main__':
    # Run with kitty +kitten hints
    ans = main(sys.argv)
    if ans:
        print(ans)
elif __name__ == '__doc__':
    cd = sys.cli_docs  # type: ignore
    cd['usage'] = usage
    cd['short_desc'] = 'Select text from screen with keyboard'
    cd['options'] = OPTIONS
    cd['help_text'] = help_text
# }}}
