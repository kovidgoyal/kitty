#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPLv3 Copyright: 2018, Kovid Goyal <kovid at kovidgoyal.net>

import os
import shlex
import sys

from .cli import options_for_completion
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


@output_serializer
def zsh_output_serializer(ans):
    lines = []
    for description, matches in ans.match_groups.items():
        cmd = ['compadd', '-U', '-J', shlex.quote(description), '-X', shlex.quote(description)]
        if description in ans.no_space_groups:
            cmd += ['-S', '""']
        cmd.append('--')
        for word, description in matches.items():
            cmd.append(shlex.quote(word))
        lines.append(' '.join(cmd) + ';')
    # debug('\n'.join(lines))
    return '\n'.join(lines)


@output_serializer
def bash_output_serializer(ans):
    lines = []
    for matches in ans.match_groups.values():
        for word in matches:
            lines.append('COMPREPLY+=({})'.format(shlex.quote(word)))
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


def complete_alias_map(ans, words, new_word, option_map, complete_args=lambda *a: None):
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
            return
        if opt is None:
            return  # some non-option word encountered
        expecting_arg = not opt.get('type', '').startswith('bool-')
    if expecting_arg:
        if opt is not None:
            complete_args(ans, opt, '' if new_word else last_word)
    else:
        prefix = '' if new_word else last_word
        ans.match_groups['Options'] = {k: opt['help'] for k, opt in option_map.items() if k.startswith(prefix)}


def complete_cli(ans, words, new_word, seq, complete_args=lambda *a: None):
    option_map = {}
    for opt in seq:
        if not isinstance(opt, str):
            for alias in opt['aliases']:
                option_map[alias] = opt
    complete_alias_map(ans, words, new_word, option_map, complete_args)


def executables(ans, prefix=None):
    matches = {}
    prefix = prefix or ''
    for src in os.environ.get('PATH', '').split(os.pathsep):
        if src:
            try:
                it = os.scandir(src)
            except EnvironmentError:
                continue
            for entry in it:
                try:
                    if entry.name.startswith(prefix) and entry.is_file() and os.access(entry.path, os.X_OK):
                        matches[entry.name] = None
                except EnvironmentError:
                    pass
    if matches:
        ans.match_groups['Executables'] = matches


def complete_remote_command(ans, cmd_name, words, new_word):
    aliases, alias_map = options_for_cmd(cmd_name)
    if not alias_map:
        return
    complete_alias_map(ans, words, new_word, alias_map)


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
    elif words[0] == '+':
        if len(words) == 1 or (len(words) == 2 and not new_word):
            prefix = words[1] if len(words) > 1 else ''
            ans.match_groups['Entry points'] = {c: None for c in namespaced_entry_points if c.startswith(prefix)}
            return ans
    else:
        complete_cli(ans, words, new_word, options_for_completion(), complete_kitty_cli_arg)

    return ans


def main(args, entry_points, namespaced_entry_points):
    if not args:
        raise SystemExit('Must specify completion style')
    cstyle = args[0]
    data = sys.stdin.read()
    try:
        parser = parsers[cstyle]
        serializer = serializers[cstyle]
    except KeyError:
        raise SystemExit('Unknown completion style: {}'.format(cstyle))
    words, new_word = parser(data)
    ans = find_completions(words, new_word, entry_points, namespaced_entry_points)
    print(serializer(ans), end='')
