#!/usr/bin/env python3
# License: GPLv3 Copyright: 2018, Kovid Goyal <kovid at kovidgoyal.net>

import os
import shlex
import sys
from typing import (
    Any, Callable, Dict, Iterable, Iterator, List, Optional, Sequence, Tuple,
    Union
)

from kittens.runner import (
    all_kitten_names, get_kitten_cli_docs, get_kitten_completer
)

from .cli import (
    OptionDict, options_for_completion, parse_option_spec, prettify
)
from .remote_control import global_options_spec
from .constants import config_dir, shell_integration_dir
from .fast_data_types import truncate_point_for_length, wcswidth
from .rc.base import all_command_names, command_for_name
from .shell import options_for_cmd
from .types import run_once
from .utils import screen_size_function

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

parsers: Dict[str, 'ParserFunc'] = {}
serializers: Dict[str, 'SerializerFunc'] = {}
shell_state: Dict[str, str] = {}


class MatchGroup:

    def __init__(
        self, x: Union[Dict[str, str], Iterable[str]],
        trailing_space: bool = True,
        is_files: bool = False,
        word_transforms: Optional[Dict[str, str]] = None,
    ):
        self.mdict = x if isinstance(x, dict) else dict.fromkeys(x, '')
        self.trailing_space = trailing_space
        self.is_files = is_files
        self.word_transforms = word_transforms or {}

    def __iter__(self) -> Iterator[str]:
        return iter(self.mdict)

    def __bool__(self) -> bool:
        return bool(self.mdict)

    def transformed_words(self) -> Iterator[str]:
        for w in self:
            yield self.word_transforms.get(w, w)

    def transformed_items(self) -> Iterator[Tuple[str, str]]:
        for w, desc in self.items():
            yield self.word_transforms.get(w, w), desc

    def items(self) -> Iterator[Tuple[str, str]]:
        return iter(self.mdict.items())

    def values(self) -> Iterator[str]:
        return iter(self.mdict.values())

    def add_prefix(self, prefix: str) -> None:
        nmap = {k: prefix + k for k in self.mdict}
        for k, nk in nmap.items():
            self.word_transforms[nk] = self.word_transforms.pop(k, k)
        self.mdict = {prefix + k: v for k, v in self.mdict.items()}


def debug(*a: Any, **kw: Any) -> None:
    from kittens.tui.loop import debug_write
    debug_write(*a, **kw)


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
        self.match_groups: Dict[str, MatchGroup] = {}
        self.delegate: Delegate = Delegate()

    def add_match_group(
        self, name: str, x: Union[Dict[str, str], Iterable[str]],
        trailing_space: bool = True,
        is_files: bool = False,
        word_transforms: Optional[Dict[str, str]] = None
    ) -> MatchGroup:
        self.match_groups[name] = m = MatchGroup(x, trailing_space, is_files, word_transforms)
        return m

    def add_prefix(self, prefix: str) -> None:
        for mg in self.match_groups.values():
            mg.add_prefix(prefix)


@run_once
def remote_control_command_names() -> Tuple[str, ...]:
    return tuple(sorted(x.replace('_', '-') for x in all_command_names()))


# Shell specific code {{{


def load_fish2_completion() -> str:
    with open(os.path.join(shell_integration_dir, 'fish', 'vendor_completions.d', 'kitty.fish')) as f:
        return f.read()


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
'''.__str__,
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
'''.__str__,
    'fish': '''
function __kitty_completions
    # Send all words up to the one before the cursor
    commandline -cop | kitty +complete fish
end

complete -f -c kitty -a "(__kitty_completions)"
'''.__str__,
    'fish2': load_fish2_completion,
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
    matcher = shell_state.get('_matcher', '')
    q = matcher.lower().split(':', maxsplit=1)[0]
    if q in ('l', 'r', 'b', 'e'):
        # this is zsh anchor based matching
        # https://zsh.sourceforge.io/Doc/Release/Completion-Widgets.html#Completion-Matching-Control
        # can be specified with matcher-list and some systems do it by default,
        # for example, Debian, which adds the following to zshrc
        # zstyle ':completion:*' matcher-list '' 'm:{a-z}={A-Z}' 'm:{a-zA-Z}={A-Za-z}' 'r:|[._-]=* r:|=* l:|=*'
        # For some reason that I dont have the
        # time/interest to figure out, returning completion candidates for
        # these matcher types break completion, so just abort in this case.
        raise SystemExit(1)
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


