#!/usr/bin/env python3
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2018, Kovid Goyal <kovid at kovidgoyal.net>

import concurrent.futures
import os
import shlex
import shutil
import subprocess
from typing import Dict, Iterator, List, Optional, Sequence, Tuple, Union

from . import global_data
from .collect import lines_for_path
from .diff_speedup import changed_center

left_lines: Tuple[str, ...] = ()
right_lines: Tuple[str, ...] = ()
GIT_DIFF = 'git diff --no-color --no-ext-diff --exit-code -U_CONTEXT_ --no-index --'
DIFF_DIFF = 'diff -p -U _CONTEXT_ --'
worker_processes: List[int] = []


def find_differ() -> Optional[str]:
    if shutil.which('git') and subprocess.Popen(['git', '--help'], stderr=subprocess.DEVNULL, stdout=subprocess.DEVNULL).wait() == 0:
        return GIT_DIFF
    if shutil.which('diff'):
        return DIFF_DIFF


def set_diff_command(opt: str) -> None:
    if opt == 'auto':
        cmd = find_differ()
        if cmd is None:
            raise SystemExit('Failed to find either the git or diff programs on your system')
    else:
        cmd = opt
    global_data.cmd = cmd


def run_diff(file1: str, file2: str, context: int = 3) -> Tuple[bool, Union[int, bool], str]:
    # returns: ok, is_different, patch
    cmd = shlex.split(global_data.cmd.replace('_CONTEXT_', str(context)))
    # we resolve symlinks because git diff does not follow symlinks, while diff
    # does. We want consistent behavior, also for integration with git difftool
    # we always want symlinks to be followed.
    path1 = os.path.realpath(file1)
    path2 = os.path.realpath(file2)
    p = subprocess.Popen(
            cmd + [path1, path2],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, stdin=subprocess.DEVNULL)
    worker_processes.append(p.pid)
    stdout, stderr = p.communicate()
    returncode = p.wait()
    worker_processes.remove(p.pid)
    if returncode in (0, 1):
        return True, returncode == 1, stdout.decode('utf-8')
    return False, returncode, stderr.decode('utf-8')


class Chunk:

    __slots__ = ('is_context', 'left_start', 'right_start', 'left_count', 'right_count', 'centers')

    def __init__(self, left_start: int, right_start: int, is_context: bool = False) -> None:
        self.is_context = is_context
        self.left_start = left_start
        self.right_start = right_start
        self.left_count = self.right_count = 0
        self.centers: Optional[Tuple[Tuple[int, int], ...]] = None

    def add_line(self) -> None:
        self.right_count += 1

    def remove_line(self) -> None:
        self.left_count += 1

    def context_line(self) -> None:
        self.left_count += 1
        self.right_count += 1

    def finalize(self) -> None:
        if not self.is_context and self.left_count == self.right_count:
            self.centers = tuple(
                changed_center(left_lines[self.left_start + i], right_lines[self.right_start + i])
                for i in range(self.left_count)
            )

    def __repr__(self) -> str:
        return 'Chunk(is_context={}, left_start={}, left_count={}, right_start={}, right_count={})'.format(
                self.is_context, self.left_start, self.left_count, self.right_start, self.right_count)


class Hunk:

    def __init__(self, title: str, left: Tuple[int, int], right: Tuple[int, int]) -> None:
        self.left_start, self.left_count = left
        self.right_start, self.right_count = right
        self.left_start -= 1  # 0-index
        self.right_start -= 1  # 0-index
        self.title = title
        self.added_count = self.removed_count = 0
        self.chunks: List[Chunk] = []
        self.current_chunk: Optional[Chunk] = None
        self.largest_line_number = max(self.left_start + self.left_count, self.right_start + self.right_count)

    def new_chunk(self, is_context: bool = False) -> Chunk:
        if self.chunks:
            c = self.chunks[-1]
            left_start = c.left_start + c.left_count
            right_start = c.right_start + c.right_count
        else:
            left_start = self.left_start
            right_start = self.right_start
        return Chunk(left_start, right_start, is_context)

    def ensure_diff_chunk(self) -> None:
        if self.current_chunk is None:
            self.current_chunk = self.new_chunk(is_context=False)
        elif self.current_chunk.is_context:
            self.chunks.append(self.current_chunk)
            self.current_chunk = self.new_chunk(is_context=False)

    def ensure_context_chunk(self) -> None:
        if self.current_chunk is None:
            self.current_chunk = self.new_chunk(is_context=True)
        elif not self.current_chunk.is_context:
            self.chunks.append(self.current_chunk)
            self.current_chunk = self.new_chunk(is_context=True)

    def add_line(self) -> None:
        self.ensure_diff_chunk()
        if self.current_chunk is not None:
            self.current_chunk.add_line()
        self.added_count += 1

    def remove_line(self) -> None:
        self.ensure_diff_chunk()
        if self.current_chunk is not None:
            self.current_chunk.remove_line()
        self.removed_count += 1

    def context_line(self) -> None:
        self.ensure_context_chunk()
        if self.current_chunk is not None:
            self.current_chunk.context_line()

    def finalize(self) -> None:
        if self.current_chunk is not None:
            self.chunks.append(self.current_chunk)
        del self.current_chunk
        # Sanity check
        c = self.chunks[-1]
        if c.left_start + c.left_count != self.left_start + self.left_count:
            raise ValueError('Left side line mismatch {} != {}'.format(c.left_start + c.left_count, self.left_start + self.left_count))
        if c.right_start + c.right_count != self.right_start + self.right_count:
            raise ValueError('Left side line mismatch {} != {}'.format(c.right_start + c.right_count, self.right_start + self.right_count))
        for c in self.chunks:
            c.finalize()


