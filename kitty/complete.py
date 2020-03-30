#!/usr/bin/env python3
# vim:fileencoding=utf-8
# License: GPLv3 Copyright: 2018, Kovid Goyal <kovid at kovidgoyal.net>

import os
import shlex
import sys
from functools import lru_cache
from typing import (
    Any, Callable, Dict, Iterable, List, Optional, Sequence, Set, Tuple
)

from kittens.runner import all_kitten_names, get_kitten_cli_docs

from .cli import (
    OptionDict, OptionSpecSeq, options_for_completion, parse_option_spec
)
from .rc.base import all_command_names, command_for_name
from .shell import options_for_cmd

'''
To add completion for a new shell, you need to:

1) Add an entry to completion scripts for your shell, this is
a simple function that calls kitty's completion code and passes the
results to the shell's completion system. This can be output by
`kitty +complete setup shell_name` and its output goes into
your shell's rc file.

2) Add an input_parser function, this takes the input from
the shell for the text being completed and returns a list of words
and a boolean indicating if we are on a new word or not. This
is passed to kitty's completion system.

3) An output_serializer function that is responsible for
taking the results from kitty's completion system and converting
them into something your shell will understand.
'''

parsers: Dict[str, Callable] = {}
serializers: Dict[str, Callable] = {}
MathGroup = Dict[str, str]


def debug(*a: Any, **kw: Any) -> None:
    kw['file'] = sys.stderr
    print(*a, **kw)


class Delegate:

    def __init__(self, words: Sequence[str] = (), pos: int = -1, new_word: bool = False):
        self.words: Sequence[str] = words
        self.pos = pos
        self.num_of_unknown_args = len(words) - pos
        self.new_word = new_word

    def __bool__(self) -> bool:
        return self.pos > -1 and self.num_of_unknown_args > 0

    @property
    def precommand(self) -> str:
        try:
            return self.words[self.pos]
        except IndexError:
            return ''


class Completions:

    def __init__(self) -> None:
        self.match_groups: Dict[str, MathGroup] = {}
        self.no_space_groups: Set[str] = set()
        self.files_groups: Set[str] = set()
        self.delegate: Delegate = Delegate()


@lru_cache(maxsize=2)
def remote_control_command_names() -> Tuple[str, ...]:
    return tuple(sorted(x.replace('_', '-') for x in all_command_names()))


# Shell specific code {{{


completion_scripts = {
    'zsh': '''#compdef kitty

_kitty() {
    local src
    # Send all words up to the word the cursor is currently on
    src=$(printf "%s\n" "${(@)words[1,$CURRENT]}" | kitty +complete zsh)
    if [[ $? == 0 ]]; then
        eval ${src}
    fi
}
compdef _kitty kitty
''',
    'bash': '''
_kitty_completions() {
    local src
    local limit
    # Send all words up to the word the cursor is currently on
    let limit=1+$COMP_CWORD
    src=$(printf "%s\n" "${COMP_WORDS[@]: 0:$limit}" | kitty +complete bash)
    if [[ $? == 0 ]]; then
        eval ${src}
    fi
}

complete -o nospace -F _kitty_completions kitty
''',
    'fish': '''
function __kitty_completions
    # Send all words up to the one before the cursor
    commandline -cop | kitty +complete fish
end

complete -f -c kitty -a "(__kitty_completions)"
''',
}

ParseResult = Tuple[List[str], bool]
ParserFunc = Callable[[str], ParseResult]
SerializerFunc = Callable[[Completions], str]


def input_parser(func: ParserFunc) -> ParserFunc:
    name = func.__name__.split('_')[0]
    parsers[name] = func
    return func


def output_serializer(func: SerializerFunc) -> SerializerFunc:
    name = func.__name__.split('_')[0]
    serializers[name] = func
    return func


@input_parser
def zsh_input_parser(data: str) -> ParseResult:
    new_word = data.endswith('\n\n')
    words = data.rstrip().splitlines()
    return words, new_word


@input_parser
def bash_input_parser(data: str) -> ParseResult:
    new_word = data.endswith('\n\n')
    words = data.rstrip().splitlines()
    return words, new_word


@input_parser
def fish_input_parser(data: str) -> ParseResult:
    return data.rstrip().splitlines(), True


