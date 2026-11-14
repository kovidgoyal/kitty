#!/usr/bin/env python
# License: GPLv3 Copyright: 2021, Kovid Goyal <kovid at kovidgoyal.net>


from .operations import repeat, styled


def render_progress_bar(frac: float, width: int = 80) -> str:
    if frac >= 1:
        return styled('🬋' * width, fg='green')
    if frac <= 0:
        return styled('🬋' * width, dim=True)
    w = frac * width
    fl = int(w)
    overhang = w - fl
    filled = repeat('🬋', fl)
    if overhang < 0.2:
        needs_break = True
    elif overhang < 0.8:
        filled += '🬃'
        fl += 1
        needs_break = False
    else:
        if fl < width - 1:
            filled += '🬋'
            fl += 1
            needs_break = True
        else:
            filled += '🬃'
            fl += 1
            needs_break = False
    ans = styled(filled, fg='blue')
    unfilled = '🬇' if width > fl and needs_break else ''
    filler = width - fl - len(unfilled)
    if filler > 0:
        unfilled += repeat('🬋', filler)
    if unfilled:
        ans += styled(unfilled, dim=True)
    return ans