@input_parser
def fish2_input_parser(data: str) -> ParseResult:
    return bash_input_parser(data)


@output_serializer
def zsh_output_serializer(ans: Completions) -> str:
    lines = []

    try:
        screen = screen_size_function(sys.stderr.fileno())()
    except OSError:
        width = 80
    else:
        width = screen.cols

    def fmt_desc(word: str, desc: str, max_word_len: int) -> Iterator[str]:
        if not desc:
            yield word
            return
        desc = prettify(desc.splitlines()[0])
        multiline = False
        if wcswidth(word) > max_word_len:
            max_desc_len = width - 2
            multiline = True
        else:
            word = word.ljust(max_word_len)
            max_desc_len = width - max_word_len - 3
        if wcswidth(desc) > max_desc_len:
            desc = desc[:truncate_point_for_length(desc, max_desc_len - 2)]
            desc += '…'

        if multiline:
            ans = f'{word}\n  {desc}'
        else:
            ans = f'{word}  {desc}'
        yield ans

    for description, matches in ans.match_groups.items():
        cmd = ['compadd', '-U', '-J', shlex.quote(description), '-X', shlex.quote(f'%B{description}%b')]
        if not matches.trailing_space:
            cmd += ['-S', '""']
        if matches.is_files:
            cmd.append('-f')
            allm = tuple(matches)
            if len(allm) > 1:
                common_prefix = os.path.commonprefix(allm)
                if common_prefix and os.sep in common_prefix:
                    common_prefix = os.path.dirname(common_prefix).rstrip(os.sep) + os.sep
                    cmd.extend(('-p', shlex.quote(common_prefix)))
                    matches = MatchGroup({k[len(common_prefix):]: v for k, v in matches.items()})
        has_descriptions = any(matches.values())
        if has_descriptions or matches.word_transforms:
            lines.append('compdescriptions=(')
            try:
                sz = max(map(wcswidth, matches.transformed_words()))
            except ValueError:
                sz = 0
            limit = min(16, sz)
            for word, desc in matches.transformed_items():
                lines.extend(map(shlex.quote, fmt_desc(word, desc, limit)))
            lines.append(')')
            if has_descriptions:
                cmd.append('-l')
            cmd.append('-d')
            cmd.append('compdescriptions')
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
    result = '\n'.join(lines)
    # debug(result)
    return result


@output_serializer
def bash_output_serializer(ans: Completions) -> str:
    lines = []
    for description, matches in ans.match_groups.items():
        for word in matches:
            if matches.trailing_space:
                word += ' '
            lines.append(f'COMPREPLY+=({shlex.quote(word)})')
    # debug('\n'.join(lines))
    return '\n'.join(lines)


@output_serializer
def fish_output_serializer(ans: Completions) -> str:
    lines = []
    for description, matches in ans.match_groups.items():
        for word in matches:
            lines.append(word.replace('\n', ' '))
    # debug('\n'.join(lines))
    return '\n'.join(lines)


@output_serializer
def fish2_output_serializer(ans: Completions) -> str:
    lines = []
    for description, matches in ans.match_groups.items():
        for word, desc in matches.items():
            q = word
            if desc:
                q = f'{q}\t{desc}'
            lines.append(q.replace('\n', ' '))
    # debug('\n'.join(lines))
    return '\n'.join(lines)

# }}}


def completions_for_first_word(ans: Completions, prefix: str, entry_points: Iterable[str], namespaced_entry_points: Iterable[str]) -> None:
    cmds = [f'@{c}' for c in remote_control_command_names()]
    ans.add_match_group('Entry points', {
        k: '' for k in
        list(entry_points) + cmds + [f'+{k}' for k in namespaced_entry_points]
        if not prefix or k.startswith(prefix)
    })
    if prefix:
        ans.delegate = Delegate([prefix], 0)


