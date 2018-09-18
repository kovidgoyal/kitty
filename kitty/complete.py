#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPLv3 Copyright: 2018, Kovid Goyal <kovid at kovidgoyal.net>

import os
import shlex
import sys

from kittens.runner import get_kitten_cli_docs, all_kitten_names

from .cli import options_for_completion, parse_option_spec
from .cmds import cmap
from .shell import options_for_cmd

parsers, serializers = {}, {}


def debug(*a, **kw):
    kw['file'] = sys.stderr
    print(*a, **kw)


class Completions:

    def __init__(self):
        self.match_groups = {}
        self.no_space_groups = set()
        self.files_groups = set()


# Shell specific code {{{


completion_scripts = {
    'zsh': '''
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


def input_parser(func):
    name = func.__name__.split('_')[0]
    parsers[name] = func
    return func


def output_serializer(func):
    name = func.__name__.split('_')[0]
    serializers[name] = func
    return func


@input_parser
def zsh_input_parser(data):
    new_word = data.endswith('\n\n')
    words = data.rstrip().splitlines()
    return words, new_word


@input_parser
def bash_input_parser(data):
    new_word = data.endswith('\n\n')
    words = data.rstrip().splitlines()
    return words, new_word


@input_parser
def fish_input_parser(data):
    return data.rstrip().splitlines(), True


@output_serializer
def zsh_output_serializer(ans):
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
        for word, description in matches.items():
            cmd.append(shlex.quote(word))
        lines.append(' '.join(cmd) + ';')
    # debug('\n'.join(lines))
    return '\n'.join(lines)


@output_serializer
def bash_output_serializer(ans):
    lines = []
    for description, matches in ans.match_groups.items():
        needs_space = description not in ans.no_space_groups
        for word in matches:
            if needs_space:
                word += ' '
            lines.append('COMPREPLY+=({})'.format(shlex.quote(word)))
    # debug('\n'.join(lines))
    return '\n'.join(lines)
# }}}


@output_serializer
def fish_output_serializer(ans):
    lines = []
    for matches in ans.match_groups.values():
        for word in matches:
            lines.append(shlex.quote(word))
    # debug('\n'.join(lines))
    return '\n'.join(lines)


def completions_for_first_word(ans, prefix, entry_points, namespaced_entry_points):
    cmds = ['@' + c for c in cmap]
    ans.match_groups['Entry points'] = {
        k: None for k in
        list(entry_points) + cmds + ['+' + k for k in namespaced_entry_points]
        if not prefix or k.startswith(prefix)
    }


def kitty_cli_opts(ans, prefix=None):
    matches = {}
    for opt in options_for_completion():
        if isinstance(opt, str):
            continue
        aliases = frozenset(x for x in opt['aliases'] if x.startswith(prefix)) if prefix else opt['aliases']
        for alias in aliases:
            matches[alias] = opt['help'].strip()
    ans.match_groups['Options'] = matches


def complete_kitty_cli_arg(ans, opt, prefix):
    prefix = prefix or ''
    if opt and opt['dest'] == 'override':
        from kitty.config import option_names_for_completion
        k = 'Config directives'
        ans.match_groups[k] = {k+'=': None for k in option_names_for_completion() if k.startswith(prefix)}
        ans.no_space_groups.add(k)


def complete_alias_map(ans, words, new_word, option_map, complete_args=None):
    expecting_arg = False
    opt = None
    last_word = words[-1] if words else ''
    for w in words:
        if expecting_arg:
            if w is last_word and not new_word:
                if opt is not None:
                    complete_args(ans, opt, w)
                return
            expecting_arg = False
            continue
        opt = option_map.get(w)
        if w is last_word and not new_word:
            if w.startswith('-'):
                ans.match_groups['Options'] = {k: opt['help'] for k, opt in option_map.items() if k.startswith(last_word)}
            else:
                if complete_args is not None:
                    complete_args(ans, None, last_word)
            return
        if opt is None:
            if complete_args is not None:
                complete_args(ans, None, '' if new_word else last_word)
            return  # some non-option word encountered
        expecting_arg = not opt.get('type', '').startswith('bool-')
    if expecting_arg:
        if opt is not None and complete_args is not None:
            complete_args(ans, opt, '' if new_word else last_word)
    else:
        prefix = '' if new_word else last_word
        if complete_args is not None:
            complete_args(ans, None, prefix)
        ans.match_groups['Options'] = {k: opt['help'] for k, opt in option_map.items() if k.startswith(prefix)}


def complete_cli(ans, words, new_word, seq, complete_args=lambda *a: None):
    option_map = {}
    for opt in seq:
        if not isinstance(opt, str):
            for alias in opt['aliases']:
                option_map[alias] = opt
    complete_alias_map(ans, words, new_word, option_map, complete_args)


def complete_remote_command(ans, cmd_name, words, new_word):
    aliases, alias_map = options_for_cmd(cmd_name)
    if not alias_map:
        return
    complete_alias_map(ans, words, new_word, alias_map)


def path_completion(prefix=''):
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
        items = os.scandir(src)
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


def complete_files_and_dirs(ans, prefix, files_group_name='Files', predicate=None):
    dirs, files = path_completion(prefix or '')
    files = filter(predicate, files)

    if dirs:
        ans.match_groups['Directories'] = dict.fromkeys(dirs)
        ans.files_groups.add('Directories'), ans.no_space_groups.add('Directories')
    if files:
        ans.match_groups[files_group_name] = dict.fromkeys(files)
        ans.files_groups.add(files_group_name)


def complete_icat_args(ans, opt, prefix):
    from mimetypes import guess_type

    def icat_file_predicate(filename):
        mt = guess_type(filename)[0]
        if mt and mt.startswith('image/'):
            return True

    if opt is None:
        complete_files_and_dirs(ans, prefix, 'Images', icat_file_predicate)


def config_file_predicate(filename):
    return filename.endswith('.conf')


def complete_diff_args(ans, opt, prefix):
    if opt is None:
        complete_files_and_dirs(ans, prefix, 'Files')
    elif opt['dest'] == 'config':
        complete_files_and_dirs(ans, prefix, 'Config Files', config_file_predicate)


def complete_kitten(ans, kitten, words, new_word):
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


def find_completions(words, new_word, entry_points, namespaced_entry_points):
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
            ans.match_groups['Remote control commands'] = {c: None for c in cmap if c.startswith(prefix)}
        else:
            complete_remote_command(ans, words[1], words[2:], new_word)
        return ans
    if words[0].startswith('@'):
        if len(words) == 1 and not new_word:
            prefix = words[0]
            ans.match_groups['Remote control commands'] = {'@' + c: None for c in cmap if c.startswith(prefix)}
        else:
            complete_remote_command(ans, words[0][1:], words[1:], new_word)
    if words[0] == '+':
        if len(words) == 1 or (len(words) == 2 and not new_word):
            prefix = words[1] if len(words) > 1 else ''
            ans.match_groups['Entry points'] = {c: None for c in namespaced_entry_points if c.startswith(prefix)}
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
                ans.match_groups['Entry points'] = {c: None for c in namespaced_entry_points if c.startswith(prefix)}
        else:
            if len(words) == 2 and not new_word:
                ans.match_groups['Kittens'] = dict.fromkeys(k for k in all_kitten_names() if k.startswith(words[1]))
            else:
                if words[0] == '+kitten':
                    complete_kitten(ans, words[1], words[2:], new_word)
    else:
        complete_cli(ans, words, new_word, options_for_completion(), complete_kitty_cli_arg)

    return ans


def setup(cstyle):
    print(completion_scripts[cstyle])


def main(args, entry_points, namespaced_entry_points):
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
