#!/usr/bin/env python3

from time import clock_gettime, CLOCK_MONOTONIC, sleep
from argparse import ArgumentParser
from random import Random
from string import printable
import sys


def main():
    parser = ArgumentParser(description='Generate text')
    parser.add_argument('--freq', default=10000, type=int, help='Number of lines to try to write per second. Will warn if not attained.')
    parser.add_argument('--color', action='store_true', help='Add color to the output')
    parser.add_argument('--unicode', action='store_true', help='Mix in some unicode characters')
    parser.add_argument('--length', default=50, type=int, help='Average line length')
    parser.add_argument('--lengthvar', default=0.3, type=float, help='Variation for line length, in ratio of line length')
    parser.add_argument('--emptylines', default=0.1, type=float, help='ratio of empty lines')
    parser.add_argument('--linesperwrite', default=1, type=int, help='number of lines to repeat/write at a time')
    parser.add_argument('--patterns', default=1000, type=int, help='number of different pattern to alternate')
    parser.add_argument('--seed', default=sys.argv[0], type=str, help='seed to get different output')
    args = parser.parse_args()

    rng = Random()
    rng.seed(args.seed)

    characters = [c for c in printable if c not in '\r\n\x0b\x0c']
    if args.color:
        characters += ['\x1b[91m', '\x1b[0m', '\x1b[1;32m', '\x1b[22m', '\x1b[35m']

    if args.unicode:
        characters += [u'日', u'本', u'💜', u'☃', u'🎩', u'🍀', u'、']

    patterns = []
    for _ in range(0, args.patterns):
        s = ""
        for _ in range(0, args.linesperwrite):
            cnt = int(rng.gauss(args.length, args.length * args.lengthvar))
            if cnt < 0 or rng.random() < args.emptylines:
                cnt = 0
            s += "".join(rng.choices(characters, k=cnt)) + '\n'
        patterns += [s]

    time_per_print = args.linesperwrite / args.freq
    t1 = clock_gettime(CLOCK_MONOTONIC)
    cnt = 0
    while True:
        sys.stdout.write(patterns[rng.randrange(0, args.patterns)])
        sys.stdout.flush()
        cnt += 1
        t2 = clock_gettime(CLOCK_MONOTONIC)
        if t2 - t1 < cnt * time_per_print:
            sleep(cnt * time_per_print - (t2 - t1))
            t1 = t2
            cnt = 0
        elif cnt >= 100:
            print("Cannot print fast enough, printed %d lines in %f seconds instead of %f seconds target" %
                  (cnt * args.linesperwrite, t2 - t1, cnt * time_per_print))
            break
        else:
            cnt += 1


if __name__ == '__main__':
    main()