def kitty_cli_opts(ans: Completions, prefix: Optional[str] = None) -> None:
    if not prefix:
        return
    matches = {}
    for opt in options_for_completion():
        if isinstance(opt, str):
            continue
        aliases = frozenset(x for x in opt['aliases'] if x.startswith(prefix)) if prefix else opt['aliases']
        for alias in aliases:
            matches[alias] = opt['help'].strip()
    ans.add_match_group('Options', matches)


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
        ans.add_match_group(k, {k+'=': '' for k in option_names_for_completion() if k.startswith(prefix)}, trailing_space=False)
    elif dest == 'listen_on':
        if ':' not in prefix:
            k = 'Address type'
            ans.add_match_group(k, {x: x for x in ('unix:', 'tcp:') if x.startswith(prefix)}, trailing_space=False)
        elif prefix.startswith('unix:') and not prefix.startswith('@'):
            complete_files_and_dirs(ans, prefix[len('unix:'):], files_group_name='UNIX sockets', add_prefix='unix:')
    else:
        complete_basic_option_args(ans, opt, prefix)


def basic_option_arg_completer(ans: Completions, opt: Optional[OptionDict], prefix: str, unknown_args: Delegate) -> None:
    prefix = prefix or ''
    if not opt:
        if unknown_args.num_of_unknown_args > 0:
            ans.delegate = unknown_args
        return
    complete_basic_option_args(ans, opt, prefix)


CompleteArgsFunc = Callable[[Completions, Optional[OptionDict], str, Delegate], None]


def complete_alias_map(
    ans: Completions,
    words: Sequence[str],
    new_word: bool,
    option_map: Dict[str, OptionDict],
    complete_args: CompleteArgsFunc = basic_option_arg_completer,
) -> None:
    expecting_arg = False
    opt: Optional[OptionDict] = None
    last_word = words[-1] if words else ''
    for i, w in enumerate(words):
        if expecting_arg:
            prev_word = '' if i == 0 else words[i-1]
            if w == '=' and i > 0 and prev_word.startswith('--') and prev_word != '--':
                if w is not last_word:
                    continue
                long_opt = option_map.get(prev_word)
                if long_opt is not None:
                    complete_args(ans, long_opt, '', Delegate())
                    return
            if w is last_word and not new_word:
                if opt is not None:
                    complete_args(ans, opt, w, Delegate())
                return
            expecting_arg = False
            continue
        if w is last_word and not new_word and w.startswith('--') and w != '--':
            parts = w.split('=', 1)
            if len(parts) == 2:
                long_opt = option_map.get(parts[0])
                if long_opt is not None:
                    complete_args(ans, long_opt, parts[1], Delegate())
                    ans.add_prefix(f'{parts[0]}=')
                return
        opt = option_map.get(w)
        if w is last_word and not new_word:
            if w.startswith('-'):
                ans.add_match_group('Options', {k: opt['help'] for k, opt in option_map.items() if k.startswith(last_word)})
            else:
                complete_args(ans, None, last_word, Delegate(words, i))
            return
        if opt is None:
            complete_args(ans, None, '' if new_word else last_word, Delegate(words, i, new_word))
            if w.startswith('--') and '=' in w:
                continue
            return  # some non-option word encountered
        expecting_arg = not opt.get('type', '').startswith('bool-')
    if expecting_arg:
        if opt is not None:
            complete_args(ans, opt, '' if new_word else last_word, Delegate())
    else:
        prefix = '' if new_word else last_word
        complete_args(ans, None, prefix, Delegate())
        ans.add_match_group('Options', {k: opt['help'] for k, opt in option_map.items() if k.startswith(prefix)})


def complete_cli(
    ans: Completions,
    words: Sequence[str],
    new_word: bool,
) -> None:
    option_map = {}
    for opt in options_for_completion():
        if not isinstance(opt, str):
            for alias in opt['aliases']:
                option_map[alias] = opt
    complete_alias_map(ans, words, new_word, option_map, complete_kitty_cli_arg)


def global_options_for_remote_cmd() -> Dict[str, OptionDict]:
    seq, disabled = parse_option_spec(global_options_spec())
    ans: Dict[str, OptionDict] = {}
    for opt in seq:
        if isinstance(opt, str):
            continue
        for alias in opt['aliases']:
            ans[alias] = opt
    return ans


