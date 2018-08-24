#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPLv3 Copyright: 2018, Kovid Goyal <kovid at kovidgoyal.net>

import os
import shlex
import sys

parsers, serializers = {}, {}


class Completions:

    def __init__(self):
        self.match_groups = {}


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


@output_serializer
def zsh_output_serializer(ans):
    lines = []
    for description, matches in ans.match_groups.items():
        output = ['compadd', '-U', '-J', shlex.quote(description), '-X', shlex.quote(description), '--']
        for word, description in matches.items():
            output.append(shlex.quote(word))
        lines.append(' '.join(output) + ';')
    return '\n'.join(lines)


def completions_for_first_word(ans, prefix, entry_points, namespaced_entry_points):
    ans.match_groups['Entry points'] = {
        k: None for k in
        list(entry_points) + ['+' + k for k in namespaced_entry_points]
        if not prefix or k.startswith(prefix)
    }


def kitty_cli_opts(ans, prefix=None):
    from kitty.cli import options_for_completion
    matches = {}
    for opt in options_for_completion():
        if isinstance(opt, str):
            continue
        aliases = frozenset(x for x in opt['aliases'] if x.startswith(prefix)) if prefix else opt['aliases']
        for alias in aliases:
            matches[alias] = opt['help'].strip()
    ans.match_groups['Options'] = matches


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


def find_completions(words, new_word, entry_points, namespaced_entry_points):
    ans = Completions()
    if not words or words[0] != 'kitty':
        return ans
    words = words[1:]
    if not words or (len(words) == 1 and not new_word):
        prefix = words[0] if words else ''
        completions_for_first_word(ans, prefix, entry_points, namespaced_entry_points)
        kitty_cli_opts(ans, prefix)
        executables(ans, prefix)
        return ans

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