@output_serializer
def zsh_output_serializer(ans: Completions) -> str:
    lines = []
    for description, matches in ans.match_groups.items():
        cmd = ['compadd', '-U', '-J', shlex.quote(description), '-X', shlex.quote(description)]
        if description in ans.no_space_groups:
            cmd += ['-S', '""']
        if description in ans.files_groups:
            cmd.append('-f')
            common_prefix = os.path.commonprefix(tuple(matches))
            if common_prefix:
                cmd.extend(('-p', shlex.quote(common_prefix)))
                matches = {k[len(common_prefix):]: v for k, v in matches.items()}
        cmd.append('--')
        for word in matches:
            cmd.append(shlex.quote(word))
        lines.append(' '.join(cmd) + ';')

    if ans.delegate:
        if ans.delegate.num_of_unknown_args == 1 and not ans.delegate.new_word:
            lines.append('_command_names -e')
        elif ans.delegate.precommand:
            for i in range(ans.delegate.pos + 1):
                lines.append('shift words')
                lines.append('(( CURRENT-- ))')
            lines.append(f'_normal -p "{ans.delegate.precommand}"')
    # debug('\n'.join(lines))
    return '\n'.join(lines)


@output_serializer
def bash_output_serializer(ans: Completions) -> str:
    lines = []
    for description, matches in ans.match_groups.items():
        needs_space = description not in ans.no_space_groups
        for word in matches:
            if needs_space:
                word += ' '
            lines.append('COMPREPLY+=({})'.format(shlex.quote(word)))
    # debug('\n'.join(lines))
    return '\n'.join(lines)


@output_serializer
def fish_output_serializer(ans: Completions) -> str:
    lines = []
    for matches in ans.match_groups.values():
        for word in matches:
            lines.append(shlex.quote(word))
    # debug('\n'.join(lines))
    return '\n'.join(lines)
# }}}


def completions_for_first_word(ans: Completions, prefix: str, entry_points: Iterable[str], namespaced_entry_points: Iterable[str]) -> None:
    cmds = ['@' + c for c in remote_control_command_names()]
    ans.match_groups['Entry points'] = {
        k: '' for k in
        list(entry_points) + cmds + ['+' + k for k in namespaced_entry_points]
        if not prefix or k.startswith(prefix)
    }
    if prefix:
        ans.delegate = Delegate([prefix], 0)


def kitty_cli_opts(ans: Completions, prefix: Optional[str] = None) -> None:
    matches = {}
    for opt in options_for_completion():
        if isinstance(opt, str):
            continue
        aliases = frozenset(x for x in opt['aliases'] if x.startswith(prefix)) if prefix else opt['aliases']
        for alias in aliases:
            matches[alias] = opt['help'].strip()
    ans.match_groups['Options'] = matches


def complete_kitty_cli_arg(ans: Completions, opt: Optional[OptionDict], prefix: str, unknown_args: Delegate) -> None:
    prefix = prefix or ''
    if not opt:
        if unknown_args.num_of_unknown_args > 0:
            ans.delegate = unknown_args
        return
    dest = opt['dest']
    if dest == 'override':
        from kitty.config import option_names_for_completion
        k = 'Config directives'
        ans.match_groups[k] = {k+'=': '' for k in option_names_for_completion() if k.startswith(prefix)}
        ans.no_space_groups.add(k)
    elif dest == 'config':

        def is_conf_file(x: str) -> bool:
            if os.path.isdir(x):
                return True
            return x.lower().endswith('.conf')

        complete_files_and_dirs(ans, prefix, files_group_name='Config files', predicate=is_conf_file)
    elif dest == 'session':
        complete_files_and_dirs(ans, prefix, files_group_name='Session files')
    elif dest == 'directory':
        complete_files_and_dirs(ans, prefix, files_group_name='Directories', predicate=os.path.isdir)
    elif dest == 'start_as':
        k = 'Start as'
        ans.match_groups[k] = {x: x for x in 'normal,fullscreen,maximized,minimized'.split(',') if x.startswith(prefix)}
        ans.no_space_groups.add(k)
    elif dest == 'listen_on':
        if ':' not in prefix:
            k = 'Address type'
            ans.match_groups[k] = {x: x for x in ('unix:', 'tcp:') if x.startswith(prefix)}
            ans.no_space_groups.add(k)
        elif prefix.startswith('unix:') and not prefix.startswith('@'):
            complete_files_and_dirs(ans, prefix[len('unix:'):], files_group_name='UNIX sockets', add_prefix='unix:')


CompleteArgsFunc = Callable[[Completions, Optional[OptionDict], str, Delegate], None]


