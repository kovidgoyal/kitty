#!./kitty/launcher/kitty +launch
# License: GPLv3 Copyright: 2022, Kovid Goyal <kovid at kovidgoyal.net>

import os
import subprocess
import sys
from typing import Any

from kitty.rc.base import (
    RemoteCommand, all_command_names, command_for_name, parse_subcommand_cli
)


def serialize_as_go_string(x: str) -> str:
    return x.replace('\n', '\\n').replace('"', '\\"')


def build_go_code(name: str, cmd: RemoteCommand, opts: Any, template: str) -> str:
    template = template[len('//go:build exclude'):]
    ans = template.replace('CMD_NAME', name).replace('__FILE__', __file__).replace('CLI_NAME', name.replace('_', '-')).replace(
        'SHORT_DESC', serialize_as_go_string(cmd.short_desc)).replace('LONG_DESC', serialize_as_go_string(cmd.desc))
    return ans


def main() -> None:
    if 'prewarmed' in getattr(sys, 'kitty_run_data'):
        os.environ.pop('KITTY_PREWARM_SOCKET')
        os.execlp(sys.executable, sys.executable, '+launch', __file__, *sys.argv[1:])
    with open('tools/cmd/at/template.go') as f:
        template = f.read()
    for name in all_command_names():
        cmd = command_for_name(name)
        args = ['xxx' for i in range((cmd.args_count or 0) + 1)]
        opts = parse_subcommand_cli(cmd, args)[0]
        code = build_go_code(name, cmd, opts, template)
        dest = f'tools/cmd/at/{name}_generated.go'
        if os.path.exists(dest):
            os.remove(dest)
        with open(dest, 'w') as f:
            f.write(code)
        subprocess.check_call('gofmt -s -w tools/cmd/at'.split())


if __name__ == '__main__':
    main()
