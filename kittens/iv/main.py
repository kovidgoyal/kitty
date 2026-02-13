#!/usr/bin/env python

import sys
from kitty.cli import parse_args

OPTIONS = '''\
--directory -d
type=str
help=Directory to process
'''

def main(args):
    try:
        opts = parse_args(args[1:], OPTIONS, usage, help_text, 'directory_processor')
        directory = opts.directory or (args[1] if len(args) > 1 else '.')
        print(f"Processing directory: {directory}")
        # Add your directory processing logic here
    except Exception as e:
        print(f"An error occurred: {e}", file=sys.stderr)
        return 1
    return 0

if __name__ == '__main__':
    sys.exit(main(sys.argv))