def complete_alias_map(
    ans: Completions,
    words: Sequence[str],
    new_word: bool,
    option_map: Dict[str, OptionDict],
    complete_args: Optional[CompleteArgsFunc] = None
) -> None:
    expecting_arg = False
    opt: Optional[OptionDict] = None
    last_word = words[-1] if words else ''
    for i, w in enumerate(words):
        if expecting_arg:
            if w is last_word and not new_word:
                if opt is not None and complete_args is not None:
                    complete_args(ans, opt, w, Delegate())
                return
            expecting_arg = False
            continue
        opt = option_map.get(w)
        if w is last_word and not new_word:
            if w.startswith('-'):
                ans.match_groups['Options'] = {k: opt['help'] for k, opt in option_map.items() if k.startswith(last_word)}
            else:
                if complete_args is not None:
                    complete_args(ans, None, last_word, Delegate(words, i))
            return
        if opt is None:
            if complete_args is not None:
                complete_args(ans, None, '' if new_word else last_word, Delegate(words, i, new_word))
            return  # some non-option word encountered
        expecting_arg = not opt.get('type', '').startswith('bool-')
    if expecting_arg:
        if opt is not None and complete_args is not None:
            complete_args(ans, opt, '' if new_word else last_word, Delegate())
    else:
        prefix = '' if new_word else last_word
        if complete_args is not None:
            complete_args(ans, None, prefix, Delegate())
        ans.match_groups['Options'] = {k: opt['help'] for k, opt in option_map.items() if k.startswith(prefix)}


def complete_cli(
    ans: Completions,
    words: Sequence[str],
    new_word: bool,
    seq: OptionSpecSeq,
    complete_args: Optional[CompleteArgsFunc] = None
) -> None:
    option_map = {}
    for opt in seq:
        if not isinstance(opt, str):
            for alias in opt['aliases']:
                option_map[alias] = opt
    complete_alias_map(ans, words, new_word, option_map, complete_args)


def complete_remote_command(ans: Completions, cmd_name: str, words: Sequence[str], new_word: bool) -> None:
    aliases, alias_map = options_for_cmd(cmd_name)
    if not alias_map:
        return
    args_completer: Optional[CompleteArgsFunc] = None
    args_completion = command_for_name(cmd_name).args_completion
    if args_completion and 'files' in args_completion:
        args_completer = remote_files_completer(args_completion['files'])
    complete_alias_map(ans, words, new_word, alias_map, complete_args=args_completer)


def path_completion(prefix: str = '') -> Tuple[List[str], List[str]]:
    prefix = prefix.replace(r'\ ', ' ')
    dirs, files = [], []
    base = '.'
    if prefix.endswith('/'):
        base = prefix
    elif '/' in prefix:
        base = os.path.dirname(prefix)
    src = os.path.expandvars(os.path.expanduser(base))
    src_prefix = os.path.abspath(os.path.expandvars(os.path.expanduser(prefix))) if prefix else ''
    try:
        items: Iterable[os.DirEntry] = os.scandir(src)
    except FileNotFoundError:
        items = ()
    for x in items:
        abspath = os.path.abspath(x.path)
        if prefix and not abspath.startswith(src_prefix):
            continue
        if prefix:
            q = prefix + abspath[len(src_prefix):].lstrip(os.sep)
            q = os.path.expandvars(os.path.expanduser(q))
        else:
            q = os.path.relpath(abspath)
        if x.is_dir():
            dirs.append(q.rstrip(os.sep) + os.sep)
        else:
            files.append(q)
    return dirs, files


def complete_files_and_dirs(
    ans: Completions,
    prefix: str,
    files_group_name: str = 'Files',
    predicate: Optional[Callable[[str], bool]] = None,
    add_prefix: Optional[str] = None
) -> None:
    dirs, files_ = path_completion(prefix or '')
    files = filter(predicate, files_)
    if add_prefix:
        dirs = list(add_prefix + x for x in dirs)
        files = (add_prefix + x for x in files)

    if dirs:
        ans.match_groups['Directories'] = dict.fromkeys(dirs)
        ans.files_groups.add('Directories')
        ans.no_space_groups.add('Directories')
    if files:
        ans.match_groups[files_group_name] = dict.fromkeys(files)
        ans.files_groups.add(files_group_name)


def complete_icat_args(ans: Completions, opt: Optional[OptionDict], prefix: str, unknown_args: Delegate) -> None:
    from mimetypes import guess_type

    def icat_file_predicate(filename: str) -> bool:
        mt = guess_type(filename)[0]
        if mt and mt.startswith('image/'):
            return True
        return False

    if opt is None:
        complete_files_and_dirs(ans, prefix, 'Images', icat_file_predicate)


