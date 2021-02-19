#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPLv3 Copyright: 2020, Kovid Goyal <kovid at kovidgoyal.net>

# Monkeypatch the stdlib multiprocessing module to work with the embedded python
# in kitty, when using the spawn launcher.


from concurrent.futures import ProcessPoolExecutor
from multiprocessing import util  # type: ignore
from multiprocessing import context, get_all_start_methods, get_context, spawn
from typing import Any, Callable, List, Optional, Tuple, Union

from .constants import kitty_exe

orig_spawn_passfds = util.spawnv_passfds
orig_executable = spawn.get_executable()


def spawnv_passfds(path: str, args: List[str], passfds: List[int]) -> Any:
    if '-c' in args:
        idx = args.index('-c')
        patched_args = [spawn.get_executable(), '+runpy'] + args[idx + 1:]
    else:
        idx = args.index('--multiprocessing-fork')
        prog = 'from multiprocessing.spawn import spawn_main; spawn_main(%s)'
        prog %= ', '.join(item for item in args[idx+1:])
        patched_args = [spawn.get_executable(), '+runpy', prog]
    return orig_spawn_passfds(kitty_exe(), patched_args, passfds)


def monkey_patch_multiprocessing() -> None:
    # Use kitty to run the worker process used by multiprocessing
    spawn.set_executable(kitty_exe())
    util.spawnv_passfds = spawnv_passfds


def unmonkey_patch_multiprocessing() -> None:
    spawn.set_executable(orig_executable)
    util.spawnv_passfds = orig_spawn_passfds


def get_process_pool_executor(
    prefer_fork: bool = False,
    max_workers: Optional[int] = None,
    initializer: Optional[Callable] = None,
    initargs: Tuple[Any, ...] = ()
) -> ProcessPoolExecutor:
    if prefer_fork and 'fork' in get_all_start_methods():
        ctx: Union[context.DefaultContext, context.ForkContext] = get_context('fork')
    else:
        monkey_patch_multiprocessing()
        ctx = get_context()
    try:
        return ProcessPoolExecutor(max_workers=max_workers, initializer=initializer, initargs=initargs, mp_context=ctx)
    except TypeError:
        return ProcessPoolExecutor(max_workers=max_workers, initializer=initializer, initargs=initargs)


def test_spawn() -> None:
    monkey_patch_multiprocessing()
    try:
        from multiprocessing import get_context
        ctx = get_context('spawn')
        q = ctx.Queue()
        p = ctx.Process(target=q.put, args=('hello',))
        p.start()
        x = q.get(timeout=2)
        assert x == 'hello'
        p.join()
    finally:
        unmonkey_patch_multiprocessing()
