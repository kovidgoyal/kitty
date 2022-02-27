#!/usr/bin/env python
# License: GPLv3 Copyright: 2022, Kovid Goyal <kovid at kovidgoyal.net>


import glob
import os
import shlex
from typing import Iterable, Iterator, List, Optional, Sequence, Tuple

from kitty.cli import parse_args
from kitty.cli_stub import CopyCLIOptions
from kitty.types import run_once


@run_once
def option_text() -> str:
    return '''
--glob
type=bool-set
Interpret file arguments as glob patterns.


--dest
The destination on the remote computer to copy to. Relative paths are resolved
relative to HOME on the remote machine. When this option is not specified, the
local file path is used as the remote destination (with the HOME directory
getting automatically replaced by the remote HOME). Note that enviroment
variables and ~ are not expanded.
'''


def parse_copy_args(args: Optional[Sequence[str]] = None) -> Tuple[CopyCLIOptions, List[str]]:
    args = list(args or ())
    try:
        opts, args = parse_args(result_class=CopyCLIOptions, args=args, ospec=option_text)
    except SystemExit as e:
        raise CopyCLIError from e
    return opts, args


def resolve_file_spec(spec: str, is_glob: bool) -> Iterator[str]:
    ans = os.path.expandvars(os.path.expanduser(spec))
    if not os.path.isabs(ans):
        ans = os.path.expanduser(f'~/{ans}')
    if is_glob:
        files = glob.glob(ans)
        if not files:
            raise CopyCLIError(f'{spec} does not exist')
    else:
        if not os.path.exists(ans):
            raise CopyCLIError(f'{spec} does not exist')
        files = [ans]
    for x in files:
        yield os.path.normpath(x).replace(os.sep, '/')


class CopyCLIError(ValueError):
    pass


def parse_copy_instructions(val: str) -> Iterable[Tuple[str, CopyCLIOptions]]:
    opts, args = parse_copy_args(shlex.split(val))
    locations: List[str] = []
    for a in args:
        locations.extend(resolve_file_spec(a, opts.glob))
    if not locations:
        raise CopyCLIError('No files to copy specified')
    if len(locations) > 1 and opts.dest:
        raise CopyCLIError('Specifying a remote location with more than one file is not supported')
    for loc in locations:
        yield loc, opts