def remote_files_completer(spec: Tuple[str, Tuple[str, ...]]) -> CompleteArgsFunc:
    name, matchers = spec

    def complete_files_map(ans: Completions, opt: Optional[OptionDict], prefix: str, unknown_args: Delegate) -> None:

        def predicate(filename: str) -> bool:
            for m in matchers:
                if isinstance(m, str):
                    from fnmatch import fnmatch
                    return fnmatch(filename, m)
            return False

        if opt is None:
            complete_files_and_dirs(ans, prefix, name, predicate)
    return complete_files_map


def config_file_predicate(filename: str) -> bool:
    return filename.endswith('.conf')


def complete_diff_args(ans: Completions, opt: Optional[OptionDict], prefix: str, unknown_args: Delegate) -> None:
    if opt is None:
        complete_files_and_dirs(ans, prefix, 'Files')
    elif opt['dest'] == 'config':
        complete_files_and_dirs(ans, prefix, 'Config Files', config_file_predicate)


def complete_kitten(ans: Completions, kitten: str, words: Sequence[str], new_word: bool) -> None:
    try:
        cd = get_kitten_cli_docs(kitten)
    except SystemExit:
        cd = None
    if cd is None:
        return
    options = cd['options']()
    seq = parse_option_spec(options)[0]
    option_map = {}
    for opt in seq:
        if not isinstance(opt, str):
            for alias in opt['aliases']:
                option_map[alias] = opt
    complete_alias_map(ans, words, new_word, option_map, {
        'icat': complete_icat_args,
        'diff': complete_diff_args,
    }.get(kitten))


def find_completions(words: Sequence[str], new_word: bool, entry_points: Iterable[str], namespaced_entry_points: Iterable[str]) -> Completions:
    ans = Completions()
    if not words or words[0] != 'kitty':
        return ans
    words = words[1:]
    if not words or (len(words) == 1 and not new_word):
        prefix = words[0] if words else ''
        completions_for_first_word(ans, prefix, entry_points, namespaced_entry_points)
        kitty_cli_opts(ans, prefix)
        return ans
    if words[0] == '@':
        if len(words) == 1 or (len(words) == 2 and not new_word):
            prefix = words[1] if len(words) > 1 else ''
            ans.match_groups['Remote control commands'] = {c: '' for c in remote_control_command_names() if c.startswith(prefix)}
        else:
            complete_remote_command(ans, words[1], words[2:], new_word)
        return ans
    if words[0].startswith('@'):
        if len(words) == 1 and not new_word:
            prefix = words[0]
            ans.match_groups['Remote control commands'] = {'@' + c: '' for c in remote_control_command_names() if c.startswith(prefix)}
        else:
            complete_remote_command(ans, words[0][1:], words[1:], new_word)
    if words[0] == '+':
        if len(words) == 1 or (len(words) == 2 and not new_word):
            prefix = words[1] if len(words) > 1 else ''
            ans.match_groups['Entry points'] = {c: '' for c in namespaced_entry_points if c.startswith(prefix)}
        else:
            if words[1] == 'kitten':
                if len(words) == 2 or (len(words) == 3 and not new_word):
                    ans.match_groups['Kittens'] = dict.fromkeys(k for k in all_kitten_names() if k.startswith('' if len(words) == 2 else words[2]))
                else:
                    complete_kitten(ans, words[2], words[3:], new_word)
        return ans
    if words[0].startswith('+'):
        if len(words) == 1:
            if new_word:
                if words[0] == '+kitten':
                    ans.match_groups['Kittens'] = dict.fromkeys(all_kitten_names())
            else:
                prefix = words[0]
                ans.match_groups['Entry points'] = {c: '' for c in namespaced_entry_points if c.startswith(prefix)}
        else:
            if len(words) == 2 and not new_word:
                ans.match_groups['Kittens'] = dict.fromkeys(k for k in all_kitten_names() if k.startswith(words[1]))
            else:
                if words[0] == '+kitten':
                    complete_kitten(ans, words[1], words[2:], new_word)
    else:
        complete_cli(ans, words, new_word, options_for_completion(), complete_kitty_cli_arg)

    return ans


def setup(cstyle: str) -> None:
    print(completion_scripts[cstyle])


def main(args: Sequence[str], entry_points: Iterable[str], namespaced_entry_points: Iterable[str]) -> None:
    if not args:
        raise SystemExit('Must specify completion style')
    cstyle = args[0]
    if cstyle == 'setup':
        return setup(args[1])
    data = sys.stdin.read()
    try:
        parser = parsers[cstyle]
        serializer = serializers[cstyle]
    except KeyError:
        raise SystemExit('Unknown completion style: {}'.format(cstyle))
    words, new_word = parser(data)
    ans = find_completions(words, new_word, entry_points, namespaced_entry_points)
    print(serializer(ans), end='')
