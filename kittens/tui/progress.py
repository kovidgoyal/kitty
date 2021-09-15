#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPLv3 Copyright: 2021, Kovid Goyal <kovid at kovidgoyal.net>


from .operations import styled


def render_progress_bar(frac: float, width: int = 80) -> str:
    if frac >= 1:
        return styled('🬋' * width, fg='green')
    if frac <= 0:
        return styled('🬋' * width, dim=True)
    w = frac * width
    overhang = w - int(w)
    filled = '🬋' * int(w)
    if overhang < 0.2:
        needs_break = True
    elif overhang < 0.8:
        filled += '🬃'
        needs_break = False
    else:
        if len(filled) < width - 1:
            filled += '🬋'
            needs_break = True
        else:
            filled += '🬃'
            needs_break = False
    ans = styled(filled, fg='blue')
    unfilled = ''
    if width > len(filled):
        if needs_break:
            unfilled += '🬇'
    filler = width - len(filled) - len(unfilled)
    if filler > 0:
        unfilled += '🬋' * filler
    if unfilled:
        ans += styled(unfilled, dim=True)
    return ans
