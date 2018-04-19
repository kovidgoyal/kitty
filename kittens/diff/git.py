#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2018, Kovid Goyal <kovid at kovidgoyal.net>

import concurrent.futures
import os
import subprocess


def run_diff(file1, file2, context=3):
    # returns: ok, is_different, patch
    p = subprocess.Popen([
        'git', '--no-index', '--no-color', '--no-ext-diff', '--exit-code', '-U', str(context), '--'
        ] + [file1, file2],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, stdin=subprocess.DEVNULL)
    stdout, stderr = p.communicate()
    returncode = p.wait()
    if returncode in (0, 1):
        return True, returncode == 1, stdout.decode('utf-8')
    return False, returncode, stderr.decode('utf-8')


class Hunk:

    def __init__(self, title, left, right):
        self.left_start, self.left_count = left
        self.right_start, self.right_count = right
        self.title = title
        self.left_lines = []
        self.right_lines = []
        self.left_pos = self.right_pos = 0

    def add_line(self):
        self.right_lines.append((self.right_pos, True))
        self.right_pos += 1

    def remove_line(self):
        self.left_lines.append((self.left_pos, True))
        self.left_pos += 1

    def _even_up_sides(self):
        delta = len(self.left_lines) - len(self.right_lines)
        if delta != 0:
            dest = self.left_lines if delta < 0 else self.right_lines
            for i in range(abs(delta)):
                dest.append((None, True))

    def context_line(self):
        self._even_up_sides()
        self.left_lines.append((self.left_pos, False))
        self.right_lines.append((self.right_pos, False))
        self.left_pos += 1
        self.right_pos += 1

    def finalize(self):
        self._even_up_sides()
        # Sanity check
        if self.left_pos != self.left_count:
            raise ValueError('Left side line mismatch {} != {}'.format(self.left_pos, self.left_count))
        if self.right_pos != self.right_count:
            raise ValueError('Right side line mismatch {} != {}'.format(self.right_pos, self.right_count))


def parse_range(x):
    parts = x[1:].split(',', 1)
    start = abs(int(parts[0]))
    count = 1 if len(parts) < 2 else int(parts[1])
    return start, count


def parse_hunk_header(line):
    parts = tuple(filter(None, line.split('@@', 2)))
    linespec = parts[0].strip()
    title = ''
    if len(parts) == 2:
        title = parts[1].strip()
    left, right = map(parse_range, linespec.split())
    return Hunk(title, left, right)


def parse_patch(raw):
    all_hunks = []
    for line in raw.splitlines():
        if line.startswith('@@ '):
            current_hunk = parse_hunk_header(line)
            all_hunks.append(current_hunk)
        else:
            if not all_hunks:
                continue
            q = line[0]
            if q == '+':
                all_hunks[-1].add_line()
            elif q == '-':
                all_hunks[-1].remove_line()
            else:
                all_hunks[-1].context_line()
    for h in all_hunks:
        h.finalize()


class Differ:

    def __init__(self):
        self.jobs = []

    def add_diff(self, file1, file2):
        key = file1, file2
        self.jobs.append(key)

    def __call__(self, context=3):
        ans = {}
        with concurrent.futures.ThreadPoolExecutor(max_workers=os.cpu_count()) as executor:
            jobs = {executor.submit(run_diff, key[0], key[1], context): key for key in self.jobs}
            for future in concurrent.futures.as_completed(jobs):
                key = jobs[future]
                try:
                    ok, returncode, output = future.result()
                except FileNotFoundError:
                    raise SystemExit('Could not find the git executable. Is it in your PATH?')
                except Exception as e:
                    print('Running git diff for {} vs. {} generated an exception'.format(key[0], key[1]))
                    raise
                if not ok:
                    print(output)
                    raise SystemExit('Running git diff for {} vs. {} failed'.format(key[0], key[1]))
                ans[key] = parse_patch(output)
        return ans