def complete_remote_command(ans: Completions, cmd_name: str, words: Sequence[str], new_word: bool) -> None:
    aliases, alias_map = options_for_cmd(cmd_name)
    try:
        args_completion = command_for_name(cmd_name).args.completion
    except KeyError:
        return
    args_completer: CompleteArgsFunc = basic_option_arg_completer
    if args_completion:
        if 'files' in args_completion:
            title, matchers = args_completion['files']
            if isinstance(matchers, tuple):
                args_completer = remote_files_completer(title, matchers)
        elif 'names' in args_completion:
            title, q = args_completion['names']
            args_completer = remote_args_completer(title, q() if callable(q) else q)
    complete_alias_map(ans, words, new_word, alias_map, complete_args=args_completer)


def complete_launch_wrapper(ans: Completions, words: Sequence[str], new_word: bool, allow_files: bool = True) -> None:
    from kitty.launch import clone_safe_opts
    aliases, alias_map = options_for_cmd('launch')
    alias_map = {k: v for k, v in alias_map.items() if v['dest'] in clone_safe_opts()}
    args_completer: CompleteArgsFunc = basic_option_arg_completer
    if allow_files:
        args_completer = remote_files_completer('Files', ('*',))
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
        items: Iterable['os.DirEntry[str]'] = os.scandir(src)
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
    files: Iterable[str] = filter(predicate, files_)
    if add_prefix:
        dirs = list(add_prefix + x for x in dirs)
        files = (add_prefix + x for x in files)

    if dirs:
        ans.add_match_group('Directories', dirs, trailing_space=False, is_files=True)
    if files:
        ans.add_match_group(files_group_name, files, is_files=True)


def filter_files_from_completion_spec(spec: Dict[str, str]) -> Callable[['os.DirEntry[str]', str], bool]:

    if 'ext' in spec:
        extensions = frozenset(os.extsep + x.lower() for x in spec['ext'].split(','))
    else:
        extensions = frozenset()

    if 'mime' in spec:
        import re
        from fnmatch import translate
        mimes = tuple(re.compile(translate(x)) for x in spec['mime'].split(','))
        from .guess_mime_type import guess_type
    else:
        mimes = ()

    if mimes or extensions:
        def check_file(x: 'os.DirEntry[str]', result: str) -> bool:
            if extensions:
                q = result.lower()
                for ext in extensions:
                    if q.endswith(ext):
                        return True
            if mimes:
                mq = guess_type(result)
                if mq:
                    for mime in mimes:
                        if mime.match(mq):
                            return True
            return False
    else:
        def check_file(x: 'os.DirEntry[str]', result: str) -> bool:
            return True

    return check_file


def complete_file_path(ans: Completions, spec: Dict[str, str], prefix: str, only_dirs: bool = False) -> None:
    prefix = prefix.replace(r'\ ', ' ')
    relative_to = spec.get('relative', '')
    if relative_to:
        if relative_to == 'conf':
            relative_to = config_dir
    else:
        relative_to = os.getcwd()
    src_dir = relative_to
    check_against = prefix
    prefix_result_with = prefix
    files, dirs = [], []
    if prefix:
        expanded_prefix = os.path.expandvars(os.path.expanduser(prefix))
        check_against = os.path.basename(expanded_prefix)
        prefix_result_with = os.path.dirname(expanded_prefix).rstrip(os.sep) + os.sep
        if os.path.isabs(expanded_prefix):
            src_dir = os.path.dirname(expanded_prefix)
        elif os.sep in expanded_prefix or (os.altsep and os.altsep in expanded_prefix):
            src_dir = os.path.join(relative_to, os.path.dirname(expanded_prefix))
        else:
            prefix_result_with = ''
    try:
        items: Iterable['os.DirEntry[str]'] = os.scandir(src_dir)
    except OSError:
        items = ()
    check_file = filter_files_from_completion_spec(spec)
    for x in items:
        if not x.name.startswith(check_against):
            continue
        result = prefix_result_with + x.name
        if x.is_dir():
            dirs.append(result.rstrip(os.sep) + os.sep)
        else:
            if check_file(x, result):
                files.append(result)
    if dirs:
        ans.add_match_group('Directories', dirs, trailing_space=False, is_files=True)
    if not only_dirs and files:
        ans.add_match_group(spec.get('group') or 'Files', files, is_files=True)