def parse_range(x: str) -> Tuple[int, int]:
    parts = x[1:].split(',', 1)
    start = abs(int(parts[0]))
    count = 1 if len(parts) < 2 else int(parts[1])
    return start, count


def parse_hunk_header(line: str) -> Hunk:
    parts: Tuple[str, ...] = tuple(filter(None, line.split('@@', 2)))
    linespec = parts[0].strip()
    title = ''
    if len(parts) == 2:
        title = parts[1].strip()
    left, right = map(parse_range, linespec.split())
    return Hunk(title, left, right)


class Patch:

    def __init__(self, all_hunks: Sequence[Hunk]):
        self.all_hunks = all_hunks
        self.largest_line_number = self.all_hunks[-1].largest_line_number if self.all_hunks else 0
        self.added_count = sum(h.added_count for h in all_hunks)
        self.removed_count = sum(h.removed_count for h in all_hunks)

    def __iter__(self) -> Iterator[Hunk]:
        return iter(self.all_hunks)

    def __len__(self) -> int:
        return len(self.all_hunks)


def parse_patch(raw: str) -> Patch:
    all_hunks = []
    current_hunk = None
    for line in raw.splitlines():
        if line.startswith('@@ '):
            current_hunk = parse_hunk_header(line)
            all_hunks.append(current_hunk)
        else:
            if current_hunk is None:
                continue
            q = line[0]
            if q == '+':
                current_hunk.add_line()
            elif q == '-':
                current_hunk.remove_line()
            elif q == '\\':
                continue
            else:
                current_hunk.context_line()
    for h in all_hunks:
        h.finalize()
    return Patch(all_hunks)


class Differ:

    diff_executor: Optional[concurrent.futures.ThreadPoolExecutor] = None

    def __init__(self) -> None:
        self.jmap: Dict[str, str] = {}
        self.jobs: List[str] = []
        if Differ.diff_executor is None:
            Differ.diff_executor = self.diff_executor = concurrent.futures.ThreadPoolExecutor(max_workers=os.cpu_count())

    def add_diff(self, file1: str, file2: str) -> None:
        self.jmap[file1] = file2
        self.jobs.append(file1)

    def __call__(self, context: int = 3) -> Union[str, Dict[str, Patch]]:
        global left_lines, right_lines
        ans: Dict[str, Patch] = {}
        executor = self.diff_executor
        assert executor is not None
        jobs = {executor.submit(run_diff, key, self.jmap[key], context): key for key in self.jobs}
        for future in concurrent.futures.as_completed(jobs):
            key = jobs[future]
            left_path, right_path = key, self.jmap[key]
            try:
                ok, returncode, output = future.result()
            except FileNotFoundError as err:
                return 'Could not find the {} executable. Is it in your PATH?'.format(err.filename)
            except Exception as e:
                return 'Running git diff for {} vs. {} generated an exception: {}'.format(left_path, right_path, e)
            if not ok:
                return output + '\nRunning git diff for {} vs. {} failed'.format(left_path, right_path)
            left_lines = lines_for_path(left_path)
            right_lines = lines_for_path(right_path)
            try:
                patch = parse_patch(output)
            except Exception:
                import traceback
                return traceback.format_exc() + '\nParsing diff for {} vs. {} failed'.format(left_path, right_path)
            else:
                ans[key] = patch
        return ans