def complete_path(ans: Completions, opt: OptionDict, prefix: str) -> None:
    spec = opt['completion']
    t = spec['type']
    if 'kwds' in spec:
        kwds = [x for x in spec['kwds'].split(',') if x.startswith(prefix)]
        if kwds:
            ans.add_match_group('Keywords', kwds)
    if t == 'file':
        complete_file_path(ans, spec, prefix)
    elif t == 'directory':
        complete_file_path(ans, spec, prefix, only_dirs=True)


def complete_basic_option_args(ans: Completions, opt: OptionDict, prefix: str) -> None:
    if opt['choices']:
        ans.add_match_group(f'Choices for {opt["dest"]}', tuple(k for k in opt['choices'] if k.startswith(prefix)))
    elif opt['completion'].get('type') in ('file', 'directory'):
        complete_path(ans, opt, prefix)


def complete_dirs(ans: Completions, prefix: str = '') -> None:
    dirs, files_ = path_completion(prefix or '')
    if dirs:
        ans.add_match_group('Directories', dirs, trailing_space=False, is_files=True)


def complete_icat_args(ans: Completions, opt: Optional[OptionDict], prefix: str, unknown_args: Delegate) -> None:
    from .guess_mime_type import guess_type

    def icat_file_predicate(filename: str) -> bool:
        mt = guess_type(filename, allow_filesystem_access=True)
        if mt and mt.startswith('image/'):
            return True
        return False

    if opt is None:
        complete_files_and_dirs(ans, prefix, 'Images', icat_file_predicate)
    else:
        complete_basic_option_args(ans, opt, prefix)


def complete_themes_args(ans: Completions, opt: Optional[OptionDict], prefix: str, unknown_args: Delegate) -> None:
    if opt is None:
        from kittens.themes.collection import load_themes
        themes = load_themes(cache_age=-1, ignore_no_cache=True)
        names = tuple(t.name for t in themes if t.name.startswith(prefix))
        ans.add_match_group('Themes', names)
    else:
        complete_basic_option_args(ans, opt, prefix)


def remote_files_completer(name: str, matchers: Tuple[str, ...]) -> CompleteArgsFunc:

    def complete_files_map(ans: Completions, opt: Optional[OptionDict], prefix: str, unknown_args: Delegate) -> None:

        def predicate(filename: str) -> bool:
            for m in matchers:
                if isinstance(m, str):
                    from fnmatch import fnmatch
                    return fnmatch(filename, m)
            return False

        if opt is None:
            complete_files_and_dirs(ans, prefix, name, predicate)
        else:
            complete_basic_option_args(ans, opt, prefix)
    return complete_files_map


def remote_args_completer(title: str, words: Iterable[str]) -> CompleteArgsFunc:
    items = sorted(words)

    def complete_names_for_arg(ans: Completions, opt: Optional[OptionDict], prefix: str, unknown_args: Delegate) -> None:
        if opt is None:
            ans.add_match_group(title, {c: '' for c in items if c.startswith(prefix)})
        else:
            complete_basic_option_args(ans, opt, prefix)

    return complete_names_for_arg


def remote_command_completer(ans: Completions, opt: Optional[OptionDict], prefix: str, unknown_args: Delegate) -> None:
    if opt is None:
        words = unknown_args.words[unknown_args.pos:]
        new_word = unknown_args.new_word
        if not words or (len(words) == 1 and not new_word):
            prefix = (words or ('',))[0]
            ans.add_match_group('Remote control commands', {c: '' for c in remote_control_command_names() if c.startswith(prefix)})
        else:
            complete_remote_command(ans, words[0], words[1:], new_word)
    else:
        basic_option_arg_completer(ans, opt, prefix, unknown_args)


def config_file_predicate(filename: str) -> bool:
    return filename.endswith('.conf')


def complete_diff_args(ans: Completions, opt: Optional[OptionDict], prefix: str, unknown_args: Delegate) -> None:
    if opt is None:
        complete_files_and_dirs(ans, prefix, 'Files')
    elif opt['dest'] == 'config':
        complete_files_and_dirs(ans, prefix, 'Config Files', config_file_predicate)
    else:
        complete_basic_option_args(ans, opt, prefix)


def complete_kitten(ans: Completions, kitten: str, words: Sequence[str], new_word: bool) -> None:
    try:
        completer = get_kitten_completer(kitten)
    except SystemExit:
        completer = None
    if completer is not None:
        completer(ans, words, new_word)
        return
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
        'themes': complete_themes_args,
    }.get(kitten, basic_option_arg_completer))


def find_completions(words: Sequence[str], new_word: bool, entry_points: Iterable[str], namespaced_entry_points: Iterable[str]) -> Completions:
    ans = Completions()
    if not words:
        return ans
    exe = os.path.basename(words[0])
    if exe in ('edit-in-kitty', 'clone-in-kitty'):
        complete_launch_wrapper(ans, words[1:], new_word, allow_files=words[0] != 'clone-in-kitty')
        return ans
    if exe != 'kitty':
        return ans
    words = words[1:]
    if not words or (len(words) == 1 and not new_word):
        if words and words[0].startswith('--') and '=' in words[0]:
            complete_cli(ans, words, new_word)
            return ans
        prefix = words[0] if words else ''
        completions_for_first_word(ans, prefix, entry_points, namespaced_entry_points)
        kitty_cli_opts(ans, prefix)
        return ans
    if words[0] == '@':
        complete_alias_map(ans, words[1:], new_word, global_options_for_remote_cmd(), remote_command_completer)
        return ans
    if words[0].startswith('@'):
        if len(words) == 1 and not new_word:
            prefix = words[0]
            ans.add_match_group('Remote control commands', {f'@{c}': '' for c in remote_control_command_names() if c.startswith(prefix)})
        else:
            complete_remote_command(ans, words[0][1:], words[1:], new_word)
        return ans
    if words[0] == '+':
        if len(words) == 1 or (len(words) == 2 and not new_word):
            prefix = words[1] if len(words) > 1 else ''
            ans.add_match_group('Entry points', {c: '' for c in namespaced_entry_points if c.startswith(prefix)})
        else:
            if words[1] == 'kitten':
                if len(words) == 2 or (len(words) == 3 and not new_word):
                    ans.add_match_group('Kittens', (k for k in all_kitten_names() if k.startswith('' if len(words) == 2 else words[2])))
                else:
                    complete_kitten(ans, words[2], words[3:], new_word)
            elif words[1] == 'open':
                complete_cli(ans, words[2:], new_word)
        return ans
    if words[0].startswith('+'):
        if len(words) == 1:
            if new_word:
                if words[0] == '+kitten':
                    ans.add_match_group('Kittens', all_kitten_names())
                elif words[0] == '+open':
                    complete_cli(ans, words[1:], new_word)
            else:
                prefix = words[0]
                ans.add_match_group('Entry points', (c for c in namespaced_entry_points if c.startswith(prefix)))
        else:
            if words[0] == '+kitten':
                if len(words) == 2 and not new_word:
                    ans.add_match_group('Kittens', (k for k in all_kitten_names() if k.startswith(words[1])))
                else:
                    complete_kitten(ans, words[1], words[2:], new_word)
            elif words[0] == '+open':
                complete_cli(ans, words[1:], new_word)
    else:
        complete_cli(ans, words, new_word)

    return ans


def setup(cstyle: str) -> None:
    print(completion_scripts[cstyle]())


def main(args: Sequence[str], entry_points: Iterable[str], namespaced_entry_points: Iterable[str]) -> None:
    if not args:
        raise SystemExit('Must specify completion style')
    cstyle = args[0]
    if cstyle == 'setup':
        return setup(args[1])
    data = sys.stdin.read()
    shell_state.clear()
    for x in args[1:]:
        parts = x.split('=', maxsplit=1)
        if len(parts) == 2:
            shell_state[parts[0]] = parts[1]
    try:
        parser = parsers[cstyle]
        serializer = serializers[cstyle]
    except KeyError:
        raise SystemExit(f'Unknown completion style: {cstyle}')
    words, new_word = parser(data)
    ans = find_completions(words, new_word, entry_points, namespaced_entry_points)
    print(serializer(ans), end='')
